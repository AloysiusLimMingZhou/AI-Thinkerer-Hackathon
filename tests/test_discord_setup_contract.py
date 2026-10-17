import pytest
from meeting_agent.discord_setup import register
from meeting_agent.config import Settings

@pytest.mark.asyncio
async def test_registration_requires_config_without_network():
    called=[]
    async def forbidden(*a,**k):called.append(a);raise AssertionError('external I/O')
    for settings in (Settings(),Settings(discord_bot_token='fake'),Settings(discord_bot_token='fake',discord_guild_id='not-a-guild')):
        with pytest.raises(ValueError):await register(settings,factory=forbidden)
    assert called==[]

@pytest.mark.asyncio
async def test_registration_is_guild_scoped_and_redacts_child_env(monkeypatch):
    observed={}
    monkeypatch.setenv('OPENAI_API_KEY','sentinel')
    monkeypatch.setenv('ELEVENLABS_API_KEY','sentinel')
    monkeypatch.setenv('BACKEND_API_TOKEN','sentinel')
    class Process:
        async def wait(self):return 0
    async def factory(*args,**kw):observed.update(args=args,**kw);return Process()
    guild='123456789012345678'
    await register(Settings(discord_bot_token='fake-discord',discord_guild_id=guild),factory=factory)
    assert observed['args'][-2:]==('--guild',guild)
    assert 'OPENAI_API_KEY' not in observed['env']
    assert 'ELEVENLABS_API_KEY' not in observed['env']
    assert 'BACKEND_API_TOKEN' not in observed['env']
    assert observed['env']['DISCORD_GUILD_ID']==guild


def test_setup_cli_safe_failure_has_no_secrets(tmp_path):
    import os,subprocess,sys
    env={k:v for k,v in os.environ.items() if k.upper() in {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP'}}
    env.update(DISCORD_BOT_TOKEN='',DISCORD_GUILD_ID='',OPENAI_API_KEY='secret-token-value',ELEVENLABS_API_KEY='secret-token-value')
    result=subprocess.run([sys.executable,'-m','meeting_agent.discord_setup'],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=5)
    assert result.returncode!=0
    assert 'secret-token-value' not in result.stderr
    assert 'DISCORD_GUILD_ID' in result.stderr
