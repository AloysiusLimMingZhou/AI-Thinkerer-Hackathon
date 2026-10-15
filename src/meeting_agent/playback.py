import time
from typing import Protocol
from fastapi import HTTPException
from .budget import PaidCallContext, paid_call_context


class Playback(Protocol):
    async def enqueue(self,session_id: str,text: str,key: str) -> str: ...
    async def is_live(self,session_id: str) -> bool: ...
    async def mute(self,session_id: str,muted: bool) -> None: ...
    async def stop(self,session_id: str) -> None: ...


class RecallPlayback:
    def __init__(self,recall):
        self.recall=recall
        with recall.repository._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS meeting_controls(session_id TEXT PRIMARY KEY,muted INTEGER NOT NULL DEFAULT 0)')

    async def is_live(self,sid):
        bot=self.recall.store.bot(sid)
        return bool(bot and bot['state'].startswith('in_call'))

    def muted(self,sid):
        row=self.recall.store.one('SELECT muted FROM meeting_controls WHERE session_id=?',(sid,))
        return bool(row and row['muted'])

    def available(self,sid):
        pending=self.recall.store.one("SELECT COUNT(*) AS n FROM recall_audio WHERE session_id=? AND expires>? AND state IN ('queued','playing')",(sid,time.time()))['n']
        return pending<2

    async def enqueue(self,sid,text,key):
        if not await self.is_live(sid) or self.muted(sid):
            raise HTTPException(409,'Meeting is not live or speech is muted')
        existing=self.recall.store.one('SELECT id FROM recall_audio WHERE id=?',(key,))
        if existing: return key
        if not self.available(sid): raise HTTPException(409,'Reply queue is full')
        started=time.perf_counter()
        with paid_call_context(PaidCallContext(sid, f'speech:{key}', 'speech')):
            audio=await self.recall.voice.generate(text)
        if not await self.is_live(sid) or self.muted(sid):
            raise HTTPException(409,'Meeting ended or speech was muted before playback')
        if not self.available(sid): raise HTTPException(409,'Reply queue is full')
        self.recall.store.add_audio(sid,text,audio,key)
        return key

    async def stop(self,sid):
        pending=self.recall.store.all("SELECT id FROM recall_audio WHERE session_id=? AND state IN ('queued','playing')",(sid,))
        self.recall.store.execute("UPDATE recall_audio SET state='cancelled',audio=X'' WHERE session_id=? AND state IN ('queued','playing')",(sid,))
        for item in pending:
            await self.recall.meeting.playback_failed(sid,item['id'])
        self.recall.repository.record_event(sid,'voice.stopped',{})

    async def mute(self,sid,muted):
        self.recall.store.execute('INSERT INTO meeting_controls VALUES(?,?) ON CONFLICT(session_id) DO UPDATE SET muted=excluded.muted',(sid,int(muted)))
        if muted: await self.stop(sid)


class PreviewPlayback:
    async def is_live(self,sid): return False
    async def enqueue(self,sid,text,key): return key
    async def mute(self,sid,muted): pass
    async def stop(self,sid): pass
