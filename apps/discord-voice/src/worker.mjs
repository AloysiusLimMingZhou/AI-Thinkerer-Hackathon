import {Client,GatewayIntentBits} from 'discord.js';
import * as voice from '@discordjs/voice';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {parseCommand,event,MAX_FRAME} from './protocol.mjs';
import {VoiceTransport} from './transport.mjs';
import {GatewayAdapter} from './gateway.mjs';
let client,transport,gateway,heartbeat,closing=false,configured=false,configPromise,pending=0;
function emit(item){
 if(closing)return;
 const raw=JSON.stringify(item)+'\n';
 if(Buffer.byteLength(raw)>MAX_FRAME||process.stdout.writableLength>24*1024*1024){shutdown();return;}
 process.stdout.write(raw);
}
async function shutdown(){
 if(closing)return;closing=true;clearInterval(heartbeat);gateway?.close();
 if(transport?.call)await transport.leave(transport.call);
 client?.destroy();process.stdin.destroy();
}
async function configure(c){
 process.env.FFMPEG_PATH=c.ffmpeg_path;
 await promisify(execFile)(c.ffmpeg_path,['-version'],{timeout:3000,windowsHide:true,maxBuffer:65536});
 client=new Client({intents:[GatewayIntentBits.Guilds,GatewayIntentBits.GuildVoiceStates,GatewayIntentBits.GuildMessages,GatewayIntentBits.MessageContent]});
 transport=new VoiceTransport({voice,client,ffmpegPath:c.ffmpeg_path,emit,maxAttendanceSeconds:c.max_attendance_seconds});
 gateway=new GatewayAdapter({client,transport,emit,guildId:c.guild_id,ownerId:c.owner_id});
 client.on('error',()=>shutdown());client.on('shardDisconnect',()=>{if(transport.call)transport.fail('gateway_disconnected');});
 client.once('clientReady',()=>emit(event('ready',{gateway:true,decoder:true})));
 await client.login(process.env.DISCORD_BOT_TOKEN);
 heartbeat=setInterval(()=>transport.health(),5000);
}
async function dispatch(c){
 if(c.type==='config'){
  if(configured)throw Error('already_configured');configured=true;configPromise=configure(c);await configPromise;return;
 }
 if(!configPromise)throw Error('not_configured');await configPromise;
 let data={};
 if(c.type==='status')data=transport.status();
 else if(c.type==='interaction_result')await gateway.resolve(c);
 else if(c.type==='join')data=await transport.join(c);
 else if(c.type==='leave')await transport.leave(c);
 else if(c.type==='mute')transport.mute(c);
 else if(c.type==='stop')transport.stop(c);
 else if(c.type==='play')await transport.play(c);
 emit(event('response',{request_id:c.request_id,ok:true,data}));
}
let buffer=Buffer.alloc(0);
process.stdin.on('data',chunk=>{
 buffer=Buffer.concat([buffer,chunk]);
 let index;
 while((index=buffer.indexOf(10))>=0){
  const line=buffer.subarray(0,index);buffer=buffer.subarray(index+1);
  let c;try{c=parseCommand(line.toString('utf8'));}catch{shutdown();return;}
  if(++pending>16){shutdown();return;}
  dispatch(c).catch(()=>{
   if(c.request_id)emit(event('response',{request_id:c.request_id,ok:false,error:'voice_command_failed',data:{}}));
   else shutdown();
  }).finally(()=>pending--);
 }
 if(buffer.length>MAX_FRAME)shutdown();
});
process.stdin.on('end',shutdown);process.stdin.on('error',shutdown);
process.stdout.on('error',shutdown);process.on('SIGTERM',shutdown);process.on('SIGINT',shutdown);
process.on('uncaughtException',shutdown);process.on('unhandledRejection',shutdown);
