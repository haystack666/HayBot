import { useEffect, useState } from 'react'
import { ChevronRight, CircleHelp, LoaderCircle, Plus, RefreshCw, Send, Sparkles, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'

const recordStates = { generating: '正在生成', sending: '发送中', sent: '已发送', failed: '失败', skipped: '已跳过', unknown: '结果未知', pending: '等待发送', cancelled: '已取消' }
const kinds = { greeting: '定时问候', idle: '主动搭话', reminder: '一次提醒', test: '能力测试' }
const capabilityNames = { supported: '已验证', rejected: 'QQ 已拒绝', unknown: '尚未验证' }
const showTime = value => value ? new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'

export default function ProactivePage({ config, update, active, busy, dirty, api, notify, Panel, Field }) {
  const [data, setData] = useState({ contacts: [], records: [], reminders: [], reason: '', today_count: 0 })
  const [working, setWorking] = useState(''), [instruction, setInstruction] = useState('自然地关心一下近况，避免重复问候。')
  const [preview, setPreview] = useState(''), [at, setAt] = useState(''), [reminder, setReminder] = useState(''), [error, setError] = useState('')
  const disabled = active || !!working || !!busy
  const unavailable = !!working || !!busy
  const unlimited = config.daily_limit !== '' && Number(config.daily_limit) === 0
  const contact = data.contacts.find(c => c.id === config.recipient_id)
  async function refresh() { const result = await api('/proactive'); setData(result); setError('') }
  useEffect(() => {
    let mounted = true
    const load = () => api('/proactive').then(result => { if (mounted) { setData(result); setError('') } }).catch(e => { if (mounted) setError(e.message) })
    load()
    const timer = setInterval(load, 10000)
    return () => { mounted = false; clearInterval(timer) }
  }, [api])
  async function perform(name, fn) {
    setWorking(name)
    try { await fn(); if (name !== 'refresh') await refresh() } catch (e) { notify(e.message, true) } finally { setWorking('') }
  }
  function setRule(index, key, value) { update('greetings', config.greetings.map((rule, i) => i === index ? { ...rule, [key]: value } : rule)) }
  return <div className="push-layout"><div className="push-main">
    <Panel title="基本设置" subtitle="仅向选定的单聊发送，使用当前人格与最近文字上下文">
      <div className="toggle-row !pt-0"><div><b>启用主动消息</b><p>机器人停止时，自动消息一起暂停。</p></div><Switch aria-label="启用自动主动消息" checked={config.enabled} disabled={disabled} onCheckedChange={v => update('enabled', v)} /></div>
      <fieldset disabled={disabled} className="form-grid border-0 m-0 p-0 mt-5">
        <Field label="单聊接收者" id="push-recipient" hint="先在 QQ 单聊机器人，再刷新接收者。"><select id="push-recipient" value={config.recipient_id} onChange={e => update('recipient_id', e.target.value)}><option value="">请选择接收者</option>{data.contacts.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
        <Field label="时区" id="push-zone"><select id="push-zone" value={config.timezone} onChange={e => update('timezone', e.target.value)}>{['Asia/Shanghai', 'Asia/Hong_Kong', 'Asia/Tokyo', 'UTC'].map(t => <option key={t}>{t}</option>)}</select></Field>
        <Field label="活跃时段开始" id="push-start"><Input id="push-start" type="time" value={config.active_start} onChange={e => update('active_start', e.target.value)} /></Field>
        <Field label="活跃时段结束" id="push-end" hint="其余时间免打扰；起止相同表示全天。"><Input id="push-end" type="time" value={config.active_end} onChange={e => update('active_end', e.target.value)} /></Field>
        <div className="field full"><div className="toggle-row limit-toggle"><div><b>每日消息次数</b><p>问候、搭话与提醒共享额度，QQ 平台仍可能限流。</p></div><div className="flex items-center gap-2"><span className="text-xs whitespace-nowrap">不限次数</span><Switch aria-label="每日不限次数" checked={unlimited} onCheckedChange={v => update('daily_limit', v ? 0 : 2)} /></div></div>{!unlimited && <Field label="每日自动消息上限" id="push-limit" hint="正整数为次数上限，0 表示不限次数。"><Input id="push-limit" type="number" min="0" value={config.daily_limit} onChange={e => update('daily_limit', e.target.value)} /></Field>}</div>
        <Field label="冷却时间（分钟）" id="push-cooldown" hint="0–1440 分钟，0 表示不冷却。"><Input id="push-cooldown" type="number" min="0" max="1440" value={config.cooldown_minutes} onChange={e => update('cooldown_minutes', e.target.value)} /></Field>
        <Field label="未回应暂停（次）" id="push-unanswered" hint="1–20 次；收到新单聊后恢复。"><Input id="push-unanswered" type="number" min="1" max="20" value={config.unanswered_limit} onChange={e => update('unanswered_limit', e.target.value)} /></Field>
      </fieldset>
    </Panel>
    <Panel title="主动搭话" subtitle="在随机间隔后自然地发起聊天">
      <div className="toggle-row !pt-0"><div><b>启用主动搭话</b><p>正在聊天或回复时跳过；连续未回应时暂停。</p></div><Switch aria-label="主动搭话" checked={config.idle_enabled} disabled={disabled} onCheckedChange={v => update('idle_enabled', v)} /></div>
      <fieldset disabled={disabled} className="form-grid border-0 m-0 p-0 mt-5"><Field label="最短间隔（分钟）" id="push-idle-min" hint="5–1440 分钟（最长 24 小时）。"><Input id="push-idle-min" type="number" min="5" max="1440" value={config.idle_min_minutes} onChange={e => update('idle_min_minutes', e.target.value)} /></Field><Field label="最长间隔（分钟）" id="push-idle-max" hint="5–1440 分钟，不能小于最短间隔。"><Input id="push-idle-max" type="number" min="5" max="1440" value={config.idle_max_minutes} onChange={e => update('idle_max_minutes', e.target.value)} /></Field></fieldset>
    </Panel>
    <details className="greetings-section"><summary><span>定时问候<small>{config.greetings.length ? config.greetings.map(rule => rule.name).join(' · ') : '尚未添加'}</small></span><ChevronRight size={16} /></summary><div className="greetings-content"><p className="push-hint !mt-0 !mb-5">按所选时区每天触发，错过时段后不集中补发。</p><fieldset disabled={disabled} className="space-y-4 border-0 m-0 p-0">{config.greetings.map((rule, index) => <div className="push-rule" key={rule.id}>
      <div className="push-rule-heading"><Switch aria-label={rule.name + '开关'} checked={rule.enabled} onCheckedChange={v => setRule(index, 'enabled', v)} /><Input aria-label="问候名称" value={rule.name} maxLength={30} onChange={e => setRule(index, 'name', e.target.value)} /><Button variant="ghost" size="icon" aria-label={'删除' + rule.name} onClick={() => update('greetings', config.greetings.filter((_, i) => i !== index))}><Trash2 size={14} /></Button></div>
      <div className="form-grid"><Field label="发送时间" id={'greeting-time-' + rule.id}><Input id={'greeting-time-' + rule.id} type="time" value={rule.time} onChange={e => setRule(index, 'time', e.target.value)} /></Field><Field label="内容方式" id={'greeting-mode-' + rule.id}><select id={'greeting-mode-' + rule.id} value={rule.mode} onChange={e => setRule(index, 'mode', e.target.value)}><option value="generated">按人格生成</option><option value="fixed">固定文字</option></select></Field><Field label={rule.mode === 'generated' ? '本次问候要求' : '消息内容'} full id={'greeting-content-' + rule.id}><Textarea id={'greeting-content-' + rule.id} rows={2} value={rule.content} maxLength={500} onChange={e => setRule(index, 'content', e.target.value)} /></Field></div>
    </div>)}<Button variant="outline" disabled={config.greetings.length >= 8} onClick={() => update('greetings', [...config.greetings, { id: Date.now().toString(36) + Math.random().toString(36).slice(2, 8), name: '定时问候', time: '12:00', enabled: true, mode: 'generated', content: '简短自然地问候一下。' }])}><Plus size={14} />添加定时问候</Button></fieldset></div></details>
    <Panel title="内容预览" subtitle="生成示例但不发送，生成用量计入 Token 统计">
      <Textarea aria-label="主动消息预览要求" rows={2} maxLength={500} value={instruction} onChange={e => setInstruction(e.target.value)} placeholder="希望它主动说些什么？" />
      <Button className="mt-4" variant="outline" disabled={unavailable || dirty || !contact || !instruction.trim()} onClick={() => perform('preview', async () => { const result = await api('/proactive/preview', 'POST', { instruction }); setPreview(result.content) })}>{working === 'preview' ? <LoaderCircle size={14} className="spin" /> : <Sparkles size={14} />}生成预览</Button>
      {preview && <div className="push-preview mt-4">{preview}</div>}
    </Panel>
    <Panel title="一次性提醒" subtitle="按指定时间发送固定文字">
      <form className="space-y-4" onSubmit={e => { e.preventDefault(); perform('reminder', async () => { await api('/proactive/reminders', 'POST', { at: new Date(at).toISOString(), content: reminder }); setAt(''); setReminder(''); notify('提醒已添加') }) }}>
        <div className="form-grid"><Field label="提醒时间（设备时区）" id="reminder-at"><Input id="reminder-at" type="datetime-local" required value={at} onChange={e => setAt(e.target.value)} /></Field><Field label="提醒内容" id="reminder-content"><Input id="reminder-content" required maxLength={500} value={reminder} onChange={e => setReminder(e.target.value)} placeholder="例如：拿快递" /></Field></div>
        <Button type="submit" variant="outline" disabled={unavailable || dirty || !contact || !at || !reminder.trim()}><Plus size={14} />添加提醒</Button>
      </form>
      <p className="push-hint">受总开关、连接、活跃时段与日上限约束；超过设定时间 5 分钟后不补发。</p>
      <div className="push-list">{data.reminders.length ? data.reminders.slice(0, 20).map(r => <div className="push-item" key={r.id}><div><b>{r.content}</b><p>{showTime(r.at)} · {recordStates[r.status]}{r.detail ? ' · ' + r.detail : ''}</p></div>{r.status === 'pending' && <Button variant="ghost" size="icon" aria-label={'取消提醒 ' + r.content} disabled={unavailable} onClick={() => perform('cancel', () => api('/proactive/reminders/' + r.id, 'DELETE'))}><Trash2 size={14} /></Button>}</div>) : <div className="empty">暂无提醒</div>}</div>
    </Panel>
  </div><aside className="push-aside" aria-label="推送状态与记录">
    <Panel title="推送状态" action={<Badge variant="secondary">{capabilityNames[contact?.capability || 'unknown']}</Badge>}>
      <dl className="stat-list"><div><dt>今日发送</dt><dd>{data.today_count} 次</dd></div><div><dt>每日上限</dt><dd>{unlimited ? '不限次数' : config.daily_limit === '' ? '待填写' : `${config.daily_limit} 次`}</dd></div><div><dt>当前状态</dt><dd>{data.busy ? '处理中' : data.reason ? '已暂停' : '等待触发'}</dd></div></dl>
      <p className="push-hint">{data.busy ? '正在生成或发送消息' : data.reason || '等待下一次触发'}</p>
      {contact?.next_idle > 0 && <p className="push-hint">下次搭话候选：{showTime(contact.next_idle)}</p>}
      <div className="action-row mt-5"><Button variant="outline" disabled={unavailable || dirty || !active || !contact} onClick={() => perform('test', async () => { const result = await api('/proactive/test', 'POST', { recipient_id: config.recipient_id }); setData(result); const record = result.records.find(item => item.kind === 'test' && item.recipient === config.recipient_id); notify(record?.detail || '请查看发送记录', record?.status !== 'sent') })}>{working === 'test' ? <LoaderCircle size={14} className="spin" /> : <Send size={14} />}发送测试消息</Button><Button variant="ghost" disabled={unavailable} onClick={() => perform('refresh', refresh)}><RefreshCw size={14} />刷新状态</Button></div>
      <p className="push-hint">测试会真实发送给接收者，每分钟最多一次。请先保存并启动机器人。</p>
      {contact && <p className="push-hint">最近互动：{showTime(contact.last_received)}</p>}
      {contact?.capability_detail && <p className="push-hint">{contact.capability_detail}<br />验证时间：{showTime(contact.checked_at)}</p>}
      {error && <p className="login-error" role="alert">状态刷新失败：{error}</p>}
    </Panel>
    <Panel title="发送记录" subtitle="实际结果与跳过原因"><div className="push-records">{data.records.length ? data.records.map(r => <div className="push-item" key={r.id}><div className="push-record-title"><b>{kinds[r.kind]}</b><Badge variant="outline">{recordStates[r.status]}</Badge></div><p>{showTime(r.created)}</p><p>{r.detail || '处理中'}</p></div>) : <div className="empty">暂无发送记录</div>}</div></Panel>
    <div className="notice"><CircleHelp size={16} /><div>主动推送权限以 QQ 接口为准。被拒绝后自动暂停，需手动重新测试；结果未知的消息不会自动重发。</div></div>
  </aside></div>
}
