import { useCallback, useEffect, useState } from 'react'
import { Archive, Bot, CircleHelp, LoaderCircle, MoreHorizontal, Pencil, Play, Plus, RefreshCw, RotateCcw, Settings2, Square, X, Trash2, MessageSquare } from 'lucide-react'
import { Dialog, DropdownMenu } from 'radix-ui'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import QQConnectDialog from './QQConnectDialog'

const states = { stopped: '已停止', connecting: '连接中', connected: '运行中', reconnecting: '重新连接中' }

export default function BotsPage({ api, notify, onChanged }) {
  const navigate = useNavigate()
  const [bots, setBots] = useState([]), [error, setError] = useState(''), [loading, setLoading] = useState(true)
  const [scanOpen, setScanOpen] = useState(false)
  const [working, setWorking] = useState({}), [dialog, setDialog] = useState(null), [name, setName] = useState(''), [submitting, setSubmitting] = useState(false)
  const refresh = useCallback(async () => { const result = await api('/bots?include_archived=true'); setBots(result.bots); setError(''); setLoading(false) }, [api])
  useEffect(() => {
    let live = true
    const load = () => api('/bots?include_archived=true').then(result => { if (live) { setBots(result.bots); setError(''); setLoading(false) } }).catch(e => { if (live) { setError(e.message); setLoading(false) } })
    load(); const timer = setInterval(load, 5000)
    return () => { live = false; clearInterval(timer) }
  }, [api])
  function open(kind, bot = null) { setName(kind === 'delete' ? '' : bot?.name || ''); setDialog({ kind, bot }) }
  async function perform(bot, operation) {
    setWorking(old => ({ ...old, [bot.id]: operation }))
    try { await api(`/bots/${bot.id}/${operation}`, 'POST'); await refresh(); await onChanged(); notify(operation === 'start' ? '机器人正在连接 QQ' : operation === 'restore' ? '机器人已恢复，保持停止状态' : '机器人已停止') } catch (e) { notify(e.message, true) } finally { setWorking(old => ({ ...old, [bot.id]: '' })) }
  }
  async function submit(event) {
    event.preventDefault(); setSubmitting(true)
    try {
      if (dialog.kind === 'create') {
        const result = await api('/bots', 'POST', { name: name.trim() })
        await onChanged(); setDialog(null); notify('机器人已创建，请配置 QQ 接入方式'); navigate(`/bots/${result.id}/qq`)
      } else if (dialog.kind === 'rename') {
        await api(`/bots/${dialog.bot.id}`, 'PATCH', { name: name.trim() }); await refresh(); await onChanged(); setDialog(null); notify('机器人名称已更新')
      } else if (dialog.kind === 'delete') {
        await api(`/bots/${dialog.bot.id}`, 'DELETE', { name }); await refresh(); await onChanged(); setDialog(null); notify('机器人及其当前数据已永久删除')
      } else {
        await api(`/bots/${dialog.bot.id}/archive`, 'POST'); await refresh(); await onChanged(); setDialog(null); notify('机器人已停止并归档，配置和历史已保留')
      }
    } catch (e) { notify(e.message, true) } finally { setSubmitting(false) }
  }
  const activeBots = bots.filter(bot => !bot.archived), archived = bots.filter(bot => bot.archived)
  const online = activeBots.filter(bot => bot.state === 'connected').length
  function botCard(bot) {
    const busy = !!working[bot.id], running = bot.state !== 'stopped'
    return <Card className="bot-card" key={bot.id}>
      <div className="bot-card-heading"><span className="bot-avatar"><Bot size={20} /></span><div className="bot-card-title"><h2>{bot.name}</h2><small>{bot.app_id ? `${bot.transport==='napcat'?'NapCat · QQ':'AppID'} · ${bot.app_id}` : '尚未配置 QQ 连接'}</small></div><Badge variant="outline">{bot.archived ? '已归档' : states[bot.state]}</Badge>
        {!bot.archived && <DropdownMenu.Root><DropdownMenu.Trigger asChild><Button variant="ghost" size="icon-sm" aria-label={`管理 ${bot.name}`} disabled={busy}><MoreHorizontal size={16} /></Button></DropdownMenu.Trigger><DropdownMenu.Portal><DropdownMenu.Content className="theme-menu" align="end" sideOffset={5}><DropdownMenu.Item className="theme-menu-item" onSelect={() => open('rename', bot)}><Pencil size={14} />重命名</DropdownMenu.Item><DropdownMenu.Item className="theme-menu-item" onSelect={() => open('archive', bot)}><Archive size={14} />归档机器人</DropdownMenu.Item></DropdownMenu.Content></DropdownMenu.Portal></DropdownMenu.Root>}
      </div>
      <dl className="bot-card-details"><div><dt>模型供应商</dt><dd title={bot.provider_name}>{bot.provider_name || '尚未选择'}</dd></div><div><dt>使用模型</dt><dd title={bot.model}>{bot.model || '尚未选择模型'}</dd></div><div><dt>主动消息</dt><dd>{bot.proactive_enabled ? '已启用' : '未启用'}</dd></div></dl>
      <div className="bot-card-stats"><div><span>已接收</span><b>{bot.stats.received.toLocaleString('zh-CN')}</b></div><div><span>已发送</span><b>{bot.stats.sent.toLocaleString('zh-CN')}</b></div><div><span>Token</span><b>{bot.stats.total_tokens.toLocaleString('zh-CN')}</b></div></div>
      <div className="bot-card-actions">{bot.archived ? <><Button variant="outline" disabled={busy} onClick={() => perform(bot, 'restore')}>{busy ? <LoaderCircle size={14} className="spin" /> : <RotateCcw size={14} />}恢复机器人</Button><Button variant="destructive-outline" disabled={busy} onClick={() => open('delete', bot)}><Trash2 size={14} />永久删除</Button></> : <><div className="action-row"><Button asChild variant="outline"><Link to={`/bots/${bot.id}/overview`}><Settings2 size={14} />打开工作台</Link></Button><Button asChild variant="outline" size="icon" title="查看聊天记录" aria-label={`查看 ${bot.name} 的聊天记录`}><Link to={`/bots/${bot.id}/chats`}><MessageSquare size={15} /></Link></Button></div><Button variant={running ? 'outline' : 'default'} disabled={busy || (!running && !bot.configured)} onClick={() => perform(bot, running ? 'stop' : 'start')}>{busy ? <LoaderCircle size={14} className="spin" /> : running ? <Square size={13} /> : <Play size={14} />}{working[bot.id] === 'start' ? '正在启动…' : running ? '停止' : '启动'}</Button></>}
      </div>
    </Card>
  }
  return <><div className="page-heading"><div><h1>机器人管理</h1></div><div className="action-row"><Button variant="outline" onClick={() => refresh().catch(e => notify(e.message, true))}><RefreshCw size={14} />刷新</Button><Button onClick={() => setScanOpen(true)}><Plus size={15} />新建机器人</Button></div></div>
    {error && <div className="notice" role="alert"><CircleHelp size={16} />{error}</div>}
    <div className="bot-summary"><div><span>机器人总数</span><strong>{activeBots.length}</strong></div><div><span>在线机器人</span><strong>{online}</strong></div><div><span>已停止 / 连接中</span><strong>{activeBots.length - online}</strong></div></div>
    {loading ? <div className="empty"><LoaderCircle size={20} className="spin inline-block" /> 正在加载机器人</div> : activeBots.length ? <div className="bot-grid">{activeBots.map(botCard)}</div> : <Card className="bot-empty"><Bot size={28} /><h2>还没有可用的机器人</h2><p>创建一个 Bot，分别设置 QQ 凭证、人格、模型与主动消息。</p><Button onClick={() => setScanOpen(true)}><Plus size={14} />新建机器人</Button></Card>}
    <p className="push-hint mt-5">各 Bot 的会话、消息统计、接收者和提醒独立保存。模型供应商连接可共享；Ollama 推理排队执行，QQ 连接与消息接收独立运行。</p>
    {archived.length > 0 && <details className="greetings-section mt-6"><summary>已归档机器人 <Badge variant="secondary">{archived.length}</Badge></summary><div className="greetings-content bot-grid">{archived.map(botCard)}</div></details>}
    <QQConnectDialog open={scanOpen} onOpenChange={setScanOpen} api={api} onManual={() => { setScanOpen(false); open('create') }} onConnected={async botId => { await refresh(); await onChanged(); setScanOpen(false); notify('QQ 凭证已保存，机器人正在自动连接 QQ'); navigate(`/bots/${botId}/overview`) }} />
    <Dialog.Root open={!!dialog} onOpenChange={value => { if (!value && !submitting) setDialog(null) }}><Dialog.Portal><Dialog.Overlay className="sheet-overlay" /><Dialog.Content className="bot-dialog"><Dialog.Title>{dialog?.kind === 'create' ? '新建机器人' : dialog?.kind === 'rename' ? '重命名机器人' : dialog?.kind === 'delete' ? '永久删除机器人' : '归档机器人'}</Dialog.Title><Dialog.Description>{dialog?.kind === 'delete' ? `将永久删除“${dialog.bot.name}”的配置、密钥、聊天记录、上下文和统计，无法恢复；其他机器人不受影响。已有平台备份不会自动清理。` : dialog?.kind === 'archive' ? `将停止“${dialog.bot.name}”并移出列表。配置、人格、会话与记录保留，之后可以恢复。` : '为机器人设置一个易于识别的名称。每个 Bot 使用独立配置。'}</Dialog.Description><form onSubmit={submit}>{dialog?.kind !== 'archive' && <div className="field"><Label htmlFor="bot-name">{dialog?.kind === 'delete' ? '输入机器人名称确认删除' : '机器人名称'}</Label><Input id="bot-name" autoComplete="off" value={name} onChange={e => setName(e.target.value)} maxLength={40} required placeholder={dialog?.kind === 'delete' ? dialog.bot.name : '例如：生活助手'} /></div>}<div className="action-row mt-6"><Button type="button" variant="outline" disabled={submitting} onClick={() => setDialog(null)}>取消</Button><Button type="submit" variant={dialog?.kind === 'delete' ? 'destructive' : 'default'} disabled={submitting || (dialog?.kind === 'delete' ? name !== dialog.bot.name : dialog?.kind !== 'archive' && !name.trim())}>{submitting && <LoaderCircle size={14} className="spin" />}{dialog?.kind === 'create' ? '创建机器人' : dialog?.kind === 'archive' ? '停止并归档' : dialog?.kind === 'delete' ? '永久删除' : '保存名称'}</Button></div></form><Dialog.Close asChild><Button className="sheet-close" variant="ghost" size="icon-sm" aria-label="关闭对话框" disabled={submitting}><X size={16} /></Button></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>
  </>
}
