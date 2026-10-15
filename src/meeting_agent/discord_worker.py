"""One supervised Node child, no shell, no AI credentials or public listening port."""
from __future__ import annotations
import asyncio,json,os,time
from pathlib import Path
from .discord_protocol import MAX_FRAME,parse_event,COMMAND,Response,WorkerHealth
class WorkerUnavailable(RuntimeError): pass
class DiscordWorker:
    def __init__(self,settings,*,process_factory=None):
        self.settings=settings
        self.factory=process_factory or asyncio.create_subprocess_exec
        self.process=None
        self.pending={}
        self.generations={}
        self.diagnostics=bytearray()
        self._health=WorkerHealth()
        self.last_health=0
        self._tasks=[]
        self._closing=False
        self._write_lock=asyncio.Lock()

    async def start(self):
        if self.process and self.process.returncode is None: return
        self._closing=False
        allowed={'PATH','PATHEXT','SYSTEMROOT','WINDIR','TEMP','TMP','COMSPEC','USERPROFILE','APPDATA','LOCALAPPDATA','PROGRAMFILES','PROGRAMFILES(X86)'}
        env={k:v for k,v in os.environ.items() if k.upper() in allowed}
        env['DISCORD_BOT_TOKEN']=self.settings.discord_bot_token or ''
        script=Path(__file__).resolve().parents[2]/'apps/discord-voice/src/worker.mjs'
        self.process=await self.factory(self.settings.discord_node_executable,str(script),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env,limit=MAX_FRAME+1)
        self.last_health=time.monotonic()
        self._tasks=[asyncio.create_task(self._stderr()),asyncio.create_task(self._watchdog())]
        await self._send(dict(protocol_version=1,type='config',guild_id=self.settings.discord_guild_id,owner_id=self.settings.discord_owner_user_id,ffmpeg_path=self.settings.discord_ffmpeg_executable,max_attendance_seconds=self.settings.discord_max_attendance_seconds))

    async def _send(self,item):
        raw=(json.dumps(item,separators=(',',':'))+'\n').encode()
        if len(raw)>MAX_FRAME: raise WorkerUnavailable('frame_too_large')
        async with self._write_lock:
            if not self.process or self.process.returncode is not None or not self.process.stdin: raise WorkerUnavailable('worker_offline')
            try: self.process.stdin.write(raw); await self.process.stdin.drain()
            except (BrokenPipeError,ConnectionResetError): raise WorkerUnavailable('worker_offline') from None

    async def request(self,command,*,timeout=15):
        item=COMMAND.validate_python(command.model_dump() if hasattr(command,'model_dump') else command)
        if len(self.pending)>=16: raise WorkerUnavailable('worker_busy')
        if not self.process or self.process.returncode is not None: raise WorkerUnavailable('worker_offline')
        future=asyncio.get_running_loop().create_future()
        self.pending[item.request_id]=future
        try:
            await self._send(item.model_dump(exclude_none=True))
            return await asyncio.wait_for(future,timeout)
        except TimeoutError: raise WorkerUnavailable('worker_timeout_uncertain') from None
        finally: self.pending.pop(item.request_id,None)

    async def _stderr(self):
        while self.process:
            data=await self.process.stderr.read(4096)
            if not data: return
            # Do not expose arbitrary child output in API responses.
            self.diagnostics.extend(data)
            del self.diagnostics[:-65536]

    async def _watchdog(self):
        while not self._closing:
            await asyncio.sleep(5)
            if time.monotonic()-self.last_health>15:
                await self.close()
                return

    async def run(self,on_event):
        try:
            while self.process and not self._closing:
                line=await self.process.stdout.readline()
                if not line: break
                try: event=parse_event(line)
                except ValueError: break
                if isinstance(event,Response):
                    future=self.pending.get(event.request_id)
                    if future and not future.done():
                        if event.ok: future.set_result(dict(ok=True,**event.data))
                        else: future.set_exception(WorkerUnavailable(event.error or 'worker_rejected'))
                    continue
                if hasattr(event,'session_id') and event.session_id:
                    if self.generations.get(event.session_id)!=event.generation: continue
                if event.type in {'ready','health'}:
                    self.last_health=time.monotonic()
                    if event.type=='health': self._health=event
                    else: self._health=WorkerHealth(gateway=event.gateway,decoder=event.decoder)
                await on_event(event)
        finally:
            self._health=WorkerHealth()
            for future in self.pending.values():
                if not future.done(): future.set_exception(WorkerUnavailable('worker_lost'))
            if not self._closing: await self.close()

    def health(self):
        if not self.process or self.process.returncode is not None or time.monotonic()-self.last_health>15: return WorkerHealth()
        return self._health

    async def close(self):
        self._closing=True
        current=asyncio.current_task()
        for task in self._tasks:
            if task is not current: task.cancel()
        if self.process:
            if self.process.stdin: self.process.stdin.close()
            try: await asyncio.wait_for(self.process.wait(),2)
            except TimeoutError:
                self.process.terminate()
                try: await asyncio.wait_for(self.process.wait(),2)
                except TimeoutError: self.process.kill(); await self.process.wait()
        await asyncio.gather(*(t for t in self._tasks if t is not current),return_exceptions=True)
        self._health=WorkerHealth()
