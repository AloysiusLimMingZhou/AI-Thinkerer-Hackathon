"use client";
import {useActionState} from 'react';
import type {DiscordAttendance,Session} from '@/lib/api-types';
import {attendanceView} from '@/lib/attendance';
import {controlDiscord,type ActionState} from '@/app/actions';
import styles from './DiscordAttendancePanel.module.css';
function Control({id,action,label}:{id:string;action:'leave'|'mute'|'unmute'|'stop-speaking';label:string}) {
 const [state,run,pending]=useActionState<ActionState,FormData>((prev)=>controlDiscord(id,action,prev),null);
 return <form action={run}><button className="btn btn-quiet" disabled={pending}>{pending?'Working…':label}</button><p aria-live="polite">{state?.error||state?.ok}</p></form>;
}
export function DiscordAttendancePanel({session,attendance,gaps}:{session:Session;attendance:DiscordAttendance|null;gaps:string[]}) {
 const view=attendanceView(session,null,attendance);
 return <section className={styles.panel} aria-labelledby="discord-call-title">
  <div><h2 id="discord-call-title">{view.label}</h2><p>{view.detail}</p></div>
  {attendance&&<>
   <p>Voice channel <code>{attendance.channel_id}</code> · Introduction: {attendance.introduction.replaceAll('_',' ')}</p>
   <dl className={styles.health}>{Object.entries(attendance.health).map(([name,healthy])=><div key={name}><dt>{name}</dt><dd>{healthy?'Ready':'Unavailable'}</dd></div>)}</dl>
   {view.canLeave&&<div className={styles.controls}>
    <Control id={session.id} action={attendance.muted?'unmute':'mute'} label={attendance.muted?'Unmute speech':'Mute speech'}/>
    <Control id={session.id} action="stop-speaking" label="Stop speaking"/>
    <Control id={session.id} action="leave" label="Leave voice channel"/>
   </div>}
  </>}
  {gaps.length>0&&<details><summary>{gaps.length} capture gap{gaps.length===1?'':'s'}</summary><ul>{gaps.map((gap,i)=><li key={i}>{gap}</li>)}</ul></details>}
 </section>;
}
