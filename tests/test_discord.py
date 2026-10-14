import json
import httpx
import pytest
from meeting_agent.config import Settings
from meeting_agent.discord_client import DiscordTransport
from meeting_agent.escalations import DeliveryError
from test_urgency import urgency_harness


def discord_settings():
    return Settings(discord_bot_token='test-only',discord_guild_id='111',discord_escalation_channel_id='222',discord_owner_user_id='333')


async def pending(h):
    await h.service.ingest(h.sid,h.utterance('Alloy, what is the budget?'))
    await h.service.ingest(h.sid,h.utterance('Yes'))
    return h.escalations.questions(h.sid)[0]


@pytest.mark.asyncio
async def test_question_segments_allow_only_owner_mention_and_persist_progress(tmp_path):
    h=urgency_harness(tmp_path); q=await pending(h)
    original='Budget @everyone <@&444> ' * 200
    h.escalations.store.execute('UPDATE unanswered_questions SET question=? WHERE id=?',(original,q['id']))
    q=h.escalations.questions(h.sid)[0]; requests=[]
    def handle(request):
        if request.method=='GET': return httpx.Response(200,json={'guild_id':'111','type':0})
        body=json.loads(request.content); requests.append((request.url.path,body))
        return httpx.Response(200,json={'id':'thread' if request.url.path.endswith('/threads') else str(len(requests))})
    transport=DiscordTransport(discord_settings(),h.escalations.store,transport=httpx.MockTransport(handle))
    ref=await transport.send_question(q)
    await transport.send_question(h.escalations.questions(h.sid)[0])
    messages=[body for path,body in requests if path.endswith('/messages')]
    assert all(len(b['content'])<=2000 for b in messages)
    assert ''.join(b['content'].split('Question segment ',1)[1].split('\n',1)[1] for b in messages)==original
    assert messages[0]['allowed_mentions']=={'parse':[],'users':['333'],'roles':[],'replied_user':False}
    assert all(b['allowed_mentions']['users']==[] for b in messages[1:])
    assert all(b['enforce_nonce'] and len(b['nonce'])<=25 for b in messages)
    assert len(messages)==3
    saved=h.escalations.questions(h.sid)[0]
    assert saved['parent_message_id']==ref.parent_message_id and saved['thread_id']=='thread'


@pytest.mark.asyncio
async def test_rate_limit_respects_delay_and_thread_retry_reuses_parent(tmp_path):
    h=urgency_harness(tmp_path); q=await pending(h); posts=[]; limited=True
    def handle(request):
        nonlocal limited
        if request.method=='GET': return httpx.Response(200,json={'guild_id':'111','type':0})
        posts.append(request.url.path)
        if request.url.path.endswith('/threads') and limited:
            limited=False
            return httpx.Response(429,json={'retry_after':2.5})
        return httpx.Response(200,json={'id':'parent' if request.url.path.endswith('/messages') else 'thread'})
    transport=DiscordTransport(discord_settings(),h.escalations.store,transport=httpx.MockTransport(handle))
    h.escalations.notifier=transport
    await h.escalations.run_once()
    assert h.escalations.store.one('SELECT * FROM escalation_outbox')['state']=='queued'
    assert not await h.escalations.run_once()
    transport.retry_at=0
    h.escalations.store.execute('UPDATE escalation_outbox SET next_at=0')
    await h.escalations.run_once()
    assert posts.count('/api/v10/channels/222/messages')==1
    assert h.escalations.questions(h.sid)[0]['state']=='awaiting_owner'


@pytest.mark.asyncio
async def test_ambiguous_create_never_blindly_retries(tmp_path):
    h=urgency_harness(tmp_path); await pending(h); calls=[]
    def handle(request):
        if request.method=='GET': return httpx.Response(200,json={'guild_id':'111','type':0})
        calls.append(request)
        raise httpx.ReadTimeout('unknown result')
    h.escalations.notifier=DiscordTransport(discord_settings(),h.escalations.store,transport=httpx.MockTransport(handle))
    await h.escalations.run_once(); await h.escalations.run_once()
    assert len(calls)==1
    assert h.escalations.store.one('SELECT * FROM escalation_outbox')['state']=='needs_attention'


@pytest.mark.asyncio
async def test_configured_channel_must_belong_to_configured_guild(tmp_path):
    h=urgency_harness(tmp_path); q=await pending(h); calls=[]
    def handle(request):
        calls.append(request.method)
        return httpx.Response(200,json={'guild_id':'different','type':0})
    transport=DiscordTransport(discord_settings(),h.escalations.store,transport=httpx.MockTransport(handle))
    with pytest.raises(DeliveryError): await transport.send_question(q)
    assert calls==['GET']


def test_discord_status_is_private_and_contains_no_secrets(tmp_path):
    from test_api import make_client
    client,_=make_client(tmp_path)
    status=client.get('/discord/status')
    assert status.status_code==200
    assert status.json()['voice_attendance_available'] is False
    assert 'DISCORD_BOT_TOKEN' in status.json()['missing']
    assert client.get('/discord/status',headers={'Authorization':'Bearer wrong'}).status_code==401


@pytest.mark.asyncio
async def test_gateway_maps_new_message_and_uses_content_intent(tmp_path,monkeypatch):
    import discord
    from types import SimpleNamespace as Obj
    from datetime import UTC,datetime
    h=urgency_harness(tmp_path); received=[]; intents=[]
    async def receive(reply): received.append(reply)
    h.escalations.receive_owner_reply=receive
    class Client:
        def __init__(self,**kwargs): intents.append(kwargs['intents'])
        def event(self,fn): setattr(self,fn.__name__,fn); return fn
        async def start(self,token):
            await self.on_ready()
            await self.on_message(Obj(id=444,guild=Obj(id=111),channel=Obj(id=222),author=Obj(id=333,bot=False),content='budget is 500',created_at=datetime.now(UTC),reference=Obj(message_id=555),webhook_id=None,attachments=[],edited_at=None))
        async def close(self): pass
    monkeypatch.setattr(discord,'Client',Client)
    transport=DiscordTransport(discord_settings(),h.escalations.store)
    await transport.gateway(h.escalations)
    assert intents[0].message_content and not intents[0].members and not intents[0].voice_states
    assert received[0].parent_message_id=='555' and received[0].author_id=='333'
