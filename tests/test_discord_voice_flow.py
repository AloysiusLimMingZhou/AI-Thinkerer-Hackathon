import asyncio,base64,io,wave
from datetime import UTC,datetime,timedelta
from types import SimpleNamespace
import pytest
from meeting_agent.discord_audio import DiscordAudio
from meeting_agent.discord_playback import DiscordPlayback
from meeting_agent.discord_protocol import AudioUtterance,PlaybackAck,OwnerReply
from meeting_agent.meeting_service import MeetingService
from meeting_agent.playback import PlaybackRouter
from meeting_agent.escalations import EscalationService,DiscordQuestionRef
from meeting_agent.minutes import MinutesService
from meeting_agent.models import SessionCreate,ContextNoteCreate
from meeting_agent.budget import PaidCallContext,current_paid_call,BudgetExceeded
from meeting_agent.cost_rates import CostQuote
from test_discord_attendance import harness,request
from test_meeting_service import EvidenceBrain
from test_minutes import Summarizer,entry

class Voice:
    def __init__(self,budget):self.budget=budget;self.calls=[]
    async def generate(self,text):
        q=CostQuote('eleven_v4_turbo',characters=len(text))
        r=self.budget.reserve(current_paid_call('speech'),q)
        self.budget.mark_dispatched(r.id);self.calls.append(text);self.budget.settle(r.id,q)
        return b'mp3'
class Transcriber:
    def __init__(self,budget):self.budget=budget;self.calls=[];self.text='Alloy, when is launch?';self.denied=False
    async def transcribe(self,wav,*,session_id,event_id):
        if self.denied:raise BudgetExceeded(self.budget.status())
        q=CostQuote('gpt-transcribe',audio_seconds=1)
        r=self.budget.reserve(PaidCallContext(session_id,'stt:'+session_id+':'+event_id,'transcription'),q)
        self.budget.mark_dispatched(r.id);self.calls.append(event_id);self.budget.settle(r.id,q);return self.text
class Notifier:
    configured=True
    def __init__(self):self.question_messages=[]
    async def send_question(self,q):
        self.question_messages.append(q);return DiscordQuestionRef('parent','thread')
    async def acknowledge(self,*a):pass

async def flow(tmp_path,knowledge=True):
    h=harness(tmp_path)
    h.voice=Voice(h.ctl.budget);h.plays=[]
    original=h.worker.request
    async def rpc(c,**kw):
        if c.type=='play':h.plays.append(c);return {'ok':True}
        return await original(c,**kw)
    h.worker.request=rpc
    h.playback=DiscordPlayback(h.ctl.store,h.worker,h.voice)
    router=PlaybackRouter(h.repo,{'discord':h.playback})
    h.meeting=MeetingService(h.repo,EvidenceBrain(),h.briefings.knowledge,router);h.playback.meeting=h.meeting
    h.escalations=EscalationService(h.repo,h.meeting,Notifier());h.escalations.settings=h.ctl.settings;h.meeting.escalations=h.escalations
    h.minutes=MinutesService(h.repo,Summarizer(),h.escalations);h.meeting.minutes=h.minutes
    h.ctl.playback=router;h.playback.on_budget=lambda sid:h.ctl.leave(sid,reason='budget')
    h.transcriber=Transcriber(h.ctl.budget);h.audio=DiscordAudio(h.transcriber,h.meeting,h.ctl);h.ctl.audio=h.audio
    async def started(sid):
        s=h.repo.get_session(sid)
        await h.meeting.queue_speech(sid,f"I'm {s.agent_name}, {s.owner_name}'s AI delegate. I transcribe this meeting and may answer aloud.",'intro:'+sid)
    h.ctl.on_started=started
    async def left(sid):
        if h.ctl.store.attendance(sid)['state']=='budget_stopped':h.minutes.pending_budget(sid)
        else:h.minutes.schedule(sid)
    h.ctl.on_left=left
    async def event(e):
        if e.type=='playback':await h.playback.acknowledge(e)
        elif e.type=='utterance':await h.audio.submit(e)
        elif e.type=='audio_gap':h.repo.record_event(e.session_id,'discord.audio_gap',e.model_dump(mode='json'))
        elif e.type=='owner_reply':
            from meeting_agent.discord_client import OwnerReply as Reply
            await h.escalations.receive_owner_reply(Reply(e.id,e.guild_id,e.channel_id,e.author_id,e.content,datetime.now(UTC),is_bot=e.bot,is_webhook=e.webhook,is_edit=e.is_edit,has_attachments=e.has_attachments))
    h.ctl.on_event=event
    briefing=h.briefings.create(SessionCreate(title='Launch',owner_name='Aloy'))
    if knowledge:h.repo.add_context(briefing.id,[ContextNoteCreate(title='Launch',content='Launch Friday.')])
    h.briefings.prepare(briefing.id)
    result=await h.ctl.handle_command(request(briefing_id=briefing.id));assert result['ok']
    h.sid=result['session_id'];h.generation=h.ctl.store.attendance(h.sid)['generation']
    async def ack(key=None):
        key=key or h.plays[-1].key
        for state in ('playing','completed'):await h.ctl.handle_event(PlaybackAck(session_id=h.sid,generation=h.generation,key=key,state=state))
    h.ack=ack;await ack()
    stream=io.BytesIO()
    with wave.open(stream,'wb') as f:f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(b'\0'*32000)
    def audio(id='e',**kw):
        values=dict(session_id=h.sid,generation=h.generation,event_id=id,participant_id='human',speaker='Jamie',spoken_at=datetime.now(UTC),received_at=datetime.now(UTC),wav_base64=base64.b64encode(stream.getvalue()).decode());values.update(kw);return AudioUtterance(**values)
    h.event=audio
    return h

@pytest.mark.asyncio
async def test_grounded_voice_duplicate_and_stale_generation(tmp_path):
    h=await flow(tmp_path)
    e=h.event();assert await h.audio.submit(e);await h.audio.drain()
    assert h.voice.calls[-1]=='Friday.';count=len(h.transcriber.calls)
    assert not await h.audio.submit(e);assert len(h.transcriber.calls)==count
    assert not await h.audio.submit(h.event('old',generation='old'))
    h.transcriber.text='Alloy, when is launch?'
    await h.audio.submit(h.event('stale',spoken_at=datetime.now(UTC)-timedelta(minutes=2)));await h.audio.drain()
    assert h.repo.get_transcript(h.sid)[-1].text=='Alloy, when is launch?'
    assert h.voice.calls.count('Friday.')==1
    with h.repo._connect() as db:assert all(r[0]==h.sid for r in db.execute('SELECT session_id FROM ai_cost_ledger'))
    await h.audio.close()

@pytest.mark.asyncio
async def test_urgent_owner_reply_spoken_once(tmp_path):
    h=await flow(tmp_path,knowledge=False)
    h.transcriber.text='Alloy, what is the budget?';await h.audio.submit(h.event('q'));await h.audio.drain();await h.ack()
    h.transcriber.text='Yes, it is urgent.';await h.audio.submit(h.event('yes'));await h.audio.drain();await h.ack()
    await h.escalations.run_once()
    assert len(h.escalations.notifier.question_messages)==1
    reply=OwnerReply(id='message',guild_id='111',channel_id='thread',author_id='333',content='The budget is 500.')
    await h.ctl.handle_event(reply);await h.ctl.handle_event(reply);await h.ack()
    spoken_owner_messages=[s for s in h.voice.calls if s.startswith('Aloy says:')]
    assert spoken_owner_messages==['Aloy says: The budget is 500.']
    assert h.escalations.store.one("SELECT state FROM owner_replies WHERE id='message'")['state']=='spoken'
    await h.audio.close()

@pytest.mark.asyncio
async def test_hard_cap_leaves_without_paid_notice(tmp_path):
    h=await flow(tmp_path)
    h.transcriber.denied=True;count=len(h.voice.calls)
    await h.audio.submit(h.event('denied'));await h.audio.drain()
    assert h.ctl.status(h.sid)['attendance']['state']=='budget_stopped'
    assert len(h.voice.calls)==count
    assert h.minutes.status(h.sid)['state']=='pending_budget'
    assert not h.worker.active
    await h.audio.close()

@pytest.mark.asyncio
async def test_minutes_retry_keeps_successful_stages(tmp_path):
    h=await flow(tmp_path)
    calls=[];deny=True
    async def summarize(session,material,*,synthesis):
        nonlocal deny
        calls.append(synthesis)
        if synthesis and deny:raise BudgetExceeded(h.ctl.budget.status())
        return '# Summary'
    h.minutes.brain=SimpleNamespace(summarize_minutes=summarize)
    transcript=[entry(1,'x'*25000),entry(2,'y'*25000)]
    with pytest.raises(BudgetExceeded):await h.minutes.finalize(h.sid,transcript)
    assert h.minutes.status(h.sid)['state']=='pending_budget'
    assert calls==[False,False,True]
    assert not await h.minutes.run_once()
    deny=False;await h.minutes.finalize(h.sid,transcript)
    assert calls==[False,False,True,True]
    assert h.minutes.status(h.sid)['state']=='ready'
    await h.audio.close()


@pytest.mark.asyncio
async def test_application_wiring_runs_voice_pipeline_without_recall(tmp_path):
    from meeting_agent.api import create_app
    from meeting_agent.repository import SQLiteRepository
    from test_discord_attendance import Worker
    from meeting_agent.config import Settings
    settings=Settings(database_path=tmp_path/'wired.db',openai_api_key='fake',elevenlabs_api_key='fake',discord_voice_enabled=True,discord_bot_token='fake',discord_guild_id='111',discord_owner_user_id='333',discord_escalation_channel_id='222')
    repo=SQLiteRepository(settings.database_path);worker=Worker()
    class FreeVoice:
        def __init__(self):self.calls=[]
        async def generate(self,text):self.calls.append(text);return b'mp3'
    voice=FreeVoice()
    app=create_app(settings=settings,repository=repo,voice=voice,brain=EvidenceBrain(),discord_worker=worker)
    result=await app.state.discord_attendance.handle_command(request())
    assert result['ok']
    assert len(voice.calls)==1 and 'AI delegate' in voice.calls[0]
    assert app.state.playback.adapters['discord'] is app.state.discord_playback
    assert app.state.recall.store.bot(result['session_id']) is None
    await app.state.discord_audio.close()

@pytest.mark.asyncio
async def test_mute_late_ack_and_capture_gap_are_visible(tmp_path):
    h=await flow(tmp_path)
    await h.audio.submit(h.event('answer'));await h.audio.drain()
    key=h.plays[-1].key
    await h.ctl.control(h.sid,'mute')
    await h.ack(key)
    assert h.ctl.store.one('SELECT state FROM discord_speech WHERE id=?',(key,))['state']=='cancelled'
    from meeting_agent.discord_protocol import AudioGap
    await h.ctl.handle_event(AudioGap(session_id=h.sid,generation=h.generation,spoken_at=datetime.now(UTC),participant_id='human',reason='decoder_failed'))
    assert any(e['type']=='discord.audio_gap' for e in h.repo.get_events(h.sid))
    await h.ctl.leave(h.sid)
    await h.ack(key)
    assert not await h.playback.is_live(h.sid)
    assert not await h.audio.submit(h.event('self',is_self=True))
    await h.audio.close()

@pytest.mark.asyncio
async def test_edited_and_unrelated_owner_messages_do_not_speak(tmp_path):
    h=await flow(tmp_path,knowledge=False)
    for event in (OwnerReply(id='x',guild_id='111',channel_id='unknown',author_id='333',content='Answer'),
                  OwnerReply(id='x',guild_id='111',channel_id='thread',author_id='other',content='Answer'),
                  OwnerReply(id='x',guild_id='111',channel_id='thread',author_id='333',content='Answer',is_edit=True)):
        await h.ctl.handle_event(event)
    assert len(h.voice.calls)==1
    await h.audio.close()


@pytest.mark.asyncio
async def test_stt_concurrency_queue_bound_and_speaker_order(tmp_path):
    h=await flow(tmp_path);release=asyncio.Event();active=0;peak=0;order=[]
    async def transcribe(wav,*,session_id,event_id):
        nonlocal active,peak
        active+=1;peak=max(peak,active);order.append(event_id)
        try:await release.wait();return 'Meeting discussion.'
        finally:active-=1
    h.transcriber.transcribe=transcribe
    await h.audio.submit(h.event('a1',participant_id='a'))
    await h.audio.submit(h.event('b1',participant_id='b'))
    await asyncio.sleep(.02)
    accepted=[await h.audio.submit(h.event('queued'+str(i),participant_id='a')) for i in range(10)]
    assert sum(accepted)==8
    release.set();await h.audio.drain()
    assert peak==2
    assert order.index('a1')<order.index('queued0')<order.index('queued1')
    assert len([e for e in h.repo.get_events(h.sid) if e['type']=='discord.audio_gap'])==2
    await h.audio.close()
