"""Versioned, bounded, path-free IPC. Interaction tokens never cross this boundary."""
from __future__ import annotations
import base64,json
from typing import Annotated,Literal,Union
from uuid import uuid4
from pydantic import BaseModel,ConfigDict,Field,TypeAdapter,AwareDatetime,field_validator
MAX_FRAME=12*1024*1024
MAX_WAV=512*1024
MAX_MP3=8*1024*1024
Id=Annotated[str,Field(min_length=1,max_length=200)]
class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')
    protocol_version: Literal[1]=1
class WorkerHealth(Strict):
    type: Literal['health']='health'
    gateway: bool=False
    connection: bool=False
    decoder: bool=False
    receiver: bool=False
    player: bool=False
    session_id: Id|None=None
    generation: Id|None=None
class Scoped(Strict):
    session_id: Id
    generation: Id
class DiscordCommandRequest(Strict):
    type: Literal['command']='command'
    interaction_id: Id
    command: Literal['join','leave','mute','unmute','stop-speaking','status']
    guild_id: Id
    actor_id: Id
    channel_id: Id|None=None
    briefing_id: Id|None=None
class AudioUtterance(Scoped):
    type: Literal['utterance']='utterance'
    event_id: Id
    participant_id: Id
    speaker: Annotated[str,Field(min_length=1,max_length=100)]
    spoken_at: AwareDatetime
    received_at: AwareDatetime
    wav_base64: str
    is_bot: bool=False
    is_self: bool=False
    @field_validator('wav_base64')
    @classmethod
    def audio(cls,value): decode_media(value,MAX_WAV); return value
class PlaybackAck(Scoped):
    type: Literal['playback']='playback'
    key: Id
    state: Literal['queued','playing','completed','failed','cancelled']
class AudioGap(Scoped):
    type: Literal['audio_gap']='audio_gap'
    participant_id: Id|None=None
    spoken_at: AwareDatetime
    reason: Annotated[str,Field(max_length=100)]
class Disconnected(Scoped):
    type: Literal['disconnected']='disconnected'
    reason: Annotated[str,Field(max_length=100)]
class Ready(Strict):
    type: Literal['ready']='ready'
    gateway: bool
    decoder: bool
    self_id: Id|None=None
class Response(Strict):
    type: Literal['response']='response'
    request_id: Id
    ok: bool
    data: dict=Field(default_factory=dict)
    error: Annotated[str,Field(max_length=100)]|None=None
class Autocomplete(Strict):
    type: Literal['autocomplete']='autocomplete'
    interaction_id: Id
    guild_id: Id
    actor_id: Id
    query: Annotated[str,Field(max_length=100)]
class OwnerReply(Strict):
    type: Literal['owner_reply']='owner_reply'
    id: Id
    guild_id: Id
    channel_id: Id
    author_id: Id
    content: Annotated[str,Field(max_length=4000)]
    bot: bool=False
    webhook: bool=False
    is_edit: bool=False
    has_attachments: bool=False
    created_at: AwareDatetime|None=None
WorkerEvent=Annotated[Union[WorkerHealth,DiscordCommandRequest,AudioUtterance,PlaybackAck,AudioGap,Disconnected,Ready,Response,Autocomplete,OwnerReply],Field(discriminator='type')]
EVENT=TypeAdapter(WorkerEvent)
def decode_media(value,limit):
    if not isinstance(value,str) or len(value)>4*((limit+2)//3): raise ValueError('Media exceeds limit')
    try: result=base64.b64decode(value,validate=True)
    except Exception: raise ValueError('Invalid media encoding') from None
    if not result or len(result)>limit: raise ValueError('Invalid media size')
    return result
def parse_event(line):
    if len(line.encode('utf-8') if isinstance(line,str) else line)>MAX_FRAME: raise ValueError('IPC frame too large')
    return EVENT.validate_json(line)
class RPC(Strict):
    request_id: Id=Field(default_factory=lambda:str(uuid4()))
class StatusCommand(RPC):
    type: Literal['status']='status'
class CallCommand(RPC):
    type: Literal['leave','stop']
    session_id: Id
    generation: Id
class JoinCommand(RPC):
    type: Literal['join']='join'
    session_id: Id
    generation: Id
    guild_id: Id
    channel_id: Id
class MuteCommand(RPC):
    type: Literal['mute']='mute'
    session_id: Id
    generation: Id
    muted: bool
class PlayCommand(RPC):
    type: Literal['play']='play'
    session_id: Id
    generation: Id
    key: Id
    audio_base64: str
    @field_validator('audio_base64')
    @classmethod
    def audio(cls,v): decode_media(v,MAX_MP3); return v
class InteractionResult(RPC):
    type: Literal['interaction_result']='interaction_result'
    interaction_id: Id
    content: Annotated[str,Field(max_length=2000)]|None=None
    choices: list[dict[str,str]]|None=Field(default=None,max_length=25)
WorkerCommand=Annotated[Union[StatusCommand,CallCommand,JoinCommand,MuteCommand,PlayCommand,InteractionResult],Field(discriminator='type')]
COMMAND=TypeAdapter(WorkerCommand)
def command(kind,**kwargs): return COMMAND.validate_python(dict(type=kind,**kwargs))
