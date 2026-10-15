import test from 'node:test';import assert from 'node:assert/strict';
import {attendanceView,loadAttendance,budgetView,minutesState} from '../lib/attendance.ts';
const session={id:'s',platform:'discord',purpose:'meeting',status:'active',agent_name:'Alloy'};
const active={state:'active',health:{receiver:true,connection:true,player:true},introduction:'completed',muted:false};
test('Discord attendance is live without Recall',()=>{
 assert.equal(attendanceView(session,null,active).live,true);
 assert.equal(attendanceView(session,null,active).canSpeak,true);
 const briefing={...session,purpose:'briefing',briefing_ready:false};
 assert.equal(attendanceView(briefing,null,null).live,false);assert.equal(attendanceView(briefing,null,null).canSpeak,false);
 assert.equal(attendanceView(session,null,{...active,introduction:'pending'}).canSpeak,false);
 assert.equal(attendanceView(session,null,{...active,state:'budget_stopped'}).live,false);
});
test('Discord detail never requests a Recall bot',async()=>{
 const calls=[];const client={bot:async()=>{calls.push('bot');return null;},discordAttendance:async()=>{calls.push('discord');return {attendance:active};}};
 assert.equal((await loadAttendance(session,client)).discord,active);assert.deepEqual(calls,['discord']);
 calls.length=0;await loadAttendance({...session,purpose:'briefing'},client);assert.deepEqual(calls,[]);
 await loadAttendance({...session,platform:'google_meet'},client);assert.deepEqual(calls,['bot']);
});
test('budget displays held money and local reset; blocked notes never claim a summary',()=>{
 const v=budgetView({month:'2026-10',timezone:'Asia/Kuala_Lumpur',reset_at:'2026-10-31T16:00:00Z',settled_micro_usd:5000000,held_micro_usd:2000000,available_micro_usd:1000000,soft_warning:true});
 assert.equal(v.settled,'$5.00');assert.equal(v.held,'$2.00');assert.equal(v.available,'$1.00');assert.equal(v.warning,true);assert.match(v.reset,/Nov|11/);
 assert.equal(minutesState({state:'pending_budget'},true).ready,false);
 assert.equal(minutesState({state:'pending_budget'},true).label,'Generate notes');
});
