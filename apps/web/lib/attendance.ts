import type {Session,Bot,DiscordAttendance,DiscordAttendanceStatus,BudgetStatus,Finalization} from './api-types';
import {botState,inCall,isFinal,type Tone} from './meeting.ts';
export function attendanceView(session:Session,bot:Bot|null,discord:DiscordAttendance|null) {
 if(session.purpose==='briefing')return {label:session.briefing_ready?'Prepared briefing':'Draft briefing',detail:'Select this briefing with /join in Discord. It does not attend a call by itself.',tone:'waiting' as Tone,live:false,canSpeak:false,canLeave:false};
 if(session.platform!=='discord') {
  const state=botState(bot,session.agent_name);
  return {...state,live:bot?!isFinal(bot):session.status==='active',canSpeak:inCall(bot),canLeave:!!bot&&!isFinal(bot)};
 }
 if(!discord)return {label:'No attendance',detail:'No Discord call is connected to this record.',tone:'waiting' as Tone,live:false,canSpeak:false,canLeave:false};
 const live=discord.state==='active',ready=live&&discord.health.receiver&&discord.introduction==='completed';
 const labels:Record<string,string>={joining:'Joining Discord',active:ready?'In the voice channel':'Receive or introduction needs attention',leaving:'Leaving Discord',ended:'Left the voice channel',interrupted:'Attendance interrupted',failed:'Could not attend',budget_stopped:'Stopped at the monthly budget'};
 return {label:labels[discord.state]||discord.state,detail:discord.error||(ready?(discord.muted?'Speech muted; continuing to take notes.':'Listening and transcribing. Answers are spoken when addressed.'):'Check receiver health and introduction playback below.'),tone:(live?(ready?'live':'problem'):['failed','interrupted','budget_stopped'].includes(discord.state)?'problem':'waiting') as Tone,live,canSpeak:ready&&!discord.muted,canLeave:['joining','active','leaving'].includes(discord.state)};
}
export async function loadAttendance(session:Session,client:{bot:(id:string)=>Promise<Bot|null>;discordAttendance:(id:string)=>Promise<DiscordAttendanceStatus>}) {
 if(session.purpose==='briefing')return {bot:null,discord:null};
 if(session.platform==='discord')return {bot:null,discord:(await client.discordAttendance(session.id)).attendance};
 return {bot:await client.bot(session.id),discord:null};
}
export function budgetView(status:BudgetStatus) {
 const usd=(n:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(n/1e6);
 return {settled:usd(status.settled_micro_usd),held:usd(status.held_micro_usd),available:usd(status.available_micro_usd),soft:usd(status.soft_limit_micro_usd),hard:usd(status.hard_limit_micro_usd),warning:status.soft_warning,reset:new Intl.DateTimeFormat('en-GB',{dateStyle:'medium',timeStyle:'short',timeZone:status.timezone}).format(new Date(status.reset_at))};
}
export function minutesState(finalization:Finalization,hasNotes:boolean) {
 return {ready:hasNotes&&finalization.state==='ready',pendingBudget:finalization.state==='pending_budget',label:finalization.state==='pending_budget'?'Generate notes':hasNotes?'Rewrite from the latest transcript':'Write minutes now'};
}
