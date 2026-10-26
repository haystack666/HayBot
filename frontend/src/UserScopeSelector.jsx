import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { RefreshCw, UserRound } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Panel, Field } from './components/console'

export function useUserScopes(api) {
  const [search, setSearch] = useSearchParams()
  const selected = search.get('user') || ''
  const [users, setUsers] = useState([]), [error, setError] = useState('')
  const choose = useCallback(value => setSearch(previous => { const next = new URLSearchParams(previous); value ? next.set('user', value) : next.delete('user'); return next }, { replace: true }), [setSearch])
  const refresh = useCallback(async () => {
    const result = await api('/users')
    setUsers(result.items)
    setError('')
    return result.items
  }, [api])
  useEffect(() => {
    let alive = true
    api('/users').then(result => { if (alive) { setUsers(result.items); setError('') } }).catch(e => { if (alive) setError(e.message) })
    return () => { alive = false }
  }, [api])
  useEffect(() => {
    if (!selected && users.length) choose(users[0].id)
  }, [selected, users, choose])
  return { users, scopeId: selected, choose, error, refresh }
}

export default function UserScopeSelector({ users, scopeId, choose, error, refresh }) {
  return <Panel title="当前用户" subtitle="日程、记忆、关系和共同经历均按 Bot 与用户独立保存。群聊与私聊分别保存。" action={<Button variant="ghost" size="icon-sm" aria-label="刷新用户列表" onClick={() => refresh().catch(() => {})}><RefreshCw size={14} /></Button>}>
    <Field label="选择用户" id="state-user"><div className="scope-select-row"><UserRound size={17} /><select className="provider-select" id="state-user" value={scopeId} onChange={event => choose(event.target.value)}><option value="" disabled>{users.length ? '请选择用户' : '暂无用户，请先通过 QQ 与机器人互动'}</option>{users.map(user => <option key={user.id} value={user.id}>{user.label}</option>)}</select></div></Field>
    {error && <p className="provider-test-message" role="alert">{error}</p>}
    {!users.length && !error && <p className="text-muted-foreground text-sm mt-3">收到第一条 QQ 消息后会建立对应用户的独立生活与记忆。</p>}
  </Panel>
}
