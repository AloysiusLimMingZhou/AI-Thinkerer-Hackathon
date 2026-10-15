from datetime import UTC,datetime
from dataclasses import replace
import pytest
from meeting_agent.discord_client import OwnerReply
from test_urgency import urgency_harness
from test_discord import discord_settings,pending


async def reply_harness(tmp_path):
    h=urgency_harness(tmp_path); h.escalations.settings=discord_settings()
    await pending(h); await h.escalations.run_once(); h.playback.queued.clear()
    h.reply=OwnerReply(message_id='owner-1',guild_id='111',channel_id='thread',author_id='333',text='The approved budget is 500.',created_at=datetime.now(UTC))
    return h


@pytest.mark.asyncio
async def test_owner_reply_deduplicates_and_is_meeting_scoped(tmp_path):
    h=await reply_harness(tmp_path)
    assert await h.escalations.receive_owner_reply(h.reply)=='queued'
    await h.escalations.receive_owner_reply(h.reply)
    assert [p.text for p in h.playback.queued]==['Aloy says: The approved budget is 500.']
    assert all(p.session_id==h.sid for p in h.playback.queued)
    chunks=h.knowledge.search(h.sid,'approved budget')
    assert chunks and 'owner-1' in chunks[0].locator
    assert h.escalations.questions(h.sid)[0]['state']=='answered'
    assert await h.escalations.receive_owner_reply(replace(h.reply,message_id='owner-2',text='Correction: budget is 600.'))=='queued'
    assert len(h.playback.queued)==2


@pytest.mark.asyncio
@pytest.mark.parametrize('change',[{'author_id':'other'},{'guild_id':'other'},{'channel_id':'other'}, {'is_bot':True},{'is_webhook':True},{'is_edit':True},{'has_attachments':True}])
async def test_untrusted_reply_never_saves_or_speaks(tmp_path,change):
    h=await reply_harness(tmp_path)
    assert await h.escalations.receive_owner_reply(replace(h.reply,**change))=='ignored'
    assert h.playback.queued==[]
    assert not h.escalations.store.all('SELECT * FROM owner_replies')


@pytest.mark.asyncio
async def test_parent_reply_race_and_post_call_reply(tmp_path):
    h=await reply_harness(tmp_path)
    h.escalations.store.execute("UPDATE unanswered_questions SET thread_id=NULL,state='escalation_queued'")
    assert await h.escalations.receive_owner_reply(replace(h.reply,channel_id='222',parent_message_id='parent'))=='queued'
    h.playback.live=False
    acknowledgements=[]
    async def ack(question,text,key): acknowledgements.append(text)
    h.notifier.acknowledge=ack
    assert await h.escalations.receive_owner_reply(replace(h.reply,message_id='late',channel_id='222',parent_message_id='parent'))=='saved_after_end'
    assert len(h.playback.queued)==1
    assert any('not spoken' in a for a in acknowledgements)


@pytest.mark.asyncio
async def test_meeting_ends_during_tts_does_not_retry_owner_audio(tmp_path):
    h=await reply_harness(tmp_path)
    async def end_during_enqueue(*args):
        h.playback.live=False
        raise RuntimeError('ended before audio queue')
    h.playback.enqueue=end_during_enqueue
    assert await h.escalations.receive_owner_reply(h.reply)=='saved_after_end'
    await h.escalations.receive_owner_reply(h.reply)
    assert h.playback.queued==[]


@pytest.mark.asyncio
async def test_oversize_reply_and_uncertain_restart_do_not_speak(tmp_path):
    h=await reply_harness(tmp_path)
    assert await h.escalations.receive_owner_reply(replace(h.reply,text='x'*2001))=='too_long'
    assert h.playback.queued==[]
    h.escalations.store.execute("INSERT INTO owner_replies VALUES('interrupted',?,'Saved','2026-10-15','processing',NULL)",(h.escalations.questions(h.sid)[0]['id'],))
    h.escalations.recover()
    assert h.escalations.store.one("SELECT * FROM owner_replies WHERE id='interrupted'")['state']=='needs_attention'


@pytest.mark.asyncio
async def test_full_audio_queue_keeps_reply_durable_until_capacity(tmp_path):
    h=await reply_harness(tmp_path)
    h.playback.available=lambda _:False
    assert await h.escalations.receive_owner_reply(h.reply)=='queued'
    assert h.playback.queued==[]
    assert h.escalations.store.one('SELECT * FROM owner_replies')['state']=='pending'
    h.playback.available=lambda _:True
    await h.escalations.drain_replies()
    assert len(h.playback.queued)==1


@pytest.mark.asyncio
async def test_owner_playback_failure_surfaces_attention_on_its_question(tmp_path):
    h=await reply_harness(tmp_path)
    await h.escalations.receive_owner_reply(h.reply)
    await h.service.playback_failed(h.sid,'discord:'+h.reply.message_id)
    assert h.escalations.store.one('SELECT * FROM owner_replies')['state']=='needs_attention'
    assert 'playback' in h.escalations.questions(h.sid)[0]['error'].lower()
