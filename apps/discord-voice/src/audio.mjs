import {spawn} from 'node:child_process';
import OpusScript from 'opusscript';
import {event} from './protocol.mjs';
const RATE=48000, CHANNELS=2, MAX_PCM=15*RATE*CHANNELS*2;
export function decodePacket(packet,decoder=new OpusScript(RATE,CHANNELS,OpusScript.Application.AUDIO)){
 try{return Buffer.from(decoder.decode(packet));}finally{if(arguments.length<2)decoder.delete();}
}
export function wav(pcm){
 const h=Buffer.alloc(44);h.write('RIFF');h.writeUInt32LE(pcm.length+36,4);h.write('WAVEfmt ',8);h.writeUInt32LE(16,16);h.writeUInt16LE(1,20);h.writeUInt16LE(1,22);h.writeUInt32LE(16000,24);h.writeUInt32LE(32000,28);h.writeUInt16LE(2,32);h.writeUInt16LE(16,34);h.write('data',36);h.writeUInt32LE(pcm.length,40);return Buffer.concat([h,pcm]);
}
export async function normalizePCM(pcm,{ffmpegPath='ffmpeg',signal}={}){
 if(!Buffer.isBuffer(pcm)||!pcm.length||pcm.length>MAX_PCM)throw Error('invalid_pcm');
 return new Promise((resolve,reject)=>{
  const child=spawn(ffmpegPath,['-hide_banner','-loglevel','error','-f','s16le','-ar','48000','-ac','2','-i','pipe:0','-f','s16le','-ar','16000','-ac','1','pipe:1'],{stdio:['pipe','pipe','pipe'],windowsHide:true,signal});
  const chunks=[];let size=0,failed=false;
  const timer=setTimeout(()=>{failed=true;child.kill();},10000);
  child.stdout.on('data',b=>{size+=b.length;if(size>480000){failed=true;child.kill();}else chunks.push(b);});
  child.stderr.on('data',()=>{});
  child.stdin.on('error',()=>{});
  child.on('error',()=>{failed=true;});
  child.on('close',code=>{clearTimeout(timer);if(failed||code!==0||!size||size%2)reject(Error('normalize_failed'));else resolve(wav(Buffer.concat(chunks)));});
  child.stdin.end(pcm);
 });
}
export class AudioCapture{
 constructor({emit,clock=Date.now,normalize=normalizePCM,decode=null,ffmpegPath='ffmpeg',endBehavior=1}){
  Object.assign(this,{emit,clock,normalize,decode,ffmpegPath,endBehavior});this.streams=new Map();this.jobs=new Set();this.sequence=0;this.healthy=true;this.closed=false;this.abort=new AbortController();this.running=0;this.waiting=[];this.tails=new Map();
 }
 gap(call,id,at,reason){this.emit(event('audio_gap',{session_id:call.session_id,generation:call.generation,participant_id:id,spoken_at:new Date(at).toISOString(),reason}));}
 subscribe(receiver,member,call){
  const id=member?.id;if(this.closed||!id||member.user?.bot||id===call.self_id||this.streams.has(id))return;
  if(this.streams.size>=8){this.gap(call,id,this.clock(),'capture_overflow');return;}
  const stream=receiver.subscribe(id,{end:{behavior:this.endBehavior,duration:700}});
  const decoder=this.decode?null:new OpusScript(RATE,CHANNELS,OpusScript.Application.AUDIO);
  const state={stream,parts:[],size:0,at:this.clock(),closed:false,decoder};
  this.streams.set(id,state);
  const flush=()=>{
   if(!state.size||this.closed)return;
   const pcm=Buffer.concat(state.parts);state.parts=[];state.size=0;
   const at=state.at;state.at+=pcm.length/(RATE*CHANNELS*2)*1000;
   const seq=++this.sequence;
   if(this.jobs.size>=8){this.gap(call,id,at,'conversion_overflow');return;}
   const previous=this.tails.get(id);
   const job=(async()=>{
    if(previous)await previous;
    if(this.running>=2)await new Promise(r=>this.waiting.push(r));
    if(this.closed)return;
    this.running++;
    try{
     const audio=await this.normalize(pcm,{ffmpegPath:this.ffmpegPath,signal:this.abort.signal});
     if(!this.closed)this.emit(event('utterance',{session_id:call.session_id,generation:call.generation,event_id:call.generation+':'+id+':'+seq,participant_id:id,speaker:(member.displayName||member.user?.username||'Unknown participant').slice(0,100),spoken_at:new Date(at).toISOString(),received_at:new Date(this.clock()).toISOString(),wav_base64:audio.toString('base64')}));
    }catch{if(!this.closed){this.healthy=false;this.gap(call,id,at,'decoder_failed');}}
    finally{this.running--;this.waiting.shift()?.();}
   })();this.tails.set(id,job);this.jobs.add(job);job.finally(()=>{this.jobs.delete(job);if(this.tails.get(id)===job)this.tails.delete(id);});
  };
  const end=()=>{
   if(state.closed)return;state.closed=true;flush();this.streams.delete(id);decoder?.delete();
  };
  stream.on('data',packet=>{
   if(state.closed||this.closed)return;
   try{
    let pcm=this.decode?this.decode(packet):decodePacket(packet,decoder);
    while(pcm.length){const size=Math.min(MAX_PCM-state.size,pcm.length);state.parts.push(pcm.subarray(0,size));state.size+=size;pcm=pcm.subarray(size);if(state.size===MAX_PCM)flush();}
   }catch{this.healthy=false;this.gap(call,id,state.at,'decoder_failed');state.parts=[];state.size=0;end();stream.destroy();}
  });
  stream.once('end',end);stream.once('close',end);stream.once('error',()=>{this.healthy=false;this.gap(call,id,state.at,'receive_failed');end();});
 }
 async drain(){while(this.jobs.size)await Promise.all([...this.jobs]);}
 close(){this.closed=true;this.abort.abort();for(const s of this.streams.values())s.stream.destroy();this.streams.clear();for(const release of this.waiting.splice(0))release();}
}
