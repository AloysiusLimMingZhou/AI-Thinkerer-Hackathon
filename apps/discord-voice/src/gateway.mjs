import {event} from './protocol.mjs';
export class GatewayAdapter{
 constructor({client,transport,emit,guildId,ownerId}){
  Object.assign(this,{client,transport,emit,guildId,ownerId});this.pending=new Map();
  this.onInteraction=i=>this.interaction(i).catch(()=>{});
  this.onMessage=m=>{
   if(m.guildId!==this.guildId||m.author?.id!==this.ownerId||m.author.bot||m.webhookId||!m.channel?.isThread())return;
   this.emit(event('owner_reply',{id:m.id,guild_id:m.guildId,channel_id:m.channelId,author_id:m.author.id,content:m.content.slice(0,4000),bot:false,webhook:false}));
  };
  client.on('interactionCreate',this.onInteraction);client.on('messageCreate',this.onMessage);
 }
 async interaction(i){
  const autocomplete=i.isAutocomplete();
  if(!autocomplete&&!i.isChatInputCommand())return;
  if(i.guildId!==this.guildId||i.user.id!==this.ownerId){
   if(autocomplete)await i.respond([]);else await i.reply({content:'Only the configured owner can control this meeting agent.',flags:64});
   return;
  }
  if(this.pending.size>=64){if(autocomplete)await i.respond([]);else await i.reply({content:'The agent is busy; try again shortly.',flags:64});return;}
  if(!autocomplete)await i.deferReply({flags:64});
  const timer=setTimeout(()=>{
   const record=this.pending.get(i.id);if(!record)return;this.pending.delete(i.id);
   (autocomplete?i.respond([]):i.editReply({content:'The agent did not respond. Check its dashboard status before retrying.'})).catch(()=>{});
  },autocomplete?1000:30000);timer.unref();
  this.pending.set(i.id,{i,timer,autocomplete});
  if(autocomplete)this.emit(event('autocomplete',{interaction_id:i.id,guild_id:i.guildId,actor_id:i.user.id,query:String(i.options.getFocused()).slice(0,100)}));
  else this.emit(event('command',{interaction_id:i.id,command:i.commandName,guild_id:i.guildId,actor_id:i.user.id,channel_id:i.options.getChannel('channel')?.id||null,briefing_id:i.options.getString('briefing')||null}));
 }
 async resolve(c){
  const record=this.pending.get(c.interaction_id);if(!record)return;
  this.pending.delete(c.interaction_id);clearTimeout(record.timer);
  if(record.autocomplete)await record.i.respond((c.choices||[]).slice(0,25));
  else await record.i.editReply({content:c.content||'Done.',allowedMentions:{parse:[]}});
 }
 close(){for(const r of this.pending.values())clearTimeout(r.timer);this.pending.clear();this.client.off('interactionCreate',this.onInteraction);this.client.off('messageCreate',this.onMessage);}
}
