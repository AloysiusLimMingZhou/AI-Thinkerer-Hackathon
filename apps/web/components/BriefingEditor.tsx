"use client";
import {useActionState,useEffect} from 'react';
import {useRouter} from 'next/navigation';
import type {Session} from '@/lib/api-types';
import {saveBriefingMetadata,removeBriefing,type ActionState} from '@/app/actions';
import styles from './SendForm.module.css';
export function BriefingEditor({session}:{session:Session}){
 const router=useRouter();
 const [state,save,pending]=useActionState<ActionState,FormData>(saveBriefingMetadata.bind(null,session.id),null);
 const [removed,remove,deleting]=useActionState<ActionState,FormData>((prev)=>removeBriefing(session.id,prev),null);
 useEffect(()=>{if(removed?.ok)router.replace('/');},[removed,router]);
 return <section style={{padding:24,display:'grid',gap:20}}>
  <div><h2>{session.briefing_ready?'Prepared Discord briefing':'Draft Discord briefing'}</h2>
   <p>Add knowledge below, then prepare this briefing. In Discord, use <code>/join</code>, choose a voice channel, and select this briefing. Leaving the briefing choice empty starts with no knowledge.</p>
  </div>
  <form action={save} className={styles.form}>
   <label className={styles.field}><span>Briefing name</span><input name="title" defaultValue={session.title} maxLength={200} required/></label>
   <div className={styles.pair}>
    <label className={styles.field}><span>Attending for</span><input name="owner_name" defaultValue={session.owner_name} maxLength={100} required/></label>
    <label className={styles.field}><span>Delegate name</span><input name="agent_name" defaultValue={session.agent_name} maxLength={100} required/></label>
   </div>
   {!session.briefing_ready&&<label className={styles.consent}><input name="prepare" type="checkbox" value="yes"/><span>Knowledge is complete. Make this briefing available to /join.</span></label>}
   <button className="btn btn-quiet" disabled={pending}>{pending?'Saving…':'Save briefing'}</button>
   <p aria-live="polite">{state?.error||state?.ok}</p>
  </form>
  <form action={remove}><button className="btn btn-quiet" disabled={deleting}>{deleting?'Deleting…':'Delete briefing'}</button><p>Knowledge already copied into meetings is preserved.</p><p aria-live="polite">{removed?.error}</p></form>
 </section>;
}
