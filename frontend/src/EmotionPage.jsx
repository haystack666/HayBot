import { useCallback, useEffect, useState } from 'react'
import { Heart, RefreshCw, Pause, Play, RotateCcw } from 'lucide-react'
import UserScopeSelector, { useUserScopes } from './UserScopeSelector'
import { Panel, Field, Notice } from './components/console'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { usePageTabs } from './components/PageTabs'
import './emotion.css'

const labels = { valence: '愉悦度', energy: '精力', tension: '紧张度', familiarity: '熟悉程度', trust: '信任', comfort: '表达舒适度' }
const numbers = [
  ['intensity', '整体影响强度', 0, 1, .1, '0 表示不影响表达；1 为完整的有界影响。'],
  ['half_life_hours', '情绪恢复半衰期（小时）', .25, 168, .25, '离线和重启期间同样衰减；关系状态不随沉默扣分。'],
  ['relationship_rate', '关系变化倍率', 0, 2, .1, '多维、缓慢变化；不是消息数量积分，也不改变关系身份。'],
  ['baseline_valence', '基线愉悦度', -100, 100, 1], ['baseline_energy', '基线精力', 0, 100, 1],
  ['baseline_tension', '基线紧张度', 0, 100, 1],
  ['event_cooldown_minutes', '同类事件冷却（分钟）', 1, 1440, 1], ['daily_event_limit', '每日有效事件上限', 1, 100, 1],
]
const switches = [['affect_tone', '影响回复语气'], ['affect_actions', '影响括号动作'], ['affect_voice', '影响语音风格'],
  ['affect_proactive', '影响主动搭话节奏'], ['use_schedule', '参考已保存的角色日程精力']]
const at = value => new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })

export default function EmotionPage({ api, config, update, active, dirty, notify }) {
  const scopes = useUserScopes(api), { scopeId } = scopes
  const { value: view, tabs } = usePageTabs([['state', '当前状态'], ['events', '证据与变更'], ['settings', '策略设置']])
  const [snapshot, setSnapshot] = useState(null), [error, setError] = useState(''), [working, setWorking] = useState(false)
  const [adjustment, setAdjustment] = useState({}), [sources, setSources] = useState(null)
  const scoped = useCallback((path = '', method = 'GET', body) => api(`/emotion${path}?scope_id=${encodeURIComponent(scopeId)}`, method, body), [api, scopeId])
  const refresh = useCallback(async () => {
    if (!scopeId) return
    const result = await scoped(); setSnapshot(result); setError(''); return result
  }, [scopeId, scoped])
  useEffect(() => {
    let alive = true
    setSnapshot(null); setSources(null); setAdjustment({}); setError('')
    if (scopeId) scoped().then(result => { if (alive) setSnapshot(result) }).catch(e => { if (alive) setError(e.message) })
    return () => { alive = false }
  }, [scopeId, scoped])
  async function mutate(path, body, text) {
    setWorking(true)
    try { setSnapshot(await scoped(path, 'POST', body)); setSources(null); notify(text) }
    catch (e) { notify(e.message, true) }
    finally { setWorking(false) }
  }
  const disabled = working || !scopeId || dirty
  return <div className="page-stack emotion-page">{tabs}
    <Notice>情感是可解释的角色表达状态，不代表真实感受。不会改变身份、权限、事实或发送限额。语音仍由独立 TTS 开关和触发策略决定。</Notice>
    {view !== 'settings' && <UserScopeSelector {...scopes} />}
    {error && <Notice alert>{error}</Notice>}
    {view === 'settings' ? <Panel title="情感策略" subtitle="情绪与衰减、关系与修复、动作语音一致性、生活与主动互动。修改配置前请停止机器人。">
      <div className="emotion-switch"><label htmlFor="emotion-enabled">启用情感系统</label><Switch id="emotion-enabled" checked={config.enabled} disabled={active} onCheckedChange={v => update('enabled', v)} /></div>
      <div className="form-grid">{numbers.map(([key, label, min, max, step, hint]) => <Field key={key} id={`emotion-${key}`} label={label} hint={hint}><Input id={`emotion-${key}`} type="number" min={min} max={max} step={step} value={config[key]} disabled={active} onChange={e => update(key, e.target.value === '' ? '' : Number(e.target.value))} /></Field>)}</div>
      {switches.map(([key, label]) => <div className="emotion-switch" key={key}><label htmlFor={`emotion-${key}`}>{label}</label><Switch id={`emotion-${key}`} checked={config[key]} disabled={active} onCheckedChange={v => update(key, v)} /></div>)}
      <p className="subtitle">情绪随时间回到基线；暂停仅暂停事件变化，时间衰减仍运行。主动互动联动只会在既定搭话间隔内适度延后，免打扰、额度和连续未回复暂停始终优先。支持的 TTS 接收风格提示与轻微语速调整，不支持时回退普通语音。</p>
    </Panel> : !snapshot ? <Panel title="情感状态"><p>{scopeId ? '正在读取…' : '与机器人互动后，可在这里选择用户查看独立状态。'}</p></Panel> : <>
      <div className="emotion-status"><Badge variant="outline">{snapshot.enabled ? '系统已启用' : '系统未启用'}</Badge><Badge variant="outline">{snapshot.control.paused ? '已暂停事件变化' : '事件变化运行中'}</Badge><Badge variant="outline">{snapshot.scope_type === 'private_relationship' ? '私聊关系' : '群聊公开表达 · 不读私聊关系'}</Badge><Button size="sm" variant="ghost" disabled={working} onClick={() => refresh().catch(e => setError(e.message))}><RefreshCw size={14} />刷新</Button></div>
      {view === 'state' ? <>
        <Panel title={snapshot.style.name} subtitle="短期情绪与长期关系分别计算；语音和动作沿用同一风格。数值仅用于后台诊断。" action={<Heart size={19} />}>
          {!!snapshot.drift_warnings?.length && <Notice>长期状态接近边界：{snapshot.drift_warnings.map(key => labels[key]).join('、')}。建议查看证据记录并按需校正；系统不会据此升级关系。</Notice>}
          <div className="emotion-metrics">{Object.entries(labels).map(([key, label]) => <div key={key}><span>{label}</span><strong>{snapshot.effective[key].toFixed(1)}</strong><meter aria-label={label} min={key === 'valence' ? -100 : 0} max="100" value={snapshot.effective[key]} /><small>基线 {snapshot.baseline[key]} · 偏移 {snapshot.drift[key] >= 0 ? '+' : ''}{snapshot.drift[key]}</small></div>)}</div>
          <p className="subtitle">{snapshot.identity_policy}。{snapshot.life.planned_activity ? `日程参考：${snapshot.life.planned_activity}；精力偏移 ${snapshot.life.energy_offset}，不代表已经执行。` : '当前无有效日程精力偏移。'}</p>
        </Panel>
        <div className="two-column"><Panel title="情感连续性" subtitle="道歉不会一键消除误会；修复需要独立的澄清证据。">
          {!snapshot.threads.length && <p>没有未完成或已记录的误会线索。</p>}{snapshot.threads.map(t => <p key={t.event_id}>事件 #{t.event_id} · {({ unresolved: '待澄清', repairing: '修复中', resolved: '已修复' })[t.state]} · {at(t.at)}</p>)}
          {snapshot.boundaries.map(b => <p key={b.event_id}>明确边界：{b.quote}</p>)}
        </Panel><Panel title="人工校正" subtitle="校正会写入证据日志，可撤回；不修改人格、记忆或关系身份。群聊只校正公开表达，不修改私聊关系。">
          <form onSubmit={e => { e.preventDefault(); if (Object.keys(adjustment).length) mutate('/adjust', adjustment, '情感状态已校正') }}><div className="form-grid">{Object.entries(labels).filter(([key]) => snapshot.scope_type === 'private_relationship' || ['valence','energy','tension'].includes(key)).map(([key, label]) => <Field key={key} id={`adjust-${key}`} label={label}><Input id={`adjust-${key}`} type="number" min={key === 'valence' ? -100 : 0} max="100" step=".1" placeholder={String(snapshot.state[key])} value={adjustment[key] ?? ''} onChange={e => setAdjustment(v => { const next = { ...v }; if (e.target.value === '') delete next[key]; else next[key] = Number(e.target.value); return next })} /></Field>)}</div><Button disabled={disabled || !Object.keys(adjustment).length}>保存校正</Button></form>
        </Panel></div>
        <Panel title="变化控制" subtitle="重置只清理当前用户的情感影响，不删除聊天、记忆或其他用户的数据；旧证据不会自动重新计分。"><div className="action-row"><Button variant="outline" disabled={disabled} onClick={() => mutate('/pause', { paused: !snapshot.control.paused }, snapshot.control.paused ? '已恢复事件变化' : '已暂停事件变化')}>{snapshot.control.paused ? <Play size={14} /> : <Pause size={14} />}{snapshot.control.paused ? '恢复变化' : '暂停变化'}</Button><Button variant="destructive-outline" disabled={disabled} onClick={() => { if (window.confirm('重置当前用户的情感状态、关系影响和待续线索？聊天和记忆不会删除。')) mutate('/reset', undefined, '已重置当前用户情感状态') }}><RotateCcw size={14} />重置当前用户</Button></div></Panel>
      </> : <>
        <Panel title="事件证据与状态变更" subtitle="最近 100 条；事件幅度由程序限制，不由模型自由打分。撤回后重算当前状态，历史前后值只表示当时结果。">
          {!snapshot.events.length && <p>尚无事件。启用后，仅有明确证据的互动才会产生有界变化。</p>}
          <div className="emotion-events">{snapshot.events.map(event => <article key={event.id}><div className="emotion-event-heading"><strong>#{event.id} {event.label}</strong><Badge variant="outline">{event.status === 'active' ? '有效' : '已撤回'}</Badge><time>{at(event.at)}</time></div>{event.quote && <blockquote>{event.quote}</blockquote>}<small>置信度 {Math.round(event.confidence * 100)}% · 来源 {event.source_ids.join('、') || '管理员操作'}{event.reason && ` · ${event.reason}`}</small><details><summary>查看状态增量与前后值</summary><pre>{JSON.stringify({ delta: event.delta, before: event.before_state, after: event.after_state }, null, 2)}</pre></details><div className="action-row">{!!event.source_ids.length && event.status === 'active' && <Button variant="ghost" size="sm" onClick={() => scoped(`/events/${event.id}/sources`).then(result => setSources({ id: event.id, ...result })).catch(e => notify(e.message, true))}>查看原始证据</Button>}{event.status === 'active' && !['pause', 'resume', 'reset'].includes(event.kind) && <Button size="sm" variant="outline" disabled={disabled} onClick={() => { if (window.confirm('撤回此事件并重算状态？')) mutate(`/events/${event.id}/retract`, undefined, '事件已撤回并重算') }}>撤回影响</Button>}</div></article>)}</div>
        </Panel>
        {sources && <Panel title={`事件 #${sources.id} 的原始证据`} action={<Button variant="ghost" size="sm" onClick={() => setSources(null)}>收起</Button>}>{sources.items.map(source => <p key={source.id}>#{source.id} · {source.content}</p>)}{!sources.items.length && <p>来源已撤回或不再可用。</p>}</Panel>}
        <Panel title="已确认回复的表达记录" subtitle="仅在 QQ 确认送达后记录，不把机器人自己生成的表达反复累加为情感证据。">{snapshot.uses.length ? snapshot.uses.map(item => <p key={item.id}>{at(item.at)} · {item.style.name} · 回复来源 {item.source_ids.join('、')}</p>) : <p>暂无已确认回复记录。</p>}</Panel>
      </>}
    </>}
  </div>
}
