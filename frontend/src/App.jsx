import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowDownLeft, ArrowUpRight, Bot, ChevronRight, CircleHelp, Cpu, FileText, LayoutDashboard, LoaderCircle, LogOut, Menu, PanelLeftClose, PanelLeftOpen, Play, Radio, RefreshCw, Save, ShieldCheck, SlidersHorizontal, Square, X, Bell, MessageSquare, CalendarDays, Brain, Image, Globe2, Smartphone } from 'lucide-react'
import { Dialog } from 'radix-ui'
import { NavLink, useNavigate, useParams, useLocation } from 'react-router-dom'
import ProactivePage from './ProactivePage'
import BotsPage from './BotsPage'
import ChatsPage from './ChatsPage'
import ProvidersPage from './ProvidersPage'
import ConfigurationPages from './ConfigurationPages'
import SchedulePage from './SchedulePage'
import DiaryPage from './DiaryPage'
import MemoryPage from './MemoryPage'
import MemesPage from './MemesPage'
import QzonePage from './QzonePage'
import LogsPage from './LogsPage'
import AndroidPage from './AndroidPage'
import BrowserPage from './BrowserPage'
import ThemeSelector from './ThemeSelector'
import BotNavigation from './components/BotNavigation'
import FeatureSearch from './components/FeatureSearch'
import { usePageTabs } from './components/PageTabs'
import { Brand, Panel, Field, Logs, Notice } from './components/console'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'

export const pages = [
  { id: 'overview', title: '工作概览', subtitle: '查看机器人状态、消息与模型用量。', icon: LayoutDashboard },
  { id: 'qq', title: '连接与模型', subtitle: '当前 Bot 的 QQ 接入与模型分配。', icon: Bot },
  { id: 'providers', title: '共享供应商', subtitle: '选择供应商和模型，管理多个本地或外部连接。', icon: Cpu },
  { id: 'rules', title: '角色与群聊', subtitle: '管理角色身份、Owner 关系和不同场景的表达。', icon: SlidersHorizontal },
  { id: 'memory', title: '角色记忆', subtitle: '管理每位用户的长期记忆、共同经历和未来约定。', icon: Brain },
  { id: 'diary', title: '私人日记', icon: FileText },
  { id: 'schedule', title: '每日日程', subtitle: '安排角色每天的活动、穿着与生活中的小插曲。', icon: CalendarDays },
  { id: 'memes', title: '表情素材', subtitle: '管理逐图语义描述，让机器人在合适的时刻发表情。', icon: Image },
  { id: 'qzone', title: 'QQ 空间', subtitle: '编辑、定时发布角色动态，管理配图与可见范围。', icon: Globe2 },
  { id: 'proactive', title: '主动互动', subtitle: '设置定时问候和主动搭话策略。', icon: Bell },
  { id: 'chats', title: '会话记录', subtitle: '查看当前 Bot 的会话记录，支持列表与气泡视图。', icon: MessageSquare },
  { id: 'browser', title: '浏览器工作台', icon: Globe2 },
  { id: 'android', title: '手机工作台', subtitle: '管理独立手机、查看画面并执行安卓操作任务。', icon: Smartphone },
  { id: 'logs', title: '运行日志', subtitle: '筛选运行事件，查看模型耗时、异常原因与消息处理链路。', icon: FileText },
]
const states = { stopped: '已停止', connecting: '连接中', connected: '运行中', reconnecting: '重新连接中' }
const numericFields = [
  ['memory', 'extraction_turns', '记忆整理轮数'], ['memory', 'top_k', '选入记忆条数'], ['memory', 'recall_limit', '检索候选条数'], ['memory', 'context_chars', '记忆字符预算'], ['memory', 'timeout', '检索超时'],
  ['ollama', 'max_tokens', '输出 Token 上限'], ['ollama', 'timeout', '请求超时'], ['ollama', 'temperature', '温度'],
  ['rules', 'debounce_seconds', '静默等待时间'], ['rules', 'debounce_max_wait', '最长收集时间'], ['rules', 'debounce_max_messages', '每批消息上限'],
  ['rules', 'split_length', '目标段长'], ['rules', 'split_max_parts', '最多气泡数'], ['rules', 'split_delay', '段间隔'],
  ['rules', 'rounds', '保留上下文'], ['rules', 'max_length', '最大回复长度'], ['rules', 'cooldown', '回复冷却'],
  ['group_chat', 'cooldown_seconds', '群聊主动接话间隔'], ['group_chat', 'max_replies_per_hour', '群聊每小时回复上限'],
  ['proactive', 'daily_limit', '每日自动消息上限'], ['proactive', 'cooldown_minutes', '问候 / 搭话冷却'],
  ['proactive', 'unanswered_limit', '连续未回应暂停次数'],
  ['proactive', 'idle_min_minutes', '最短搭话间隔'], ['proactive', 'idle_max_minutes', '最长搭话间隔'],
]
async function requestApi(path, method = 'GET', body) {
  const res = await fetch(`/api${path}`, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, ...(body ? { body: JSON.stringify(body) } : {}) })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) { const error = new Error(typeof data.detail === 'string' ? data.detail : '请求失败，请稍后重试'); error.status = res.status; throw error }
  return data
}
function Navigation({ botId, bots, switchBot, guardLeave, closeMenu, mobile = false }) {
  return <><Brand /><div className="bot-selector"><label htmlFor={mobile ? 'mobile-bot-selector' : 'bot-selector'}>当前机器人</label><select id={mobile ? 'mobile-bot-selector' : 'bot-selector'} aria-label="切换机器人" value={botId || ''} onChange={event => switchBot(event.target.value)}><option value="" disabled>选择机器人</option>{bots.map(bot => <option key={bot.id} value={bot.id}>{bot.name}</option>)}</select></div>
    <FeatureSearch {...{botId,guardLeave,closeMenu}} keyboard={!mobile} />
    {botId && <BotNavigation {...{botId,pages,closeMenu,mobile,guardLeave}} />}
    <nav className="sidebar-bottom workspace-navigation" aria-label="工作空间"><NavLink to="/bots" end className={({isActive})=>`nav-button ${isActive?'active':''}`} onClick={event=>{if(!guardLeave())event.preventDefault();else closeMenu?.()}}><Bot size={16}/><span className="nav-text">机器人管理</span></NavLink><NavLink to="/providers" className={({isActive})=>`nav-button ${isActive?'active':''}`} onClick={event=>{if(!guardLeave())event.preventDefault();else closeMenu?.()}}><Cpu size={16}/><span className="nav-text">共享供应商</span></NavLink></nav></>
}
function Overview({ status, config, ollamaState, navigate, providers }) {
  const metrics = [
    { label: '机器人状态', value: states[status.state], note: config.transport === 'napcat' ? '外部 NapCat WebSocket' : 'QQ 官方 WebSocket', icon: Radio },
    { label: '已接收消息', value: status.stats.received ?? 0, note: '累计接收的消息数量', icon: ArrowDownLeft },
    { label: '已发送回复', value: status.stats.sent ?? 0, note: '累计成功发送的消息数量', icon: ArrowUpRight },
    { label: 'Token 总用量', value: status.stats.total_tokens ?? 0, note: '输入 + 输出 Token', icon: FileText },
  ]
  return <div className="page-stack"><div className="metrics">{metrics.map(({ label, value, note, icon: Icon }) => <Card className="metric" key={label}><div className="metric-label"><span>{label}</span><Icon size={16} /></div><strong className="metric-value">{typeof value === 'number' ? value.toLocaleString('zh-CN') : value}</strong><p className="metric-note">{note}</p></Card>)}</div>
    <Panel title="常用入口" subtitle="查看对话、处理手机任务或翻阅角色生活。"><div className="overview-shortcuts">{[['chats','查看会话','最近私聊与群聊'],['android','手机工作台','任务、接管与执行结果'],['diary','翻阅日记','已保存正文与写作习惯'],['rules?view=group','群聊参与','公开人格与各群设置']].map(([path,title,detail])=><button key={path} onClick={()=>navigate(path)}><b>{title}<ChevronRight size={14}/></b><small>{detail}</small></button>)}</div></Panel>
    <div className="two-column"><Panel title="服务连接" subtitle="QQ 官方接口与所选模型服务">
      <div className="connection"><Bot size={22} /><div className="connection-info"><strong>{config.transport==='napcat'?'外部 NapCat':'QQ 官方机器人'}</strong><small>{config.transport==='napcat'?(config.napcat.self_id?`QQ · ${config.napcat.self_id}`:'尚未配置外部连接'):(config.qq.app_id?`AppID · ${config.qq.app_id}`:'尚未填写机器人凭证')}</small></div><Badge variant="secondary">{(config.transport==='napcat'?config.napcat.self_id&&config.napcat.ws_url:config.qq.secret_set) ? status.state === 'connected' ? '已连接' : '已配置' : '待配置'}</Badge><Button variant="ghost" size="icon-sm" onClick={() => navigate('qq')} aria-label="配置 QQ"><ChevronRight size={15} /></Button></div>
      <div className="connection"><Cpu size={22} /><div className="connection-info"><strong>{providers.find(item => item.id === config.ollama.provider_id)?.name || '模型供应商'}</strong><small>{config.ollama.model || '尚未选择模型'}</small><small>{providers.find(item => item.id === config.ollama.provider_id)?.base_url || config.ollama.url}</small></div><Badge variant="secondary">{ollamaState === 'online' ? '可访问' : ollamaState === 'offline' ? '不可访问' : '待验证'}</Badge><Button variant="ghost" size="icon-sm" onClick={() => navigate('providers')} aria-label="配置模型供应商"><ChevronRight size={15} /></Button></div>
    </Panel><Panel title="Token 用量" subtitle="按模型服务实际返回累计，重启保留"><dl className="stat-list">{[['输入 Token', status.stats.input_tokens ?? 0], ['输出 Token', status.stats.output_tokens ?? 0], ['合计 Token', status.stats.total_tokens ?? 0]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value.toLocaleString('zh-CN')}</dd></div>)}</dl><div className="processing-summary"><span>正在处理 <b>{status.jobs}</b> 项</span><span>等待合并 / 排队 <b>{status.inbox?.queued || 0}</b> 条</span><span>累计异常 <b>{status.stats.errors ?? 0}</b> 次</span></div></Panel></div>
    <Panel title="最近运行记录" subtitle="查看全部可筛选事件、展开详情与处理链路" action={<Button variant="ghost" size="sm" onClick={() => navigate('logs')}>查看全部<ChevronRight size={14} /></Button>}><Logs logs={status.logs} limit={6} /></Panel>
  </div>
}

export default function App({ page }) {
  const routerNavigate = useNavigate()
  const { botId } = useParams()
  const api = useCallback((path, method = 'GET', body) => {
    if (!botId || path === '/login' || path === '/logout' || path.startsWith('/bots')) return requestApi(path, method, body)
    return requestApi(`/bots/${encodeURIComponent(botId)}${path.replace(/^\/bot\//, '/')}`, method, body)
  }, [botId])
  const [providers, setProviders] = useState([])
  const loadProviders = useCallback(async () => { const result = await requestApi('/providers'); setProviders(result.providers); return result.providers }, [])
  const [bots, setBots] = useState([]), [loadError, setLoadError] = useState('')
  const loadBotList = useCallback(async () => { const result = await requestApi('/bots'); setBots(result.bots); return result.bots }, [])
  const [authed, setAuthed] = useState(null), [password, setPassword] = useState(''), [loginError, setLoginError] = useState('')
  const [config, setConfig] = useState(null), [savedConfig, setSavedConfig] = useState(null), [dirty, setDirty] = useState(false)
  const [collapsed, setCollapsed] = useState(false), [mobileOpen, setMobileOpen] = useState(false)
  const [status, setStatus] = useState({ state: 'stopped', stats: {}, logs: [], jobs: 0, uptime: 0 })
  const [models, setModels] = useState([]), [ollamaState, setOllamaState] = useState('unknown'), [busy, setBusy] = useState(''), [toast, setToast] = useState(null), [pollError, setPollError] = useState(false)
  const timer = useRef(null), mounted = useRef(true)
  const notify = useCallback((text, error = false) => { setToast({ text, error }); clearTimeout(timer.current); timer.current = setTimeout(() => setToast(null), 6000) }, [])
  const checkModels = useCallback(async c => { try { const r = await api('/models/test', 'POST', c); if (mounted.current) { setModels(r.models); setOllamaState(r.models_supported === false ? 'unknown' : 'online') } return r.models } catch (e) { if (mounted.current) setOllamaState('offline'); throw e } }, [api])
  const applySettings = useCallback(c => { const next = { ...c, qq: { ...c.qq, secret: '' }, napcat: { ...c.napcat, token: '' } }; setConfig(next); setSavedConfig(structuredClone(next)); setDirty(false) }, [])
  const load = useCallback(async () => {
    setLoadError('')
    await Promise.all([loadBotList(), loadProviders()])
    if (botId) {
      const [settings, status] = await Promise.all([api('/settings'), api('/status')])
      applySettings(settings); setStatus(status); checkModels(settings.ollama).catch(() => {})
    }
    setAuthed(true)
  }, [botId, loadBotList, loadProviders, api, checkModels, applySettings])
  useEffect(() => {
    mounted.current = true
    load().catch(error => { if (error.status === 401) setAuthed(false); else { setAuthed(true); setLoadError(error.message) } })
    return () => { mounted.current = false; clearTimeout(timer.current) }
  }, [load])
  useEffect(() => {
    if (!authed || loadError) return
    const poll = setInterval(() => {
      loadBotList().catch(error => { if (error.status === 401) setAuthed(false); else setPollError(true) })
      if (botId) api('/status').then(result => { setStatus(result); setPollError(false) }).catch(error => {
        if (error.status === 401) setAuthed(false)
        else if (error.status === 404) setLoadError(error.message)
        else setPollError(true)
      })
    }, 5000)
    return () => clearInterval(poll)
  }, [authed, loadError, botId, api, loadBotList])
  useEffect(() => {
    const bot = bots.find(item => item.id === botId)
    document.title = authed ? `${page === 'bots' ? '机器人管理' : pages.find(item => item.id === page).title}${bot ? ` · ${bot.name}` : ''} · HayBot` : 'HayBot · QQ AI 机器人配置平台'
  }, [page, authed, bots, botId])
  function update(section, key, value) { setConfig(c => ({ ...c, [section]: { ...c[section], [key]: value }, ...((section === 'napcat' && key === 'self_id' || section === 'qq' && key === 'app_id') && c[section][key] !== value ? {proactive:{...c.proactive,enabled:false,recipient_id:''}} : {}) })); setDirty(true); if (section === 'ollama' && (key === 'url' || key === 'provider_id')) { setOllamaState('unknown'); setModels([]) } }
  async function action(name, fn, message) { setBusy(name); try { await fn(); if (message) notify(message); if (botId) { setStatus(await api('/status')); if (name === 'toggle') await loadProviders() } } catch (e) { notify(e.message, true); if (e.status === 401) setAuthed(false) } finally { setBusy('') } }
  async function save() {
    const body = structuredClone(config)
    for (const [section, key, label] of numericFields) {
      const value = body[section][key]
      if (String(value).trim() === '' || !Number.isFinite(Number(value))) throw new Error(`${label}请填写数字`)
      body[section][key] = Number(value)
    }
    delete body.qq.secret_set
    delete body.napcat.token_set
    applySettings(await api('/settings', 'PUT', body))
  }
  function setTransport(value) { setConfig(c => ({...c,transport:value,proactive:{...c.proactive,enabled:false,recipient_id:''}}));setDirty(true) }
  function cancel() { setConfig(structuredClone(savedConfig)); setDirty(false); checkModels(savedConfig.ollama).catch(() => {}) }
  function navigate(next) { routerNavigate(`/bots/${botId}/${next}`); setMobileOpen(false) }
  function guardLeave() { return !dirty || window.confirm('当前机器人有未保存的配置。确定离开当前页面吗？') }
  function switchBot(next) { if (next && next !== botId && guardLeave()) { routerNavigate(`/bots/${next}/${!botId ? 'overview' : page}`); setMobileOpen(false) } }
  const active = !!botId && status.state !== 'stopped', current = page === 'bots' ? { title: '机器人管理', subtitle: '' } : pages.find(p => p.id === page)
  const { search } = useLocation()
  const readOnlyConfig = ['qq','rules'].includes(page) || ['memory','schedule'].includes(page) && new URLSearchParams(search).get('view') === 'settings' || page === 'proactive' && new URLSearchParams(search).get('view') !== 'qzone'
  const currentBot = bots.find(bot => bot.id === botId)
  const connections = usePageTabs([['qq','QQ 连接'],['models','模型分配']])
  const toggleButton = <Button disabled={!!busy || (!active && dirty)} variant={active ? 'outline' : 'default'} onClick={() => action('toggle', () => api(active ? '/bot/stop' : '/bot/start', 'POST'), active ? '机器人已停止' : '机器人正在连接 QQ')}>{busy === 'toggle' ? <LoaderCircle size={14} className="spin" /> : active ? <Square size={13} /> : <Play size={14} />}{active ? '停止机器人' : '启动机器人'}</Button>
  if (authed === null) return <div className="loading-page"><LoaderCircle className="spin" aria-label="正在加载 HayBot" /></div>
  if (!authed) return <div className="login-page"><div className="login-theme"><ThemeSelector /></div><div className="login-heading"><Brand /><p>QQ AI 机器人管理平台</p></div><Card className="login-card"><h1>登录管理平台</h1><p>连接 QQ 官方机器人与多个模型供应商。</p><form onSubmit={async e => { e.preventDefault(); setBusy('login'); setLoginError(''); try { await api('/login', 'POST', { password }); setPassword(''); await load() } catch (err) { setLoginError(err.message) } finally { setBusy('') } }}><Label htmlFor="password">管理密码</Label><Input id="password" type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required placeholder="输入管理密码" />{loginError && <span className="login-error" role="alert">{loginError}</span>}<Button disabled={!!busy}>{busy ? <LoaderCircle size={15} className="spin" /> : <LogOut size={15} />}登录 HayBot</Button></form><small>密码保存在项目 .env 的 ADMIN_PASSWORD 中</small></Card><p className="login-footer"><ShieldCheck size={13} /> 本地部署 · 数据自主掌控</p></div>
  if (loadError) return <div className="loading-page"><div className="load-error"><Brand /><h1>无法打开机器人</h1><p className="subtitle">{loadError}</p><Button asChild className="mt-5"><NavLink to="/bots">返回机器人管理</NavLink></Button></div></div>
  return <div className={`shell ${collapsed ? 'sidebar-collapsed' : ''}`}><a className="skip-link" href="#main-content">跳转到主要内容</a><aside className="sidebar"><Navigation {...{botId, bots, switchBot, guardLeave}} /></aside><div className="workspace"><header className="topbar"><div className="header-start">
    <Button className="desktop-menu" variant="ghost" size="icon" onClick={() => setCollapsed(!collapsed)} aria-label={collapsed ? '展开侧栏' : '折叠侧栏'}>{collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}</Button>
    <Dialog.Root open={mobileOpen} onOpenChange={setMobileOpen}><Dialog.Trigger asChild><Button className="mobile-menu" variant="ghost" size="icon" aria-label="打开导航"><Menu size={18} /></Button></Dialog.Trigger><Dialog.Portal><Dialog.Overlay className="sheet-overlay" /><Dialog.Content className="mobile-sidebar"><Dialog.Title className="sr-only">HayBot 导航</Dialog.Title><Dialog.Description className="sr-only">选择机器人管理页面</Dialog.Description><Dialog.Close asChild><Button variant="ghost" size="icon-sm" className="sheet-close" aria-label="关闭导航"><X size={16} /></Button></Dialog.Close><Navigation {...{botId, bots, switchBot, guardLeave}} closeMenu={() => setMobileOpen(false)} mobile /></Dialog.Content></Dialog.Portal></Dialog.Root>
    <div className="breadcrumb"><span className="breadcrumb-bot" title={currentBot?.name}>{currentBot?.name || '工作空间'}</span><ChevronRight size={13} /><b>{current.title}</b></div></div><div className="top-actions"><Badge variant="outline" className="runtime-badge"><span className={`status-dot ${active ? 'live' : ''}`} />{botId ? states[status.state] : `${bots.filter(bot => bot.state === 'connected').length} 在线`}</Badge><span className="topbar-divider" /><ThemeSelector /><Button variant="ghost" size="icon" aria-label="退出登录" title="退出登录" onClick={() => action('logout', async () => { await api('/logout', 'POST'); setAuthed(false); setConfig(null); setSavedConfig(null); setDirty(false) })}><LogOut size={16} /></Button></div></header>
    <main className={`main ${page === 'browser' ? 'main-browser' : ''}`} id="main-content">{page !== 'bots' && <div className="page-heading"><div><span className="page-scope">{botId ? `当前 Bot · ${currentBot?.name || ''}` : '工作空间 · 共享资源'}</span><h1>{current.title}</h1>{current.subtitle && <p className="subtitle">{current.subtitle}</p>}</div><div className="action-row">{botId && (page === 'overview' || active && readOnlyConfig) && toggleButton}</div></div>}
    {dirty && botId && <div className="config-savebar" role="status"><span>当前 Bot 有未保存的配置{active && <small>停止机器人后可保存</small>}</span><div className="action-row"><Button variant="outline" disabled={!!busy} onClick={cancel}>撤销更改</Button><Button disabled={!!busy || active} onClick={() => action('save', save, '配置已保存')}><Save size={14}/>{busy === 'save' ? '保存中…' : '保存更改'}</Button></div></div>}
    {botId && status.state === 'stopped' && status.start_error && <Notice alert>自动启动失败：{status.start_error}。已保存的机器人无需重新扫码，可检查配置后点击“启动机器人”重试。</Notice>}
    {pollError && <Notice alert>后台连接中断，页面显示上次状态，正在重试。</Notice>}
    {dirty && (page === 'overview' || page === 'logs' || page === 'chats' || page === 'qzone') && <Notice>有尚未保存的配置，请返回配置页面保存或取消更改。</Notice>}
    {botId && active && readOnlyConfig && <Notice>连接、模型与角色策略在运行期间只读。修改这些配置前请先停止机器人。</Notice>}
    {page === 'bots' && <BotsPage api={api} notify={notify} onChanged={loadBotList} />}
    {page === 'overview' && <Overview status={status} config={config} ollamaState={ollamaState} navigate={navigate} providers={providers} />}
    {page === 'qq' && connections.tabs}
    {botId && <ConfigurationPages {...{page, config, active, busy, dirty, update, action, api, notify, checkModels, models, ollamaState, setTransport}} connectionView={connections.value} guardLeave={guardLeave} />}
    {(page === 'providers' || page === 'qq' && connections.value === 'models') && <ProvidersPage key={botId || 'shared'} providers={providers} refreshProviders={loadProviders} globalApi={requestApi} assignmentOnly={!!botId} guardLeave={guardLeave} {...{config, update, active, busy, dirty, notify}} />}
    {page === 'proactive' && <ProactivePage config={config.proactive} update={(key, value) => update('proactive', key, value)} active={active} busy={busy} dirty={dirty} api={api} notify={notify} Panel={Panel} Field={Field} space={<QzonePage key={botId} {...{api,notify,dirty}} />} />}
    {page === 'schedule' && <SchedulePage config={config.schedule} update={(key, value) => update('schedule', key, value)} {...{active, busy, dirty, api, notify}} model={config.ollama.model} />}
    {page === 'memory' && <MemoryPage config={config.memory} update={(key, value) => update('memory', key, value)} {...{active, busy, dirty, api, notify}} />}
    {page === 'memes' && <MemesPage {...{api, providers, notify}} memory={config.memory} onSaved={memes => { setConfig(c => ({ ...c, memes })); setSavedConfig(c => ({ ...c, memes })) }} />}
    {page === 'android' && <AndroidPage key={botId} {...{api, notify, providers, botId}} />}
    {page === 'browser' && <BrowserPage key={botId} {...{api, notify, botId}} />}
    {page === 'diary' && <DiaryPage key={botId} {...{api, notify}} />}
    {page === 'qzone' && <QzonePage key={botId} {...{api,notify,dirty}} />}
    {page === 'chats' && <><div className="page-quicklinks"><Button variant="outline" size="sm" onClick={()=>navigate('rules?view=group')}>群聊参与设置<ChevronRight size={13}/></Button><Button variant="ghost" size="sm" onClick={()=>navigate('memory')}>查看角色记忆</Button></div><ChatsPage api={api} botName={currentBot?.name} /></>}
    {page === 'logs' && <LogsPage key={botId} {...{api, notify}} />}
    <footer className="footer"><span>HayBot <span className="footer-dot">·</span> 本地机器人管理平台</span><span>{botId ? `已运行 ${Math.floor(status.uptime / 60)} 分钟` : '多个机器人独立运行'}</span></footer></main></div>
    {toast && <div className={`toast ${toast.error ? 'error' : ''}`} role={toast.error ? 'alert' : 'status'}>{toast.error ? <CircleHelp size={16} /> : <ShieldCheck size={16} />}<span>{toast.text}</span><button aria-label="关闭提示" onClick={() => setToast(null)}><X size={14} /></button></div>}
  </div>
}
