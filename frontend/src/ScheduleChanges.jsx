import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { History, LoaderCircle, MessageSquare } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Panel } from './components/console'
import { mergeScheduleChanges } from './lib/schedule-changes'

function Activities({ items }) {
  return items.map((item, index) => <div className="schedule-diff-activity" key={`${item.start}-${index}`}><time>{item.start}–{item.end}</time><b>{item.activity}</b><p>{item.location} · {item.outfit}</p></div>)
}

function Continuity({ value, empty = '无跨日承接安排' }) {
  return value ? <div className="schedule-event-diff"><b>{value.target_date} · 跨日承接</b><Activities items={value.activities} /></div> : <p className="schedule-diff-text">{empty}</p>
}

export default function ScheduleChanges({ snapshot, api, notify }) {
  const { botId } = useParams()
  const [older, setOlder] = useState([])
  const [cursor, setCursor] = useState(undefined)
  const [loading, setLoading] = useState(false)
  useEffect(() => { setOlder([]); setCursor(undefined) }, [snapshot?.date])
  const generation = snapshot?.schedule?.generation_id || snapshot?.schedule?.revision
  useEffect(() => {
    setOlder(previous => mergeScheduleChanges(previous, snapshot?.changes || [], snapshot?.date, generation))
  }, [snapshot?.changes, snapshot?.date, generation])
  const records = mergeScheduleChanges(older, snapshot?.changes || [], snapshot?.date, generation)
  const before = cursor === undefined ? snapshot?.changes_next_before : cursor
  async function loadOlder() {
    setLoading(true)
    try {
      const result = await api(`/schedule/changes?day=${encodeURIComponent(snapshot.date)}&before=${before}`)
      setOlder(previous => [...previous, ...result.items])
      setCursor(result.next_before)
    } catch (error) { notify(error.message, true) }
    finally { setLoading(false) }
  }
  return <div id="schedule-changes"><Panel title="对话引起的修改" subtitle="自动同步已确认的聊天约定，保留修改前后与触发对话。" action={<Badge variant="secondary">今天 {snapshot?.change_count || 0} 次</Badge>}>
    {!records.length ? <div className="schedule-audit-empty"><History size={21} /><p>今天还没有因对话修改日程。</p><small>例如：聊到“今晚留下陪我”，角色答应后会自动调整安排，无需报出具体时间。</small></div> : <div className="schedule-audit-list">{records.map((change, index) => <article className="schedule-change" key={change.id}>
      <div className="schedule-change-meta"><time>{new Date(change.at * 1000).toLocaleTimeString('zh-CN', { timeZone: change.timezone, hour12: false })}</time><span>{change.sender_name}</span><Badge variant={change.current_generation ? 'secondary' : 'outline'}>{change.current_generation ? '对话调整' : '此前版本'}</Badge></div>
      <h3>{change.reason}</h3>
      {change.diff.method === 'semantic' && <div className="schedule-change-meta"><Badge variant="outline">对话语义识别</Badge><Badge variant="outline">{change.diff.time_inferred ? '时间由系统推定' : '沿用明确约定的时间'}</Badge></div>}
      {change.diff.evidence && <p className="schedule-diff-text">确认依据：{change.diff.evidence}</p>}
      {change.source_content && <blockquote><span>触发消息</span><p>{change.source_content}</p></blockquote>}
      <details open={index === 0}><summary>查看修改前后</summary><div className="schedule-diff-grid"><div><h4>原安排</h4><Activities items={change.diff.activities_before} />{['summary', 'outfit', 'appearance'].map(field => change.diff[`${field}_before`] && <p className="schedule-diff-text" key={field}>{({summary:'概述',outfit:'主要穿着',appearance:'仪容'})[field]}：{change.diff[`${field}_before`]}</p>)}</div><div><h4>调整后</h4><Activities items={change.diff.activities_after} />{['summary', 'outfit', 'appearance'].map(field => change.diff[`${field}_after`] && <p className="schedule-diff-text" key={field}>{({summary:'概述',outfit:'主要穿着',appearance:'仪容'})[field]}：{change.diff[`${field}_after`]}</p>)}</div></div>
        {!!change.diff.events_removed.length && <div className="schedule-event-diff"><b>取消的待发生事件</b>{change.diff.events_removed.map((event, index) => <p key={index}>{event.time} · {event.event}</p>)}</div>}
        {!!change.diff.events_added.length && <div className="schedule-event-diff"><b>新增事件</b>{change.diff.events_added.map((event, index) => <p key={index}>{event.time} · {event.event}</p>)}</div>}
        {Object.hasOwn(change.diff, 'continuity_after') && <div className="schedule-diff-grid"><div><h4>原跨日安排</h4><Continuity value={change.diff.continuity_before} /></div><div><h4>调整后跨日安排</h4><Continuity value={change.diff.continuity_after} empty="已取消跨日承接" /></div></div>}
      </details>
      {change.conversation_id && <Link className="subtle-link" to={`/bots/${botId}/chats?conversation=${encodeURIComponent(change.conversation_id)}&view=chat`}><MessageSquare size={12} />查看触发聊天</Link>}
    </article>)}</div>}
    {before && <Button variant="outline" size="sm" className="mt-4" disabled={loading} onClick={loadOlder}>{loading && <LoaderCircle size={13} className="spin" />}查看更早修改</Button>}
  </Panel></div>
}
