import {Readable} from 'node:stream';
import {AudioCapture} from './audio.mjs';
import {event,media,MAX_MP3} from './protocol.mjs';
export class VoiceTransport{
 constructor({voice,client,ffmpegPath='ffmpeg',emit,clock=Date.now,autoTick=true,maxAttendanceSeconds=14400}){
  Object.assign(this,{voice,client,ffmpegPath,emit,clock,autoTick,maxAttendanceSeconds});this.call=null;this.queue=[];this.current=null;this.seen=new Set();this.muted=false;this.reconnecting=false;
 }
 scope(c){if(!this.call||c.session_id!==this.call.session_id||c.generation!==this.call.generation)throw Error('stale_generation');}
 ack(key,state){if(this.call)this.emit(event('playback',{session_id:this.call.session_id,generation:this.call.generation,key,state}));}
 status(){return {gateway:this.client.isReady(),connection:!!this.connection,decoder:!!this.capture,receiver:!!this.capture?.healthy,player:!!this.player,...(this.call?{session_id:this.call.session_id,generation:this.call.generation}:{}),channel_id:this.call?.channel_id,muted:this.muted};}
 health(){const {channel_id,muted,...h}=this.status();this.emit(event('health',h));return h;}
 async join(c){
  if(this.call){this.scope(c);return this.health();}
  const guild=await this.client.guilds.fetch(c.guild_id),channel=await guild.channels.fetch(c.channel_id);
  if(!channel||channel.type!==2)throw Error('voice_channel_required');
  const permissions=channel.permissionsFor(guild.members.me||await guild.members.fetchMe());
  if(!permissions?.has(['ViewChannel','Connect','Speak']))throw Error('voice_permissions_required');
  this.call={...c,self_id:this.client.user.id};this.channel=channel;this.started=this.clock();this.emptySince=null;this.muted=false;this.seen.clear();
  try{
   this.connection=this.voice.joinVoiceChannel({channelId:c.channel_id,guildId:c.guild_id,adapterCreator:guild.voiceAdapterCreator,selfDeaf:false,selfMute:false});
   this.connection.on('error',()=>this.fail('connection_error'));
   await this.voice.entersState(this.connection,this.voice.VoiceConnectionStatus.Ready,15000);
   if(!this.call)throw Error('join_interrupted');
   this.capture=new AudioCapture({emit:this.emit,clock:this.clock,ffmpegPath:this.ffmpegPath,endBehavior:this.voice.EndBehaviorType.AfterSilence});
   this.onSpeaking=id=>{const member=this.channel.members.get(id);if(member)this.capture?.subscribe(this.connection.receiver,member,this.call);};
   this.connection.receiver.speaking.on('start',this.onSpeaking);
   this.player=this.voice.createAudioPlayer();this.subscription=this.connection.subscribe(this.player);
   this.player.on('stateChange',(old,next)=>{
    if(next.status===this.voice.AudioPlayerStatus.Playing&&this.current)this.ack(this.current.key,'playing');
    if(next.status===this.voice.AudioPlayerStatus.Idle&&this.current){this.ack(this.current.key,'completed');this.current=null;this.next();}
   });
   this.player.on('error',()=>{if(this.current){this.ack(this.current.key,'failed');this.current=null;}this.next();});
   this.connection.on('stateChange',(_,next)=>{if(next.status===this.voice.VoiceConnectionStatus.Disconnected)this.reconnect();});
   if(this.autoTick)this.timer=setInterval(()=>this.tick(),5000);
   return this.health();
  }catch{await this.leave(c);throw Error('voice_start_failed');}
 }
 async reconnect(){
  if(this.reconnecting||!this.call)return;this.reconnecting=true;
  try{
   const connection=this.connection;let ok=false;
   for(let i=0;i<2&&!ok&&this.call;i++){
    try{await this.voice.entersState(connection,this.voice.VoiceConnectionStatus.Ready,5000);ok=true;}catch{if(i===0)connection.rejoin();}
   }
   if(!ok&&this.call)await this.fail('connection_lost');
  }finally{this.reconnecting=false;}
 }
 tick(){
  if(!this.call)return;
  const humans=[...this.channel.members.values()].some(m=>!m.user.bot);
  if(humans)this.emptySince=null;else if(this.emptySince===null)this.emptySince=this.clock();
  if(this.clock()-this.started>=this.maxAttendanceSeconds*1000)this.fail('maximum_duration');
  else if(this.emptySince!==null&&this.clock()-this.emptySince>=60000)this.fail('empty_channel');
  else this.health();
 }
 async fail(reason){const c=this.call;if(!c)return;await this.leave(c);this.emit(event('disconnected',{session_id:c.session_id,generation:c.generation,reason}));}
 async play(c){
  this.scope(c);if(this.muted)throw Error('speech_muted');
  if(this.seen.has(c.key))return;
  if(this.queue.length+(this.current?1:0)>=2)throw Error('queue_full');
  const bytes=media(c.audio_base64,MAX_MP3);this.seen.add(c.key);if(this.seen.size>2000){this.seen.delete(this.seen.values().next().value);}
  this.queue.push({key:c.key,bytes});this.ack(c.key,'queued');this.next();
 }
 next(){
  if(!this.call||this.muted||this.current||!this.queue.length)return;
  this.current=this.queue.shift();
  try{this.resource=this.voice.createAudioResource(Readable.from(this.current.bytes));this.player.play(this.resource);}
  catch{this.ack(this.current.key,'failed');this.current=null;this.next();}
 }
 stop(c){
  this.scope(c);const current=this.current;this.current=null;const pending=this.queue.splice(0);
  this.player?.stop(true);this.resource?.playStream?.destroy();this.resource=null;
  if(current)this.ack(current.key,'cancelled');for(const item of pending)this.ack(item.key,'cancelled');
 }
 mute(c){this.scope(c);this.muted=c.muted;if(c.muted)this.stop(c);}
 async leave(c){
  if(!this.call)return;this.scope(c);
  clearInterval(this.timer);this.capture?.close();
  if(this.onSpeaking)this.connection?.receiver.speaking.off('start',this.onSpeaking);
  this.stop(c);this.subscription?.unsubscribe();this.player?.removeAllListeners();this.connection?.removeAllListeners();this.connection?.destroy();
  this.connection=null;this.player=null;this.capture=null;this.call=null;this.seen.clear();
 }
}
