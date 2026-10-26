export const logCategories = { system: '系统', qq: 'QQ 连接', message: '消息处理', model: '模型调用', memory: '角色记忆', schedule: '每日日程', proactive: '主动消息', config: '配置管理' }
export const logLevels = { error: '错误', warn: '警告', info: '信息', debug: '调试' }
const ranges = { '1h': 3600, '24h': 86400, '7d': 604800, all: null }
export function readLogFilters(params) {
  return { level: Object.hasOwn(logLevels, params.get('level')) ? params.get('level') : '',
    category: Object.hasOwn(logCategories, params.get('category')) ? params.get('category') : '',
    q: (params.get('q') || '').slice(0, 200), range: Object.hasOwn(ranges, params.get('range')) ? params.get('range') : '24h',
    trace: (params.get('trace') || '').slice(0, 100) }
}
export function logQuery(filters, now = Date.now()) {
  const params = new URLSearchParams({ limit: '50' })
  if (filters.level) params.set('level', filters.level)
  if (filters.category) params.set('category', filters.category)
  if (filters.q.trim()) params.set('q', filters.q.trim())
  if (filters.trace) params.set('trace_id', filters.trace)
  if (ranges[filters.range]) params.set('start', String(Math.max(0, now / 1000 - ranges[filters.range])))
  return params.toString()
}
export function mergeLogPages(previous, incoming) {
  return [...new Map([...previous, ...incoming].map(item => [item.id, item])).values()].sort((a, b) => b.id - a.id)
}
export function duration(value) { return typeof value !== 'number' ? '' : value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(2)} s` }
