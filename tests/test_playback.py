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
