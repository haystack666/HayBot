import { useCallback, useEffect, useRef, useState } from 'react'
import { Dialog } from 'radix-ui'
import { Settings2, Plus, X, Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Field, Notice } from './components/console'
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
export default function BrowserDouyin({ api, notify, children, onCheck }) {
  const [config,setConfig]=useState(null),[savedConfig,setSavedConfig]=useState(null),[bound,setBound]=useState(true),[tasks,setTasks]=useState([]),[goal,setGoal]=useState(''),[settings,setSettings]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[operations,setOperations]=useState([]),[autoStatus,setAutoStatus]=useState(null)
  const [page,setPage]=useState('live'),[category,setCategory]=useState('general'),[newTask,setNewTask]=useState(false),[detailId,setDetailId]=useState(null),[taskFilter,setTaskFilter]=useState('all'),[operationFilter,setOperationFilter]=useState('all')
  const [progressId,setProgressId]=useState(null),[progressOpen,setProgressOpen]=useState(false)
  const progressLayout=useRef(null), progressButton=useRef(null)
  const refresh = useCallback(async () => { try { const value=await api('/browser/douyin/tasks');setTasks(value.tasks);setAutoStatus(value.auto_browse||null);setOperations(value.operations||[]);setError('') } catch(e){setError(e.message)} },[api])
  useEffect(()=>{let alive=true;api('/browser/douyin/config').then(v=>{if(alive){setConfig(v.config);setSavedConfig(v.config);setBound(v.qq_account_bound)}}).catch(e=>{if(alive)setError(e.message)});refresh();const timer=setInterval(refresh,3000);return()=>{alive=false;clearInterval(timer)}},[api,refresh])
  const current=tasks.find(active)
  const update=(key,value)=>setConfig(c=>({...c,[key]:value}))
  const viewing={...viewingDefaults,...config?.viewing}
  const interactions={...interactionDefaults,...config?.interactions,owner:{...interactionDefaults.owner,...config?.interactions?.owner}}
  const autoBrowse={enabled:false,daily_video_limit:30,...config?.auto_browse}
  const updateAuto=(key,value)=>update('auto_browse',{...autoBrowse,[key]:value})
  const updateViewing=(key,value)=>setConfig(c=>({...c,viewing:{...viewingDefaults,...c.viewing,[key]:value}}))
  const save=async()=>{const invalid=viewingError(viewing)||interactionError(interactions)||(!Number.isInteger(autoBrowse.daily_video_limit)||autoBrowse.daily_video_limit<1||autoBrowse.daily_video_limit>1000?'每日视频总数须为 1–1000 的整数':'');if(invalid){setError(invalid);return}setBusy(true);try{const saved=await api('/browser/douyin/config','PUT',{...config,viewing,interactions,auto_browse:autoBrowse});setConfig(saved);setSavedConfig(saved);setBound(true);setError('');setSettings(false);notify?.('抖音设置已保存')}catch(e){setError(e.message)}finally{setBusy(false)}}
  const start=async e=>{e.preventDefault();setBusy(true);try{await api('/browser/douyin/tasks','POST',{goal});setGoal('');setNewTask(false);setPage('live');await refresh()}catch(e){setError(e.message)}finally{setBusy(false)}}
  const stop=async id=>{setBusy(true);try{await api(`/browser/douyin/tasks/${id}/stop`,'POST',{});await refresh()}catch(e){setError(e.message)}finally{setBusy(false)}}
  const verify=async id=>{setBusy(true);try{const result=await api(`/browser/douyin/operations/${id}/verify`,'POST',{});await refresh();notify?.(result.reason||'核对完成')}catch(e){setError(e.message)}finally{setBusy(false)}}
  const detail = tasks.find(t=>t.id===detailId)
  const progressTask=tasks.find(t=>t.id===progressId)
  const progressTarget=current||progressTask
  const closeProgress=useCallback(()=>{setProgressOpen(false);progressButton.current?.focus({preventScroll:true})},[])
  useEffect(()=>{
    const root=progressLayout.current, viewer=root?.querySelector('.browser-viewer')
    if(!viewer)return
    const measure=()=>{
      const height=viewer.getBoundingClientRect().height
      if(height>0)root.style.setProperty('--browser-progress-height',`${Math.max(360,Math.round(height))}px`)
    }
    const observer=new ResizeObserver(measure);observer.observe(viewer);measure()
    return()=>observer.disconnect()
  },[])
  useEffect(()=>{
    if(!progressOpen||page!=='live')return
    const escape=e=>{if(e.key==='Escape'&&!document.querySelector('[role="dialog"]')&&!document.querySelector('.browser-viewer.is-expanded')){e.preventDefault();closeProgress()}}
    document.addEventListener('keydown',escape)
    return()=>document.removeEventListener('keydown',escape)
  },[progressOpen,page,closeProgress])
  const unknownCount=operations.filter(o=>o.status==='unknown').length
  const categories={general:'浏览偏好',viewing:'观看策略',schedule:'自动浏览',interaction:'互动权限',browser:'浏览器'}
  return <div className="browser-workbench">
    <div className="browser-workbench-actions"><Button size="sm" variant="outline" onClick={()=>{setCategory('general');setSettings(true)}}><Settings2 size={14}/>浏览设置</Button><Button size="sm" onClick={()=>setNewTask(true)}><Plus size={14}/>新建任务</Button></div>
    <div className="browser-page-tabs" role="tablist" aria-label="工作台内容">{[['live','工作台'],['tasks','任务记录'],['operations','互动记录']].map(([key,label])=><button key={key} role="tab" aria-selected={page===key} aria-controls={`browser-tab-${key}`} id={`browser-tab-button-${key}`} onClick={()=>setPage(key)}>{label}{key==='tasks'&&<span>{tasks.length}</span>}{key==='operations'&&unknownCount>0&&<span className="browser-pending-count">{unknownCount} 待核对</span>}</button>)}</div>
    {error&&<Notice alert>{error}</Notice>}
    <section id="browser-tab-live" role="tabpanel" aria-labelledby="browser-tab-button-live" hidden={page!=='live'}>
      <div ref={progressLayout} className={`browser-progress-layout ${progressOpen?'progress-open':''}`}><div className="browser-viewer-column">{children}
      <div className="browser-current-task"><Play size={17}/><div><b>{current?.goal||'当前没有运行中的任务'}</b><span>{current ? `${labels[current.state]} · ${current.steps.length} 步` : config?.enabled ? '可从新建任务或 Owner 私聊发起' : '在浏览设置中开启自主浏览'}</span></div>{progressTarget&&<><Button ref={progressButton} size="sm" variant="ghost" aria-expanded={progressOpen} aria-controls="browser-live-progress" onClick={()=>{setProgressId(progressTarget.id);setProgressOpen(v=>progressTarget.id===progressId?!v:true)}}>{progressOpen?'收起进度':'查看进度'}</Button><Button size="icon-sm" variant="ghost" aria-label="停止任务" disabled={busy||!current} onClick={()=>stop(current.id)}><X size={15}/></Button></>}</div>
    {autoStatus?.enabled&&<div className="browser-auto-strip"><div className="action-row"><span>{autoStatus.peak?'高峰时段':'空闲时段'} · 今日 {autoStatus.today_watched} / {autoStatus.daily_video_limit} 条</span><Button size="sm" variant="outline" disabled={busy} onClick={async()=>{setBusy(true);try{await api(`/browser/douyin/auto/${autoStatus.hold_reason?'resume':'pause'}`,'POST',{});await refresh()}catch(e){setError(e.message)}finally{setBusy(false)}}}>{autoStatus.hold_reason?'恢复自动浏览':'暂停今日自动浏览'}</Button></div>{autoStatus.hold_reason&&<p>{autoStatus.hold_reason}</p>}{!current&&!autoStatus.hold_reason&&autoStatus.next_run_at&&<p>下次可运行：{new Date(autoStatus.next_run_at).toLocaleString('zh-CN',{hour12:false})}</p>}{autoStatus.calendar_warning&&<Notice>{autoStatus.calendar_warning}</Notice>}</div>}
      </div><aside id="browser-live-progress" className="browser-progress-pane" aria-label="任务进度" aria-hidden={!progressOpen} inert={!progressOpen}><div className="browser-progress-inner">
        <header className="browser-progress-header"><h2>任务进度</h2><Button size="icon-sm" variant="ghost" aria-label="收起任务进度" onClick={closeProgress}><X size={16}/></Button></header>
        <div className="browser-progress-scroll">{progressTask&&<>
          <div className="browser-progress-state"><span>{labels[progressTask.state]||progressTask.state}</span><time>{new Date(progressTask.created*1000).toLocaleTimeString('zh-CN',{hour12:false})} 开始</time></div>
          <h3>{progressTask.goal}</h3><p className="browser-progress-count">{progressTask.steps.length} 步 · {progressTask.steps.filter(s=>s.interaction?.status==='confirmed').length} 次互动已确认</p>
          {progressTask.result&&<Notice>{progressTask.result}</Notice>}
          {progressTask.steps.length>0&&<div className="browser-progress-current"><span>最近一步</span><b>{progressTask.steps.at(-1).reason}</b>{progressTask.steps.at(-1).current?.title&&<p>{progressTask.steps.at(-1).current.title}</p>}</div>}
          {(progressTask.origin?.source==='qq'||progressTask.notification)&&<p>QQ 回报：{({sent:'已收到发送回执',unknown:'发送结果未确认',skipped:'授权或连接已变化，未发送',sending:'正在发送'})[progressTask.notification]||'尚未发送'}</p>}
          <h4>执行记录 <span>最近优先</span></h4><TaskProgress task={{...progressTask,steps:[...progressTask.steps].reverse()}}/>
        </>}</div>
        <footer className="browser-progress-footer"><span>{progressTask&&active(progressTask)?'自动更新 · 不影响浏览':'进度已保存'}</span>{progressTask&&active(progressTask)&&<Button size="sm" variant="outline" disabled={busy} onClick={()=>stop(progressTask.id)}>停止任务</Button>}</footer>
      </div></aside></div>
    </section>
    <section id="browser-tab-tasks" role="tabpanel" aria-labelledby="browser-tab-button-tasks" hidden={page!=='tasks'}><div className="browser-record-toolbar">{[['all','全部'],['running','进行中'],['completed','已完成'],['blocked','需处理']].map(([key,label])=><Button key={key} size="sm" variant={taskFilter===key?'secondary':'ghost'} onClick={()=>setTaskFilter(key)}>{label}</Button>)}</div><div className="browser-records">{tasks.filter(t=>taskFilter==='all'||taskFilter==='running'&&active(t)||taskFilter==='blocked'&&['blocked','failed','unknown','interrupted'].includes(t.state)||t.state===taskFilter).map(t=><article className="browser-record" key={t.id}><div><b>{t.goal}</b><small>{new Date(t.created*1000).toLocaleString('zh-CN',{hour12:false})}</small></div><span>{labels[t.state]||t.state}</span><Button size="sm" variant="outline" onClick={()=>setDetailId(t.id)}>查看</Button></article>)}{!tasks.length&&<div className="empty">暂无任务记录</div>}</div></section>
    <section id="browser-tab-operations" role="tabpanel" aria-labelledby="browser-tab-button-operations" hidden={page!=='operations'}><div className="browser-record-toolbar">{[['all','全部'],['unknown','待核对'],['confirmed','已确认'],['failed','未成功']].map(([key,label])=><Button key={key} size="sm" variant={operationFilter===key?'secondary':'ghost'} onClick={()=>setOperationFilter(key)}>{label}</Button>)}</div>
    <div className="douyin-operation-list">{operations.filter(item=>operationFilter==='all'||item.status===operationFilter).map(item=>{
      let receipt={};try{receipt=JSON.parse(item.receipt||'{}')}catch{}
      const detail=item.details||{}, videoOperation=['like','comment','reply_comment','share','share_note'].includes(item.op)
      const contentLabel=({comment:'评论正文',reply_comment:'回复正文',reply_dm:'私信正文',share_note:'分享附言'})[item.op]
      return <article className="browser-interaction" key={item.id}>
        <header><b>{({comment:'新评论',reply_comment:'评论回复',reply_dm:'私信回复',like:'点赞',share:'站内分享',share_note:'分享附言'})[item.op]||item.op}</b><span data-status={item.status}>{({confirmed:'已确认',failed:'未成功',unknown:'待核对',pending:'提交中'})[item.status]||item.status}</span><time>{new Date(item.created*1000).toLocaleString('zh-CN',{hour12:false})}</time></header>
        {videoOperation&&<div className="browser-interaction-video"><strong>{detail.video_title||'历史记录未保存视频标题'}</strong>{detail.video_url ? <a href={detail.video_url} target="_blank" rel="noreferrer">打开视频 ↗</a> : <span>未保存可用的视频链接</span>}</div>}
        <dl><div><dt>互动内容</dt><dd>{item.op==='like'?'点赞此视频':item.op==='share'?`分享视频卡片${detail.recipient?'给 '+detail.recipient:'给主人'}`:contentLabel||'互动'}</dd></div>
          {contentLabel&&<div><dt>{contentLabel}</dt><dd className="browser-interaction-text">{detail.text||detail.sticker||'历史记录未保存正文'}{detail.mention_owner&&<span className="browser-interaction-mention"> · @主人</span>}</dd></div>}
          {detail.recipient&&item.op!=='share'&&<div><dt>接收人</dt><dd>{detail.recipient}</dd></div>}
        </dl>
        <footer>{receipt.reason&&<span>{receipt.reason}</span>}{item.status==='unknown'&&['like','comment','reply_comment','share'].includes(item.op)&&<Button size="sm" variant="outline" disabled={busy||!!current} onClick={()=>verify(item.id)}>核对结果</Button>}</footer>
      </article>
    })}</div>
      {!operations.length&&<div className="empty">暂无互动记录</div>}
    </section>
    <Dialog.Root open={settings} onOpenChange={value=>{setSettings(value);if(!value)setConfig(savedConfig)}}><Dialog.Portal><Dialog.Overlay className="sheet-overlay"/><Dialog.Content className="browser-settings-drawer">
      <div className="browser-dialog-heading"><Dialog.Title>浏览设置</Dialog.Title><Dialog.Close asChild><Button size="icon-sm" variant="ghost" aria-label="关闭设置"><X size={17}/></Button></Dialog.Close></div><Dialog.Description className="sr-only">当前机器人的浏览偏好、自动浏览和互动权限</Dialog.Description>
      <div className="browser-settings-layout"><nav aria-label="设置分类">{Object.entries(categories).map(([key,label])=><button key={key} aria-current={category===key?'page':undefined} onClick={()=>setCategory(key)}>{label}</button>)}</nav><div className="browser-settings-content">{error&&<Notice alert>{error}</Notice>}{current&&<Notice>任务运行期间不可修改设置，请先停止任务。</Notice>}{config?<>
      <section hidden={category!=='general'}><div className="action-row"><label><input type="checkbox" checked={config.enabled} disabled={!!current||busy} onChange={e=>update('enabled',e.target.checked)}/> 开启自主浏览</label><label><input type="checkbox" checked={config.qq_enabled} disabled={!!current||busy} onChange={e=>update('qq_enabled',e.target.checked)}/> 允许 Owner 私聊发起</label></div>
      <div className="form-grid">
        <Field label="QQ Owner ID" id="browser-owner"><Input id="browser-owner" value={config.qq_owner_id} maxLength={128} disabled={!!current||busy} onChange={e=>update('qq_owner_id',e.target.value)}/></Field>
        <Field label="识别自然语言请求" id="browser-natural"><input id="browser-natural" type="checkbox" checked={config.natural_requests} disabled={!!current||busy} onChange={e=>update('natural_requests',e.target.checked)}/></Field>
        <Field label="角色兴趣" id="browser-character"><Textarea id="browser-character" value={config.character_interests} maxLength={2000} disabled={!!current||busy} onChange={e=>update('character_interests',e.target.value)}/></Field>
        <Field label="主人喜好" id="browser-owner-interests"><Textarea id="browser-owner-interests" value={config.owner_interests} maxLength={2000} disabled={!!current||busy} onChange={e=>update('owner_interests',e.target.value)}/></Field>
        <Field label="内容筛选要求" id="browser-constraints" full><Textarea id="browser-constraints" value={config.content_constraints} maxLength={2000} disabled={!!current||busy} onChange={e=>update('content_constraints',e.target.value)}/></Field>
        {[['timeout_minutes','每次时间上限（分钟）',1,120],['max_steps','步骤上限',5,300],['buffering_wait_seconds','缓冲等待（秒）',30,600]].map(([key,label,min,max])=><Field key={key} label={label} id={`browser-${key}`}><Input id={`browser-${key}`} type="number" min={min} max={max} value={config[key]} disabled={!!current||busy} onChange={e=>update(key,Number(e.target.value))}/></Field>)}
      </div>
      </section><section hidden={category!=='viewing'}><fieldset className="browser-viewing-settings" disabled={!!current||busy}>
        <legend>观看策略</legend>
        <label><input type="checkbox" checked={viewing.preview_enabled} onChange={e=>updateViewing('preview_enabled',e.target.checked)}/> 长视频分段跳看</label>
        <div className="form-grid">{viewingFields.map(([key,label,min,max])=><Field key={key} label={label} id={`browser-viewing-${key}`}><Input id={`browser-viewing-${key}`} type="number" min={min} max={max} step={1} value={viewing[key]} disabled={!viewing.preview_enabled&&key!=='max_video_minutes'} onChange={e=>updateViewing(key,e.target.value===''?'':Number(e.target.value))}/></Field>)}</div>
      </fieldset>
      </section><section hidden={category!=='schedule'}><fieldset className="browser-viewing-settings" disabled={!!current||busy}>
        <legend>空闲时段自动刷</legend>
        <div className="form-grid"><label><input type="checkbox" checked={autoBrowse.enabled} onChange={e=>updateAuto('enabled',e.target.checked)}/> 开启自动刷视频</label>
        <Field label="每日视频总数" id="douyin-auto-limit"><Input id="douyin-auto-limit" type="number" min={1} max={1000} value={autoBrowse.daily_video_limit} onChange={e=>updateAuto('daily_video_limit',e.target.value===''?'':Number(e.target.value))}/></Field></div>
        <p className="browser-task-capability">北京时间周一至周五 9:00–12:00、14:00–18:00 为高峰；周末与中国法定节假日全天空闲。进入高峰后完成当前操作即暂停。当天实际看过的不同视频各计一次，手动浏览也计入，重复观看不重复计数。</p>
      </fieldset>
      </section><section hidden={category!=='interaction'}><DouyinInteractionSettings value={interactions} onChange={v=>update('interactions',v)} disabled={!!current||busy}/>
      </section>{!bound&&config.qq_enabled&&<Notice>保存后，QQ 授权会绑定当前接入账号。</Notice>}

      <section hidden={category!=='browser'}><h3>Google Chrome</h3><p>无头运行，默认静音；每个 Bot 独立保留登录资料。实时画面与接管始终可用。</p><p>画面按浏览器视口原始尺寸采集，JPEG 质量 90%。</p><Button variant="outline" size="sm" onClick={()=>{setSettings(false);setConfig(savedConfig);onCheck()}}>重新检测环境</Button></section>
      </>:<div role="status">正在读取设置…</div>}</div></div><div className="browser-dialog-footer"><span>仅作用于当前 Bot</span><Dialog.Close asChild><Button size="sm" variant="outline">取消</Button></Dialog.Close><Button size="sm" disabled={!config||!!current||busy} onClick={save}>保存设置</Button></div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={newTask} onOpenChange={setNewTask}><Dialog.Portal><Dialog.Overlay className="sheet-overlay"/><Dialog.Content className="browser-task-dialog"><div className="browser-dialog-heading"><Dialog.Title>新建浏览任务</Dialog.Title><Dialog.Close asChild><Button size="icon-sm" variant="ghost" aria-label="关闭新建任务"><X size={16}/></Button></Dialog.Close></div><Dialog.Description>抖音 · 按当前角色的兴趣与权限执行</Dialog.Description>{error&&<Notice alert>{error}</Notice>}{!config?.enabled&&<Notice>请先在浏览设置中开启自主浏览。</Notice>}{current&&<Notice>已有任务运行中，请先等待完成或停止当前任务。</Notice>}
    <form className="browser-new-task-form" onSubmit={start}><Textarea rows={5} aria-label="抖音浏览任务" placeholder="去抖音看看你感兴趣的内容" value={goal} maxLength={3000} disabled={busy||!!current||!config?.enabled} onChange={e=>setGoal(e.target.value)}/><Button type="submit" disabled={busy||!!current||!config?.enabled||!goal.trim()}>开始浏览</Button></form>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={!!detailId} onOpenChange={value=>{if(!value)setDetailId(null)}}><Dialog.Portal><Dialog.Overlay className="sheet-overlay"/><Dialog.Content className="browser-detail-drawer"><div className="browser-dialog-heading"><Dialog.Title>任务详情</Dialog.Title><Dialog.Close asChild><Button size="icon-sm" variant="ghost" aria-label="关闭任务详情"><X size={16}/></Button></Dialog.Close></div><Dialog.Description className="sr-only">执行进度和平台回执</Dialog.Description><div className="browser-detail-body">{detail&&(()=>{const task=detail;return <><h3>{task.goal}</h3><p>{labels[task.state]||task.state} · {new Date(task.created*1000).toLocaleString()}</p>
{task.result&&<p>{task.result}</p>}{(task.origin.source==='qq'||task.notification)&&<p>QQ 回报：{({sent:'已收到发送回执',unknown:'发送结果未确认，请在后台查看',skipped:'授权或连接已变化，未发送',sending:'正在发送'})[task.notification]||'尚未发送'}</p>}<TaskProgress task={task}/>{active(task)&&<Button size="sm" variant="outline" disabled={busy} onClick={()=>stop(task.id)}>停止任务</Button>}</>})()}</div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>
}
