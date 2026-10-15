import test from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';import fs from 'node:fs';import ts from 'typescript';
function actions(backend){
 const source=fs.readFileSync(new URL('../app/actions.ts',import.meta.url),'utf8');
 const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
 const module={exports:{}};
 const require=id=>id==='next/cache'?{revalidatePath(){}}:id==='@/lib/backend'?{backend,BackendError:class extends Error{},BackendUnreachable:class extends Error{}}:id==='@/lib/meeting'?{DEFAULT_AGENT:'Alloy',DEFAULT_OWNER:'Aloy'}:{randomUUID:()=> 'id'};
 vm.runInNewContext(code,{module,exports:module.exports,require,FormData,File,console});return module.exports;
}
test('Discord briefing save prepares knowledge without launching Recall and retries drafts',async()=>{
 const calls=[];let fail=true;
 const backend={createBriefing:async()=>{calls.push('create');return {id:'draft',purpose:'briefing',platform:'discord'};},getSession:async()=>({id:'draft',purpose:'briefing',platform:'discord'}),updateBriefing:async()=>{},addKnowledge:async()=>{calls.push('knowledge');if(fail)throw Error('invalid file');},prepareBriefing:async()=>calls.push('prepare'),launchBot:async()=>assert.fail('No Recall dispatch')};
 const a=actions(backend);assert.equal(typeof a.saveDiscordBriefing,'function');
 const form=new FormData();form.set('title','Launch');form.set('notes','Launch Friday.');
 const draft=await a.saveDiscordBriefing(null,form);assert.equal(draft.sessionId,'draft');assert.ok(draft.error);assert.deepEqual(calls,['create','knowledge']);
 fail=false;const ready=await a.saveDiscordBriefing(draft,form);assert.ok(ready.ok);assert.deepEqual(calls,['create','knowledge','knowledge','prepare']);
});
