from dataclasses import replace
from datetime import UTC,datetime
import pytest
from meeting_agent.discord_client import OwnerReply
from meeting_agent.escalations import DeliveryError
from meeting_agent.meeting_models import MeetingUtterance
from meeting_agent.minutes import MinutesService
from meeting_agent.models import SessionCreate
from test_minutes import Summarizer,entry
from test_owner_replies import reply_harness
from test_urgency import urgency_harness
from test_discord import discord_settings,pending


@pytest.mark.asyncio
async def test_end_during_tts_refreshes_previously_ready_minutes(tmp_path):
    h=await reply_harness(tmp_path)
    minutes=MinutesService(h.repo,Summarizer(),h.escalations)
    h.service.minutes=minutes
    minutes.transcript=lambda sid:[entry(0,'Budget discussion.')]
    await minutes.finalize(h.sid,minutes.transcript(h.sid))
    async def end_during_tts(*args):
        h.playback.live=False
        raise RuntimeError('call ended')
    h.playback.enqueue=end_during_tts
    assert await h.escalations.receive_owner_reply(h.reply)=='saved_after_end'
    assert minutes.status(h.sid)['state']=='processing'
    await minutes.run_once()
    assert h.reply.text in h.repo.get_minutes(h.sid).content


@pytest.mark.asyncio
async def test_answer_received_during_parent_thread_race_survives_thread_failure(tmp_path):
    h=urgency_harness(tmp_path); h.escalations.settings=discord_settings()
    await pending(h)
    class Notifier:
        async def send_question(self,question):
            h.escalations.store.execute('UPDATE unanswered_questions SET parent_message_id=? WHERE id=?',('parent',question['id']))
            reply=OwnerReply(message_id='race',guild_id='111',channel_id='222',parent_message_id='parent',author_id='333',text='Budget is 500.',created_at=datetime.now(UTC))
            assert await h.escalations.receive_owner_reply(reply)=='queued'
            raise DeliveryError('Thread creation failed')
    h.escalations.notifier=Notifier()
    await h.escalations.run_once()
    question=h.escalations.questions(h.sid)[0]
    assert question['state']=='answered'
    assert 'Thread creation failed' in question['error']
    assert h.escalations.store.one('SELECT * FROM escalation_outbox')['state']=='needs_attention'


@pytest.mark.asyncio
@pytest.mark.parametrize('reply_state',['queued','processing'])
async def test_restart_surfaces_uncertain_owner_playback_without_replay(tmp_path,reply_state):
    from test_recall import make_backend,session
    client,recall,_=make_backend(tmp_path); sid=session(client)
    recall.reserve(sid,'restart-test',None)
    recall.store.execute("UPDATE recall_bots SET state='in_call_recording' WHERE session_id=?",(sid,))
    escalations=recall.meeting.escalations; escalations.settings=discord_settings()
    q=escalations.open_question(sid,MeetingUtterance(event_id='q',platform='google_meet',speaker='Jamie',text='What is the budget?'),'prompt','utterance')
    escalations.store.execute("UPDATE unanswered_questions SET state='awaiting_owner',parent_message_id='parent',thread_id='thread' WHERE id=?",(q['id'],))
    reply=OwnerReply(message_id='uncertain',guild_id='111',channel_id='thread',author_id='333',text='Budget is 500.',created_at=datetime.now(UTC))
    await escalations.receive_owner_reply(reply)
    escalations.store.execute('UPDATE owner_replies SET state=? WHERE id=?',(reply_state,reply.message_id))
    recall.store.claim_audio(sid)
    recall.store.recover(); escalations.recover()
    assert recall.store.one("SELECT state FROM recall_audio WHERE id='discord:uncertain'")['state']=='failed'
    assert escalations.store.one("SELECT state FROM owner_replies WHERE id='uncertain'")['state']=='needs_attention'
    assert 'playback' in escalations.questions(sid)[0]['error'].lower()
    assert recall.store.claim_audio(sid) is None


@pytest.mark.asyncio
async def test_interrupted_unknown_prompt_closes_urgency_window(tmp_path):
    from test_recall import make_backend,session
    client,recall,_=make_backend(tmp_path); sid=session(client)
    recall.reserve(sid,'prompt-restart-test',None)
    recall.store.execute("UPDATE recall_bots SET state='in_call_recording' WHERE session_id=?",(sid,))
    e=recall.meeting.escalations
    q=e.open_question(sid,MeetingUtterance(event_id='unknown',platform='google_meet',speaker='Jamie',text='What is the catering budget?'),'unknown-prompt','utterance')
    recall.store.add_audio(sid,'Unknown prompt',b'mp3','unknown-prompt')
    recall.store.claim_audio(sid)
    recall.store.recover(); e.recover()
    assert e.questions(sid)[0]['state']=='urgency_expired'


@pytest.mark.asyncio
async def test_muted_meeting_cannot_starve_replies_for_another_meeting(tmp_path):
    h=urgency_harness(tmp_path)
    first=h.escalations.open_question(h.sid,h.utterance('What is the budget?'),'prompt','utterance')
    other=h.repo.create_session(SessionCreate(title='Other meeting',owner_name='Aloy')).id
    second=h.escalations.open_question(other,h.utterance('What is the launch date?'),'prompt2','utterance2')
    for index in range(5):
        question=first if index<4 else second
        h.escalations.store.execute('INSERT INTO owner_replies VALUES(?,?,?,?,?,NULL)',(f'message-{index}',question['id'],'Owner answer',f'2026-10-15T00:00:0{index}Z','pending'))
    h.playback.muted=lambda sid:sid==h.sid
    await h.escalations.drain_replies()
    assert len(h.playback.queued)==1 and h.playback.queued[0].session_id==other
