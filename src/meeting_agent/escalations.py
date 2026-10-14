"""Persisted urgency confirmation; network side effects live in a separate outbox."""
import asyncio
import re
import time
from dataclasses import dataclass
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
        if u.speaker=='Unknown participant': return False
        if question['participant_id'] and u.participant_id:
            return question['participant_id']==u.participant_id
        return question['speaker'].casefold()==u.speaker.casefold()

    def cancel_prompt(self,sid,key):
        self.store.execute("UPDATE unanswered_questions SET state='urgency_expired',error='Prompt playback failed' WHERE session_id=? AND prompt_key=? AND state='awaiting_urgency'",(sid,key))

    def handle_confirmation(self,sid,u):
        if u.speaker=='Unknown participant' or not u.is_final:
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
                self.store.execute("UPDATE unanswered_questions SET state='delivery_failed',error=? WHERE id=?",(message,question['id']))
        else:
            with self.repository._connect() as db:
                db.execute("UPDATE unanswered_questions SET state='awaiting_owner',parent_message_id=?,thread_id=?,error=NULL WHERE id=?",(ref.parent_message_id,ref.thread_id,question['id']))
                db.execute("UPDATE escalation_outbox SET state='sent',parent_message_id=?,thread_id=?,error=NULL WHERE id=?",(ref.parent_message_id,ref.thread_id,job['id']))
        self._event(self.store.one('SELECT * FROM unanswered_questions WHERE id=?',(question['id'],)))
        return True

    def recover(self):
        self.store.execute("UPDATE escalation_outbox SET state='needs_attention',error='Interrupted send; reconcile before retrying' WHERE state='processing'")
        self.store.execute("UPDATE unanswered_questions SET state='delivery_failed',error='Interrupted send; reconcile before retrying' WHERE state='escalation_queued' AND id IN (SELECT question_id FROM escalation_outbox WHERE state='needs_attention')")

    async def worker(self):
        self.recover()
        while True:
            try:
                if not await self.run_once(): await asyncio.sleep(0.25)
            except asyncio.CancelledError: raise
            except Exception: await asyncio.sleep(1)
