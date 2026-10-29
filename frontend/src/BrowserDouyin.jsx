import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Panel, Field, Notice } from './components/console'
import DouyinInteractionSettings from './DouyinInteractionSettings'
import {interactionDefaults,interactionError} from './lib/douyin-interactions.mjs'
import { viewingDefaults, viewingFields, viewingError } from './lib/browser-viewing.mjs'

const labels = { queued:'等待开始', running:'浏览中', completed:'已完成', blocked:'需要处理', paused:'进度已保存', failed:'未完成', interrupted:'已中断', cancelled:'已停止', unknown:'状态待核对' }
const active = t => ['queued','running'].includes(t.state)
const ranges = value => value?.map(([a,b])=>`${a}–${b} 秒`).join('、')

function TaskProgress({ task }) {
  return <>
    <ol>{task.steps.map((step,i)=><li key={i}>
      <span>{step.reason}</span>{step.current?.title&&<p>{step.current.title}</p>}
      {step.interaction&&<p>{({confirmed:'已确认',failed:'未成功',unknown:'结果待核对，请勿重发'})[step.interaction.status]}{step.interaction.reason?` · ${step.interaction.reason}`:''}</p>}
      {step.skipped&&<p>{step.skipped.title&&`${step.skipped.title} · `}{step.skipped.reason}</p>}
      {step.actionError&&<p>操作未执行 · {step.actionError.reason}</p>}
      {step.seekFailed&&<p>跳转未确认，未播放该片段</p>}
      {step.previewComplete&&<p>默认分段预览已结束，未完整观看</p>}
      {step.watch&&<small>播放推进 {step.watch.advancedSeconds} 秒 · 抽样 {step.watch.samples.length} 次 · 无音频理解
        {step.watch.mode==='preview'&&<> · 分段跳看{step.watch.seek?`（跳至 ${Math.round(step.watch.seek.actual)} 秒）`:''}</>}
        {step.watch.coverageRanges&&<><br/>累计播放：{ranges(step.watch.coverageRanges)||'尚未推进'}{step.watch.fullDuration?` / 全长 ${Math.round(step.watch.fullDuration)} 秒`:''} · {step.watch.partial?'未完整播放':'已覆盖全片'}{step.watch.ended?' · 已到结尾':''}</>}
      </small>}
    </li>)}</ol>
    {!!task.decision_errors?.length&&<details className="browser-decision-errors"><summary>操作格式诊断（{task.decision_errors.length}）</summary>
      {task.decision_errors.map(item=><div key={item.sequence}><p>第 {item.sequence} 次校验未通过 · 本轮尝试 {item.attempt}/3：{item.error}</p><pre>{item.response}</pre></div>)}
    </details>}
  </>
}
export default function BrowserDouyin({ api, notify }) {
  const [config,setConfig]=useState(null),[bound,setBound]=useState(true),[tasks,setTasks]=useState([]),[goal,setGoal]=useState(''),[settings,setSettings]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[operations,setOperations]=useState([]),[autoStatus,setAutoStatus]=useState(null)
  const refresh = useCallback(async () => { try { const value=await api('/browser/douyin/tasks');setTasks(value.tasks);setAutoStatus(value.auto_browse||null);setOperations(value.operations||[]);setError('') } catch(e){setError(e.message)} },[api])
  useEffect(()=>{let alive=true;api('/browser/douyin/config').then(v=>{if(alive){setConfig(v.config);setBound(v.qq_account_bound)}}).catch(e=>{if(alive)setError(e.message)});refresh();const timer=setInterval(refresh,3000);return()=>{alive=false;clearInterval(timer)}},[api,refresh])
  const current=tasks.find(active)
  const update=(key,value)=>setConfig(c=>({...c,[key]:value}))
  const viewing={...viewingDefaults,...config?.viewing}
  const interactions={...interactionDefaults,...config?.interactions,owner:{...interactionDefaults.owner,...config?.interactions?.owner}}
  const autoBrowse={enabled:false,daily_video_limit:30,...config?.auto_browse}
  const updateAuto=(key,value)=>update('auto_browse',{...autoBrowse,[key]:value})
  const updateViewing=(key,value)=>setConfig(c=>({...c,viewing:{...viewingDefaults,...c.viewing,[key]:value}}))
  const save=async()=>{const invalid=viewingError(viewing)||interactionError(interactions)||(!Number.isInteger(autoBrowse.daily_video_limit)||autoBrowse.daily_video_limit<1||autoBrowse.daily_video_limit>1000?'每日视频总数须为 1–1000 的整数':'');if(invalid){setError(invalid);return}setBusy(true);try{setConfig(await api('/browser/douyin/config','PUT',{...config,viewing,interactions,auto_browse:autoBrowse}));setBound(true);setError('');notify?.('抖音设置已保存')}catch(e){setError(e.message)}finally{setBusy(false)}}
  const start=async e=>{e.preventDefault();setBusy(true);try{await api('/browser/douyin/tasks','POST',{goal});setGoal('');await refresh()}catch(e){setError(e.message)}finally{setBusy(false)}}
  const stop=async id=>{setBusy(true);try{await api(`/browser/douyin/tasks/${id}/stop`,'POST',{});await refresh()}catch(e){setError(e.message)}finally{setBusy(false)}}
  return <Panel title="抖音自主浏览" action={<Button size="sm" variant="outline" aria-expanded={settings} onClick={()=>setSettings(v=>!v)}>{settings?'收起设置':'设置'}</Button>}>
    {error&&<Notice alert>{error}</Notice>}
    {config&&settings&&<div className="page-stack">
      <div className="action-row"><label><input type="checkbox" checked={config.enabled} disabled={!!current||busy} onChange={e=>update('enabled',e.target.checked)}/> 开启自主浏览</label><label><input type="checkbox" checked={config.qq_enabled} disabled={!!current||busy} onChange={e=>update('qq_enabled',e.target.checked)}/> 允许 Owner 私聊发起</label></div>
      <div className="form-grid">
        <Field label="QQ Owner ID" id="browser-owner"><Input id="browser-owner" value={config.qq_owner_id} maxLength={128} disabled={!!current||busy} onChange={e=>update('qq_owner_id',e.target.value)}/></Field>
        <Field label="识别自然语言请求" id="browser-natural"><input id="browser-natural" type="checkbox" checked={config.natural_requests} disabled={!!current||busy} onChange={e=>update('natural_requests',e.target.checked)}/></Field>
        <Field label="角色兴趣" id="browser-character"><Textarea id="browser-character" value={config.character_interests} maxLength={2000} disabled={!!current||busy} onChange={e=>update('character_interests',e.target.value)}/></Field>
        <Field label="主人喜好" id="browser-owner-interests"><Textarea id="browser-owner-interests" value={config.owner_interests} maxLength={2000} disabled={!!current||busy} onChange={e=>update('owner_interests',e.target.value)}/></Field>
        <Field label="内容筛选要求" id="browser-constraints" full><Textarea id="browser-constraints" value={config.content_constraints} maxLength={2000} disabled={!!current||busy} onChange={e=>update('content_constraints',e.target.value)}/></Field>
        {[['timeout_minutes','每次时间上限（分钟）',1,120],['max_steps','步骤上限',5,300],['buffering_wait_seconds','缓冲等待（秒）',30,600]].map(([key,label,min,max])=><Field key={key} label={label} id={`browser-${key}`}><Input id={`browser-${key}`} type="number" min={min} max={max} value={config[key]} disabled={!!current||busy} onChange={e=>update(key,Number(e.target.value))}/></Field>)}
      </div>
      <fieldset className="browser-viewing-settings" disabled={!!current||busy}>
        <legend>观看策略</legend>
        <label><input type="checkbox" checked={viewing.preview_enabled} onChange={e=>updateViewing('preview_enabled',e.target.checked)}/> 长视频分段跳看</label>
        <div className="form-grid">{viewingFields.map(([key,label,min,max])=><Field key={key} label={label} id={`browser-viewing-${key}`}><Input id={`browser-viewing-${key}`} type="number" min={min} max={max} step={1} value={viewing[key]} disabled={!viewing.preview_enabled&&key!=='max_video_minutes'} onChange={e=>updateViewing(key,e.target.value===''?'':Number(e.target.value))}/></Field>)}</div>
      </fieldset>
      <fieldset className="browser-viewing-settings" disabled={!!current||busy}>
        <legend>空闲时段自动刷</legend>
        <div className="form-grid"><label><input type="checkbox" checked={autoBrowse.enabled} onChange={e=>updateAuto('enabled',e.target.checked)}/> 开启自动刷视频</label>
        <Field label="每日视频总数" id="douyin-auto-limit"><Input id="douyin-auto-limit" type="number" min={1} max={1000} value={autoBrowse.daily_video_limit} onChange={e=>updateAuto('daily_video_limit',e.target.value===''?'':Number(e.target.value))}/></Field></div>
        <p className="browser-task-capability">北京时间周一至周五 9:00–12:00、14:00–18:00 为高峰；周末与中国法定节假日全天空闲。进入高峰后完成当前操作即暂停。当天实际看过的不同视频各计一次，手动浏览也计入，重复观看不重复计数。</p>
      </fieldset>
      <DouyinInteractionSettings value={interactions} onChange={v=>update('interactions',v)} disabled={!!current||busy}/>
      {!bound&&config.qq_enabled&&<Notice>保存后，QQ 授权会绑定当前接入账号。</Notice>}
      <div><Button size="sm" disabled={!!current||busy} onClick={save}>保存设置</Button></div>
    </div>}
    {config&&!config.enabled&&<Notice>在设置中开启后，可从这里或 Owner 私聊发起抖音任务。</Notice>}
    {autoStatus?.enabled&&<div className="page-stack"><div className="action-row"><span>{autoStatus.peak?'高峰时段':'空闲时段'} · 今日 {autoStatus.today_watched} / {autoStatus.daily_video_limit} 条</span><Button size="sm" variant="outline" disabled={busy} onClick={async()=>{setBusy(true);try{await api(`/browser/douyin/auto/${autoStatus.hold_reason?'resume':'pause'}`,'POST',{});await refresh()}catch(e){setError(e.message)}finally{setBusy(false)}}}>{autoStatus.hold_reason?'恢复自动浏览':'暂停今日自动浏览'}</Button></div>{autoStatus.hold_reason&&<p>{autoStatus.hold_reason}</p>}{!current&&!autoStatus.hold_reason&&autoStatus.next_run_at&&<p>下次可运行：{new Date(autoStatus.next_run_at).toLocaleString('zh-CN',{hour12:false})}</p>}{autoStatus.calendar_warning&&<Notice>{autoStatus.calendar_warning}</Notice>}</div>}
    <form className="action-row" onSubmit={start}><Input aria-label="抖音浏览任务" placeholder="去抖音看看你感兴趣的内容" value={goal} maxLength={3000} disabled={busy||!!current||!config?.enabled} onChange={e=>setGoal(e.target.value)}/><Button type="submit" disabled={busy||!!current||!config?.enabled||!goal.trim()}>开始浏览</Button>{current&&<Button type="button" variant="outline" disabled={busy} onClick={()=>stop(current.id)}>停止</Button>}</form>
    <p className="browser-task-capability">评论、@、点赞、私信回复与站内分享按设置执行。</p>
    {!!operations.length&&<details><summary>最近互动（{operations.length}）</summary><div className="douyin-operation-list">{operations.map(item=><div key={item.id}><span>{({comment:'新评论',reply_comment:'评论回复',reply_dm:'私信回复',like:'点赞',share:'站内分享',share_note:'分享附言'})[item.op]}</span><span>{({confirmed:'已确认',failed:'未成功',unknown:'待核对',pending:'提交中'})[item.status]}</span><time>{new Date(item.created*1000).toLocaleString()}</time></div>)}</div></details>}
    <div className="browser-task-list">{tasks.slice(0,10).map(task=><details key={task.id} className="browser-task"><summary><span>{labels[task.state]||task.state}</span><strong>{task.goal}</strong><time>{new Date(task.created*1000).toLocaleString('zh-CN',{hour12:false})}</time></summary>{task.result&&<p>{task.result}</p>}{task.origin.source==='qq'&&<p>QQ 回报：{({sent:'已收到发送回执',unknown:'发送结果未确认',skipped:'授权或回复时效已变化'})[task.notification]||'尚未发送'}</p>}<TaskProgress task={task}/></details>)}</div>
  </Panel>
}
