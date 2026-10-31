import { usePageTabs, Section } from './components/PageTabs'
import { useCallback, useEffect, useState } from 'react'
import { Dialog } from 'radix-ui'
import { Link, useParams } from 'react-router-dom'
import { Brain, History, LoaderCircle, Pencil, Pin, Plus, RefreshCw, Search, Trash2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { Field, Notice, Panel } from './components/console'
import UserScopeSelector, { useUserScopes } from './UserScopeSelector'
import { scopePath } from './lib/memory-config'

const categories = { fact: '个人资料', preference: '偏好', boundary: '边界', relationship: '关系', episode: '共同经历', commitment: '约定' }
const states = { pending: '待履行', fulfilled: '已确认履行', canceled: '已取消' }
const at = value => value ? new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'
const localDate = value => { if (!value) return ''; const date = new Date(value * 1000); return new Date(date - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16) }
const initial = { category: 'fact', content: '', key: '', pinned: false, importance: 50, due_at: '', end_at: '', expires_at: '', commitment_state: 'pending' }

export default function MemoryPage({ config, update, active, busy, dirty, api, notify }) {
  const { botId } = useParams()
  const selection = useUserScopes(api)
  const scopedApi = useCallback((path, method, body) => api(scopePath(path, selection.scopeId), method, body), [api, selection.scopeId])
  const tabs = usePageTabs([['entries','记忆内容'],['context','上下文诊断'],['history','修改记录'],['settings','记忆设置']])
  return <div className="page-stack">{tabs.tabs}
    <Section show={tabs.value === 'settings'}><Panel title="记忆策略" subtitle="整理实际对话，保留偏好、边界、共同经历和带日期的约定。">
      <div className="toggle-row !pt-0"><div><b>启用长期记忆</b><p>需先配置独立的 Embedding；Rerank 可选。已有记忆不会因关闭开关被删除。</p></div><Switch aria-label="启用长期记忆" checked={config.enabled} disabled={active || !!busy} onCheckedChange={value => update('enabled', value)} /></div>
      <Link className="subtle-link mt-4" to={`/bots/${botId}/providers`}>配置 Embedding 与 Rerank 模型</Link>
      <fieldset disabled={active || !!busy} className="form-grid border-0 m-0 p-0 mt-5">
        {[['extraction_turns', '每几轮整理一次', 1, 30, '1–30 轮；停止聊天 30 秒后也会整理待处理消息。'], ['top_k', '每次选入的记忆数', 1, 30, '相关记忆最多 1–30 条，固定保留项优先。'], ['recall_limit', '初步检索条数', 5, 100, '全文与语义检索候选，5–100 条。'], ['context_chars', '记忆上下文字符预算', 500, 16000, '包括摘要与相关记忆，500–16000 字符。'], ['timeout', '检索接口超时（秒）', 5, 120, '5–120 秒；接口异常时使用全文检索。']].map(([key, label, min, max, hint]) => <Field key={key} label={label} id={`memory-${key}`} hint={hint}><Input id={`memory-${key}`} type="number" min={min} max={max} value={config[key]} onChange={event => update(key, event.target.value)} /></Field>)}
      </fieldset>
      <div className="schedule-commands"><div><code>/记住 内容</code><span>明确保存一条信息</span></div><div><code>/查看记忆</code><span>查看当前用户的长期记忆</span></div><div><code>/忘记 编号</code><span>遗忘并防止旧聊天重新提取</span></div><div><code>/reset</code><span>先说明影响，二次确认后清空当前用户的上下文与长期记忆</span></div></div>
      {dirty && <p className="text-muted-foreground text-sm mt-3">策略修改保存后生效，下方记忆操作立即生效。</p>}
    </Panel>
    </Section><Section show={tabs.value !== 'settings'}><UserScopeSelector {...selection} />
    {selection.scopeId ? <UserMemory key={selection.scopeId} api={scopedApi} enabled={config.enabled} notify={notify} view={tabs.value} /> : <Panel title="用户记忆"><div className="memory-empty"><Brain size={28} /><p>选择用户后查看与管理对应记忆。</p></div></Panel>}
  </Section></div>
}

function UserMemory({ api, enabled, notify, view }) {
  const { botId } = useParams()
  const [snapshot, setSnapshot] = useState(null), [error, setError] = useState(''), [offset, setOffset] = useState(0)
  const [working, setWorking] = useState(''), [editor, setEditor] = useState(null), [draft, setDraft] = useState(initial)
  const [deleting, setDeleting] = useState(null), [sources, setSources] = useState(null), [search, setSearch] = useState('')
  const refresh = useCallback(async () => { const result = await api(`/memory?offset=${offset}`); setSnapshot(result); setError(''); return result }, [api, offset])
  useEffect(() => {
    let alive = true
    const load = () => api(`/memory?offset=${offset}`).then(result => { if (alive) { setSnapshot(result); setError('') } }).catch(e => { if (alive) setError(e.message) })
    load(); const timer = setInterval(load, 5000)
    return () => { alive = false; clearInterval(timer) }
  }, [api, offset])
  async function action(name, work, message) {
    setWorking(name)
    try { await work(); await refresh(); if (message) notify(message) }
    catch (e) { setError(e.message); notify(e.message, true) }
    finally { setWorking('') }
  }
  function edit(item) {
    setEditor(item || { id: null })
    setDraft(item ? { ...initial, ...item, due_at: localDate(item.due_at), end_at: localDate(item.end_at), expires_at: localDate(item.expires_at) } : { ...initial })
  }
  async function save(event) {
    event.preventDefault()
    if (String(draft.importance).trim() === '' || !Number.isInteger(Number(draft.importance))) { setError('重要度请填写 0–100 的整数'); return }
    const body = { category: draft.category, content: draft.content, key: draft.key, pinned: draft.pinned, importance: Number(draft.importance),
      due_at: draft.category === 'commitment' && draft.due_at ? new Date(draft.due_at).toISOString() : null,
      end_at: draft.category === 'commitment' && draft.end_at ? new Date(draft.end_at).toISOString() : null,
      expires_at: draft.expires_at ? new Date(draft.expires_at).toISOString() : null, commitment_state: draft.commitment_state }
    await action('save', async () => { await api(editor.id ? `/memory/${editor.id}` : '/memory', editor.id ? 'PUT' : 'POST', body); setEditor(null) }, '记忆已保存，后续对话使用新信息')
  }
  const index = snapshot?.index
  const indexTitle = !enabled ? '记忆未启用' : !index?.current ? '等待建立索引' : ({ ready: '索引就绪', indexing: '正在生成向量', error: '索引异常', pending: '等待建立索引' })[index?.status]
  const items = (snapshot?.items || []).filter(item => !search || item.content.includes(search) || categories[item.category]?.includes(search))
  const failed = snapshot?.jobs?.some(job => job.status === 'failed')
  return <>
    {error && <Notice alert>{error}</Notice>}
    <Section show={view === 'context'}><Panel title="本轮上下文预算" subtitle="最近一次普通聊天的选入记录，不包含聊天正文或完整提示词。输入与图片 Token 为估算值。">
      {snapshot?.context ? <><p>状态：{snapshot.context.status === 'ready' ? '已组装' : '必要内容超出预算，已阻止请求'} · {snapshot.context.model} · {at(snapshot.context.updated)}</p><p>窗口 {snapshot.context.window} · 输入预算 {snapshot.context.input_budget} · 预计输入 {snapshot.context.estimated_input ?? snapshot.context.mandatory_tokens}</p><p>输出预留 {snapshot.context.output_reserve} · 额外推理 {snapshot.context.reasoning_reserve} · 安全预留 {snapshot.context.safety_reserve}</p><p>完整历史轮次：选入 {snapshot.context.history_selected ?? 0} / {snapshot.context.history_available}，裁剪 {snapshot.context.history_dropped ?? 0}；裁剪仅影响本轮输入，不删除聊天档案。</p><div className="memory-audit">{snapshot.context.blocks.map(block => <p key={block.name}>{block.name} · {block.selected ? '已选入' : '预算不足，未选入'} · 约 {block.estimated_tokens} Token</p>)}</div></> : <p>此用户还没有普通聊天诊断记录。</p>}
      <Link className="subtle-link" to={`/bots/${botId}/qq?view=models`}>调整当前机器人的模型窗口与预留 →</Link>
    </Panel><Panel title="摘要版本与来源覆盖" subtitle="仅保留最近 12 版；更正、遗忘和到期会清除失效版本正文，来源编号只用于追溯，不代表所有来源细节都被摘要保留。" action={<Button size="sm" variant="outline" disabled={!enabled || !!working} onClick={() => action('summary', () => api('/memory/rebuild-summary', 'POST'), '已安排摘要重建；最多读取屏障后最近 240 条本人消息和确认回复')}><RefreshCw size={13} />重建摘要</Button>}>
      {(snapshot?.summary_versions || []).map(version => <details key={version.id}><summary>版本 #{version.id} · {version.valid ? '有效' : '已失效'} · {at(version.updated)} · 来源 {version.source_ids.length} 条</summary>{version.valid && <p>{version.content || '无摘要正文'}</p>}<p>来源编号：{version.source_ids.join('、') || '无（旧版或手动摘要）'}</p>{version.valid && version.working_state.map((item, n) => <p key={n}>待续：{item.content} · 来源 {item.evidence.join('、')}</p>)}{!version.valid && <p>失效原因：{version.reason}；旧正文已清理。</p>}</details>)}
      {!snapshot?.summary_versions?.length && <p>尚无摘要版本。</p>}
    </Panel></Section>
    <Section show={view === 'entries'}><Panel title="摘要与检索" subtitle="记忆原文、来源与摘要保存在本机；调用外部模型时只发送此用户范围内的资料。" action={<Button variant="ghost" size="icon-sm" aria-label="刷新记忆" onClick={() => refresh().catch(e => setError(e.message))}><RefreshCw size={14} /></Button>}>
      <div className="memory-index"><div><Badge variant="outline">{indexTitle}</Badge><span>{index?.indexed || 0} / {index?.total || 0} 条已索引</span></div><div className="action-row"><Button size="sm" variant="outline" disabled={!enabled || !!working} onClick={() => action('organize', () => api('/memory/organize', 'POST'), '已加入整理队列')}>{working === 'organize' ? <LoaderCircle size={13} className="spin" /> : <Brain size={13} />}整理最近聊天</Button><Button size="sm" variant="outline" disabled={!enabled || !!working} onClick={() => action('rebuild', () => api('/memory/rebuild', 'POST'), '已安排重建此用户的索引')}><RefreshCw size={13} />重建索引</Button></div></div>
      {index?.error && <p className="provider-test-message" role="status">{index.error}</p>}
      <div className="memory-summary"><h3>滚动对话摘要</h3><p>{snapshot?.summary || '还没有摘要。正常聊天后会自动整理，也可点击「整理最近聊天」。'}</p></div>
      {failed && <div className="memory-task-warning"><span>有整理任务失败，原始聊天已保留。</span><Button size="sm" variant="outline" disabled={!!working} onClick={() => action('retry', () => api('/memory/retry', 'POST'), '已安排重试')}>重试失败任务</Button></div>}
      {!!snapshot?.jobs?.length && <details className="memory-task-details"><summary>最近整理任务</summary>{snapshot.jobs.slice(0, 8).map(job => <div key={job.id}><span>{at(job.created)}</span><span>{({ pending: '等待整理', running: '整理中', done: '已完成', failed: '失败', canceled: '已取消旧任务' })[job.status]}</span>{job.error && <small>{job.error}</small>}</div>)}</details>}
    </Panel>
    <Panel title="长期记忆" subtitle={snapshot ? `${snapshot.owner.label} · 共 ${snapshot.total} 条有效记忆` : '正在读取…'} action={<Button size="sm" disabled={!!working} onClick={() => edit()}><Plus size={14} />添加记忆</Button>}>
      <div className="memory-search"><Search size={15} /><Input aria-label="搜索当前页记忆" placeholder="搜索当前页内容或类型" value={search} onChange={event => setSearch(event.target.value)} /></div>
      {!items.length ? <div className="memory-empty"><Brain size={28} /><p>{search ? '当前页没有匹配的记忆。' : '还没有保存长期记忆。'}</p><small>重要偏好会从真实对话中整理，也可以手动添加。</small></div> : <div className="memory-list">{items.map(item => <article className="memory-item" key={item.id}>
        <div className="memory-item-heading"><div><Badge variant="secondary">{categories[item.category]}</Badge><span>#{item.id}</span>{item.pinned && <Badge variant="outline"><Pin size={10} />固定保留</Badge>}{item.category === 'commitment' && <Badge variant="outline">{states[item.commitment_state]}</Badge>}</div><div className="action-row"><Button variant="ghost" size="icon-sm" aria-label={`编辑记忆 ${item.id}`} onClick={() => edit(item)}><Pencil size={14} /></Button><Button variant="destructive-outline" size="icon-sm" aria-label={`遗忘记忆 ${item.id}`} onClick={() => setDeleting(item)}><Trash2 size={14} /></Button></div></div>
        <p className="memory-content">{item.content}</p>
        {item.category === 'commitment' && <p className="memory-appointment">{at(item.due_at)} — {at(item.end_at)}{item.commitment_state === 'pending' && item.end_at * 1000 < Date.now() ? ' · 时间已过，未经确认履行' : ''}</p>}
        <div className="memory-item-meta"><span>重要度 {item.importance} · 更新于 {at(item.updated)}</span>{item.expires_at && <span>到期 {at(item.expires_at)}</span>}<Button size="sm" variant="ghost" disabled={!!working} onClick={() => action('sources', async () => setSources({ item, ...(await api(`/memory/${item.id}/sources`)) }))}>查看来源（{item.source_ids.length}）</Button></div>
      </article>)}</div>}
      {!!snapshot?.total && <div className="memory-pagination"><Button size="sm" variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>上一页</Button><span>{offset + 1}–{Math.min(offset + 50, snapshot.total)} / {snapshot.total}</span><Button size="sm" variant="outline" disabled={offset + 50 >= snapshot.total} onClick={() => setOffset(offset + 50)}>下一页</Button></div>}
    </Panel>
    </Section><Section show={view === 'history'}><Panel title="记忆修改记录" subtitle="最近 50 次新增、更正与遗忘；遗忘后的内容不会保留在此记录里。">
      {!snapshot?.audit?.length ? <div className="memory-empty"><History size={24} /><p>还没有记忆修改记录。</p></div> : <div className="memory-audit">{snapshot.audit.map(record => <details key={record.id}><summary><span>{({ create: '新增记忆', update: '更正记忆', forget: '遗忘记忆', expire: '记忆到期', reset: '用户确认重置', write_rejected: '自动记忆写入被拦截' })[record.action]}{record.memory_id != null ? ` #${record.memory_id}` : ''}</span><time>{at(record.at)}</time></summary>{record.before?.content && <p><b>修改前：</b>{record.before.content}</p>}{record.after?.content && <p><b>修改后：</b>{record.after.content}</p>}{record.action === 'write_rejected' && <p>{record.after?.reason === 'sensitive_credential' ? '检测到可能的敏感凭证，不写入长期记忆。' : '旧事实与新内容冲突，但缺少用户明确更正依据，未覆盖旧事实。'}</p>}{record.action === 'expire' && <p>记忆已到期，不再参与检索，摘要与近期上下文已清理。</p>}{record.action === 'reset' && <p>用户通过 /reset 二次确认，已清空上下文和全部长期记忆（{record.after?.count || 0} 条），后台聊天档案保留。</p>}{record.action === 'forget' && <p>内容已遗忘，相关旧任务与摘要已失效。</p>}</details>)}</div>}
    </Panel></Section>
    <Dialog.Root open={!!editor} onOpenChange={open => { if (!open && !working) setEditor(null) }}><Dialog.Portal><Dialog.Overlay className="sheet-overlay" /><Dialog.Content className="provider-dialog memory-dialog"><Dialog.Title>{editor?.id ? '编辑记忆' : '添加记忆'}</Dialog.Title><Dialog.Description>仅影响当前用户。保存后立即生效，并清理可能含旧信息的摘要与近期上下文。</Dialog.Description><form className="provider-form" onSubmit={save}><Field label="记忆类型" id="memory-category"><select className="provider-select" id="memory-category" disabled={!!editor?.id} value={draft.category} onChange={event => setDraft(old => ({ ...old, category: event.target.value }))}>{Object.entries(categories).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field><Field label="记忆内容" id="memory-content"><Textarea id="memory-content" autoFocus required maxLength={800} rows={4} value={draft.content} onChange={event => setDraft(old => ({ ...old, content: event.target.value }))} placeholder="例如：用户不喝咖啡，喜欢清淡的茶。" /></Field><Field label="重要度" id="memory-importance"><Input id="memory-importance" type="number" min="0" max="100" value={draft.importance} onChange={event => setDraft(old => ({ ...old, importance: event.target.value }))} /></Field><div className="toggle-row"><div><b>固定保留</b><p>优先加入对话记忆，仍受单次上下文预算限制。</p></div><Switch aria-label="固定保留记忆" checked={draft.pinned} onCheckedChange={value => setDraft(old => ({ ...old, pinned: value }))} /></div>{draft.category === 'commitment' && <><Field label="开始时间" id="memory-due" hint="按当前设备时区填写，保存时转换为带时区的具体时间。"><Input id="memory-due" type="datetime-local" required value={draft.due_at} onChange={event => setDraft(old => ({ ...old, due_at: event.target.value }))} /></Field><Field label="结束时间" id="memory-end"><Input id="memory-end" type="datetime-local" required value={draft.end_at} onChange={event => setDraft(old => ({ ...old, end_at: event.target.value }))} /></Field><Field label="约定状态" id="memory-commitment-state"><select className="provider-select" id="memory-commitment-state" value={draft.commitment_state} onChange={event => setDraft(old => ({ ...old, commitment_state: event.target.value }))}>{Object.entries(states).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field></>}<Field label="到期时间（可选）" id="memory-expiry" hint="到期后不再参与检索，留空长期保留。"><Input id="memory-expiry" type="datetime-local" value={draft.expires_at} onChange={event => setDraft(old => ({ ...old, expires_at: event.target.value }))} /></Field>{error && <p className="provider-test-message" role="alert">{error}</p>}<div className="dialog-actions"><Button type="button" variant="outline" onClick={() => setEditor(null)} disabled={!!working}>取消</Button><Button disabled={!!working}>{working === 'save' && <LoaderCircle size={14} className="spin" />}保存记忆</Button></div></form><Dialog.Close asChild><Button variant="ghost" size="icon-sm" className="dialog-close" aria-label="关闭记忆编辑" disabled={!!working}><X size={15} /></Button></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={!!deleting} onOpenChange={open => { if (!open && !working) setDeleting(null) }}><Dialog.Portal><Dialog.Overlay className="sheet-overlay" /><Dialog.Content className="bot-dialog"><Dialog.Title>遗忘这条记忆？</Dialog.Title><Dialog.Description>仅遗忘当前用户的此条记忆，清理相关摘要和近期上下文，并阻止旧聊天再次提取。原始聊天档案保留。</Dialog.Description><p className="memory-content mt-4">{deleting?.content}</p><div className="dialog-actions"><Dialog.Close asChild><Button variant="outline" disabled={!!working}>取消</Button></Dialog.Close><Button variant="destructive" disabled={!!working} onClick={() => action('delete', async () => { await api(`/memory/${deleting.id}`, 'DELETE'); setDeleting(null) }, '已遗忘此条记忆')}>确认遗忘</Button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={!!sources} onOpenChange={open => { if (!open) setSources(null) }}><Dialog.Portal><Dialog.Overlay className="sheet-overlay" /><Dialog.Content className="provider-dialog memory-dialog"><Dialog.Title>记忆来源</Dialog.Title><Dialog.Description>记忆 #{sources?.item.id}，只显示当前用户范围内的来源消息。</Dialog.Description><div className="memory-sources">{sources?.items?.length ? sources.items.map(source => <article key={source.id}><div><Badge variant="outline">{source.role === 'user' ? '用户' : '机器人'}</Badge><time>{at(source.at || source.recorded_at)}</time></div><p>{source.content}</p><Link className="subtle-link" to={`/bots/${botId}/chats?conversation=${encodeURIComponent(source.conversation_id)}&view=chat`}>查看对应聊天</Link></article>) : <p>此记忆由管理员手动添加，没有关联的聊天消息。</p>}</div><Dialog.Close asChild><Button variant="ghost" size="icon-sm" className="dialog-close" aria-label="关闭来源"><X size={15} /></Button></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>
  </>
}
