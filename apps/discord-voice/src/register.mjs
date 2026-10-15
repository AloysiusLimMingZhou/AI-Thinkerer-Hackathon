import {pathToFileURL} from 'node:url';
export function guildCommands(){
 return [
  {name:'join',description:'Attend a voice meeting as your AI delegate',dm_permission:false,options:[{type:7,name:'channel',description:'Standard voice channel',required:true,channel_types:[2]},{type:3,name:'briefing',description:'Optional prepared website briefing',autocomplete:true}]},
  ...[['leave','Leave and save meeting notes'],['mute','Mute speech and keep taking notes'],['unmute','Enable speech'],['stop-speaking','Cancel current and queued speech'],['status','Show meeting health and monthly budget']].map(([name,description])=>({name,description,dm_permission:false}))
 ];
}
export async function main(args=process.argv.slice(2)){
 const guild=args[args.indexOf('--guild')+1];
 if(!args.includes('--guild')||!/^\d{15,22}$/.test(guild||'')||guild!==process.env.DISCORD_GUILD_ID||!process.env.DISCORD_BOT_TOKEN)throw Error('Provide --guild matching DISCORD_GUILD_ID and a bot token');
 const {REST,Routes}=await import('discord.js');
 const rest=new REST({version:'10'}).setToken(process.env.DISCORD_BOT_TOKEN);
 const app=await rest.get(Routes.oauth2CurrentApplication());
 await rest.put(Routes.applicationGuildCommands(app.id,guild),{body:guildCommands()});
 process.stdout.write('Guild meeting commands registered.\n');
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href)main().catch(()=>{process.stderr.write('Guild registration failed; check credentials, guild and bot permissions.\n');process.exitCode=1;});
