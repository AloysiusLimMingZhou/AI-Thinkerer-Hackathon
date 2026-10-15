"""Configured Discord escalation transport. Meeting policy stays in EscalationService."""
import asyncio
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime

import httpx

from .escalations import DeliveryError, DiscordQuestionRef


@dataclass(frozen=True)
class OwnerReply:
    message_id: str
    guild_id: str
    channel_id: str
    author_id: str
    text: str
    created_at: datetime
    parent_message_id: str | None = None
    is_bot: bool = False
    is_webhook: bool = False
    is_edit: bool = False
    has_attachments: bool = False


def mentions(owner=None):
    return {'parse':[],'users':[owner] if owner else [],'roles':[],'replied_user':False}


class DiscordTransport:
    def __init__(self,settings,store,*,transport=None):
        self.settings,self.store=settings,store
        self.transport=transport
        self.retry_at=0
        self.gateway_state='disabled' if not self.configured else 'disconnected'
        self.client=None
        self.channel_checked=False

    @property
    def missing(self):
        return [key.upper() for key in ('discord_bot_token','discord_guild_id','discord_escalation_channel_id','discord_owner_user_id') if not getattr(self.settings,key)]

    @property
    def configured(self): return not self.missing

    def status(self):
        return {'configured':self.configured,'missing':self.missing,'gateway':self.gateway_state,'voice_attendance_available':False}

    async def _request(self,method,path,body=None):
        if not self.configured: raise DeliveryError('Discord configuration is incomplete')
        if self.retry_at>time.time(): raise DeliveryError('Discord rate limited',retry_after=self.retry_at-time.time())
        try:
            async with httpx.AsyncClient(base_url='https://discord.com/api/v10',transport=self.transport,timeout=15,headers={'Authorization':'Bot '+self.settings.discord_bot_token}) as client:
                response=await client.request(method,path,json=body)
        except httpx.HTTPError as error:
            raise DeliveryError('Discord request outcome is uncertain; reconcile provider state',ambiguous=method=='POST') from error
        if response.status_code==429:
            try: delay=max(float(response.json()['retry_after']),0.1)
            except (ValueError,KeyError,TypeError): delay=5
            self.retry_at=time.time()+delay
            raise DeliveryError('Discord rate limited',retry_after=delay)
        if response.status_code>=500:
            raise DeliveryError('Discord server outcome is uncertain; reconcile provider state',ambiguous=method=='POST')
        if not response.is_success:
            raise DeliveryError(f'Discord returned HTTP {response.status_code}; check bot permissions and channel IDs')
        try: return response.json()
        except ValueError: raise DeliveryError('Discord returned an invalid response',ambiguous=method=='POST') from None

    async def _message(self,channel,content,key,owner=None):
        nonce=hashlib.sha256(key.encode()).hexdigest()[:25]
        return await self._request('POST',f'/channels/{channel}/messages',{'content':content,'nonce':nonce,'enforce_nonce':True,'allowed_mentions':mentions(owner)})

    async def send_question(self,question):
        sid,qid=question['session_id'],question['id']
        if not self.channel_checked:
            channel=await self._request('GET',f'/channels/{self.settings.discord_escalation_channel_id}')
            if channel.get('guild_id')!=self.settings.discord_guild_id or channel.get('type')!=0:
                raise DeliveryError('Use a text channel in the configured Discord guild')
            self.channel_checked=True
        job=self.store.one('SELECT * FROM escalation_outbox WHERE question_id=?',(qid,))
        parent=question.get('parent_message_id') or job['parent_message_id']
        thread=question.get('thread_id') or job['thread_id']
        segments=[question['question'][i:i+1800] for i in range(0,len(question['question']),1800)] or ['']
        if not parent:
            session=self.store.repository.get_session(sid)
            header=f'<@{self.settings.discord_owner_user_id}> {session.title[:40]} — {question["speaker"][:30]} asks. Please reply in this question’s thread.'
            result=await self._message(self.settings.discord_escalation_channel_id,header+f'\nQuestion segment 1/{len(segments)}\n'+segments[0],qid+':parent',self.settings.discord_owner_user_id)
            parent=result['id']
            with self.store.repository._connect() as db:
                db.execute('UPDATE unanswered_questions SET parent_message_id=? WHERE id=?',(parent,qid))
                db.execute('UPDATE escalation_outbox SET parent_message_id=?,sent_segments=1 WHERE question_id=?',(parent,qid))
        if not thread:
            result=await self._request('POST',f'/channels/{self.settings.discord_escalation_channel_id}/messages/{parent}/threads',{'name':f'Question {qid[:8]}','auto_archive_duration':1440})
            thread=result['id']
            with self.store.repository._connect() as db:
                db.execute('UPDATE unanswered_questions SET thread_id=? WHERE id=?',(thread,qid))
                db.execute('UPDATE escalation_outbox SET thread_id=? WHERE question_id=?',(thread,qid))
        sent=self.store.one('SELECT sent_segments FROM escalation_outbox WHERE question_id=?',(qid,))['sent_segments']
        for index in range(max(sent,1),len(segments)):
            await self._message(thread,f'Question segment {index+1}/{len(segments)}\n'+segments[index],f'{qid}:segment:{index}')
            self.store.execute('UPDATE escalation_outbox SET sent_segments=? WHERE question_id=?',(index+1,qid))
        return DiscordQuestionRef(str(parent),str(thread))

    async def acknowledge(self,question,text,key):
        channel=question['thread_id'] or self.settings.discord_escalation_channel_id
        await self._message(channel,text,key)

    async def gateway(self,escalations):
        if not self.configured: return
        import discord
        intents=discord.Intents.none()
        intents.guilds=True; intents.guild_messages=True; intents.message_content=True
        client=discord.Client(intents=intents,max_messages=None)
        self.client=client
        @client.event
        async def on_ready(): self.gateway_state='connected'
        @client.event
        async def on_disconnect(): self.gateway_state='disconnected'
        @client.event
        async def on_message(message):
            if not message.guild: return
            reply=OwnerReply(message_id=str(message.id),guild_id=str(message.guild.id),channel_id=str(message.channel.id),author_id=str(message.author.id),text=message.content,created_at=message.created_at,
                parent_message_id=str(message.reference.message_id) if message.reference and message.reference.message_id else None,
                is_bot=message.author.bot,is_webhook=bool(message.webhook_id),has_attachments=bool(message.attachments),is_edit=bool(message.edited_at))
            try: await escalations.receive_owner_reply(reply)
            except Exception:
                self.gateway_state='reply_failed; check meeting activity'
        try:
            self.gateway_state='connecting'
            await client.start(self.settings.discord_bot_token)
        except asyncio.CancelledError: raise
        except Exception:
            self.gateway_state='failed; check token, Message Content intent and permissions'
        finally:
            await client.close()
