import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Field } from './components/console'
import { interactionNumbers } from './lib/douyin-interactions.mjs'

export default function DouyinInteractionSettings({value,onChange,disabled}) {
 const set=(key,next)=>onChange({...value,[key]:next})
 const person=(p,change,prefix)=><div className="form-grid"><Field label="抖音号" id={`${prefix}-handle`}><Input id={`${prefix}-handle`} value={p.handle} maxLength={80} onChange={e=>change({...p,handle:e.target.value.trim()})}/></Field><Field label="昵称" id={`${prefix}-nickname`}><Input id={`${prefix}-nickname`} value={p.nickname} maxLength={80} onChange={e=>change({...p,nickname:e.target.value})}/></Field></div>
 return <fieldset className="browser-viewing-settings" disabled={disabled}>
  <legend>抖音互动</legend>
  <div className="action-row">{[['comments_enabled','发表新评论'],['replies_enabled','回复评论'],['likes_enabled','点赞'],['messages_enabled','回复私信'],['shares_enabled','分享给 Owner']].map(([key,label])=><label key={key}><input type="checkbox" checked={value[key]} onChange={e=>set(key,e.target.checked)}/> {label}</label>)}</div>
  <details><summary>Owner 抖音账号</summary>{person(value.owner,p=>set('owner',p),'douyin-owner')}</details>
  <div className="form-grid">{interactionNumbers.map(([key,label,min,max])=><Field key={key} label={label} hint={key==='dm_check_interval_seconds'?'漏检复查间隔；新消息由独立私信页的变化即时唤醒处理':undefined} id={`douyin-${key}`}><Input id={`douyin-${key}`} type="number" min={min} max={max} step={1} value={value[key]} onChange={e=>set(key,e.target.value===''?'':Number(e.target.value))}/></Field>)}
  <Field label="公开评论风格" id="douyin-public-style" full><Textarea id="douyin-public-style" value={value.public_style} maxLength={2000} onChange={e=>set('public_style',e.target.value)}/></Field></div>
  <details><summary>私信白名单（{value.whitelist.length}）</summary>
    {value.whitelist.map((p,i)=><div key={i} className="douyin-whitelist-row">{person(p,next=>set('whitelist',value.whitelist.map((old,index)=>index===i?next:old)),`douyin-whitelist-${i}`)}<Button type="button" size="sm" variant="destructive" onClick={()=>set('whitelist',value.whitelist.filter((_,index)=>index!==i))}>移除</Button></div>)}
    <Button type="button" size="sm" variant="outline" disabled={value.whitelist.length>=100} onClick={()=>set('whitelist',[...value.whitelist,{handle:'',nickname:''}])}>添加用户</Button>
  </details>
  <p className="browser-task-capability">私信仅回复先来信的人；非白名单还须已关注自己，总次数按所有人合计、跨任务累计。每日额度按北京时间重置，分享按抖音站内流程发送。结果待核对的提交占用额度且不会重发。</p>
 </fieldset>
}
