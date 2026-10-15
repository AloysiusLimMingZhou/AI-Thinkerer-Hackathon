"""Bounded full-meeting finalization, independent of the transport's call state."""
import asyncio
import hashlib
import json
import time
from datetime import UTC,datetime
from fastapi import HTTPException
from uuid import uuid4
from .budget import BudgetExceeded,PaidCallContext,paid_call_context

LIMIT=30000


def batches(records):
    current=''
    for record in records:
        for offset in range(0,len(record),LIMIT):
            piece=record[offset:offset+LIMIT]
            if current and len(current)+len(piece)+2>LIMIT:
                yield current; current=''
            current+=('\n\n' if current else '')+piece
    if current: yield current


def transcript_records(entries):
    for item in sorted((t for t in entries if t.is_final),key=lambda t:(t.spoken_at,t.id)):
        header=f'[{item.spoken_at.isoformat()}] {item.speaker}: '
        # Repeat provenance when a single utterance needs several segments.
        width=max(1,LIMIT-len(header))
        for offset in range(0,len(item.text),width): yield header+item.text[offset:offset+width]


class MinutesService:
    def __init__(self,repository,brain,escalations):
        self.repository,self.brain,self.escalations=repository,brain,escalations
        self.store=escalations.store
        self.locks={}; self.clock=time.time
        self.transcript=repository.get_transcript
        self.store.execute('''CREATE TABLE IF NOT EXISTS finalizations(
            session_id TEXT PRIMARY KEY REFERENCES sessions(id),state TEXT NOT NULL,error TEXT,
            fingerprint TEXT,updated_at TEXT NOT NULL,pending INTEGER NOT NULL DEFAULT 0,
            revision INTEGER NOT NULL DEFAULT 0,waiting_until REAL)''')
        self.store.execute('CREATE TABLE IF NOT EXISTS minutes_stages(session_id TEXT,fingerprint TEXT,stage_key TEXT,result TEXT,PRIMARY KEY(session_id,fingerprint,stage_key))')
        self.store.execute('CREATE TABLE IF NOT EXISTS minutes_attempts(id TEXT PRIMARY KEY,session_id TEXT,fingerprint TEXT,stage_key TEXT,state TEXT)')

    def status(self,sid):
        self.store.execute("UPDATE finalizations SET state='failed',error='Final transcript has not arrived. Check Recall processing, then retry minutes.',waiting_until=NULL,pending=0 WHERE session_id=? AND state='processing' AND waiting_until<?",(sid,self.clock()))
        return self.store.one('SELECT * FROM finalizations WHERE session_id=?',(sid,)) or {'session_id':sid,'state':'idle','error':None}

    def _processing(self,sid,*,pending=0,waiting_until=None):
        now=datetime.now(UTC).isoformat()
        self.store.execute("INSERT INTO finalizations(session_id,state,updated_at,pending,waiting_until) VALUES(?,'processing',?,?,?) ON CONFLICT(session_id) DO UPDATE SET state='processing',error=NULL,updated_at=excluded.updated_at,pending=excluded.pending,waiting_until=excluded.waiting_until,revision=finalizations.revision+1",(sid,now,pending,waiting_until))
        self.repository.record_event(sid,'minutes.processing',{})

    def wait_for_transcript(self,sid):
        previous=self.status(sid)
        # Repeated transport departures must not restart an already completed or timed-out wait.
        if previous['state']!='failed' and not previous.get('waiting_until'):
            self._processing(sid,waiting_until=self.clock()+300)

    def schedule(self,sid):
        previous=self.status(sid)
        if previous['state'] in {'pending_budget','failed'}:
            if previous['state']=='pending_budget':self.pending_budget(sid)
            return
        self._processing(sid,pending=1,waiting_until=previous.get('waiting_until'))

    def _appendix(self,sid):
        questions=self.escalations.questions(sid)
        replies=self.store.all('SELECT r.*,q.question FROM owner_replies r JOIN unanswered_questions q ON q.id=r.question_id WHERE q.session_id=? ORDER BY r.created_at,r.id',(sid,))
        parts=[]
        if questions:
            parts.append('## Tracked questions\n'+ '\n'.join(f'- [{q["state"]}] {q["speaker"]}: {q["question"]}' for q in questions))
        accepted=[r for r in replies if r['state']!='too_long']
        if accepted:
            parts.append('## Owner replies\n'+'\n'.join(f'- Discord message {r["id"]} [{r["state"]}] — {r["question"]}\n  {r["text"]}' for r in accepted))
        gaps=[e for e in self.repository.get_events(sid) if e['type']=='discord.audio_gap']
        if gaps:
            parts.append('## Capture gaps\n'+'\n'.join(f'- {e["payload"].get("spoken_at", e["created_at"])}: {e["payload"].get("reason","audio unavailable")}' for e in gaps))
        return '\n\n'.join(parts)

    async def finalize(self,sid,transcript):
        async with self.locks.setdefault(sid,asyncio.Lock()):
            session=self.repository.get_session(sid)
            if not session: raise HTTPException(404,'Session not found')
            records=list(transcript_records(transcript))
            appendix=self._appendix(sid)
            qa=[f'Assistant Q&A: {q["question"]}\n{q["answer"]}' for q in self.repository.get_qa_log(sid)]
            fingerprint=hashlib.sha256(json.dumps([session.title,session.owner_name,records,qa,appendix],ensure_ascii=False).encode()).hexdigest()
            previous=self.status(sid)
            existing=self.repository.get_minutes(sid)
            if previous['state']=='ready' and previous.get('fingerprint')==fingerprint and existing: return existing
            self._processing(sid)
            revision=self.status(sid)['revision']
            try:
                if not records and not appendix: raise HTTPException(409,'Cannot generate empty minutes')
                material=list(batches(records+qa+([appendix] if appendix else [])))
                if len(material)>1:
                    summaries=[await self._stage(sid,fingerprint,'segment:'+str(index),part,synthesis=False) for index,part in enumerate(material)]
                    # Include short authoritative appendices verbatim in the final synthesis too.
                    tail='\n\n'+appendix if len(appendix)<LIMIT//2 else ''
                    for _ in range(8):
                        joined='\n\n'.join(summaries)
                        if len(joined+tail)<=LIMIT:
                            material=[joined+tail]; break
                        reduced=[await self._stage(sid,fingerprint,f'reduce:{_}:{index}',part,synthesis=False) for index,part in enumerate(batches(summaries))]
                        if len('\n\n'.join(reduced))>=len(joined): raise RuntimeError('Summary did not compress')
                        summaries=reduced
                    else: raise RuntimeError('Too many summary levels')
                content=await self._stage(sid,fingerprint,'final',material[0],synthesis=True)
                if not content.strip(): raise RuntimeError('Empty minutes output')
                if appendix: content+='\n\n'+appendix
                minutes=self.repository.save_minutes(sid,content)
                self.store.execute("UPDATE finalizations SET state=CASE WHEN revision=? THEN 'ready' ELSE 'processing' END,fingerprint=?,error=NULL,updated_at=? WHERE session_id=?",(revision,fingerprint,minutes.updated_at.isoformat(),sid))
                self.repository.record_event(sid,'minutes.generated',minutes.model_dump(mode='json'))
                return minutes
            except BudgetExceeded:
                self.pending_budget(sid,fingerprint=fingerprint)
                raise
            except Exception as error:
                message='No final text is available yet.' if isinstance(error,HTTPException) else 'Minutes generation failed. Check model configuration and retry.'
                self.store.execute("UPDATE finalizations SET state='failed',error=?,pending=0,waiting_until=NULL WHERE session_id=? AND revision=?",(message,sid,revision))
                self.repository.record_event(sid,'minutes.failed',{'error':message})
                raise

    async def run_once(self):
        row=self.store.one("SELECT session_id FROM finalizations WHERE state='processing' AND pending=1 AND waiting_until IS NULL ORDER BY updated_at LIMIT 1")
        if not row: return False
        sid=row['session_id']
        self.store.execute('UPDATE finalizations SET pending=0 WHERE session_id=?',(sid,))
        try: await self.finalize(sid,self.transcript(sid))
        except Exception: pass  # finalize persists a sanitized, visible failure.
        return True

    def recover(self):
        self.store.execute("UPDATE finalizations SET state='failed',error='Finalization interrupted. Retry minutes.' WHERE state='processing' AND pending=0 AND waiting_until IS NULL")

    async def worker(self):
        self.recover()
        while True:
            if not await self.run_once(): await asyncio.sleep(0.5)


    async def _stage(self,session_id,fingerprint,stage_key,material,*,synthesis):
        cached=self.store.one('SELECT result FROM minutes_stages WHERE session_id=? AND fingerprint=? AND stage_key=?',(session_id,fingerprint,stage_key))
        if cached:return cached['result']
        attempt=str(uuid4())
        self.store.execute("INSERT INTO minutes_attempts VALUES(?,?,?,?,'processing')",(attempt,session_id,fingerprint,stage_key))
        try:
            with paid_call_context(PaidCallContext(session_id,'minutes:'+attempt,'minutes')):
                result=await self.brain.summarize_minutes(self.repository.get_session(session_id),material,synthesis=synthesis)
            if not result.strip():raise RuntimeError('Empty summary')
            with self.repository._connect() as db:
                db.execute('INSERT OR REPLACE INTO minutes_stages VALUES(?,?,?,?)',(session_id,fingerprint,stage_key,result))
                db.execute("UPDATE minutes_attempts SET state='completed' WHERE id=?",(attempt,))
            return result
        except BudgetExceeded:
            self.store.execute("UPDATE minutes_attempts SET state='blocked' WHERE id=?",(attempt,));raise
        except BaseException:
            self.store.execute("UPDATE minutes_attempts SET state='uncertain' WHERE id=?",(attempt,));raise

    def pending_budget(self,sid,*,fingerprint=None):
        now=datetime.now(UTC).isoformat()
        self.store.execute("INSERT INTO finalizations(session_id,state,error,updated_at) VALUES(?,'pending_budget','Monthly AI budget cannot cover notes. Generate notes manually after reset or a configuration change.',?) ON CONFLICT(session_id) DO UPDATE SET state='pending_budget',error=excluded.error,updated_at=excluded.updated_at,pending=0,waiting_until=NULL",(sid,now))
        if fingerprint:
            partial=self.store.all('SELECT result FROM minutes_stages WHERE session_id=? AND fingerprint=? ORDER BY stage_key',(sid,fingerprint))
        else:partial=[]
        appendix=self._appendix(sid)
        content='# Notes awaiting AI budget\n\nThe transcript is saved. A complete model summary has not been generated.'
        if partial:content+='\n\n## Partial summaries\n\n'+'\n\n'.join(p['result'] for p in partial)
        if appendix:content+='\n\n'+appendix
        self.repository.save_minutes(sid,content)
        self.repository.record_event(sid,'minutes.pending_budget',{})
