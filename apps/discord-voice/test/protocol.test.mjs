import test from 'node:test';
import assert from 'node:assert/strict';
import {parseCommand,MAX_FRAME} from '../src/protocol.mjs';
test('strict IPC envelopes and media bounds',()=>{
 assert.equal(parseCommand(JSON.stringify({protocol_version:1,type:'status',request_id:'r'})).type,'status');
 for(const v of [{protocol_version:2,type:'status',request_id:'r'},{protocol_version:1,type:'status'}, {protocol_version:1,type:'status',request_id:'r',secret:'x'}])
  assert.throws(()=>parseCommand(JSON.stringify(v)));
 assert.throws(()=>parseCommand('x'.repeat(MAX_FRAME+1)));
 assert.throws(()=>parseCommand(JSON.stringify({protocol_version:1,type:'play',request_id:'r',session_id:'s',generation:'g',key:'k',audio_base64:'!'})));
});
