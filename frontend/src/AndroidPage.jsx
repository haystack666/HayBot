import { usePageTabs, Section } from './components/PageTabs'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { Dialog } from 'radix-ui'
import { ArrowLeft, Home, Layers, LoaderCircle, Pencil, Play, RefreshCw, Smartphone, Square, Trash2, Hand, Send } from 'lucide-react'
import { Panel, Field, Notice } from './components/console'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import AndroidLive from './AndroidLive'
import AndroidViewer from './AndroidViewer'
import AndroidCompanion from './AndroidCompanion'
import AndroidApps from './AndroidApps'
import { androidConfigPayload } from './lib/android'
import { livePoint } from './lib/android-live'

const states = { stopped: '已停止', starting: '正在启动', booting: '安卓开机中', running: '运行中', error: '设备异常', queued: '排队中', completed: '已完成', failed: '失败', cancelled: '已停止', unknown: '结果未知', blocked: '需要接管', budget_exhausted: '已保存进度', paused: '已暂停 · 可继续' }
const time = value => new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })

export default function AndroidPage({ api, notify, providers, botId }) {
  const [snapshot, setSnapshot] = useState(null), [config, setConfig] = useState(null), [saved, setSaved] = useState(null)
  const [device, setDevice] = useState(null), [screen, setScreen] = useState(null), [error, setError] = useState(''), [working, setWorking] = useState('')
  const [diagnostics, setDiagnostics] = useState({})
  const [goal, setGoal] = useState(''), [text, setText] = useState(''), [name, setName] = useState('Android'), [confirm, setConfirm] = useState(null), [autoPreview, setAutoPreview] = useState(false)
  const tabs = usePageTabs([['workspace','手机与任务'],['tasks','任务记录'],['apps','初始化与应用'],['settings','任务设置']])
  const records = usePageTabs([['records','执行记录'],['publications','公开互动']], 'taskView')
  const { hash } = useLocation()
  const [taskSearch,setTaskSearch] = useState(''), [taskFilter,setTaskFilter] = useState('all')
  const [selectedTaskId,setSelectedTaskId] = useState(null)
  const [rename, setRename] = useState(null)
  const stream = useRef(null)
  const [liveMode, setLiveMode] = useState(true)
  const live = useRef(true), refreshing = useRef(false), pointer = useRef(null), busy = useRef(false)
  const refresh = useCallback(async () => {
    const next = await api('/android')
    if (!live.current) return next
    setSnapshot(next)
    const first = next.devices[0]
    if (first) {
      if (!['starting'].includes(first.state)) {
        try { const current = await api(`/android/devices/${first.id}`); if (live.current) setDevice(current) } catch { if (live.current) setDevice(first) }
      } else setDevice(first)
    } else { setDevice(null); setScreen(null) }
    return next
  }, [api])
  useEffect(() => {
    live.current = true
    refresh().then(next => { if (live.current) { setConfig(next.config); setSaved(next.config) } }).catch(e => { if (live.current) setError(e.message) })
    const timer = setInterval(() => { if (!refreshing.current) { refreshing.current = true; refresh().catch(e => { if (live.current) setError(e.message) }).finally(() => { refreshing.current = false }) } }, 5000)
    return () => { live.current = false; clearInterval(timer) }
  }, [refresh])
  const preview = useCallback(async () => {
    if (!device || refreshing.current) return
    refreshing.current = true
    try { const next = await api(`/android/devices/${device.id}/observe`); if (live.current) { setScreen(next); setError('') } }
    finally { refreshing.current = false }
  }, [api, device?.id])
  useEffect(() => {
    if (tabs.value !== 'workspace' || !autoPreview || device?.state !== 'running') return
    const timer = setInterval(() => preview().catch(e => { if (live.current) { setError(e.message); setAutoPreview(false) } }), 3000)
    return () => clearInterval(timer)
  }, [autoPreview, preview, device?.state, tabs.value])
  async function action(key, task, message) {
    if (busy.current) return
    busy.current = true; setWorking(key); setError('')
    try { await task(); await refresh(); if (message) notify(message) }
    catch (e) { if (live.current) { setError(e.message); notify(e.message, true) } }
    finally { busy.current = false; if (live.current) setWorking('') }
  }
  const activeTask = snapshot?.tasks.find(task => ['queued', 'running'].includes(task.state))
  const modelProviders = providers.filter(p => p.purpose === 'chat' && p.vision)
  const changed = JSON.stringify(config) !== JSON.stringify(saved)
  async function manual(value) {
    if (!device || working || activeTask) return
    if (stream.current?.controlOwned && stream.current.sendAction(value)) return
    await action('manual', async () => { await api(`/android/devices/${device.id}/manual`, 'POST', value); await new Promise(resolve => setTimeout(resolve, 400)); await preview() })
  }
  function pointerDown(event) { if (!working && !activeTask) { event.currentTarget.setPointerCapture(event.pointerId); pointer.current = { x: event.clientX, y: event.clientY } } }
  function pointerUp(event) {
    const start = pointer.current; pointer.current = null
    if (!start || !device || !screen) return
    const image = event.currentTarget, bounds = image.getBoundingClientRect()
    const width = image.naturalWidth || device.config.width, height = image.naturalHeight || device.config.height
    const first = livePoint(start.x, start.y, bounds, width, height)
    const last = livePoint(event.clientX, event.clientY, bounds, width, height)
    if (!first || !last) return
    if (Math.hypot(event.clientX - start.x, event.clientY - start.y) > 15) manual({ kind: 'swipe', x: first.x, y: first.y, x2: last.x, y2: last.y })
    else manual({ kind: 'tap', x: last.x, y: last.y })
  }
  const configReady = !!config
  useEffect(() => {
    if (!configReady || tabs.value !== 'settings' || !hash) return
    const frame=requestAnimationFrame(() => document.getElementById(hash.slice(1))?.scrollIntoView({block:'center'}))
    return () => cancelAnimationFrame(frame)
  }, [configReady,tabs.value,hash])
  if (!snapshot || !config) return <div className="page-stack">{error ? <Notice alert>{error}</Notice> : <div className="empty"><LoaderCircle className="spin" size={20} />加载安卓设备…</div>}</div>
  const selectedTask = snapshot.tasks.find(task => task.id === selectedTaskId)
  const visibleTasks = snapshot.tasks.filter(task => (taskFilter === 'all' || task.state === taskFilter) && (!taskSearch.trim() || `${task.goal} ${task.result || ''}`.toLowerCase().includes(taskSearch.trim().toLowerCase())))
  const taskReason = activeTask ? '已有任务正在执行，可先停止或等待完成。' : !config.enabled ? '请在任务设置中允许执行安卓任务并保存。' : device?.owner_login ? '正在 Owner 登录模式，请完成登录后恢复 Bot。' : changed ? '任务设置有未保存的修改，请先保存。' : device?.state !== 'running' ? '请先启动手机。' : ''
  function taskRows(items) { return <div className="phone-task-list">{items.map(task => <button key={task.id} className="phone-task-row" onClick={() => setSelectedTaskId(task.id)}><span className="phone-task-copy"><b>{task.goal}</b><small>{time(task.created)} · {task.steps.length} 步{task.origin?.notify_owner ? ` · QQ：${({ready:'待发送',sending:'发送中',sent:'已确认发送',unknown:'结果未知',skipped:'未发送'})[task.notification] || '未发送'}` : ''}</small></span><Badge variant="outline" data-state={task.state}>{states[task.state] || task.state}</Badge><span aria-hidden="true">›</span></button>)}</div> }
  return <div className="page-stack android-page">
    {tabs.tabs}
    {error && <Notice alert>{error}</Notice>}
    <div className="android-runtime-bar"><div><Smartphone size={16}/><b>{device?.name || '安卓设备'}</b>{device && <Button variant="ghost" size="sm" disabled={!!working} onClick={() => setRename({ id: device.id, name: device.name })}><Pencil size={13}/>修改名称</Button>}<Badge variant="outline" data-state={snapshot.runtime.ready ? 'completed' : 'blocked'}>{snapshot.runtime.ready ? '运行时就绪' : snapshot.configured ? '运行时未就绪' : '运行时未配置'}</Badge></div><Button variant="outline" size="sm" disabled={!!working} onClick={() => action('refresh',refresh)}><RefreshCw size={14}/>刷新</Button></div>
    <Section show={tabs.value === 'workspace'}><div className="phone-workspace">
      <Panel title={device?.name || '创建安卓设备'} subtitle={device ? `${device.config.width} × ${device.config.height} · 当前 Bot 独占` : '每个 Bot 一台独立手机，应用和账号单独保存。'} action={device && <Badge variant="outline">{states[device.state] || device.state}</Badge>}>
        {!device ? <form className="page-stack" onSubmit={e => { e.preventDefault(); action('create', async () => { await api('/android/devices', 'POST', { name, google_play: true }); setScreen(null) }, '设备已创建，点击启动开机') }}><Field id="android-name" label="设备名称"><Input id="android-name" value={name} required maxLength={60} onChange={e => setName(e.target.value)} /></Field>{!snapshot.runtime.google_play_ready && <Notice>请先在宿主构建 Google 套件兼容镜像，再创建手机。</Notice>}<Button disabled={!!working || !snapshot.runtime.ready || !snapshot.runtime.google_play_ready}><Smartphone size={14} />创建设备</Button></form> : <div className="page-stack">
          <div className="android-device-actions"><Button size="sm" disabled={!!working || !['stopped', 'error'].includes(device.state)} onClick={() => action('start', () => api(`/android/devices/${device.id}/control/start`, 'POST'), '设备正在启动')}><Play size={13} />启动</Button><Button size="sm" variant="outline" disabled={!!working || !['running', 'booting', 'error'].includes(device.state)} onClick={() => action('stop', async () => { await api(`/android/devices/${device.id}/control/stop`, 'POST'); setScreen(null); setAutoPreview(false) }, '设备已停止')}><Square size={13} />停止</Button><Button size="sm" variant="outline" disabled={!!working || device.state !== 'running'} onClick={() => action('takeover', () => api(`/android/devices/${device.id}/control/takeover`, 'POST'), '已停止任务，可手动操作设备')}><Hand size={13} />人工接管</Button></div>
          <Notice>{device.owner_login ? 'owner 登录模式：Bot 已暂停操作和取图。请自行完成账号登录、验证码，再点击「完成登录」。' : '应用登录必须由 owner 自行完成。登录前请先进入 owner 登录模式。'}</Notice>
          <Button variant="outline" disabled={!!working || device.state !== 'running'} onClick={() => action('login', async () => { await api(`/android/devices/${device.id}/login/${device.owner_login ? 'finish' : 'begin'}`, 'POST'); if (device.owner_login) stream.current?.reconnect() }, device.owner_login ? '已退出登录模式，可重新提交任务' : 'Bot 已暂停，请自行登录应用')}>{device.owner_login ? '完成登录，恢复 Bot' : 'owner 登录模式'}</Button>
          <AndroidViewer name={device.name}>{tabs.value === 'workspace' && liveMode && device.state === 'running' ? <AndroidLive ref={stream} botId={botId} device={device} disabled={!!working} onTakeover={async () => { await api(`/android/devices/${device.id}/control/takeover`, 'POST'); await refresh() }} onFallback={() => setLiveMode(false)} /> : <>
          <div className={`android-screen ${working || activeTask ? 'android-screen-busy' : ''}`} style={{ aspectRatio: `${device.config.width}/${device.config.height}` }}>
            {screen ? <img draggable={false} src={`data:image/png;base64,${screen.image}`} alt="安卓设备当前画面；点击或拖动进行操作" onPointerDown={pointerDown} onPointerUp={pointerUp} onPointerCancel={() => { pointer.current = null }} /> : <div className="android-screen-empty"><Smartphone size={36} /><span>{device.state === 'running' ? '点击「获取画面」查看手机' : '启动安卓后查看画面'}</span></div>}
          </div>
          <div className="android-preview-actions"><Button variant="outline" size="sm" disabled={!!working || device.state !== 'running'} onClick={() => action('preview', preview)}><RefreshCw size={13} />获取画面</Button><label className="android-auto-preview"><Switch checked={autoPreview} disabled={device.state !== 'running'} onCheckedChange={setAutoPreview} aria-label="自动更新画面" /><span>自动更新</span></label></div>
          {screen && <p className="push-hint">画面时间：{time(screen.at)}。点击屏幕进行轻触，拖动进行滑动。</p>}
          </>}
          {!liveMode && <Button size="sm" variant="outline" disabled={device.state !== 'running'} onClick={() => { setAutoPreview(false); setLiveMode(true) }}>切换实时视频</Button>}
          <div className="android-keybar">{[['back', ArrowLeft, '返回'], ['home', Home, '主页'], ['recent', Layers, '最近应用']].map(([key, Icon, title]) => <Button key={key} variant="outline" size="sm" disabled={!!working || !!activeTask || device.state !== 'running'} onClick={() => manual({ kind: 'key', key })}><Icon size={15} />{title}</Button>)}</div>
          <form className="android-input-row" onSubmit={e => { e.preventDefault(); const value = text; manual({ kind: 'text', text: value }).then(() => setText('')) }}><Input aria-label="向设备输入文字" placeholder="先点中输入框，再输入中文或文字" value={text} maxLength={2000} onChange={e => setText(e.target.value)} /><Button size="icon" aria-label="输入文字" disabled={!text || !!working || !!activeTask || device.state !== 'running'}><Send size={15} /></Button></form>
          {device.error && <Notice alert>{device.error}</Notice>}
          </AndroidViewer>
        </div>}
      </Panel>
<div className="page-stack phone-task-column"><Panel title="给手机一个任务">
        <form className="page-stack" onSubmit={e => { e.preventDefault(); action('task', () => api('/android/tasks', 'POST', { device_id: device.id, goal }), '任务已开始，可在下方查看步骤') }}><Textarea aria-label="安卓任务目标" placeholder="例如：打开设置，查看 Android 版本，然后回到桌面。" rows={4} value={goal} maxLength={3000} onChange={e => setGoal(e.target.value)} /><div className="action-row justify-end">{activeTask && <Button type="button" variant="outline" disabled={!!working} onClick={() => action('cancel', () => api(`/android/tasks/${activeTask.id}/cancel`, 'POST'), '任务已停止')}>停止任务</Button>}<Button disabled={!!working || !!activeTask || !config.enabled || device?.owner_login || changed || !goal.trim() || device?.state !== 'running'}><Play size={14} />开始任务</Button></div></form>
        {activeTask && <p className="push-hint">任务进行中。手动操作前请点击「人工接管」。</p>}
        {taskReason && <p className="push-hint">{taskReason} <button className="subtle-link" onClick={() => tabs.select('settings')}>任务设置 →</button></p>}
      </Panel>
      {activeTask && <Panel title="当前任务" action={<Badge variant="outline">{states[activeTask.state]}</Badge>}><p className="phone-current-goal">{activeTask.goal}</p>{activeTask.progress?.checkpoint?.summary && <p className="push-hint">{activeTask.progress.checkpoint.summary}</p>}<Button size="sm" variant="outline" onClick={() => setSelectedTaskId(activeTask.id)}>查看执行详情</Button></Panel>}
      <Panel title="最近任务" action={<Button variant="ghost" size="sm" onClick={() => tabs.select('tasks')}>全部记录 →</Button>}>{snapshot.tasks.length ? taskRows(snapshot.tasks.slice(0,5)) : <div className="empty">还没有任务，提交一个目标开始。</div>}</Panel>
    </div></div></Section>
    <Section show={tabs.value === 'tasks'}>{records.tabs}<Section show={records.value === 'records'}><Panel title="任务记录" subtitle="执行结果与 QQ 回传分别展示。选择任务查看完整步骤和诊断。"><div className="phone-task-filters"><Input aria-label="搜索当前任务记录" placeholder="搜索任务目标或结果…" value={taskSearch} onChange={e=>setTaskSearch(e.target.value)}/><select className="provider-select" aria-label="任务状态筛选" value={taskFilter} onChange={e=>setTaskFilter(e.target.value)}><option value="all">全部状态</option>{[...new Set(snapshot.tasks.map(task=>task.state))].map(state=><option key={state} value={state}>{states[state] || state}</option>)}</select><small>{visibleTasks.length} 条记录</small></div>{visibleTasks.length ? taskRows(visibleTasks) : <div className="empty">{snapshot.tasks.length ? '没有匹配的任务记录。' : '暂无任务记录。'}</div>}</Panel></Section><Section show={records.value === 'publications'}>
    <Panel title="公开互动记录" subtitle="记录评论正文、平台、发送核对结果；结果未知时不会自动重发。"><div className="page-stack">{(snapshot.publications || []).map(item => <article className="android-task" key={item.id}><div className="action-row justify-between"><b>{item.platform}{item.mention ? ' · @ owner' : ''}</b><Badge variant="outline" data-state={item.state}>{{ draft: '草稿', mention_selected: '已选中 owner', sending: '发送中', verified: '已核对', unknown: '待人工核对', cancelled: '已取消' }[item.state] || item.state}</Badge></div><p>{item.text}</p><p className="push-hint">{item.detail} · {time(item.created)}</p></article>)}</div>{!snapshot.publications?.length && <div className="empty">还没有公开互动记录。</div>}</Panel>
    </Section></Section>
    <Section show={tabs.value === 'apps'}>{device ? <AndroidApps api={api} runtime={snapshot.runtime} device={device} activeTask={activeTask} action={action} working={working}/> : <Panel title="初始化与应用"><div className="empty">请先在手机与任务中创建设备。</div></Panel>}</Section>
    <Section show={tabs.value === 'settings'}>
    {!snapshot.configured && <Notice>先在部署电脑运行 <code>python3 scripts/android_runtime.py setup</code>，再运行 <code>start</code>。按安装提示把运行时连接配置加入 HayBot，然后重建 app 服务。</Notice>}
    {snapshot.runtime.detail && <details className="help-details"><summary>运行时连接信息</summary><p className="push-hint">{snapshot.runtime.detail}</p></details>}
    <form className="page-stack" onSubmit={e => { e.preventDefault(); action('config', async () => { const value = await api('/android/config', 'PUT', androidConfigPayload(config)); setConfig(value); setSaved(value) }, '安卓任务配置已保存') }}>
      <Panel className="phone-settings-panel" title="任务权限与模型" subtitle="手机任务单独保存配置，独立选择支持图片的操作模型。">
          <div className="toggle-row !pt-0"><div><b>允许执行安卓任务</b><p>由你在下方提交目标后开始操作。</p></div><Switch checked={config.enabled} disabled={!!working || !!activeTask} onCheckedChange={value => setConfig(c => ({ ...c, enabled: value }))} aria-label="允许执行安卓任务" /></div>
          <div className="toggle-row"><div><b>允许 QQ 私聊操作手机</b><p>仅下方授权用户可发起任务、查询进度或停止。</p></div><Switch checked={config.qq_enabled} disabled={!!working || !!activeTask} onCheckedChange={value => setConfig(c => ({ ...c, qq_enabled: value }))} aria-label="允许 QQ 私聊操作手机" /></div>
          <Field id="android-qq-owner" label="QQ 授权用户 ID" hint="NapCat 填 QQ 号；官方机器人填私聊用户 ID。每个 Bot 单独配置。"><Input id="android-qq-owner" value={config.qq_owner_id} disabled={!!activeTask} required={config.qq_enabled} maxLength={128} onChange={e => setConfig(c => ({ ...c, qq_owner_id: e.target.value }))} placeholder="填写允许操作这台手机的用户" /></Field>
          <div className="toggle-row"><div><b>识别自然语言手机请求</b><p>使用当前 Bot 的对话模型识别明确委托；群聊和其他用户不能操作。</p></div><Switch checked={config.natural_requests} disabled={!!working || !!activeTask} onCheckedChange={value => setConfig(c => ({ ...c, natural_requests: value }))} aria-label="识别自然语言手机请求" /></div>
          <p className="push-hint">QQ 指令：/手机 任务内容 · /手机进度 · /停止手机 · /手机截图。任务完成后回复真实结果，截图指令发送图片。</p>
          <Field id="android-provider" label="视觉供应商"><select id="android-provider" className="provider-select" value={config.provider_id} disabled={!!activeTask} onChange={e => setConfig(c => ({ ...c, provider_id: e.target.value }))}><option value="">使用当前 Bot 的对话供应商</option>{modelProviders.map(p => <option value={p.id} key={p.id}>{p.name}</option>)}</select></Field>
          <Field id="android-model" label="操作模型" hint="填写已开通图片输入的模型名称。"><Input id="android-model" value={config.model} disabled={!!activeTask} required={config.enabled} maxLength={200} onChange={e => setConfig(c => ({ ...c, model: e.target.value }))} placeholder="填写视觉模型名称" /></Field>
          <div className="toggle-row"><div><b>按任务复杂程度自动分配预算</b><p className="push-hint">先制定计划，分阶段推进；有新进展时自动延长，停滞时保存成果并暂停。</p></div><Switch aria-label="自适应任务预算" checked={config.adaptive_budget !== false} disabled={!!activeTask} onCheckedChange={value => setConfig(c => ({ ...c, adaptive_budget: value }))} /></div>
          {config.adaptive_budget === false && <div className="form-grid">{[['max_steps', '每阶段最多操作步数', 1, 10000], ['timeout_minutes', '每阶段时限（分钟）', 1, 1440]].map(([key, label, min, max]) => <Field key={key} id={`android-${key}`} label={label}><Input id={`android-${key}`} type="number" required min={min} max={max} value={config[key]} disabled={!!activeTask} onChange={e => setConfig(c => ({ ...c, [key]: e.target.value }))} /></Field>)}</div>}
          <p className="push-hint">到达阶段边界不会清空成果。继续任务会重新观察当前画面，保留步骤和已收集结果，不重放旧动作。</p>
      </Panel><Panel title="浏览兴趣与公开互动" subtitle="兴趣、内容筛选、评论风格及各平台授权集中配置。"><AndroidCompanion value={config.companion} disabled={!!activeTask} onChange={companion => setConfig(c => ({ ...c, companion }))} /></Panel>
          <div className={changed ? "local-savebar" : "action-row justify-end"}>{changed && <span>手机任务设置有未保存的修改</span>}<div className="action-row">{changed && <Button type="button" variant="outline" disabled={!!working} onClick={()=>setConfig(structuredClone(saved))}>撤销更改</Button>}<Button disabled={!!working || !!activeTask || !changed}>保存任务配置</Button></div></div>
        </form>
    {device && <Panel title="设备维护" subtitle="停止手机后可操作。移除容器保留数据，销毁设备会永久删除应用与账号。">          <div className="android-delete-row"><Button variant="destructive-outline" size="sm" disabled={!!working || device.state !== 'stopped'} onClick={() => setConfirm('container')}><Trash2 size={13} />移除容器</Button><Button variant="destructive-outline" size="sm" disabled={!!working || device.state !== 'stopped'} onClick={() => setConfirm('destroy')}>销毁设备数据</Button></div></Panel>}
    </Section>
    <Dialog.Root open={!!selectedTask} onOpenChange={v => { if(!v)setSelectedTaskId(null) }}><Dialog.Portal><Dialog.Overlay className="sheet-overlay"/><Dialog.Content className="phone-task-dialog"><div className="phone-detail-heading"><div><Dialog.Title>任务详情</Dialog.Title><Dialog.Description>当前 Bot 的任务目标、执行结果、回传状态与完整步骤</Dialog.Description></div><Dialog.Close asChild><Button variant="outline" size="sm">关闭</Button></Dialog.Close></div>{selectedTask && (() => { const task=selectedTask; return (<article className="android-task" key={task.id}><div className="android-task-heading"><Badge variant="outline" data-state={task.state}>{states[task.state] || task.state}</Badge><time>{time(task.created)}</time></div><h3>{task.goal}</h3>{task.origin?.notify_owner && <p className="push-hint">QQ 结果发送：{{ ready: '待发送', sending: '发送中', sent: 'QQ 已确认发送', unknown: '发送结果未知，请先核对 QQ，不自动重发', skipped: '未发送' }[task.notification] || '未发送'}</p>}{task.result && <p>{task.result}</p>}{task.progress?.plan && <p className="push-hint">计划：{(task.progress.plan.milestones || []).join(' → ')}</p>}{task.progress?.checkpoint?.summary && <p>{task.progress.checkpoint.summary}</p>}{task.progress?.stage && <p className="push-hint">第 {task.progress.stage.index} 阶段 · {task.progress.stage.used_steps} / {task.progress.stage.step_limit} 次决策 · 已用 {Math.round(task.progress.stage.elapsed_seconds / 60)} 分钟</p>}{!!task.progress?.links?.length && <div><b>已观察并保存的链接</b><ul>{task.progress.links.map(item => <li key={item.url}><a href={item.url} target="_blank" rel="noreferrer">{item.url}</a></li>)}</ul></div>}{!!task.progress?.legacy_candidates?.length && <details><summary>旧任务中提到的候选链接 · 尚需重新核对</summary><ul>{task.progress.legacy_candidates.map(item => <li key={item.url}><a href={item.url} target="_blank" rel="noreferrer">{item.url}</a></li>)}</ul></details>}{['paused','budget_exhausted','failed','cancelled','unknown','blocked'].includes(task.state) && <Button size="sm" variant="outline" disabled={!!working || !!activeTask || device?.owner_login || device?.state !== 'running'} onClick={() => action('resume', () => api(`/android/tasks/${task.id}/resume`, 'POST'), '从当前状态继续，已有进度保留')}>继续此任务</Button>}<details><summary>查看步骤 · {task.steps.length} 步</summary><ol>{task.steps.map(step => <li key={step.index}><b>{step.index}. {step.kind === 'verified' ? '核对完成' : step.kind}</b><p>{step.reason}</p>{step.action && <code>{JSON.stringify(step.action)}</code>}</li>)}</ol></details><div className="android-diagnostic-actions"><Button size="sm" variant="ghost" disabled={!!working} onClick={() => action('diagnostics', async () => { const value = await api(`/android/tasks/${task.id}/diagnostics`); setDiagnostics(d => ({ ...d, [task.id]: value.attempts })) })}>查看模型返回 · {task.diagnostic_count || 0}</Button></div>{diagnostics[task.id] && <div className="android-diagnostics">{!diagnostics[task.id].length ? <p className="push-hint">此任务没有保存模型返回。旧版任务仅保留错误和步骤，原始正文无法还原。</p> : diagnostics[task.id].map(attempt => <details key={attempt.id}><summary>第 {attempt.step} 步 · 第 {attempt.attempt} 次 · {attempt.error ? '格式不合格' : '格式有效'}</summary><p>{attempt.error}</p><p className="push-hint">模型：{attempt.metadata.model} · 结束原因：{attempt.metadata.finish_reason || attempt.metadata.status || '未提供'} · 正文 {attempt.metadata.content_chars} 字符</p><pre>{attempt.content || '（模型正文为空）'}</pre></details>)}</div>}</article>) })()}</Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={!!rename} onOpenChange={value => { if (!value && !working) setRename(null) }}><Dialog.Portal><Dialog.Overlay className="sheet-overlay"/><Dialog.Content className="provider-dialog"><Dialog.Title>修改手机名称</Dialog.Title><Dialog.Description>名称用于后台识别这台手机，支持 1–60 个字符，保存后立即生效。</Dialog.Description><form className="page-stack" onSubmit={e => { e.preventDefault(); if (!rename?.name.trim()) return; action('rename', async () => { await api(`/android/devices/${rename.id}`, 'PATCH', { name: rename.name.trim() }); setRename(null) }, '手机名称已更新') }}><Field id="android-rename" label="手机名称"><Input id="android-rename" autoFocus required maxLength={60} disabled={!!working} value={rename?.name || ''} onChange={e => setRename(value => ({ ...value, name: e.target.value }))}/></Field><div className="dialog-actions"><Button type="button" variant="outline" disabled={!!working} onClick={() => setRename(null)}>取消</Button><Button disabled={!!working || !rename?.name.trim() || rename.name.trim() === device?.name}>{working === 'rename' ? '保存中…' : '保存名称'}</Button></div></form></Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={!!confirm} onOpenChange={value => { if (!value && !working) setConfirm(null) }}><Dialog.Portal><Dialog.Overlay className="sheet-overlay" /><Dialog.Content className="provider-dialog"><Dialog.Title>{confirm === 'destroy' ? '永久销毁这台手机？' : '移除安卓容器？'}</Dialog.Title><Dialog.Description>{confirm === 'destroy' ? '应用、登录账号及全部手机数据将永久删除，无法恢复。此操作只影响当前 Bot 的安卓设备。' : '会移除已停止的容器，手机数据保留。再次点击「启动」即可重建并继续使用。'}</Dialog.Description><div className="dialog-actions"><Button variant="outline" disabled={!!working} onClick={() => setConfirm(null)}>返回</Button><Button variant={confirm === 'destroy' ? 'destructive' : 'outline'} disabled={!!working} onClick={() => action('delete', async () => { await api(`/android/devices/${device.id}${confirm === 'destroy' ? `?destroy_data=true&confirm=${device.id}` : ''}`, 'DELETE'); setScreen(null); setConfirm(null) }, confirm === 'destroy' ? '设备数据已销毁' : '容器已移除，手机数据已保留')}>{confirm === 'destroy' ? '确认永久销毁' : '移除并保留数据'}</Button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>
}
