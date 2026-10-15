import {test} from 'node:test';
import assert from 'node:assert/strict';
import {activityFrom,shouldRefresh} from '../lib/meeting.ts';

test('spoken unknown answer is distinct from silence in activity',()=>{
  const events=[{sequence:1,created_at:'2026-10-15',type:'agent.decision',payload:{action:'defer',reason:'knowledge unavailable'}}];
  const activity=activityFrom(events,'Alloy',s=>s);
  assert.match(activity[0].title,/couldn.t answer/i);
});

test('call departure continues polling through finalization and stops on ready/failure',()=>{
  const session={status:'ended'}; const bot={state:'call_ended'};
  assert.equal(shouldRefresh(session,bot,{state:'processing'}),true);
  assert.equal(shouldRefresh(session,bot,{state:'ready'}),false);
  assert.equal(shouldRefresh(session,bot,{state:'failed'}),false);
});
