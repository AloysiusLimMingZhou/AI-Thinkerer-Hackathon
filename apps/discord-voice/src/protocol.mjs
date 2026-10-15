export const MAX_FRAME=12*1024*1024, MAX_WAV=512*1024, MAX_MP3=8*1024*1024;
export function media(value,limit){
 if(typeof value!=='string'||!value.length||value.length>4*Math.ceil(limit/3)||!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value))throw Error('invalid_media');
 const bytes=Buffer.from(value,'base64');if(!bytes.length||bytes.length>limit)throw Error('invalid_media');return bytes;
}
const layouts={
 config:['guild_id','owner_id','ffmpeg_path','max_attendance_seconds'],
 status:[],join:['session_id','generation','guild_id','channel_id'],leave:['session_id','generation'],stop:['session_id','generation'],
 mute:['session_id','generation','muted'],play:['session_id','generation','key','audio_base64'],
 interaction_result:['interaction_id','content','choices']
};
export function parseCommand(line){
 if(Buffer.byteLength(line)>MAX_FRAME)throw Error('frame_too_large');
 const item=JSON.parse(line);
 if(!item||Array.isArray(item)||item.protocol_version!==1||!Object.hasOwn(layouts,item.type))throw Error('invalid_command');
 const allowed=['protocol_version','type',...(item.type==='config'?[]:['request_id']),...layouts[item.type]];
 if(Object.keys(item).some(k=>!allowed.includes(k)))throw Error('extra_field');
 for(const key of allowed){
  if(['content','choices'].includes(key)||item.type==='config')continue;
  if(key==='muted'){if(typeof item[key]!=='boolean')throw Error('invalid_muted');}
  else if(key!=='protocol_version'&&key!=='audio_base64'&&(typeof item[key]!=='string'||!item[key].length||item[key].length>200))throw Error('missing_id');
 }
 if(item.type==='play')media(item.audio_base64,MAX_MP3);
 if(item.type==='interaction_result'){
  if(item.content!=null&&(typeof item.content!=='string'||item.content.length>2000))throw Error('invalid_content');
  if(item.choices!=null&&(!Array.isArray(item.choices)||item.choices.length>25||item.choices.some(v=>typeof v.name!=='string'||typeof v.value!=='string'||v.name.length>100||v.value.length>100)))throw Error('invalid_choices');
 }
 if(item.type==='config'&&(typeof item.ffmpeg_path!=='string'||item.ffmpeg_path.length>1000||!Number.isInteger(item.max_attendance_seconds)||item.max_attendance_seconds<60||item.max_attendance_seconds>14400))throw Error('invalid_config');
 return item;
}
export function event(type,data={}){return {protocol_version:1,type,...data};}
