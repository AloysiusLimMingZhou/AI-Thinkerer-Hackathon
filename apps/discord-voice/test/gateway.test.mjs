import test from 'node:test';import assert from 'node:assert/strict';import {EventEmitter} from 'node:events';
import {GatewayAdapter} from '../src/gateway.mjs';import {guildCommands} from '../src/register.mjs';
test('private command and bounded autocomplete never login or register',async()=>{
 const client=new EventEmitter();let deferred=0;const events=[];
 const gateway=new GatewayAdapter({client,transport:{},emit:e=>events.push(e),guildId:'g',ownerId:'o'});
 const i={id:'i',guildId:'g',user:{id:'o'},commandName:'join',isAutocomplete:()=>false,isChatInputCommand:()=>true,deferReply:async()=>deferred++,options:{getChannel:()=>({id:'v'}),getString:()=>null},editReply:async()=>{}};
 await gateway.interaction(i);assert.equal(deferred,1);assert.equal(events[0].type,'command');assert.equal(events[0].channel_id,'v');
 await gateway.resolve({interaction_id:'i',content:'Joined'});
 assert.equal(guildCommands()[0].options[0].channel_types[0],2);
 gateway.close();
});
