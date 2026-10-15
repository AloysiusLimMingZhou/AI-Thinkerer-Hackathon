"""One transcript-to-decision pipeline for all meeting transports."""
import asyncio
import hashlib
import json
import re
import time
from datetime import UTC, datetime

from .meeting_models import BrainAnswer, UNKNOWN_ANSWER
from .models import AgentDecision, Citation, UtteranceCreate
from .services import conversation_gate
from .budget import PaidCallContext, paid_call_context


def social_request(text,name):
    text=re.sub(r'(?<!\w)'+re.escape(name)+r'(?!\w)','',text,flags=re.I)
    text=' '.join(re.sub(r'[^\w\s]',' ',text).lower().split())
    return bool(re.fullmatch(r'(?:hi|hey|hello|thanks|thank you|hi how are you|how are you|who are you|what is your name|got it|okay|ok)',text))


def grounded_result(result,chunks,allow_social=False):
    if not isinstance(result,BrainAnswer):
        return UNKNOWN_ANSWER,[],'defer'
    if result.kind=='social' and allow_social and result.text.strip():
        return result.text.strip(),[],'answer'
    by_id={chunk.id:chunk for chunk in chunks}
    citations=[]
    if result.kind=='supported' and result.text.strip() and result.evidence:
        for evidence in result.evidence:
            chunk=by_id.get(evidence.chunk_id)
            if not chunk or not evidence.quote.strip() or evidence.quote not in chunk.text:
                return UNKNOWN_ANSWER,[],'defer'
            citations.append(Citation(id=chunk.id,source=chunk.source,title=chunk.title,
                filename=chunk.filename,locator=chunk.locator,quote=evidence.quote))
        return result.text.strip(),citations,'answer'
    return UNKNOWN_ANSWER,[],'defer'


class MeetingService:
    def __init__(self,repository,brain,knowledge,playback):
        self.repository,self.brain,self.knowledge,self.playback=repository,brain,knowledge,playback
        self.locks={}
        self.escalations=None
        with repository._connect() as db:
            columns={r[1] for r in db.execute('PRAGMA table_info(transcript)')}
            if 'participant_id' not in columns: db.execute('ALTER TABLE transcript ADD COLUMN participant_id TEXT')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS meeting_inputs(id TEXT PRIMARY KEY,session_id TEXT,state TEXT,decision TEXT);
                CREATE TABLE IF NOT EXISTS speech_intents(id TEXT PRIMARY KEY,session_id TEXT,text TEXT,state TEXT);
            ''')

    async def ingest(self,sid,utterance,*,preview=False):
        async with self.locks.setdefault(sid,asyncio.Lock()):
            with paid_call_context(PaidCallContext(sid, f'ingest:{utterance.platform}:{utterance.event_id}', 'ingest')):
                return await self._ingest(sid,utterance,preview)

    async def _ingest(self,sid,u,preview):
        key=hashlib.sha256(f'{sid}:{u.platform}:{u.event_id}'.encode()).hexdigest()
        session=self.repository.get_session(sid)
        if not session: raise ValueError('Unknown session')
        with self.repository._connect() as db:
            prior=db.execute('SELECT decision FROM meeting_inputs WHERE id=?',(key,)).fetchone()
            if prior and prior['decision'] and u.is_final:
                previous=AgentDecision.model_validate_json(prior['decision'])
                if previous.reason=='waiting for final caption':
                    db.execute('DELETE FROM meeting_inputs WHERE id=?',(key,))
                    prior=None
            if prior:
                return AgentDecision.model_validate_json(prior['decision']) if prior['decision'] else AgentDecision(action='stay_silent',reason='Interrupted input needs attention')
            db.execute('INSERT INTO meeting_inputs VALUES(?,?,?,NULL)',(key,sid,'processing'))
        is_self=u.is_self or u.speaker.casefold() in {session.agent_name.casefold(),f'{session.agent_name} (AI delegate)'.casefold()}
        if is_self:
            decision=AgentDecision(action='stay_silent',reason='agent own voice')
            self._decision(sid,key,decision)
            return decision
        entry=self.repository.add_transcript(sid,UtteranceCreate(speaker=u.speaker[:100],text=u.text,is_final=u.is_final,spoken_at=u.spoken_at))
        with self.repository._connect() as db:
            db.execute('UPDATE transcript SET participant_id=? WHERE id=?',(u.participant_id,entry.id))
        self.repository.record_event(sid,'transcript.utterance',{**entry.model_dump(mode='json'),'participant_id':u.participant_id})
        history=self.repository.get_transcript(sid)
        qa=self.repository.get_qa_log(sid)
        if self.escalations and not preview and u.is_final and not getattr(self.playback,'muted',lambda _:False)(sid) and await self.playback.is_live(sid) and (datetime.now(UTC)-u.received_at).total_seconds()<=30:
            confirmation=self.escalations.handle_confirmation(sid,u)
            if confirmation:
                self.repository.add_qa(sid,u.text,confirmation.answer or '',[])
                self._decision(sid,key,confirmation,entry.id)
                await self.queue_speech(sid,confirmation.answer or '',key)
                return confirmation
        approved,reason=conversation_gate(u.text,speaker=u.speaker,session=session,transcript=history,qa_log=qa,force_answer=u.force_answer)
        if not u.is_final and not u.force_answer:
            approved,reason=False,'waiting for final caption'
        if not preview:
            if (datetime.now(UTC)-u.received_at).total_seconds()>30:
                approved,reason=False,'stale transcript'
            elif not await self.playback.is_live(sid):
                approved,reason=False,'meeting ended'
            elif getattr(self.playback,'muted',lambda _:False)(sid):
                approved,reason=False,'speech muted'
            elif hasattr(self.playback,'recall'):
                pending=self.playback.recall.store.one("SELECT COUNT(*) AS n FROM recall_audio WHERE session_id=? AND expires>? AND state IN ('queued','playing')",(sid,time.time()))['n']
                if pending>=2: approved,reason=False,'reply queue full'
        if not approved:
            decision=AgentDecision(action='stay_silent',reason=reason)
            self._decision(sid,key,decision,entry.id)
            return decision
        query=u.text
        if qa and reason=='same-speaker conversation follow-up': query=str(qa[-1]['question'])+' '+query
        chunks=self.knowledge.search(sid,query)
        social=social_request(u.text,session.agent_name)
        started=time.perf_counter()
        if chunks or social:
            result=await self.brain.answer(session,u.text,self.repository.get_dialogue(sid),chunks)
            answer,citations,action=grounded_result(result,chunks,social)
        else:
            answer,citations,action=UNKNOWN_ANSWER,[],'defer'
        self.repository.add_qa(sid,u.text,answer,citations)
        decision=AgentDecision(action=action,reason='knowledge unavailable' if action=='defer' else reason,answer=answer,citations=citations)
        if action=='defer' and not preview and self.escalations:
            self.escalations.open_question(sid,u,key,entry.id)
        self._decision(sid,key,decision,entry.id,round((time.perf_counter()-started)*1000))
        if not preview:
            if (datetime.now(UTC)-u.received_at).total_seconds()<=60:
                await self.queue_speech(sid,answer,key,round((time.perf_counter()-started)*1000))
        return decision

    def _decision(self,sid,key,decision,utterance_id=None,answer_ms=None):
        with self.repository._connect() as db:
            db.execute("UPDATE meeting_inputs SET state='done',decision=? WHERE id=?",(decision.model_dump_json(),key))
        payload=decision.model_dump(mode='json')
        payload.update(utterance_id=utterance_id,answer_ms=answer_ms)
        self.repository.record_event(sid,'agent.decision',payload)

    async def queue_speech(self,sid,text,key,answer_ms=0):
        with self.repository._connect() as db:
            inserted=db.execute("INSERT OR IGNORE INTO speech_intents VALUES(?,?,?,'processing')",(key,sid,text)).rowcount
        if not inserted: return
        started=time.perf_counter()
        try:
            await self.playback.enqueue(sid,text,key)
        except Exception:
            with self.repository._connect() as db: db.execute("UPDATE speech_intents SET state='needs_attention' WHERE id=?",(key,))
            self.repository.record_event(sid,'voice.failed',{'id':key})
            await self.playback_failed(sid,key)
            raise
        with self.repository._connect() as db: db.execute("UPDATE speech_intents SET state='queued' WHERE id=?",(key,))
        voice_ms=round((time.perf_counter()-started)*1000)
        self.repository.record_event(sid,'voice.queued',{'id':key,'answer_ms':answer_ms,'voice_ms':voice_ms,'response_ready_ms':answer_ms+voice_ms})

    async def playback_failed(self,sid,key):
        with self.repository._connect() as db:
            db.execute("UPDATE speech_intents SET state='failed' WHERE id=? AND session_id=?",(key,sid))
        if self.escalations:
            self.escalations.cancel_prompt(sid,key)
            if key.startswith('discord:'):
                message_id=key.removeprefix('discord:')
                self.escalations.owner_playback_failed(sid,message_id)
