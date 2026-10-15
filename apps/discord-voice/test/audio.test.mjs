import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter,once} from 'node:events';
import {PassThrough} from 'node:stream';
import {AudioCapture,normalizePCM,decodePacket} from '../src/audio.mjs';
import {readFile} from 'node:fs/promises';
test('real Opus fixture becomes finite mono 16kHz WAV',async()=>{
 const packet=Buffer.from((await readFile(new URL('./fixtures/opus.json',import.meta.url),'utf8')).trim(),'base64');
 const pcm=decodePacket(packet);
 const wav=await normalizePCM(pcm,{ffmpegPath:process.env.FFMPEG_PATH||'ffmpeg'});
 assert.equal(wav.readUInt32LE(24),16000);assert.equal(wav.readUInt16LE(22),1);assert.equal(wav.readUInt16LE(34),16);
 assert.equal(wav.readUInt32LE(40),wav.length-44);
});
test('capture splits at fifteen seconds',async()=>{
 const clips=[],streams=[]; const receiver={subscribe(){const s=new PassThrough({objectMode:true});streams.push(s);return s;}};
 const capture=new AudioCapture({emit:e=>clips.push(e),clock:()=>100000,decode:()=>Buffer.alloc(48000*4),normalize:async p=>Buffer.alloc(44+p.length/6)});
 capture.subscribe(receiver,{id:'human',displayName:'Alloy',user:{bot:false}},{session_id:'s',generation:'g',self_id:'bot'});
 for(let i=0;i<31;i++)streams[0].write(Buffer.from([1]));
 streams[0].end(); await once(streams[0],'end'); await capture.drain();
 assert.deepEqual(clips.map(x=>Buffer.from(x.wav_base64,'base64').length),[480044,480044,32044]);
 assert.equal(new Date(clips[1].spoken_at)-new Date(clips[0].spoken_at),15000);
 assert.equal(new Set(clips.map(x=>x.event_id)).size,3);
 capture.close();
});
test('decoder failure degrades receive and bots have no stream',async()=>{
 const events=[];let streams=0;const stream=new PassThrough({objectMode:true});
 const capture=new AudioCapture({emit:e=>events.push(e),decode:()=>{throw Error('bad');}});
 const receiver={subscribe(){streams++;return stream;}};
 const call={session_id:'s',generation:'g',self_id:'self'};
 capture.subscribe(receiver,{id:'self',user:{bot:false}},call);
 capture.subscribe(receiver,{id:'bot',user:{bot:true}},call);
 assert.equal(streams,0);
 capture.subscribe(receiver,{id:'human',displayName:'Human',user:{bot:false}},call);
 stream.write(Buffer.from([1]));await capture.drain();
 assert.equal(events[0].type,'audio_gap');assert.equal(capture.healthy,false);capture.close();
});
