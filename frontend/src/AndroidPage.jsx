import { useCallback, useEffect, useRef, useState } from 'react'
import { Dialog } from 'radix-ui'
import { ArrowLeft, Home, Layers, LoaderCircle, Play, RefreshCw, Smartphone, Square, Trash2, Hand, Send } from 'lucide-react'
import { Panel, Field, Notice } from './components/console'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import AndroidCompanion from './AndroidCompanion'
import AndroidApps from './AndroidApps'
import { pointOnScreen, androidConfigPayload } from './lib/android'

const states = { stopped: '已停止', starting: '正在启动', booting: '安卓开机中', running: '运行中', error: '设备异常', queued: '排队中', completed: '已完成', failed: '失败', cancelled: '已停止', unknown: '结果未知', blocked: '需要接管', budget_exhausted: '达到步骤上限' }
const time = value => new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })

export default function AndroidPage({ api, notify, providers }) {
  const [snapshot, setSnapshot] = useState(null), [config, setConfig] = useState(null), [saved, setSaved] = useState(null)
  const [device, setDevice] = useState(null), [screen, setScreen] = useState(null), [error, setError] = useState(''), [working, setWorking] = useState('')
  const [diagnostics, setDiagnostics] = useState({})
  const [goal, setGoal] = useState(''), [text, setText] = useState(''), [name, setName] = useState('Android'), [confirm, setConfirm] = useState(null), [autoPreview, setAutoPreview] = useState(false)
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
    if (!autoPreview || device?.state !== 'running') return
    const timer = setInterval(() => preview().catch(e => { if (live.current) { setError(e.message); setAutoPreview(false) } }), 3000)
    return () => clearInterval(timer)
  }, [autoPreview, preview, device?.state])
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
    await action('manual', async () => { await api(`/android/devices/${device.id}/manual`, 'POST', value); await new Promise(resolve => setTimeout(resolve, 400)); await preview() })
  }
  function pointerDown(event) { if (!working && !activeTask) { event.currentTarget.setPointerCapture(event.pointerId); pointer.current = { x: event.clientX, y: event.clientY } } }
  function pointerUp(event) {
    const start = pointer.current; pointer.current = null
    if (!start || !device || !screen) return
    const bounds = event.currentTarget.getBoundingClientRect(), size = device.config
    const first = pointOnScreen(start.x, start.y, bounds, size.width, size.height)
    const last = pointOnScreen(event.clientX, event.clientY, bounds, size.width, size.height)
    if (Math.hypot(event.clientX - start.x, event.clientY - start.y) > 15) manual({ kind: 'swipe', x: first.x, y: first.y, x2: last.x, y2: last.y })
    else manual({ kind: 'tap', ...last })
  }
  if (!snapshot || !config) return <div className="page-stack">{error ? <Notice alert>{error}</Notice> : <div className="empty"><LoaderCircle className="spin" size={20} />加载安卓设备…</div>}</div>
  return <div className="page-stack android-page">
    {error && <Notice alert>{error}</Notice>}
    {!snapshot.configured && <Notice>先在部署电脑运行 <code>python3 scripts/android_runtime.py setup</code>，再运行 <code>start</code>。按安装提示把运行时连接配置加入 HayBot，然后重建 app 服务。</Notice>}
    <div className="android-runtime-bar"><div><Smartphone size={18} /><b>安卓运行时</b><Badge variant="outline">{snapshot.runtime.ready ? '已就绪' : snapshot.configured ? '未就绪' : '未配置'}</Badge></div><Button variant="outline" size="sm" disabled={!!working} onClick={() => action('refresh', refresh)}><RefreshCw size={14} />刷新</Button></div>
    {snapshot.runtime.detail && snapshot.configured && <p className="push-hint">{snapshot.runtime.detail}</p>}
    <div className="android-layout">
      <Panel title={device?.name || '创建安卓设备'} subtitle={device ? `${device.config.width} × ${device.config.height} · 当前 Bot 独占` : '每个 Bot 一台独立手机，应用和账号单独保存。'} action={device && <Badge variant="outline">{states[device.state] || device.state}</Badge>}>
        {!device ? <form className="page-stack" onSubmit={e => { e.preventDefault(); action('create', async () => { await api('/android/devices', 'POST', { name }); setScreen(null) }, '设备已创建，点击启动开机') }}><Field id="android-name" label="设备名称"><Input id="android-name" value={name} required maxLength={60} onChange={e => setName(e.target.value)} /></Field><Button disabled={!!working || !snapshot.runtime.ready}><Smartphone size={14} />创建设备</Button></form> : <div className="page-stack">
          <div className="android-device-actions"><Button size="sm" disabled={!!working || !['stopped', 'error'].includes(device.state)} onClick={() => action('start', () => api(`/android/devices/${device.id}/control/start`, 'POST'), '设备正在启动')}><Play size={13} />启动</Button><Button size="sm" variant="outline" disabled={!!working || !['running', 'booting', 'error'].includes(device.state)} onClick={() => action('stop', async () => { await api(`/android/devices/${device.id}/control/stop`, 'POST'); setScreen(null); setAutoPreview(false) }, '设备已停止')}><Square size={13} />停止</Button><Button size="sm" variant="outline" disabled={!!working || device.state !== 'running'} onClick={() => action('takeover', () => api(`/android/devices/${device.id}/control/takeover`, 'POST'), '已停止任务，可手动操作设备')}><Hand size={13} />人工接管</Button></div>
          <Notice>{device.owner_login ? 'owner 登录模式：Bot 已暂停操作和取图。请自行完成账号登录、验证码，再点击「完成登录」。' : '应用登录必须由 owner 自行完成。登录前请先进入 owner 登录模式。'}</Notice>
          <Button variant="outline" disabled={!!working || device.state !== 'running'} onClick={() => action('login', () => api(`/android/devices/${device.id}/login/${device.owner_login ? 'finish' : 'begin'}`, 'POST'), device.owner_login ? '已退出登录模式，可重新提交任务' : 'Bot 已暂停，请自行登录应用')}>{device.owner_login ? '完成登录，恢复 Bot' : 'owner 登录模式'}</Button>
          <div className={`android-screen ${working || activeTask ? 'android-screen-busy' : ''}`} style={{ aspectRatio: `${device.config.width}/${device.config.height}` }}>
            {screen ? <img draggable={false} src={`data:image/png;base64,${screen.image}`} alt="安卓设备当前画面；点击或拖动进行操作" onPointerDown={pointerDown} onPointerUp={pointerUp} onPointerCancel={() => { pointer.current = null }} /> : <div className="android-screen-empty"><Smartphone size={36} /><span>{device.state === 'running' ? '点击「获取画面」查看手机' : '启动安卓后查看画面'}</span></div>}
          </div>
          <div className="android-preview-actions"><Button variant="outline" size="sm" disabled={!!working || device.state !== 'running'} onClick={() => action('preview', preview)}><RefreshCw size={13} />获取画面</Button><label className="android-auto-preview"><Switch checked={autoPreview} disabled={device.state !== 'running'} onCheckedChange={setAutoPreview} aria-label="自动更新画面" /><span>自动更新</span></label></div>
          {screen && <p className="push-hint">画面时间：{time(screen.at)}。点击屏幕进行轻触，拖动进行滑动。</p>}
          <div className="android-keybar">{[['back', ArrowLeft, '返回'], ['home', Home, '主页'], ['recent', Layers, '最近应用']].map(([key, Icon, title]) => <Button key={key} variant="outline" size="sm" disabled={!!working || !!activeTask || device.state !== 'running'} onClick={() => manual({ kind: 'key', key })}><Icon size={15} />{title}</Button>)}</div>
          <form className="android-input-row" onSubmit={e => { e.preventDefault(); const value = text; manual({ kind: 'text', text: value }).then(() => setText('')) }}><Input aria-label="向设备输入文字" placeholder="先点中输入框，再输入中文或文字" value={text} maxLength={2000} onChange={e => setText(e.target.value)} /><Button size="icon" aria-label="输入文字" disabled={!text || !!working || !!activeTask || device.state !== 'running'}><Send size={15} /></Button></form>
          {device.error && <Notice alert>{device.error}</Notice>}
          <div className="android-delete-row"><Button variant="ghost" size="sm" disabled={!!working || device.state !== 'stopped'} onClick={() => setConfirm('container')}><Trash2 size={13} />移除容器</Button><Button variant="ghost" size="sm" disabled={!!working || device.state !== 'stopped'} onClick={() => setConfirm('destroy')}>销毁设备数据</Button></div>
        </div>}
      </Panel>
      <div className="page-stack android-controls"><Panel title="操作模型" subtitle="独立选择支持图片的模型，普通聊天配置不受影响。">
        <form className="page-stack" onSubmit={e => { e.preventDefault(); action('config', async () => { const value = await api('/android/config', 'PUT', androidConfigPayload(config)); setConfig(value); setSaved(value) }, '安卓任务配置已保存') }}>
          <div className="toggle-row !pt-0"><div><b>允许执行安卓任务</b><p>由你在下方提交目标后开始操作。</p></div><Switch checked={config.enabled} disabled={!!working || !!activeTask} onCheckedChange={value => setConfig(c => ({ ...c, enabled: value }))} aria-label="允许执行安卓任务" /></div>
          <div className="toggle-row"><div><b>允许 QQ 私聊操作手机</b><p>仅下方授权用户可发起任务、查询进度或停止。</p></div><Switch checked={config.qq_enabled} disabled={!!working || !!activeTask} onCheckedChange={value => setConfig(c => ({ ...c, qq_enabled: value }))} aria-label="允许 QQ 私聊操作手机" /></div>
          <Field id="android-qq-owner" label="QQ 授权用户 ID" hint="NapCat 填 QQ 号；官方机器人填私聊用户 ID。每个 Bot 单独配置。"><Input id="android-qq-owner" value={config.qq_owner_id} disabled={!!activeTask} required={config.qq_enabled} maxLength={128} onChange={e => setConfig(c => ({ ...c, qq_owner_id: e.target.value }))} placeholder="填写允许操作这台手机的用户" /></Field>
          <div className="toggle-row"><div><b>识别自然语言手机请求</b><p>使用当前 Bot 的对话模型识别明确委托；群聊和其他用户不能操作。</p></div><Switch checked={config.natural_requests} disabled={!!working || !!activeTask} onCheckedChange={value => setConfig(c => ({ ...c, natural_requests: value }))} aria-label="识别自然语言手机请求" /></div>
          <p className="push-hint">QQ 指令：/手机 任务内容 · /手机进度 · /停止手机 · /手机截图。任务完成后回复真实结果，截图指令发送图片。</p>
          <Field id="android-provider" label="视觉供应商"><select id="android-provider" className="provider-select" value={config.provider_id} disabled={!!activeTask} onChange={e => setConfig(c => ({ ...c, provider_id: e.target.value }))}><option value="">使用当前 Bot 的对话供应商</option>{modelProviders.map(p => <option value={p.id} key={p.id}>{p.name}</option>)}</select></Field>
          <Field id="android-model" label="操作模型" hint="填写已开通图片输入的模型名称。"><Input id="android-model" value={config.model} disabled={!!activeTask} required={config.enabled} maxLength={200} onChange={e => setConfig(c => ({ ...c, model: e.target.value }))} placeholder="填写视觉模型名称" /></Field>
          <div className="form-grid">{[['max_steps', '最多操作步数', 1, 60], ['timeout_minutes', '任务时限（分钟）', 1, 20]].map(([key, label, min, max]) => <Field key={key} id={`android-${key}`} label={label}><Input id={`android-${key}`} type="number" required min={min} max={max} value={config[key]} disabled={!!activeTask} onChange={e => setConfig(c => ({ ...c, [key]: e.target.value }))} /></Field>)}</div>
          <AndroidCompanion value={config.companion} disabled={!!activeTask} onChange={companion => setConfig(c => ({ ...c, companion }))} />
          <div className="action-row justify-end"><Button disabled={!!working || !!activeTask || !changed}>保存任务配置</Button></div>
        </form>
      </Panel><Panel title="给手机一个任务" subtitle="模型逐步观察、操作，再通过画面检查结果。">
        <form className="page-stack" onSubmit={e => { e.preventDefault(); action('task', () => api('/android/tasks', 'POST', { device_id: device.id, goal }), '任务已开始，可在下方查看步骤') }}><Textarea aria-label="安卓任务目标" placeholder="例如：打开设置，查看 Android 版本，然后回到桌面。" rows={4} value={goal} maxLength={3000} onChange={e => setGoal(e.target.value)} /><div className="action-row justify-end">{activeTask && <Button type="button" variant="outline" disabled={!!working} onClick={() => action('cancel', () => api(`/android/tasks/${activeTask.id}/cancel`, 'POST'), '任务已停止')}>停止任务</Button>}<Button disabled={!!working || !!activeTask || !config.enabled || device?.owner_login || changed || !goal.trim() || device?.state !== 'running'}><Play size={14} />开始任务</Button></div></form>
        {activeTask && <p className="push-hint">任务进行中。手动操作前请点击「人工接管」。</p>}
      </Panel></div>
    </div>
    {device && <AndroidApps api={api} device={device} activeTask={activeTask} action={action} working={working} />}
    {!!snapshot.publications?.length && <Panel title="公开互动记录" subtitle="记录评论正文、平台、发送核对结果；结果未知时不会自动重发。"><div className="page-stack">{snapshot.publications.map(item => <article className="android-task" key={item.id}><div className="action-row justify-between"><b>{item.platform}{item.mention ? ' · @ owner' : ''}</b><Badge variant="outline">{{ draft: '草稿', mention_selected: '已选中 owner', sending: '发送中', verified: '已核对', unknown: '待人工核对', cancelled: '已取消' }[item.state] || item.state}</Badge></div><p>{item.text}</p><p className="push-hint">{item.detail} · {time(item.created)}</p></article>)}</div></Panel>}
    <Panel title="任务记录" subtitle="记录目标、每步操作与完成依据；停止任务不会撤销已经执行的动作。">
      {!snapshot.tasks.length ? <div className="empty">暂无任务，先启动手机并提交一个目标。</div> : <div className="android-tasks">{snapshot.tasks.map(task => <article className="android-task" key={task.id}><div className="android-task-heading"><Badge variant="outline">{states[task.state] || task.state}</Badge><time>{time(task.created)}</time></div><h3>{task.goal}</h3>{task.result && <p>{task.result}</p>}<details><summary>查看步骤 · {task.steps.length} 步</summary><ol>{task.steps.map(step => <li key={step.index}><b>{step.index}. {step.kind === 'verified' ? '核对完成' : step.kind}</b><p>{step.reason}</p>{step.action && <code>{JSON.stringify(step.action)}</code>}</li>)}</ol></details><div className="android-diagnostic-actions"><Button size="sm" variant="ghost" disabled={!!working} onClick={() => action('diagnostics', async () => { const value = await api(`/android/tasks/${task.id}/diagnostics`); setDiagnostics(d => ({ ...d, [task.id]: value.attempts })) })}>查看模型返回 · {task.diagnostic_count || 0}</Button></div>{diagnostics[task.id] && <div className="android-diagnostics">{!diagnostics[task.id].length ? <p className="push-hint">此任务没有保存模型返回。旧版任务仅保留错误和步骤，原始正文无法还原。</p> : diagnostics[task.id].map(attempt => <details key={attempt.id}><summary>第 {attempt.step} 步 · 第 {attempt.attempt} 次 · {attempt.error ? '格式不合格' : '格式有效'}</summary><p>{attempt.error}</p><p className="push-hint">模型：{attempt.metadata.model} · 结束原因：{attempt.metadata.finish_reason || attempt.metadata.status || '未提供'} · 正文 {attempt.metadata.content_chars} 字符</p><pre>{attempt.content || '（模型正文为空）'}</pre></details>)}</div>}</article>)}</div>}
    </Panel>
    <Dialog.Root open={!!confirm} onOpenChange={value => { if (!value && !working) setConfirm(null) }}><Dialog.Portal><Dialog.Overlay className="sheet-overlay" /><Dialog.Content className="provider-dialog"><Dialog.Title>{confirm === 'destroy' ? '永久销毁这台手机？' : '移除安卓容器？'}</Dialog.Title><Dialog.Description>{confirm === 'destroy' ? '应用、登录账号及全部手机数据将永久删除，无法恢复。此操作只影响当前 Bot 的安卓设备。' : '会移除已停止的容器，手机数据保留。再次点击「启动」即可重建并继续使用。'}</Dialog.Description><div className="dialog-actions"><Button variant="outline" disabled={!!working} onClick={() => setConfirm(null)}>返回</Button><Button disabled={!!working} onClick={() => action('delete', async () => { await api(`/android/devices/${device.id}${confirm === 'destroy' ? `?destroy_data=true&confirm=${device.id}` : ''}`, 'DELETE'); setScreen(null); setConfirm(null) }, confirm === 'destroy' ? '设备数据已销毁' : '容器已移除，手机数据已保留')}>{confirm === 'destroy' ? '确认永久销毁' : '移除并保留数据'}</Button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>
}
