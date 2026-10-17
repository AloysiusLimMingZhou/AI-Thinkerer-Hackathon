"""Bounded STT dispatch, stable identity and raw-audio disposal."""
import asyncio
from datetime import UTC,datetime
from .discord_protocol import decode_media,MAX_WAV
from .meeting_models import MeetingUtterance
from .budget import BudgetExceeded
from .transcription import audio_duration

class DiscordAudio:
    def __init__(self,transcriber,meeting,attendance):
        self.transcriber,self.meeting,self.attendance=transcriber,meeting,attendance
        self.semaphore=asyncio.Semaphore(2);self.tasks={};self.tails={};self.waiting_tasks=set();self.closed=False
        attendance.store.execute("CREATE TABLE IF NOT EXISTS discord_audio_inputs(id TEXT PRIMARY KEY,session_id TEXT,generation TEXT,state TEXT)")
    def valid(self,e):
        row=self.attendance.store.attendance(e.session_id)
        return bool(row and row['generation']==e.generation and row['state']=='active')
    def gap(self,e,reason):
        self.attendance.repository.record_event(e.session_id,'discord.audio_gap',{'event_id':e.event_id,'participant_id':e.participant_id,'spoken_at':e.spoken_at.isoformat(),'reason':reason})
    async def submit(self,event):
        if self.closed or not self.valid(event) or event.participant_id==getattr(self.attendance.worker,'self_id',None) or event.is_bot or event.is_self:return False
        id=event.session_id+':'+event.event_id
        inserted=self.attendance.store.execute("INSERT OR IGNORE INTO discord_audio_inputs VALUES(?,?,?,'pending')",(id,event.session_id,event.generation))
        if not inserted:return False
        if len(self.waiting_tasks)>=8:
            self.gap(event,'transcription_queue_full');self.attendance.store.execute("UPDATE discord_audio_inputs SET state='gap' WHERE id=?",(id,));return False
        speaker=(event.session_id,event.participant_id);previous=self.tails.get(speaker)
        task=asyncio.create_task(self._process(id,event,previous));self.tasks[task]=(event.session_id,event.generation);self.tails[speaker]=task;self.waiting_tasks.add(task)
        def done(t):
            self.tasks.pop(t,None);self.waiting_tasks.discard(t)
            if self.tails.get(speaker) is t:self.tails.pop(speaker,None)
        task.add_done_callback(done);return True
    async def _process(self,id,e,previous):
        started=False
        try:
            if previous:
                try:await asyncio.shield(previous)
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():raise
            async with self.semaphore:
                self.waiting_tasks.discard(asyncio.current_task());started=True
                if not self.valid(e):return
                wav=decode_media(e.wav_base64,MAX_WAV);audio_duration(wav)
                self.attendance.store.execute("UPDATE discord_audio_inputs SET state='processing' WHERE id=?",(id,))
                text=await self.transcriber.transcribe(wav,session_id=e.session_id,event_id=e.event_id)
                del wav
                if not self.valid(e):return
                await self.meeting.ingest(e.session_id,MeetingUtterance(event_id=e.event_id,platform='discord',participant_id=e.participant_id,speaker=e.speaker,text=text,spoken_at=e.spoken_at,received_at=e.received_at))
                self.attendance.store.execute("UPDATE discord_audio_inputs SET state='done' WHERE id=?",(id,))
        except BudgetExceeded:
            self.gap(e,'monthly_budget_exhausted')
            await self.attendance.leave(e.session_id,reason='budget')
        except asyncio.CancelledError:
            self.gap(e,'transcription_cancelled');raise
        except Exception:
            self.gap(e,'transcription_or_reply_failed')
        finally:
            self.attendance.store.execute("UPDATE discord_audio_inputs SET state='gap' WHERE id=? AND state IN ('pending','processing')",(id,))
    async def drain(self):
        while self.tasks:await asyncio.gather(*list(self.tasks),return_exceptions=True)
    async def close_session(self,sid,generation):
        current=asyncio.current_task()
        targets=[t for t,(s,g) in self.tasks.items() if s==sid and g==generation and t is not current]
        for t in targets:t.cancel()
        await asyncio.gather(*targets,return_exceptions=True)
    async def cancel(self,sid):
        row=self.attendance.store.attendance(sid)
        if row:await self.close_session(sid,row['generation'])
    async def close(self):
        self.closed=True
        targets=list(self.tasks)
        for t in targets:t.cancel()
        await asyncio.gather(*targets,return_exceptions=True)
