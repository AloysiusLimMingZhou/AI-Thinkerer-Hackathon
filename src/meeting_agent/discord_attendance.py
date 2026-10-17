"""Authorization, durable ownership and policy stay in Python."""
import asyncio,json,shutil
from datetime import UTC,datetime
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from .discord_store import DiscordStore
from .discord_protocol import command,DiscordCommandRequest
from .discord_worker import WorkerUnavailable
from .models import SessionCreate
from .cost_rates import CostQuote
from .budget import BudgetExceeded

class DiscordAttendance:
    def __init__(self,settings,repository,briefings,worker,playback,budget):
        self.settings,self.repository,self.briefings,self.worker,self.playback,self.budget=settings,repository,briefings,worker,playback,budget
        self.store=DiscordStore(repository);self.lock=asyncio.Lock()
        self.audio=None;self.on_started=None;self.on_left=None;self.on_event=None

    def missing(self):
        names=('discord_bot_token','discord_guild_id','discord_owner_user_id','discord_escalation_channel_id','openai_api_key','elevenlabs_api_key')
        result=[n.upper() for n in names if not getattr(self.settings,n)]
        if not self.settings.discord_voice_enabled:result.append('DISCORD_VOICE_ENABLED')
        if not shutil.which(self.settings.discord_node_executable):result.append('DISCORD_NODE_EXECUTABLE')
        if not shutil.which(self.settings.discord_ffmpeg_executable):result.append('DISCORD_FFMPEG_EXECUTABLE')
        if not (Path(__file__).resolve().parents[2]/'apps/discord-voice/node_modules/@discordjs/voice/package.json').exists():result.append('DISCORD_VOICE_DEPENDENCIES')
        health=self.worker.health()
        if not health.gateway:result.append('DISCORD_GATEWAY')
        if not health.decoder:result.append('DISCORD_DECODER')
        return result

    def status(self,session_id=None):
        row=self.store.attendance(session_id) if session_id else self.store.active(self.settings.discord_guild_id)
        if session_id:
            session=self.repository.get_session(session_id)
            if not session:raise HTTPException(404,'Session not found')
            if session.platform!='discord' or session.purpose!='meeting':raise HTTPException(409,'Not a Discord attendance session')
        missing=self.missing()
        attendance=None
        if row:
            attendance={**row,'health':json.loads(row['health_json']),'muted':bool(row['muted'])};attendance.pop('health_json',None)
        return {'configured':not missing,'missing':missing,'voice_attendance_available':not missing,'attendance':attendance,'worker_health':self.worker.health().model_dump(exclude_none=True),'models':{'transcription':self.settings.openai_transcription_model,'answer':self.settings.openai_answer_model,'speech':self.settings.elevenlabs_model_id},'budget':self.budget.status().model_dump(mode='json')}

    def choices(self,query):
        return [{'name':s.title[:100],'value':s.id} for s in self.briefings.list(query[:100])]

    def authorized(self,guild,actor):
        if guild!=self.settings.discord_guild_id:return 'guild_required'
        if actor!=self.settings.discord_owner_user_id:return 'owner_required'
        return None

    async def _reconcile(self,row):
        try: status=await self.worker.request(command('status'),timeout=3)
        except WorkerUnavailable:return row
        if status.get('session_id')==row['session_id'] and status.get('generation')==row['generation']:
            if row['state']=='joining' and all(status.get(k) for k in ('connection','decoder','receiver','player')):
                await self._activate(row['session_id'],status)
            return self.store.attendance(row['session_id'])
        if status.get('session_id'):return row
        self.store.transition(row['session_id'],'failed',error='Connection was not established')
        return None

    async def handle_command(self,request):
        request=DiscordCommandRequest.model_validate(request)
        denied=self.authorized(request.guild_id,request.actor_id)
        if denied:return {'ok':False,'code':denied}
        async with self.lock:
            previous=self.store.one('SELECT result_json FROM discord_interactions WHERE id=?',(request.interaction_id,))
            if previous:return json.loads(previous['result_json'])
            try:
                if request.command=='join':result=await self._join(request)
                elif request.command=='status':result={'ok':True,**self.status()}
                else:
                    row=self.store.active(request.guild_id)
                    if not row:result={'ok':False,'code':'no_active_meeting'}
                    else:result=await self.control(row['session_id'],request.command)
            except HTTPException as exc:result={'ok':False,'code':'invalid_request','message':str(exc.detail)[:200]}
            except BudgetExceeded:result={'ok':False,'code':'monthly_budget_exhausted'}
            except WorkerUnavailable:result={'ok':False,'code':'worker_unavailable'}
            self.store.execute('INSERT OR IGNORE INTO discord_interactions VALUES(?,?)',(request.interaction_id,json.dumps(result)))
            return result

    async def _join(self,request):
        active=self.store.active(request.guild_id)
        if active and active['state'] in {'joining','leaving'}:active=await self._reconcile(active)
        if active:
            if active['channel_id']==request.channel_id:
                return {'ok':active['state']=='active','code':'existing_attendance','session_id':active['session_id'],'state':active['state']}
            return {'ok':False,'code':'leave_first','session_id':active['session_id']}
        if not request.channel_id:return {'ok':False,'code':'voice_channel_required'}
        missing=self.missing()
        if missing:return {'ok':False,'code':'not_ready','missing':missing}
        # Admission must cover the introduction and a first bounded listening/answer operation.
        self.budget.ensure_available([CostQuote(self.settings.elevenlabs_model_id,characters=400),CostQuote(self.settings.openai_transcription_model,audio_seconds=15),CostQuote(self.settings.openai_answer_model,input_tokens=32000,output_tokens=1000)])
        session=self.briefings.snapshot(request.briefing_id,SessionCreate(title='Discord meeting '+datetime.now(UTC).strftime('%Y-%m-%d %H:%M'),owner_name='Owner',platform='discord'))
        generation=str(uuid4());self.worker.generations[session.id]=generation
        self.store.execute("INSERT INTO discord_attendance(session_id,guild_id,channel_id,generation,state,started_at) VALUES(?,?,?,?,'joining',?)",(session.id,request.guild_id,request.channel_id,generation,datetime.now(UTC).isoformat()))
        try:
            health=await self.worker.request(command('join',session_id=session.id,generation=generation,guild_id=request.guild_id,channel_id=request.channel_id))
        except WorkerUnavailable as error:
            if str(error) in {'voice_channel_required','voice_permissions_required','voice_start_failed'}:
                self.store.transition(session.id,'failed',error=str(error))
                self.worker.generations.pop(session.id,None)
                return {'ok':False,'code':str(error),'session_id':session.id}
            self.store.execute('UPDATE discord_attendance SET error=? WHERE session_id=?',('Join outcome uncertain; check status before retrying',session.id))
            return {'ok':False,'code':'join_uncertain','session_id':session.id}
        if not all(health.get(k) for k in ('connection','decoder','receiver','player')):
            await self.leave(session.id,reason='startup_failed')
            return {'ok':False,'code':'receive_not_ready','session_id':session.id}
        return await self._activate(session.id,health)

    async def _activate(self,sid,health):
        self.store.transition(sid,'active',health={k:bool(health.get(k)) for k in ('gateway','connection','decoder','receiver','player')})
        if self.on_started:
            try:await self.on_started(sid)
            except BudgetExceeded:
                await self.leave(sid,reason='budget')
                return {'ok':False,'code':'monthly_budget_exhausted','session_id':sid}
            except Exception:
                self.store.execute("UPDATE discord_attendance SET introduction='failed' WHERE session_id=?",(sid,))
                await self.leave(sid,reason='startup_failed')
                return {'ok':False,'code':'introduction_failed','session_id':sid}
        return {'ok':True,'code':'joined','session_id':sid,'dashboard_url':self.settings.web_base_url+'/meetings/'+sid}

    async def control(self,sid,action):
        row=self.store.attendance(sid)
        if not row:raise HTTPException(404,'Attendance not found')
        if action=='leave':return await self.leave(sid)
        if action not in {'mute','unmute','stop-speaking'}:raise HTTPException(422,'Unknown attendance action')
        if row['state']!='active':raise HTTPException(409,'Meeting is not active')
        if action in {'mute','unmute'}:
            await self.playback.mute(sid,action=='mute')
            self.store.execute('UPDATE discord_attendance SET muted=? WHERE session_id=?',(int(action=='mute'),sid))
        else:await self.playback.stop(sid)
        return {'ok':True,'session_id':sid}

    async def leave(self,session_id,*,reason='owner'):
        row=self.store.attendance(session_id)
        if not row:raise HTTPException(404,'Attendance not found')
        if row['state'] not in {'joining','active','leaving'}:return {'ok':True,'session_id':session_id,'state':row['state']}
        self.store.transition(session_id,'leaving')
        if self.audio:await self.audio.cancel(session_id)
        try:
            await self.playback.stop(session_id)
        except Exception:
            self.repository.record_event(session_id,'discord.stop_uncertain',{})
        # Leaving must not depend on an independent speech-stop acknowledgement.
        try:
            await self.worker.request(command('leave',session_id=session_id,generation=row['generation']))
        except WorkerUnavailable:
            try:await self.worker.close()
            except Exception:
                self.store.execute('UPDATE discord_attendance SET error=? WHERE session_id=?',('Worker shutdown needs attention; departure is unconfirmed',session_id))
                return {'ok':False,'code':'leave_uncertain','session_id':session_id}
        state='budget_stopped' if reason=='budget' else 'failed' if reason=='startup_failed' else 'ended'
        self.store.transition(session_id,state,error=None if reason=='owner' else reason,health={k:False for k in ('gateway','connection','decoder','receiver','player')})
        self.worker.generations.pop(session_id,None)
        if self.on_left:await self.on_left(session_id)
        return {'ok':True,'session_id':session_id,'state':state}

    async def recover(self):
        for row in self.store.all("SELECT * FROM discord_attendance WHERE state IN ('joining','active','leaving')"):
            self.store.transition(row['session_id'],'interrupted',error='Worker interrupted; join again explicitly',health={k:False for k in ('gateway','connection','decoder','receiver','player')})
            if self.on_left:await self.on_left(row['session_id'])

    async def handle_event(self,event):
        if event.type=='command':
            result=await self.handle_command(event)
            if event.command=='status' and result.get('ok'):
                s=result;row=s.get('attendance');b=s['budget'];message=f"Meeting: {row['state'] if row else 'none'}. Receive: {s['worker_health']['receiver']}. Models: {', '.join(s['models'].values())}. Estimated USD {b['settled_micro_usd']/1e6:.2f} settled, {b['held_micro_usd']/1e6:.2f} held; USD {b['available_micro_usd']/1e6:.2f} available. "+('Soft budget warning. ' if b['soft_warning'] else '')+f"Reset: {b['reset_at']}."
            else:message=result.get('dashboard_url') or result.get('message') or result.get('code','Done')
            await self.worker.request(command('interaction_result',interaction_id=event.interaction_id,content=message[:2000]))
            return
        if event.type=='owner_reply':
            if self.on_event:await self.on_event(event)
            return
        if event.type=='autocomplete':
            choices=self.choices(event.query) if not self.authorized(event.guild_id,event.actor_id) else []
            await self.worker.request(command('interaction_result',interaction_id=event.interaction_id,choices=choices),timeout=1)
            return
        if getattr(event,'session_id',None):
            row=self.store.attendance(event.session_id)
            if not row or row['generation']!=event.generation or row['state'] not in {'joining','active','leaving'}:return
            if event.type=='health':
                health=event.model_dump(exclude={'type','protocol_version','session_id','generation'})
                self.store.execute('UPDATE discord_attendance SET health_json=? WHERE session_id=?',(json.dumps(health),event.session_id))
            elif event.type=='disconnected':
                if self.audio:await self.audio.cancel(event.session_id)
                self.store.transition(event.session_id,'ended' if event.reason in {'empty_channel','maximum_duration'} else 'interrupted',error=event.reason,health={k:False for k in ('gateway','connection','decoder','receiver','player')})
                self.worker.generations.pop(event.session_id,None)
                if self.on_left:await self.on_left(event.session_id)
        if self.on_event:await self.on_event(event)
