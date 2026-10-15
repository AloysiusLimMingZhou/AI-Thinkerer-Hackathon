"""Generation-fenced, durable Discord speech. Only a playback ACK confirms delivery."""
import asyncio,base64,json
from fastapi import HTTPException
from .budget import BudgetExceeded,PaidCallContext,paid_call_context
from .discord_protocol import command,MAX_MP3

class DiscordPlayback:
    def __init__(self,store,worker,voice):
        self.store,self.worker,self.voice=store,worker,voice
        self.meeting=None;self.on_budget=None;self.locks={}
        store.execute("CREATE TABLE IF NOT EXISTS discord_speech(id TEXT PRIMARY KEY,session_id TEXT,generation TEXT,state TEXT)")
    def _row(self,sid):return self.store.attendance(sid)
    def _connected(self,sid):
        row=self._row(sid)
        return bool(row and row['state']=='active' and json.loads(row['health_json']).get('receiver'))
    async def is_live(self,sid):
        row=self._row(sid)
        return self._connected(sid) and row['introduction']=='completed'
    def muted(self,sid):
        row=self._row(sid);return bool(row and row['muted'])
    def available(self,sid):
        return self.store.one("SELECT COUNT(*) AS n FROM discord_speech WHERE session_id=? AND state IN ('processing','queued','playing')",(sid,))['n']<2
    async def enqueue(self,sid,text,key):
        async with self.locks.setdefault(sid,asyncio.Lock()):
            if not self._connected(sid) or self.muted(sid):raise HTTPException(409,'Discord voice is not live or is muted')
            row=self._row(sid);generation=row['generation']
            if row['introduction']!='completed' and key!='intro:'+sid:raise HTTPException(409,'Delegate introduction has not completed')
            prior=self.store.one('SELECT * FROM discord_speech WHERE id=?',(key,))
            if prior:
                if prior['session_id']!=sid or prior['generation']!=generation:raise HTTPException(409,'Speech identity mismatch')
                return key
            if not self.available(sid):raise HTTPException(409,'Reply queue is full')
            self.store.execute("INSERT INTO discord_speech VALUES(?,?,?,'processing')",(key,sid,generation))
            try:
                with paid_call_context(PaidCallContext(sid,'speech:'+key,'speech')):audio=await self.voice.generate(text)
                if not audio or len(audio)>MAX_MP3:raise ValueError('Invalid speech audio')
                current=self._row(sid)
                pending=self.store.one('SELECT state FROM discord_speech WHERE id=?',(key,))['state']
                if not self._connected(sid) or current['generation']!=generation or self.muted(sid) or pending!='processing':raise HTTPException(409,'Speech cancelled before playback')
                self.store.execute("UPDATE discord_speech SET state='queued' WHERE id=?",(key,))
                await self.worker.request(command('play',session_id=sid,generation=generation,key=key,audio_base64=base64.b64encode(audio).decode()))
                return key
            except BudgetExceeded:
                self.store.execute("UPDATE discord_speech SET state='failed' WHERE id=?",(key,))
                if self.on_budget:await self.on_budget(sid)
                raise
            except BaseException:
                self.store.execute("UPDATE discord_speech SET state='needs_attention' WHERE id=? AND state IN ('processing','queued','playing')",(key,))
                raise

    async def acknowledge(self,e):
        row=self._row(e.session_id)
        speech=self.store.one('SELECT * FROM discord_speech WHERE id=?',(e.key,))
        if not row or row['generation']!=e.generation or row['state']!='active' or not speech or speech['session_id']!=e.session_id or speech['generation']!=e.generation:return
        allowed={'queued':{'queued'},'playing':{'queued','playing'},'completed':{'playing'},'failed':{'queued','playing'},'cancelled':{'processing','queued','playing'}}
        if speech['state'] not in allowed[e.state]:return
        self.store.execute('UPDATE discord_speech SET state=? WHERE id=?',(e.state,e.key))
        self.store.execute('UPDATE speech_intents SET state=? WHERE id=? AND session_id=?',(e.state,e.key,e.session_id))
        if e.key=='intro:'+e.session_id:
            self.store.execute('UPDATE discord_attendance SET introduction=? WHERE session_id=?',(e.state,e.session_id))
        if e.state=='completed':
            if e.key.startswith('discord:'):
                self.store.execute("UPDATE owner_replies SET state='spoken',error=NULL WHERE id=? AND question_id IN (SELECT id FROM unanswered_questions WHERE session_id=?)",(e.key.removeprefix('discord:'),e.session_id))
            self.store.repository.record_event(e.session_id,'voice.played',{'id':e.key})
        elif e.state in {'failed','cancelled'} and self.meeting:await self.meeting.playback_failed(e.session_id,e.key)
        if e.key=='intro:'+e.session_id and e.state in {'failed','cancelled'}:
            self.store.execute("UPDATE discord_attendance SET error='Introduction did not complete; speech disabled' WHERE session_id=?",(e.session_id,))

    async def stop(self,sid):
        row=self._row(sid)
        if not row:return
        pending=self.store.all("SELECT id FROM discord_speech WHERE session_id=? AND state IN ('processing','queued','playing')",(sid,))
        self.store.execute("UPDATE discord_speech SET state='cancelled' WHERE session_id=? AND state IN ('processing','queued','playing')",(sid,))
        for item in pending:
            if self.meeting:await self.meeting.playback_failed(sid,item['id'])
        if row['state'] in {'joining','active','leaving'}:await self.worker.request(command('stop',session_id=sid,generation=row['generation']))
    async def mute(self,sid,muted):
        row=self._row(sid)
        if not row:raise HTTPException(404,'Attendance not found')
        self.store.execute('UPDATE discord_attendance SET muted=? WHERE session_id=?',(int(muted),sid))
        if muted:await self.stop(sid)
        await self.worker.request(command('mute',session_id=sid,generation=row['generation'],muted=muted))
    async def recover(self):
        for row in self.store.all("SELECT * FROM discord_speech WHERE state IN ('processing','queued','playing')"):
            self.store.execute("UPDATE discord_speech SET state='needs_attention' WHERE id=?",(row['id'],))
            if self.meeting:await self.meeting.playback_failed(row['session_id'],row['id'])
