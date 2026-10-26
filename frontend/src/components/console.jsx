import { CircleHelp } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'

export function Brand() {
  return <div className="brand"><span className="brand-mark" aria-hidden="true">H</span><strong className="brand-name">HayBot</strong></div>
}

export function Panel({ title, subtitle, children, action, className = '' }) {
  return <Card className={`panel ${className}`}><div className="panel-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div><div className="panel-content">{children}</div></Card>
}

export function Field({ label, id, hint, full, children }) {
  return <div className={`field ${full ? 'full' : ''}`}><Label htmlFor={id}>{label}</Label>{children}{hint && <small>{hint}</small>}</div>
}

export function Notice({ children, alert = false }) {
  return <div className="notice" role={alert ? 'alert' : undefined}><CircleHelp size={16} /><div>{children}</div></div>
}

export function Logs({ logs, limit = 100 }) {
  if (!logs.length) return <div className="empty">暂无运行日志</div>
  return <table className="log-table" aria-label="运行日志"><thead><tr><th>时间</th><th>级别</th><th>事件</th></tr></thead><tbody>{logs.slice(0, limit).map(log => <tr key={log.id}><td className="log-time">{new Date(log.at * 1000).toLocaleTimeString('zh-CN', { hour12: false })}</td><td><Badge variant="outline" className="log-level">{log.level.toUpperCase()}</Badge></td><td className="log-message">{log.message}</td></tr>)}</tbody></table>
}
