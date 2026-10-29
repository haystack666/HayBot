import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Dialog } from 'radix-ui'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { AlertCircle, AlertTriangle, ArrowDown, ArrowRight, Check, ChevronRight, Clock3, Copy, Download, FileSearch, FilterX, Info, LoaderCircle, Pause, Play, RefreshCw, Search, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Field, Notice, Panel } from './components/console'
import { duration, logCategories, logLevels, logQuery, mergeLogPages, readLogFilters } from './lib/logs'

const icons = { error: AlertCircle, warn: AlertTriangle, info: Info, debug: Search }
const at = value => new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
const fields = { batch_count: '合并用户消息数', batch_id: '消息批次编号', segment_index: '当前气泡序号', segment_count: '本次气泡总数', stage: '处理阶段', model: '模型', provider: '供应商', provider_type: '接口类型', duration_ms: '耗时', input_tokens: '输入 Token', output_tokens: '输出 Token', total_tokens: '总 Token', http_status: 'HTTP 状态', error_type: '异常类型', error_code: '错误码', reason: '详细原因', retry_in: '重试等待（秒）', attempt: '尝试次数', count: '数量', image_count: '图片数量', state: '状态', trigger: '触发类型', request_url: '服务地址', request_operation: '请求操作', message_id: 'QQ 消息 ID', sent_message_id: '发送确认 ID', revision: '日程版本' }
const stages = { chat: '对话回复', browser_decision: '浏览器任务决策', schedule: '日程生成', memory: '记忆整理', proactive: '主动消息', embedding: '记忆嵌入', rerank: '记忆重排', diary: '日记写作', diary_review: '日记核对' }

function Level({ level }) { const Icon = icons[level] || Info; return <span className={`event-level event-level-${level}`}><Icon size={13} />{logLevels[level] || level}</span> }
function Metadata({ event }) {
  const detail = event.details || {}
  return <div className="event-metadata"><span>{logCategories[event.category] || '系统'}</span>{event.user && <span>{event.user}</span>}{detail.model && <span title={detail.model}>{detail.model}</span>}{typeof detail.duration_ms === 'number' && <span><Clock3 size={11} />{duration(detail.duration_ms)}</span>}{typeof detail.total_tokens === 'number' && <span>{detail.total_tokens.toLocaleString()} Token</span>}{detail.http_status && <span>HTTP {detail.http_status}</span>}</div>
}

export default function LogsPage({ api, notify }) {
  const { botId } = useParams()
  const [params, setParams] = useSearchParams()
  const filters = useMemo(() => readLogFilters(params), [params])
  const key = JSON.stringify(filters)
  const query = useMemo(() => logQuery(filters), [key])
  const selected = /^\d+$/.test(params.get('event') || '') ? Number(params.get('event')) : null
  const [items, setItems] = useState([]), [snapshot, setSnapshot] = useState(null), [error, setError] = useState('')
  const [loading, setLoading] = useState(true), [olderLoading, setOlderLoading] = useState(false), [before, setBefore] = useState(null)
  const [auto, setAuto] = useState(true), [search, setSearch] = useState(filters.q), [refreshEpoch, setRefreshEpoch] = useState(0)
  const requestGeneration = useRef(0), active = useRef(true), autoRef = useRef(auto), latest = useRef(null)
  autoRef.current = auto
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  useEffect(() => { setSearch(filters.q) }, [filters.q])
  const change = useCallback((values, replace = false) => {
    setParams(previous => {
      const next = new URLSearchParams(previous)
      for (const [name, value] of Object.entries(values)) value ? next.set(name, value) : next.delete(name)
      next.delete('event')
      return next
    }, { replace })
  }, [setParams])
  useEffect(() => {
    if (search === filters.q) return
    const timer = setTimeout(() => change({ q: search }, true), 350)
    return () => clearTimeout(timer)
  }, [search, filters.q, change])
  useEffect(() => {
    let alive = true, pending = false, hasSnapshot = false
    requestGeneration.current += 1; setOlderLoading(false)
    latest.current = null; setItems([]); setSnapshot(null); setBefore(null); setLoading(true); setError('')
    const load = async (initial = false) => {
      if (pending || !initial && !autoRef.current) return
      pending = true
      try {
        const result = await api(`/logs?${query}${!initial && latest.current ? `&after=${latest.current}` : ''}`)
        if (!alive) return
        setItems(previous => !hasSnapshot ? result.items : mergeLogPages(previous, result.items))
        setSnapshot(result)
        if (!hasSnapshot) setBefore(result.next_before)
        hasSnapshot = true
        if (result.latest_id) latest.current = Math.max(latest.current || 0, result.latest_id)
        setError('')
      } catch (e) { if (alive) setError(e.message) }
      finally { pending = false; if (alive) setLoading(false) }
    }
    load(true); const timer = setInterval(() => load(false), 5000)
    return () => { alive = false; clearInterval(timer) }
  }, [api, query, refreshEpoch])
  async function older() {
    const requestKey = requestGeneration.current
    setOlderLoading(true)
    try {
      const result = await api(`/logs?${query}&before=${before}`)
      if (!active.current || requestGeneration.current !== requestKey) return
      setItems(previous => mergeLogPages(previous, result.items)); setBefore(result.next_before)
    } catch (e) { if (active.current && requestGeneration.current === requestKey) setError(e.message) }
    finally { if (active.current && requestGeneration.current === requestKey) setOlderLoading(false) }
  }
  function open(id) { setParams(previous => { const next = new URLSearchParams(previous); id ? next.set('event', id) : next.delete('event'); return next }, { replace: true }) }
  function exportLogs() {
    const file = new Blob([JSON.stringify({ exported_at: new Date().toISOString(), bot_id: botId, filters, logs: items }, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(file), link = document.createElement('a')
    link.href = url; link.download = `haybot-${botId}-logs-${new Date().toISOString().slice(0, 10)}.json`; link.click(); URL.revokeObjectURL(url)
    notify(`已导出当前加载的 ${items.length} 条日志`)
  }
  const summary = snapshot?.summary || {}
  return <div className="page-stack logs-page">
    <div className="logs-summary" aria-label="日志级别统计">{[['', '全部事件'], ...Object.entries(logLevels).map(([level, label]) => [level, label])].map(([level, label]) => <button type="button" className={filters.level === level ? 'selected' : ''} aria-pressed={filters.level === level} key={level} onClick={() => change({ level })}><span>{label}</span><strong>{(level ? summary[level] || 0 : Object.values(summary).reduce((a, b) => a + b, 0)).toLocaleString()}</strong></button>)}</div>
    <Panel title="运行事件" subtitle="查看事件详情，沿处理链路定位问题。新事件每 5 秒同步，保留最近 10,000 条。" action={<div className="action-row"><Button variant="outline" size="sm" aria-pressed={!auto} onClick={() => setAuto(value => !value)}>{auto ? <Pause size={13} /> : <Play size={13} />}{auto ? '暂停刷新' : '继续刷新'}</Button><Button variant="ghost" size="icon-sm" aria-label="刷新日志" disabled={loading} onClick={() => setRefreshEpoch(value => value + 1)}><RefreshCw size={14} className={loading ? 'spin' : ''} /></Button><Button variant="outline" size="sm" disabled={!items.length} onClick={exportLogs}><Download size={13} />导出当前结果</Button></div>}>
      <div className="logs-filters"><div className="logs-search"><Search size={15} /><Input aria-label="搜索运行日志" maxLength={200} placeholder="搜索事件、用户、模型、错误或链路编号" value={search} onChange={e => setSearch(e.target.value)} /></div><Field label="事件分类" id="log-category"><select className="provider-select" id="log-category" value={filters.category} onChange={e => change({ category: e.target.value })}><option value="">全部分类</option>{Object.entries(logCategories).map(([value, title]) => <option key={value} value={value}>{title}</option>)}</select></Field><Field label="时间范围" id="log-range"><select className="provider-select" id="log-range" value={filters.range} onChange={e => change({ range: e.target.value })}><option value="1h">最近 1 小时</option><option value="24h">最近 24 小时</option><option value="7d">最近 7 天</option><option value="all">全部保留记录</option></select></Field></div>
      {(filters.level || filters.category || filters.q || filters.trace || filters.range !== '24h') && <div className="logs-filter-state">{filters.trace && <Badge variant="outline">处理链路 {filters.trace.slice(0, 12)}</Badge>}<span>匹配 {snapshot?.total || 0} 条，已加载 {items.length} 条</span><Button variant="ghost" size="sm" onClick={() => change({ level: '', category: '', q: '', trace: '', range: '' })}><FilterX size={13} />清除筛选</Button></div>}
      {error && <Notice alert>{error}。已加载的日志会保留，可点击刷新重试。</Notice>}
      {loading ? <div className="logs-empty"><LoaderCircle className="spin" size={22} /><p>正在读取日志…</p></div> : !items.length ? <div className="logs-empty"><FileSearch size={28} /><h3>没有匹配的运行事件</h3><p>可以清除筛选，或等待机器人处理新消息。</p></div> : <div className="event-list">{items.map(event => <button type="button" className={`event-row ${selected === event.id ? 'is-selected' : ''}`} key={event.id} onClick={() => open(event.id)} aria-label={`查看日志 ${event.id}：${event.message}`}><div className="event-row-start"><Level level={event.level} /><time>{at(event.at)}</time></div><div className="event-row-body"><strong>{event.message}</strong><Metadata event={event} /></div><ChevronRight size={15} /></button>)}</div>}
      {before && <div className="logs-more"><Button variant="outline" size="sm" disabled={olderLoading} onClick={older}>{olderLoading ? <LoaderCircle size={13} className="spin" /> : <ArrowDown size={13} />}加载更早日志</Button></div>}
      <div className="logs-footnote"><span>{auto ? '自动刷新中' : '已暂停自动刷新'} · 已加载 {items.length} 条</span><span>凭证自动隐藏；旧版事件可能没有模型与耗时详情。</span></div>
    </Panel>
    <LogDetail key={selected} id={selected} api={api} open={open} notify={notify} onTrace={trace => change({ trace, q: '', level: '', category: '', range: 'all' })} />
  </div>
}

function LogDetail({ id, api, open, notify, onTrace }) {
  const { botId } = useParams()
  const [event, setEvent] = useState(null), [error, setError] = useState(''), [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!id) return
    let alive = true
    api(`/logs/${id}`).then(result => { if (alive) setEvent(result) }).catch(e => { if (alive) setError(e.message) })
    return () => { alive = false }
  }, [id, api])
  async function copy() {
    try { await navigator.clipboard.writeText(JSON.stringify(event, null, 2)); setCopied(true) }
    catch { notify('复制失败，请使用导出功能保存日志', true) }
  }
  return <Dialog.Root open={!!id} onOpenChange={value => { if (!value) open(null) }}><Dialog.Portal><Dialog.Overlay className="sheet-overlay" /><Dialog.Content className="provider-dialog log-detail-dialog"><Dialog.Title>事件详情</Dialog.Title><Dialog.Description>查看处理信息、异常原因和关联聊天，凭证已隐藏。</Dialog.Description>{error ? <Notice alert>{error}</Notice> : !event ? <div className="logs-empty"><LoaderCircle className="spin" size={22} /></div> : <>
    <div className="log-detail-heading"><Level level={event.level} /><time>{at(event.at)}</time><span>#{event.id}</span></div><h3 className="log-detail-title">{event.message}</h3><Metadata event={event} />
    <dl className="log-detail-fields">{Object.entries(fields).filter(([key]) => event.details[key] !== undefined && event.details[key] !== '').map(([key, label]) => <div key={key} className={key === 'reason' || key === 'request_url' ? 'full' : ''}><dt>{label}</dt><dd>{key === 'duration_ms' ? duration(event.details[key]) : key === 'stage' ? stages[event.details[key]] || event.details[key] : String(event.details[key])}</dd></div>)}</dl>
    {!Object.keys(event.details).length && <Notice>这是旧版记录，只保存了时间、级别与事件摘要。升级后的新事件会包含详细信息。</Notice>}
    {!!event.messages.length && <section className="log-message-preview"><h4>关联消息</h4>{event.messages.map((message, index) => <div key={message.id || index}><Badge variant="outline">{message.role === 'user' ? '用户消息' : '机器人回复'}</Badge><p>{message.content}</p></div>)}{event.conversation_id && <Link className="subtle-link" to={`/bots/${botId}/chats?conversation=${encodeURIComponent(event.conversation_id)}&view=chat`}>查看完整聊天<ArrowRight size={12} /></Link>}</section>}
    {event.trace_id && <section className="log-trace"><div className="log-trace-heading"><h4>处理链路</h4><Button size="sm" variant="ghost" onClick={() => onTrace(event.trace_id)}>在列表中筛选</Button></div><code>{event.trace_id}</code><ol>{event.related.map(item => <li key={item.id}><button type="button" onClick={() => open(item.id)} className={item.id === event.id ? 'selected' : ''}><span>{new Date(item.at * 1000).toLocaleTimeString('zh-CN', { hour12: false })}</span><strong>{item.message}</strong>{typeof item.details.duration_ms === 'number' && <small>{duration(item.details.duration_ms)}</small>}</button></li>)}</ol></section>}
    <div className="dialog-actions"><Button variant="outline" size="sm" onClick={copy}>{copied ? <Check size={13} /> : <Copy size={13} />}{copied ? '已复制' : '复制脱敏详情'}</Button><Button size="sm" onClick={() => open(null)}>关闭</Button></div>
  </>}<Dialog.Close asChild><Button variant="ghost" size="icon-sm" className="dialog-close" aria-label="关闭日志详情"><X size={15} /></Button></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>
}
