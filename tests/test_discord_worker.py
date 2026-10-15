import asyncio,json,sys
from pathlib import Path
import pytest
from pydantic import ValidationError
from meeting_agent.config import Settings
from meeting_agent.discord_protocol import parse_event,command,WorkerHealth
from meeting_agent.discord_worker import DiscordWorker,WorkerUnavailable

def test_protocol_rejects_bad_envelopes_and_media():
    base=dict(protocol_version=1,type='health',gateway=True,connection=False,decoder=True,receiver=False,player=True)
    assert parse_event(json.dumps(base)).type=='health'
    for extra in ({'secret':'x'},{'protocol_version':2}):
        with pytest.raises((ValueError,ValidationError)): parse_event(json.dumps(base|extra))
    with pytest.raises(ValueError): parse_event('x'* (12*1024*1024+1))
    with pytest.raises(ValueError): parse_event(json.dumps(dict(protocol_version=1,type='utterance',session_id='s',generation='g',event_id='e',participant_id='p',speaker='X',spoken_at='2026-10-15T00:00:00Z',received_at='2026-10-15T00:00:00Z',wav_base64='!')))

@pytest.mark.asyncio
async def test_worker_env_and_generation_fence(monkeypatch):
    child_env={}
    async def factory(*args,**kw):
        child_env.update(kw['env'])
        return await asyncio.create_subprocess_exec(sys.executable,str(Path(__file__).parent/'fixtures/discord_worker_stub.py'),**kw)
    monkeypatch.setenv('OPENAI_API_KEY','never-child')
    monkeypatch.setenv('ELEVENLABS_API_KEY','never-child')
    monkeypatch.setenv('BACKEND_API_TOKEN','never-child')
    worker=DiscordWorker(Settings(discord_bot_token='fake'),process_factory=factory)
    handled_old_generation_events=[]
    async def handler(e): handled_old_generation_events.append(e)
    await worker.start()
    runner=asyncio.create_task(worker.run(handler))
    worker.generations['s']='new'
    try:
        assert (await worker.request(command('status')))['ok']
        await worker.request(command('stop',session_id='s',generation='new'))
        await asyncio.sleep(.05)
        assert handled_old_generation_events==[]
        assert 'OPENAI_API_KEY' not in child_env
        assert 'ELEVENLABS_API_KEY' not in child_env
        assert 'BACKEND_API_TOKEN' not in child_env
        assert len(worker.diagnostics)<=65536
    finally:
        await worker.close()
        await runner

@pytest.mark.asyncio
async def test_child_reaped_after_eof():
    async def factory(*args,**kw):
        return await asyncio.create_subprocess_exec(sys.executable,'-c','pass',**kw)
    worker=DiscordWorker(Settings(discord_bot_token='fake'),process_factory=factory)
    await worker.start()
    process=worker.process
    await worker.run(lambda e: asyncio.sleep(0))
    with pytest.raises(WorkerUnavailable): await worker.request(command('status'),timeout=.1)
    await worker.close()
    assert process.returncode is not None

@pytest.mark.asyncio
async def test_timeout_is_uncertain_and_pending_is_bounded():
    async def factory(*args,**kw):
        return await asyncio.create_subprocess_exec(sys.executable,str(Path(__file__).parent/'fixtures/discord_worker_stub.py'),**kw)
    worker=DiscordWorker(Settings(discord_bot_token='fake'),process_factory=factory)
    await worker.start()
    runner=asyncio.create_task(worker.run(lambda e:asyncio.sleep(0)))
    try:
        with pytest.raises(WorkerUnavailable): await worker.request(command('leave',session_id='s',generation='g'),timeout=.02)
        assert not worker.pending
    finally: await worker.close(); await runner
