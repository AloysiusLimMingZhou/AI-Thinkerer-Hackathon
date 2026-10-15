import test from 'node:test';import assert from 'node:assert/strict';import {EventEmitter} from 'node:events';
import {VoiceTransport} from '../src/transport.mjs';
function fixture(){
 const events=[];let now=0, destroyed=0; const player=new EventEmitter(); player.stop=()=>{};player.play=()=>{};
 const connection=new EventEmitter();connection.receiver={speaking:new EventEmitter(),subscribe(){throw Error('unused');}};connection.subscribe=()=>({unsubscribe(){}});connection.destroy=()=>destroyed++;
 const channel={id:'c',type:2,permissionsFor:()=>({has:()=>true}),members:new Map([['h',{user:{bot:false}}]])};
 const client={user:{id:'self'},isReady:()=>true,guilds:{fetch:async()=>({voiceAdapterCreator:{},members:{me:{}},channels:{fetch:async()=>channel}})}};
 const voice={joinVoiceChannel:opts=>{assert.equal(opts.selfDeaf,false);return connection;},entersState:async()=>{},VoiceConnectionStatus:{Ready:'ready',Disconnected:'disconnected',Connecting:'connecting',Signalling:'signalling'},AudioPlayerStatus:{Idle:'idle',Playing:'playing'},EndBehaviorType:{AfterSilence:1},createAudioPlayer:()=>player,createAudioResource:()=>({})};
 const transport=new VoiceTransport({voice,client,emit:e=>events.push(e),clock:()=>now,autoTick:false});
 return {transport,events,channel,player,connection,setNow:n=>now=n,destroyed:()=>destroyed};
}
const call={session_id:'s',generation:'g',guild_id:'guild',channel_id:'c'};
test('permission checks, queue acknowledgements and cleanup',async()=>{
 const f=fixture();f.channel.type=13;await assert.rejects(f.transport.join(call));f.channel.type=2;
 await f.transport.join(call);assert.equal(f.transport.status().receiver,true);
 await f.transport.play({...call,key:'one',audio_base64:Buffer.from('mp3').toString('base64')});
 f.player.emit('stateChange',{status:'idle'},{status:'playing'});f.player.emit('stateChange',{status:'playing'},{status:'idle'});
 assert.deepEqual(f.events.filter(e=>e.type==='playback').map(e=>e.state),['queued','playing','completed']);
 f.transport.mute({...call,muted:true});
 await assert.rejects(f.transport.play({...call,key:'two',audio_base64:'bXAz'}));
 await f.transport.leave(call);assert.equal(f.destroyed(),1);assert.equal(f.connection.receiver.speaking.listenerCount('start'),0);
});
test('no human grace and maximum attendance leave',async()=>{
 const f=fixture();await f.transport.join(call);f.channel.members.clear();
 f.transport.tick();f.setNow(59000);f.transport.tick();assert.equal(f.destroyed(),0);f.setNow(61000);f.transport.tick();await new Promise(r=>setImmediate(r));assert.equal(f.destroyed(),1);
 const g=fixture();await g.transport.join(call);g.setNow(14400001);g.transport.tick();await new Promise(r=>setImmediate(r));assert.equal(g.destroyed(),1);
});
