export const interactionDefaults=Object.freeze({comments_enabled:false,replies_enabled:false,likes_enabled:false,messages_enabled:false,shares_enabled:false,owner:{handle:'',nickname:''},whitelist:[],comment_daily_limit:10,reply_daily_limit:10,comment_task_limit:3,deepseek_probability:50,other_probability:15,dm_total_limit:20,share_task_limit:3,share_daily_limit:10,public_style:''})
export const interactionNumbers=[['comment_daily_limit','每日新评论上限',0,500],['reply_daily_limit','每日评论回复上限',0,500],['comment_task_limit','每次任务新评论上限',0,100],['deepseek_probability','DeepSeek 评论概率（%）',0,100],['other_probability','其他内容评论概率（%）',0,100],['dm_total_limit','非白名单私信总回复上限',0,10000],['share_task_limit','每次任务分享上限',0,100],['share_daily_limit','每日分享上限',0,500]]
export function interactionError(value){
 for(const [key,label,min,max] of interactionNumbers)if(!Number.isInteger(value[key])||value[key]<min||value[key]>max)return `${label}须为 ${min}–${max} 的整数`
 for(const p of [value.owner,...value.whitelist])if(!!p.handle.trim()!==!!p.nickname.trim()||!/^[\p{L}\p{N}_.-]*$/u.test(p.handle))return '请同时填写正确的抖音号和昵称'
 if(value.shares_enabled&&!value.owner.handle)return '开启站内分享前请填写 Owner 的抖音号和昵称'
 const handles=value.whitelist.map(p=>p.handle)
 if(handles.some(p=>!p)||new Set(handles).size!==handles.length)return '白名单抖音号不能为空或重复'
 return ''
}
