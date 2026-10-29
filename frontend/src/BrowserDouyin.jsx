import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Panel, Field, Notice } from './components/console'

const labels = { queued:'等待开始', running:'浏览中', completed:'已完成', blocked:'需要处理', paused:'进度已保存', failed:'未完成', interrupted:'已中断', cancelled:'已停止', unknown:'状态待核对' }
const active = t => ['queued','running'].includes(t.state)
export default function BrowserDouyin({ api, notify }) {
  const [config,setConfig]=useState(null),[bound,setBound]=useState(true),[tasks,setTasks]=useState([]),[goal,setGoal]=useState(''),[settings,setSettings]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('')
  const refresh = useCallback(async () => { try { const value=await api('/browser/douyin/tasks');setTasks(value.tasks);setError('') } catch(e){setError(e.message)} },[api])
  useEffect(()=>{let alive=true;api('/browser/douyin/config').then(v=>{if(alive){setConfig(v.config);setBound(v.qq_account_bound)}}).catch(e=>{if(alive)setError(e.message)});refresh();const timer=setInterval(refresh,3000);return()=>{alive=false;clearInterval(timer)}},[api,refresh])
  const current=tasks.find(active)
  const update=(key,value)=>setConfig(c=>({...c,[key]:value}))
  const save=async()=>{setBusy(true);try{setConfig(await api('/browser/douyin/config','PUT',config));setBound(true);notify?.('抖音设置已保存')}catch(e){setError(e.message)}finally{setBusy(false)}}
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
      {!bound&&config.qq_enabled&&<Notice>保存后，QQ 授权会绑定当前接入账号。</Notice>}
      <div><Button size="sm" disabled={!!current||busy} onClick={save}>保存设置</Button></div>
    </div>}
    {config&&!config.enabled&&<Notice>在设置中开启后，可从这里或 Owner 私聊发起抖音任务。</Notice>}
    <form className="action-row" onSubmit={start}><Input aria-label="抖音浏览任务" placeholder="去抖音看看你感兴趣的内容" value={goal} maxLength={3000} disabled={busy||!!current||!config?.enabled} onChange={e=>setGoal(e.target.value)}/><Button type="submit" disabled={busy||!!current||!config?.enabled||!goal.trim()}>开始浏览</Button>{current&&<Button type="button" variant="outline" disabled={busy} onClick={()=>stop(current.id)}>停止</Button>}</form>
    <p className="browser-task-capability">支持搜索、刷推荐、观看和读取评论；评论发布、@、点赞与私信尚未接入。</p>
    <div className="browser-task-list">{tasks.slice(0,10).map(task=><details key={task.id} className="browser-task"><summary><span>{labels[task.state]||task.state}</span><strong>{task.goal}</strong><time>{new Date(task.created*1000).toLocaleString('zh-CN',{hour12:false})}</time></summary>{task.result&&<p>{task.result}</p>}{task.origin.source==='qq'&&<p>QQ 回报：{({sent:'已收到发送回执',unknown:'发送结果未确认',skipped:'授权或回复时效已变化'})[task.notification]||'尚未发送'}</p>}<ol>{task.steps.map((step,i)=><li key={i}><span>{step.reason}</span>{step.current?.title&&<p>{step.current.title}</p>}{step.watch&&<small>播放推进 {step.watch.advancedSeconds} 秒 · 抽样 {step.watch.samples.length} 次 · 无音频理解</small>}</li>)}</ol></details>)}</div>
  </Panel>
}
