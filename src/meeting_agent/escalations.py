"""Persisted urgency confirmation; network side effects live in a separate outbox."""
import asyncio
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4
from .escalation_store import EscalationStore
from .models import AgentDecision


@dataclass
class DiscordQuestionRef:
    parent_message_id: str
    thread_id: str


class DeliveryError(Exception):
    def __init__(self,message,*,retry_after=None,ambiguous=False):
        super().__init__(message)
        self.retry_after,self.ambiguous=retry_after,ambiguous


def question_terms(text):
    stop={'alloy','aloy','what','when','where','which','who','why','how','the','and','our','your','this','that','there','could','would','please','tell','about','does','have','know','urgent','yes','its'}
    return {t for t in re.findall(r'\w+',text.casefold()) if len(t)>2 and t not in stop}


class EscalationService:
    def __init__(self,repository,meeting,notifier=None):
        self.repository,self.meeting,self.notifier=repository,meeting,notifier
        self.store=EscalationStore(repository)
        self.clock=time.time
        self.settings=None

    def _event(self,question):
        self.repository.record_event(question['session_id'],'question.updated',question)

    def questions(self,sid):
        self.store.execute("UPDATE unanswered_questions SET state='urgency_expired' WHERE session_id=? AND state='awaiting_urgency' AND urgency_deadline<?",(sid,self.clock()))
        return self.store.all('SELECT * FROM unanswered_questions WHERE session_id=? ORDER BY asked_at,id',(sid,))

    def open_question(self,sid,utterance,prompt_key,utterance_id):
        terms=question_terms(utterance.text)
        for question in self.questions(sid):
            same=self._same_speaker(question,utterance)
            original=question_terms(question['question'])
            if same and question['state']=='awaiting_urgency' and terms and len(terms & original)/max(len(terms|original),1)>=0.5:
                return question
        qid=str(uuid4()); now=self.clock()
        self.store.execute('INSERT INTO unanswered_questions(id,session_id,utterance_id,participant_id,speaker,question,state,asked_at,urgency_deadline,prompt_key) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (qid,sid,utterance_id,utterance.participant_id,utterance.speaker,utterance.text,'awaiting_urgency',now,now+60,prompt_key))
        question=self.store.one('SELECT * FROM unanswered_questions WHERE id=?',(qid,))
        self._event(question)
        return question

    def _same_speaker(self,question,u):
        if u.speaker=='Unknown participant' and not u.participant_id: return False
        if question['participant_id'] and u.participant_id:
            return question['participant_id']==u.participant_id
        return question['speaker'].casefold()==u.speaker.casefold()

    def cancel_prompt(self,sid,key):
        self.store.execute("UPDATE unanswered_questions SET state='urgency_expired',error='Prompt playback failed' WHERE session_id=? AND prompt_key=? AND state='awaiting_urgency'",(sid,key))

    def handle_confirmation(self,sid,u):
        if (u.speaker=='Unknown participant' and not u.participant_id) or not u.is_final:
            return None
        text=' '.join(u.text.casefold().replace('’',"'").split())
        negative=bool(re.search(r"\b(?:no rush|don't contact|do not contact|not a priority)\b|^(?:no|nah)\b|\b(?:not|isn't|isnt|don't|dont|do not|doesn't)\b(?:\W+\w+){0,6}\W+urgent\b",text))
        uncertain=bool(re.search(r"\?|\b(?:maybe|whether|wonder|if|perhaps|unsure)\b|^(?:is|are|was|would|could|should)\b",text))
        positive=not uncertain and bool(re.search(r'\burgent\b|^(?:yes|yep|yeah)\b',text))
        if not negative and not positive: return None
        session=self.repository.get_session(sid)
        addressed=bool(re.search(r'(?<!\w)'+re.escape(session.agent_name.casefold())+r'(?!\w)',text))
        candidates=[]
        terms=question_terms(u.text)
        questions=self.questions(sid)
        for question in questions:
            if question['state'] not in {'awaiting_urgency','urgency_expired','escalation_queued','awaiting_owner','delivery_failed'}: continue
            same=self._same_speaker(question,u)
            overlap=len(terms & question_terms(question['question']))
            if same or (addressed and overlap): candidates.append((overlap,question))
        if not candidates: return None
        maximum=max(score for score,_ in candidates)
        if maximum: candidates=[pair for pair in candidates if pair[0]==maximum]
        # Pending questions take precedence over older resolved/expired requests.
        pending=[pair for pair in candidates if pair[1]['state']=='awaiting_urgency']
        if pending: candidates=pending
        if len(candidates)>1:
            return AgentDecision(action='answer',reason='ambiguous urgency',answer='Which question is urgent?')
        question=candidates[0][1]
        state=question['state']
        if state=='urgency_expired':
            return AgentDecision(action='answer',reason='urgency expired',answer="I've kept that as an open question in the meeting notes.")
        if state in {'escalation_queued','awaiting_owner'}:
            return AgentDecision(action='answer',reason='already escalated',answer=f"I've already queued that question for {session.owner_name}.")
        if state=='delivery_failed':
            return AgentDecision(action='answer',reason='delivery failed',answer=f"I couldn't reach {session.owner_name} in Discord. I've kept the question in the meeting notes.")
        if negative:
            self.store.execute("UPDATE unanswered_questions SET state='not_urgent' WHERE id=?",(question['id'],))
            self._event(self.store.one('SELECT * FROM unanswered_questions WHERE id=?',(question['id'],)))
            return AgentDecision(action='answer',reason='not urgent',answer="Okay, I've kept the question in the meeting notes.")
        with self.repository._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("INSERT OR IGNORE INTO escalation_outbox(id,question_id,state) VALUES(?,?,'queued')",(question['id'],question['id']))
            db.execute("UPDATE unanswered_questions SET state='escalation_queued' WHERE id=? AND state='awaiting_urgency'",(question['id'],))
        if self.notifier is None or not getattr(self.notifier,'configured',True):
            self.store.execute("UPDATE unanswered_questions SET state='delivery_failed',error='Discord is not configured' WHERE id=?",(question['id'],))
            self.store.execute("UPDATE escalation_outbox SET state='blocked',error='Discord is not configured' WHERE id=?",(question['id'],))
            answer=f"I couldn't reach {session.owner_name} in Discord. I've kept the question in the meeting notes."
        else:
            answer=f"I'll ask {session.owner_name} in Discord."
        self._event(self.store.one('SELECT * FROM unanswered_questions WHERE id=?',(question['id'],)))
        return AgentDecision(action='answer',reason='urgent confirmation',answer=answer)

    async def run_once(self):
        with self.repository._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT * FROM escalation_outbox WHERE state='queued' AND next_at<=? ORDER BY rowid LIMIT 1",(self.clock(),)).fetchone()
            if not row: return False
            job=dict(row)
            db.execute("UPDATE escalation_outbox SET state='processing',attempts=attempts+1 WHERE id=?",(job['id'],))
        question=self.store.one('SELECT * FROM unanswered_questions WHERE id=?',(job['question_id'],))
        try:
            if self.notifier is None: raise DeliveryError('Discord is not configured')
            ref=await self.notifier.send_question(question)
        except Exception as error:
            retry=isinstance(error,DeliveryError) and error.retry_after is not None and not error.ambiguous and job['attempts']<4
            message=str(error) if isinstance(error,DeliveryError) else type(error).__name__
            self.store.execute('UPDATE escalation_outbox SET state=?,next_at=?,error=? WHERE id=?',
                ('queued' if retry else 'needs_attention',self.clock()+(getattr(error,'retry_after',None) or 0),message,job['id']))
            if not retry:
                self.store.execute("UPDATE unanswered_questions SET state=CASE WHEN state='answered' THEN state ELSE 'delivery_failed' END,error=? WHERE id=?",(message,question['id']))
        else:
            with self.repository._connect() as db:
                db.execute("UPDATE unanswered_questions SET state=CASE WHEN state='answered' THEN state ELSE 'awaiting_owner' END,parent_message_id=?,thread_id=?,error=NULL WHERE id=?",(ref.parent_message_id,ref.thread_id,question['id']))
                db.execute("UPDATE escalation_outbox SET state='sent',parent_message_id=?,thread_id=?,error=NULL WHERE id=?",(ref.parent_message_id,ref.thread_id,job['id']))
        self._event(self.store.one('SELECT * FROM unanswered_questions WHERE id=?',(question['id'],)))
        return True

    async def _ack(self,question,text,key):
        if not hasattr(self.notifier,'acknowledge'): return
        try: await self.notifier.acknowledge(question,text,key)
        except Exception:
            self.repository.record_event(question['session_id'],'discord.ack_failed',{'question_id':question['id'],'reply_id':key})

    async def receive_owner_reply(self,reply):
        settings=self.settings
        if not settings or reply.guild_id!=settings.discord_guild_id or reply.author_id!=settings.discord_owner_user_id:
            return 'ignored'
        if reply.is_bot or reply.is_webhook or reply.is_edit or reply.has_attachments or not reply.text.strip():
            return 'ignored'
        question=self.store.one('SELECT * FROM unanswered_questions WHERE thread_id=?',(reply.channel_id,))
        if not question and reply.channel_id==settings.discord_escalation_channel_id and reply.parent_message_id:
            question=self.store.one('SELECT * FROM unanswered_questions WHERE parent_message_id=?',(reply.parent_message_id,))
        if not question: return 'ignored'
        sid=question['session_id']
        async with self.meeting.locks.setdefault(sid,asyncio.Lock()):
            previous=self.store.one('SELECT * FROM owner_replies WHERE id=?',(reply.message_id,))
            if previous: return 'queued' if previous['state'] in {'pending','processing','queued'} else previous['state']
            if len(reply.text)>2000:
                self.store.execute("INSERT INTO owner_replies VALUES(?,?,?,?,?,NULL)",(reply.message_id,question['id'],reply.text,reply.created_at.isoformat(),'too_long'))
                await self._ack(question,'Please shorten your answer to 2,000 characters or fewer; it has not been spoken.',reply.message_id+':long')
                return 'too_long'
            now=datetime.now(UTC).isoformat()
            from .knowledge import MAX_MEETING_CHARS
            with self.repository._connect() as db:
                current=db.execute('SELECT COALESCE(SUM(length(content)),0) FROM knowledge_sources WHERE session_id=?',(sid,)).fetchone()[0]
                full=current+len(reply.text)>MAX_MEETING_CHARS
                db.execute('INSERT INTO owner_replies VALUES(?,?,?,?,?,?)',(reply.message_id,question['id'],reply.text,reply.created_at.isoformat(),'needs_attention' if full else 'pending','Knowledge limit reached; answer saved but not spoken' if full else None))
                if not full:
                    self.meeting.knowledge._store(db,sid,'discord:'+reply.message_id,'discord_owner','Owner reply '+reply.message_id,None,[(f'Discord message {reply.message_id}',reply.text)],now)
                    db.execute('INSERT INTO qa_log VALUES(?,?,?,?,?,?)',('discord:'+reply.message_id,sid,question['question'],reply.text,'[]',now))
                    db.execute("UPDATE unanswered_questions SET state='answered',error=NULL WHERE id=?",(question['id'],))
            self._event(self.store.one('SELECT * FROM unanswered_questions WHERE id=?',(question['id'],)))
            self.repository.record_event(sid,'owner.reply',{'id':reply.message_id,'question_id':question['id'],'text':reply.text,'state':'needs_attention' if full else 'pending'})
            if full: return 'needs_attention'
            return await self._relay(reply.message_id,question)

    async def _relay(self,message_id,question):
        sid=question['session_id']
        reply=self.store.one('SELECT * FROM owner_replies WHERE id=?',(message_id,))
        if reply['state']!='pending': return reply['state']
        if not await self.meeting.playback.is_live(sid):
            self.store.execute("UPDATE owner_replies SET state='saved_after_end' WHERE id=?",(message_id,))
            await self._ack(question,'Saved in the meeting notes; not spoken because the meeting has ended.',message_id+':ended')
            if getattr(self.meeting,'minutes',None): self.meeting.minutes.schedule(sid)
            return 'saved_after_end'
        if getattr(self.meeting.playback,'muted',lambda _:False)(sid) or not getattr(self.meeting.playback,'available',lambda _:True)(sid):
            return 'queued'
        self.store.execute("UPDATE owner_replies SET state='processing' WHERE id=? AND state='pending'",(message_id,))
        session=self.repository.get_session(sid)
        try:
            await self.meeting.queue_speech(sid,f'{session.owner_name} says: {reply["text"]}','discord:'+message_id)
        except Exception:
            live=await self.meeting.playback.is_live(sid)
            state='needs_attention' if live else 'saved_after_end'
            self.store.execute('UPDATE owner_replies SET state=?,error=? WHERE id=?',(state,'Playback did not complete; do not replay without checking',message_id))
            if not live:
                if getattr(self.meeting,'minutes',None): self.meeting.minutes.schedule(sid)
                await self._ack(question,'Saved in the meeting notes; not spoken because the meeting has ended.',message_id+':ended')
            return state
        self.store.execute("UPDATE owner_replies SET state='queued' WHERE id=?",(message_id,))
        self.repository.record_event(sid,'owner.relay_queued',{'id':message_id,'question_id':question['id']})
        return 'queued'

    async def drain_replies(self):
        replies=self.store.all("SELECT r.id,r.question_id,q.session_id FROM owner_replies r JOIN unanswered_questions q ON q.id=r.question_id WHERE r.state='pending' ORDER BY r.created_at")
        attempted={}
        for reply in replies:
            sid=reply['session_id']
            lock=self.meeting.locks.setdefault(sid,asyncio.Lock())
            if lock.locked() or attempted.get(sid,0)>=4: continue
            attempted[sid]=attempted.get(sid,0)+1
            question=self.store.one('SELECT * FROM unanswered_questions WHERE id=?',(reply['question_id'],))
            async with lock:
                await self._relay(reply['id'],question)

    def owner_playback_failed(self,sid,message_id):
        message='Owner reply playback failed or was interrupted; check before replaying'
        self.store.execute("UPDATE owner_replies SET state='needs_attention',error=? WHERE id=? AND question_id IN (SELECT id FROM unanswered_questions WHERE session_id=?)",(message,message_id,sid))
        self.store.execute('UPDATE unanswered_questions SET error=? WHERE session_id=? AND id IN (SELECT question_id FROM owner_replies WHERE id=?)',(message,sid,message_id))
        self.repository.record_event(sid,'owner.relay_failed',{'id':message_id})

    def recover(self):
        self.store.execute("UPDATE escalation_outbox SET state='needs_attention',error='Interrupted send; reconcile before retrying' WHERE state='processing'")
        self.store.execute("UPDATE unanswered_questions SET state='delivery_failed',error='Interrupted send; reconcile before retrying' WHERE state='escalation_queued' AND id IN (SELECT question_id FROM escalation_outbox WHERE state='needs_attention')")
        for reply in self.store.all("SELECT r.id,q.session_id FROM owner_replies r JOIN unanswered_questions q ON q.id=r.question_id WHERE r.state='processing'"):
            self.owner_playback_failed(reply['session_id'],reply['id'])
        self.store.execute("UPDATE speech_intents SET state='needs_attention' WHERE state='processing'")
        recall=getattr(self.meeting.playback,'recall',None)
        if recall:
            def uncertain(key):
                audio=recall.store.one('SELECT state,expires FROM recall_audio WHERE id=?',(key,))
                return not audio or audio['state'] in {'failed','expired','cancelled','playing'} or (audio['state']!='played' and audio['expires']<self.clock())
            for reply in self.store.all("SELECT r.id,q.session_id FROM owner_replies r JOIN unanswered_questions q ON q.id=r.question_id WHERE r.state='queued'"):
                key='discord:'+reply['id']
                if uncertain(key):
                    self.owner_playback_failed(reply['session_id'],reply['id'])
                    self.store.execute("UPDATE speech_intents SET state='needs_attention' WHERE id=?",(key,))
            for question in self.store.all("SELECT session_id,prompt_key FROM unanswered_questions WHERE state='awaiting_urgency'"):
                if uncertain(question['prompt_key']): self.cancel_prompt(question['session_id'],question['prompt_key'])

    async def worker(self):
        self.recover()
        while True:
            try:
                await self.drain_replies()
                if not await self.run_once(): await asyncio.sleep(0.25)
            except asyncio.CancelledError: raise
            except Exception: await asyncio.sleep(1)
