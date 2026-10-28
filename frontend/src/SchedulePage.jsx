import { usePageTabs, Section } from './components/PageTabs'
import { useCallback, useEffect, useState } from 'react'
import { Dialog } from 'radix-ui'
import { CalendarDays, Clock3, LoaderCircle, MapPin, RefreshCw, Shirt, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { Field, Notice, Panel } from './components/console'
import ScheduleChanges from './ScheduleChanges'
import UserScopeSelector, { useUserScopes } from './UserScopeSelector'
import { scopePath } from './lib/memory-config'

const at = value => value ? new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'

export default function SchedulePage(props) {
  const selection = useUserScopes(props.api)
  const scopedApi = useCallback((path, method, body) => props.api(scopePath(path, selection.scopeId), method, body), [props.api, selection.scopeId])
  return <div className="page-stack"><UserScopeSelector {...selection} /><ScopedSchedule key={selection.scopeId} {...props} scopeId={selection.scopeId} api={scopedApi} /></div>
}

function ScopedSchedule({ config, update, active, busy, dirty, api, notify, model, scopeId }) {
  const [snapshot, setSnapshot] = useState(null)
  const [error, setError] = useState('')
  const [generating, setGenerating] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)
  const refresh = useCallback(async () => {
    if (!scopeId) return
    const result = await api('/schedule')
    setSnapshot(result)
    setError('')
  }, [api, scopeId])
  useEffect(() => {
    if (!scopeId) return
    let alive = true
    const load = async () => {
      try { const result = await api('/schedule'); if (alive) { setSnapshot(result); setError('') } }
      catch (e) { if (alive) setError(e.message) }
    }
    load()
    const interval = setInterval(load, 5000)
    return () => { alive = false; clearInterval(interval) }
  }, [api, scopeId])
  async function generate(reset = false) {
    setGenerating(true)
    try {
      setSnapshot(await api(reset ? '/schedule/reset' : '/schedule/generate', 'POST'))
      setError('')
      notify(reset ? '当日日程已重置，新安排已生效' : '当日日程已生成')
    } catch (e) {
      setError(e.message)
      notify(e.message, true)
      refresh().catch(() => {})
    } finally { setGenerating(false) }
  }
  const plan = snapshot?.schedule
  const working = generating || snapshot?.busy || snapshot?.updating
  const current = plan?.activities[snapshot.current_index]
  const minute = snapshot?.now?.slice(11, 16) || '00:00'
  const tabs = usePageTabs([['today','今日日程'],['history','历史与变更'],['settings','日程设置']])
  return <div className="schedule-page space-y-5">
    {tabs.tabs}<Section show={tabs.value === 'settings'}><Panel title="角色的日常生活" subtitle="生活设定作为生成模板；每位用户拥有独立日程、穿着、事件与约定。">
      <div className="toggle-row !pt-0"><div><b>启用每日日程</b><p>让活动、穿着和已经发生的事件参与聊天；对话中确认的改约会实时同步到日程，无需报出具体时刻。</p></div><Switch aria-label="启用每日日程" checked={config.enabled} disabled={active || !!busy} onCheckedChange={value => update('enabled', value)} /></div>
      <fieldset disabled={active || !!busy} className="form-grid border-0 m-0 p-0 mt-5">
        <Field label="生活设定" id="schedule-premise" full hint="填写身份、工作日与周末安排、作息和穿衣偏好。人格沿用「身份与私聊」，模型沿用当前 Bot 的选择。">
          <Textarea id="schedule-premise" rows={5} maxLength={6000} value={config.premise} onChange={e => update('premise', e.target.value)} placeholder="例如：经管系大一学生，周一到周五在学校上课，住校；周末回家。喜欢早起，晚上去图书馆，穿衣偏休闲。" />
        </Field>
        <Field label="日程时区" id="schedule-timezone" full hint="按此时区每天 00:00 更新；默认北京时间，与主动消息时区分别配置。">
          <Input id="schedule-timezone" list="schedule-timezones" value={config.timezone} onChange={e => update('timezone', e.target.value)} placeholder="Asia/Shanghai" />
          <datalist id="schedule-timezones"><option value="Asia/Shanghai" /><option value="Asia/Tokyo" /><option value="Europe/London" /><option value="America/New_York" /><option value="UTC" /></datalist>
        </Field>
      </fieldset>
      <p className="schedule-model">生成模型：<span>{model || '请先选择模型'}</span></p>
      <div className="schedule-commands"><div><code>/查看日程</code><span>在 QQ 查看今天的完整安排</span></div><div><code>/重置日程</code><span>重新生成今天的日程并立即生效</span></div></div>
    </Panel>
    </Section>{dirty && <Notice>请先保存生活设定，再生成或重置日程。已有日程按保存的配置运行。</Notice>}
    {(error || snapshot?.error) && <Notice alert>{error || snapshot.error}。已有日程会保留，可检查模型后重试。</Notice>}
    <Section show={tabs.value === 'today'}><Panel title="今日日程" subtitle={snapshot ? `${snapshot.date} · ${snapshot.timezone} · 当前 ${minute}` : '正在读取当天安排…'} action={<div className="action-row schedule-actions">
      <Button variant="outline" size="sm" disabled={working} onClick={() => refresh().catch(e => setError(e.message))} aria-label="刷新日程"><RefreshCw size={14} /></Button>
      <Button size="sm" variant={plan ? 'outline' : 'default'} disabled={!scopeId || !config.enabled || dirty || working || !!busy || !snapshot} onClick={() => plan ? setConfirmReset(true) : generate()}>
        {working ? <LoaderCircle size={14} className="spin" /> : plan ? <RefreshCw size={14} /> : <Sparkles size={14} />}
        {working ? '正在生成…' : plan ? '重置当日日程' : '生成当日日程'}
      </Button>
    </div>}>
      {working && <div className="schedule-progress" role="status"><LoaderCircle size={15} className="spin" />{snapshot?.updating ? '正在同步对话中确认的安排…' : '正在调用模型生成完整日程，慢速模型可能需要几分钟。'}</div>}
      {!plan ? <div className="schedule-empty"><CalendarDays size={30} strokeWidth={1.3} /><h3>今天的故事，还没有展开</h3><p>{!scopeId ? '请先选择用户，或通过 QQ 与机器人互动建立用户范围。' : !config.enabled ? '填写生活设定，开启并保存每日日程后，即可生成今天的安排。' : '点击「生成当日日程」，或等待后台自动生成。'}</p></div> : <>
        {!snapshot.enabled && <Notice>每日日程已关闭。下方保留的安排不会参与聊天或自动更新。</Notice>}
        <div className="schedule-day-heading"><div><h3>{plan.summary}</h3><p>生成于 {at(plan.generated_at)}{plan.updated_at ? ` · 最近调整 ${at(plan.updated_at)}` : ''}</p></div><Badge variant="secondary">{plan.activities.length} 段活动 · {plan.events.length} 个事件</Badge></div>
        {snapshot.continuity && <Notice><b>已确认的跨日安排 · {snapshot.continuity.target_date}</b><p>{snapshot.continuity.reason}</p><p>{snapshot.continuity.activities.map(item => `${item.start}–${item.end} ${item.activity} · ${item.location}`).join('；')}</p><small>{snapshot.continuity.time_inferred ? '分钟时间由系统推定，实际进展会随对话调整。' : '按对话中确认的时间衔接。'}</small></Notice>}
        {!!snapshot.change_count && <a className="subtle-link mb-4" href="#schedule-changes">查看今天 {snapshot.change_count} 次对话调整</a>}
        <div className="schedule-attire"><div><Shirt size={16} /><div><b>今日主要穿着</b><p>{plan.outfit}</p></div></div><div><Sparkles size={16} /><div><b>发型与仪容</b><p>{plan.appearance}</p></div></div></div>
        {current && <div className="schedule-now"><Clock3 size={17} /><div><b>此刻 · {current.activity}</b><p>{current.location} · {current.outfit}</p></div><Badge variant="outline">进行中</Badge></div>}
        <ol className="schedule-timeline" aria-label="当天活动时间线">{plan.activities.map((item, index) => {
          const selected = index === snapshot.current_index
          const events = plan.events.filter(event => event.time >= item.start && event.time < item.end)
          const adjusted = plan.dialogue_ranges?.some(range => range.start < item.end && range.end > item.start) || snapshot.changes?.some(change => change.current_generation && change.diff.activities_after.some(patch => patch.start < item.end && patch.end > item.start && patch.activity === item.activity && patch.location === item.location && patch.outfit === item.outfit))
          return <li className={`schedule-activity ${selected ? 'is-current' : ''}`} key={`${item.start}-${item.end}`}>
            <div className="schedule-time"><time>{item.start}</time><span>{item.end}</span></div>
            <div className="schedule-activity-content"><div className="schedule-activity-title"><h4>{item.activity}</h4>{selected && <Badge variant="secondary">现在</Badge>}{adjusted && <Badge variant="outline">对话调整</Badge>}</div><p className="schedule-location"><MapPin size={12} />{item.location}</p><p className="schedule-outfit">穿着：{item.outfit}</p>
              {events.map((event, eventIndex) => <div className="schedule-event" key={`${event.time}-${eventIndex}`}><Sparkles size={12} /><div><span>{event.time} · {event.time <= minute ? '已发生' : '待发生'}</span><p>{event.event}</p></div></div>)}
            </div>
          </li>
        })}</ol>
      </>}
      {snapshot?.enabled && <p className="schedule-footer">下次更新：{new Date(snapshot.next_refresh * 1000).toLocaleString('zh-CN', { timeZone: snapshot.timezone, hour12: false })}（{snapshot.timezone}）。平台运行期间自动更新，重启后补齐当天日程。随机事件仅在发生后进入聊天上下文。</p>}
    </Panel>
    {!!plan?.commitment_conflicts?.length && <Notice alert>以下约定时间有冲突，请在记忆页面核对：{plan.commitment_conflicts.map(item => item.content).join('；')}</Notice>}
    </Section><Section show={tabs.value === 'history'}><ScheduleChanges {...{snapshot, api, notify}} /></Section>
    <Dialog.Root open={confirmReset} onOpenChange={setConfirmReset}><Dialog.Portal><Dialog.Overlay className="sheet-overlay" /><Dialog.Content className="bot-dialog"><Dialog.Title>重置当日日程</Dialog.Title><Dialog.Description>重新生成今天的全部安排、穿着和随机事件。成功后立即替换，生成失败会保留原日程；聊天记录不受影响。</Dialog.Description><div className="action-row mt-6"><Dialog.Close asChild><Button variant="outline">取消</Button></Dialog.Close><Button disabled={working || dirty} onClick={() => { setConfirmReset(false); generate(true) }}>重新生成</Button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>
}
