import asyncio
from types import SimpleNamespace
import pytest
from meeting_agent.config import Settings
from meeting_agent.models import SessionCreate,ContextNoteCreate
from meeting_agent.repository import SQLiteRepository
from meeting_agent.knowledge import KnowledgeService
from meeting_agent.briefings import BriefingService
from meeting_agent.budget import BudgetService
from meeting_agent.discord_protocol import DiscordCommandRequest,WorkerHealth
from meeting_agent.discord_attendance import DiscordAttendance
from meeting_agent.discord_worker import WorkerUnavailable
from test_meeting_service import FakePlayback

class Worker:
    def __init__(self):self.join_calls=[];self.generations={};self.active={};self.uncertain=False
    def health(self):return WorkerHealth(gateway=True,decoder=True)
    async def request(self,c,**kw):
        if c.type=='join':
            self.join_calls.append(c);self.active=dict(session_id=c.session_id,generation=c.generation,channel_id=c.channel_id,gateway=True,decoder=True,connection=True,receiver=True,player=True)
            if self.uncertain:self.uncertain=False;raise WorkerUnavailable('worker_timeout_uncertain')
            return self.active
        if c.type=='status':return self.active
        if c.type=='leave':self.active={}
        return {'ok':True}

def harness(tmp_path,**changes):
    opts=dict(openai_api_key='fake',elevenlabs_api_key='fake',discord_voice_enabled=True,discord_bot_token='fake',discord_guild_id='111',discord_owner_user_id='333',discord_escalation_channel_id='222',database_path=tmp_path/'db')
    opts.update(changes);settings=Settings(**opts);repo=SQLiteRepository(settings.database_path)
    briefings=BriefingService(repo,KnowledgeService(repo));worker=Worker()
    ctl=DiscordAttendance(settings,repo,briefings,worker,FakePlayback(),BudgetService(repo,settings))
    return SimpleNamespace(ctl=ctl,repo=repo,worker=worker,briefings=briefings)

def request(id='one',**kw):
    values=dict(interaction_id=id,command='join',guild_id='111',actor_id='333',channel_id='444')
    values.update(kw);return DiscordCommandRequest(**values)

@pytest.mark.asyncio
async def test_join_is_owner_only_and_idempotent(tmp_path):
    h=harness(tmp_path)
    denied=await h.ctl.handle_command(request(actor_id='other'))
    assert denied['code']=='owner_required';assert not h.worker.join_calls
    first=await h.ctl.handle_command(request('first'));repeated=await h.ctl.handle_command(request('first'))
    same=await h.ctl.handle_command(request('same'))
    assert repeated['session_id']==first['session_id']==same['session_id'];assert len(h.worker.join_calls)==1
    assert h.repo.get_session(first['session_id']).platform=='discord'
    with h.repo._connect() as db:assert db.execute('SELECT * FROM recall_bots WHERE session_id=?',(first['session_id'],)).fetchone() is None if db.execute("SELECT name FROM sqlite_master WHERE name='recall_bots'").fetchone() else True
    assert (await h.ctl.handle_command(request('elsewhere',channel_id='555')))['code']=='leave_first'

@pytest.mark.asyncio
async def test_snapshot_optional_and_readiness_before_join(tmp_path):
    h=harness(tmp_path)
    b=h.briefings.create(SessionCreate(title='Briefing',owner_name='Aloy'))
    h.repo.add_context(b.id,[ContextNoteCreate(title='Launch',content='Launch Friday.')])
    assert (await h.ctl.handle_command(request('draft',briefing_id=b.id)))['ok'] is False
    h.briefings.prepare(b.id)
    joined=await h.ctl.handle_command(request('ready',briefing_id=b.id));assert joined['ok']
    assert h.repo.get_context(joined['session_id'])[0].content=='Launch Friday.'
    await h.ctl.leave(joined['session_id'])
    empty=await h.ctl.handle_command(request('empty'))
    assert not h.repo.get_context(empty['session_id'])
    missing=harness(tmp_path/'missing',openai_api_key=None)
    assert (await missing.ctl.handle_command(request()))['code']=='not_ready';assert not missing.worker.join_calls

@pytest.mark.asyncio
async def test_uncertain_join_is_reconciled(tmp_path):
    h=harness(tmp_path);h.worker.uncertain=True
    uncertain=await h.ctl.handle_command(request())
    assert uncertain['code']=='join_uncertain'
    reconciled=await h.ctl.handle_command(request('retry'))
    assert reconciled['session_id']==uncertain['session_id'];assert len(h.worker.join_calls)==1
    await h.ctl.recover()
    assert h.ctl.status(reconciled['session_id'])['attendance']['state']=='interrupted'

@pytest.mark.asyncio
async def test_concurrent_join_and_controls(tmp_path):
    h=harness(tmp_path)
    results=await asyncio.gather(*(h.ctl.handle_command(request(str(i))) for i in range(5)))
    assert len(h.worker.join_calls)==1
    assert len({x['session_id'] for x in results})==1
    assert (await h.ctl.handle_command(request('mute',command='mute')))['ok']
    assert h.ctl.status()['attendance']['muted']
    assert (await h.ctl.handle_command(request('wrongguild',guild_id='bad')))['code']=='guild_required'


def test_private_attendance_routes_and_no_key_startup(tmp_path,monkeypatch):
    from meeting_agent.api import create_app
    from fastapi.testclient import TestClient
    from meeting_agent.discord_worker import DiscordWorker
    async def forbidden(*a,**k):raise AssertionError('Must not start without keys')
    monkeypatch.setattr(DiscordWorker,'start',forbidden)
    settings=Settings(database_path=tmp_path/'api.db',backend_api_token='private',discord_voice_enabled=True)
    repo=SQLiteRepository(settings.database_path)
    app=create_app(settings=settings,repository=repo)
    with TestClient(app) as client:
        assert client.get('/discord/status').status_code==401
        headers={'Authorization':'Bearer private'}
        s=client.get('/discord/status',headers=headers).json()
        assert not s['voice_attendance_available']
        sid=repo.create_session(SessionCreate(title='D',owner_name='Owner',platform='discord')).id
        assert client.get(f'/sessions/{sid}/discord-attendance',headers=headers).status_code==200
        assert client.post(f'/sessions/{sid}/discord-attendance/mute',headers=headers).status_code==404


@pytest.mark.asyncio
async def test_reconciled_join_uses_the_same_introduction_once(tmp_path):
    h=harness(tmp_path);introduced=[]
    async def intro(sid):introduced.append(sid)
    h.ctl.on_started=intro;h.worker.uncertain=True
    first=await h.ctl.handle_command(request())
    assert first['code']=='join_uncertain'
    recovered=await h.ctl.handle_command(request('retry'))
    assert recovered['ok']
    assert introduced==[first['session_id']]
    await h.ctl.handle_command(request('same'))
    assert introduced==[first['session_id']]
    assert len(h.worker.join_calls)==1
