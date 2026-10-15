import asyncio
from test_recall import make_backend,session,launch


def test_mute_cancels_audio_and_exposes_stop_to_media_page(tmp_path):
    client,service,_=make_backend(tmp_path)
    sid=session(client); launch(client,service,sid)
    service.store.add_audio(sid,'Hello',b'mp3','clip')
    service.store.claim_audio(sid)
    response=client.post(f'/sessions/{sid}/mute',json={'muted':True})
    assert response.status_code==200
    token=service.media_token(sid,service.store.bot(sid)['media_expires'])
    result=client.get(f'/recall/media/{sid}/audio/clip/state',params={'token':token})
    assert result.json()['state']=='cancelled'
    assert service.store.one('SELECT audio FROM recall_audio WHERE id=?',('clip',))['audio']==b''
    assert client.post(f'/sessions/{sid}/mute',json={'muted':False}).status_code==200


import pytest
from fastapi import HTTPException
from meeting_agent.playback import PlaybackRouter
from meeting_agent.models import SessionCreate
from test_meeting_service import FakePlayback

@pytest.mark.asyncio
async def test_router_uses_platform_and_rejects_briefings(tmp_path):
    from meeting_agent.repository import SQLiteRepository
    repo=SQLiteRepository(tmp_path/'router.db')
    sid=repo.create_session(SessionCreate(title='Discord',owner_name='Aloy',platform='discord')).id
    draft=repo.create_session(SessionCreate(title='Briefing',owner_name='Aloy',platform='discord',purpose='briefing')).id
    recall_adapter,discord_adapter=FakePlayback(),FakePlayback()
    router=PlaybackRouter(repo,{'google_meet':recall_adapter,'discord':discord_adapter})
    await router.enqueue(sid,'Hello.','intent-1')
    assert recall_adapter.queued==[]
    assert [(x.session_id,x.text,x.key) for x in discord_adapter.queued]==[(sid,'Hello.','intent-1')]
    discord_adapter._muted=True
    assert router.muted(sid)
    assert router.available(sid)
    with pytest.raises(HTTPException):
        await router.enqueue(draft,'Hello.','no')

@pytest.mark.asyncio
async def test_common_availability_prevents_paid_answer(tmp_path):
    from test_meeting_service import harness
    h=harness(tmp_path)
    h.playback.available=lambda sid:False
    decision=await h.service.ingest(h.sid,h.utterance())
    assert decision.action=='stay_silent'
    assert decision.reason=='reply queue full'
    assert h.playback.queued==[]
