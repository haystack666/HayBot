import { usePageTabs, Section } from './components/PageTabs'
import { useCallback, useEffect, useRef, useState } from 'react'
import { BookOpen, LoaderCircle, RefreshCw, Save, Trash2 } from 'lucide-react'
import { Panel, Field, Notice } from './components/console'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'

const statuses = { ready: '已保存', writing: '写作中', failed: '未完成' }

export default function DiaryPage({ api, notify }) {
  const [snapshot, setSnapshot] = useState(null), [config, setConfig] = useState(null)
  const [entries, setEntries] = useState({ items: [], total: 0 }), [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState(''), [entry, setEntry] = useState(null), [versions, setVersions] = useState(null)
  const [day, setDay] = useState(''), [busy, setBusy] = useState(''), [error, setError] = useState(''), [dirty, setDirty] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState(false)
  const dirtyRef = useRef(false), loadId = useRef(0), entryId = useRef(0)
  const load = useCallback(async () => {
    const id = ++loadId.current
    const [state, list] = await Promise.all([api('/diary'), api(`/diary/entries?offset=${offset}&limit=20`)])
    if (id !== loadId.current) return
    setSnapshot(state); setEntries(list); setError('')
    if (!dirtyRef.current) setConfig(state.config)
    setDay(value => value || state.today)
  }, [api, offset])
  useEffect(() => {
    load().catch(e => setError(e.message))
    const timer = setInterval(() => load().catch(e => setError(e.message)), 5000)
    return () => { clearInterval(timer); loadId.current++ }
  }, [load])
  const selectedVersion = entries.items.find(item => item.id === selected)?.revision
  const selectedStatus = entries.items.find(item => item.id === selected)?.status
  useEffect(() => {
    const id = ++entryId.current
    setEntry(null); setVersions(null); setDeleteConfirm(false)
    if (selected) api(`/diary/entries/${selected}`).then(value => { if (id === entryId.current) setEntry(value) }).catch(e => { if (id === entryId.current) setError(e.message) })
    return () => { entryId.current++ }
  }, [api, selected, selectedVersion, selectedStatus])
  function update(key, value) { dirtyRef.current = true; setDirty(true); setConfig(c => ({ ...c, [key]: value })) }
  async function run(name, fn) { setBusy(name); try { await fn() } catch (e) { notify(e.message, true) } finally { setBusy('') } }
  const tabs = usePageTabs([['entries','日记本'],['settings','写作习惯']])
  useEffect(() => { if (!selected && entries.items.length) setSelected(entries.items[0].id) }, [entries.items, selected])
  const writing = busy === 'write' || snapshot?.busy
  const changed = dirty || !!busy
  return <div className="page-stack diary-page">{tabs.tabs}
    <p className="page-context">写给自己，Owner 可翻看 · 写完安静保存 · 日记感受不会自动写入长期记忆</p>
    {error && <Notice alert>{error}</Notice>}
    <Section show={tabs.value === 'settings'}><Panel title="写日记的习惯">
      {!config ? <p className="push-hint">正在加载…</p> : <>
        <fieldset disabled={!!busy} className="form-grid border-0 m-0 p-0">
          <Field label="每天自动写作" id="diary-enabled"><label className="flex items-center gap-2"><input id="diary-enabled" type="checkbox" checked={config.enabled} onChange={e => update('enabled', e.target.checked)} />每天回顾一次</label></Field>
          <Field label="写作时间" id="diary-time" hint="错过时可在下次运行补齐最近一天；不批量补造旧日记。"><Input id="diary-time" type="time" value={config.time} onChange={e => update('time', e.target.value)} /></Field>
          <Field label="时区" id="diary-zone"><Input id="diary-zone" value={config.timezone} onChange={e => update('timezone', e.target.value)} /></Field>
          <Field label="Owner 私聊账号" id="diary-owner" hint="QQ 官方填写私聊用户 OpenID，NapCat 填 QQ 号。只选定这个人的私聊；群聊成员 OpenID 不能代替私聊 OpenID。留空时不读取任何人的私聊，也不向聊天提供日记。"><Input id="diary-owner" list="diary-contacts" maxLength={128} value={config.owner_id} onChange={e => update('owner_id', e.target.value)} /><datalist id="diary-contacts">{snapshot?.contacts.map(c => <option value={c.id} key={c.id}>{c.name}</option>)}</datalist></Field>
          <Field label="群聊素材" id="diary-groups"><label className="flex items-center gap-2"><input id="diary-groups" type="checkbox" checked={config.include_groups} onChange={e => update('include_groups', e.target.checked)} />参考当天已收到的群聊</label></Field>
          <Field label="自主分享" id="diary-sharing" hint="只在与绑定 Owner 的私聊中参考，不向群友提供日记。关闭后仅在后台查看。"><label className="flex items-center gap-2"><input id="diary-sharing" type="checkbox" checked={config.allow_sharing} onChange={e => update('allow_sharing', e.target.checked)} />允许自行选择分享片段</label></Field>
          <Field label="写作偏好（可选）" id="diary-instruction" full hint="例如多留意让自己有感触的小事。不要填写每日必须发生的剧情。"><Textarea id="diary-instruction" rows={3} maxLength={2000} value={config.instruction} onChange={e => update('instruction', e.target.value)} /></Field>
        </fieldset>
        <div className={dirty ? "local-savebar mt-4" : "action-row mt-4"}>{dirty && <span>日记设置有未保存的修改</span>}<div className="action-row">{dirty && <Button variant="outline" disabled={!!busy} onClick={()=>{setConfig(structuredClone(snapshot.config));dirtyRef.current=false;setDirty(false)}}>撤销更改</Button>}<Button disabled={!dirty || !!busy} onClick={() => run('save', async () => { const saved = await api('/diary/config', 'PUT', config); dirtyRef.current = false; setDirty(false); setConfig(saved); await load(); notify('日记设置已保存') })}><Save size={14} />保存日记设置</Button></div></div>
      </>}
    </Panel>
    </Section><Section show={tabs.value === 'entries'}><div className="diary-workspace">
      <Panel title="日记本" subtitle={`${entries.total} 篇 · 按日期保存，同一天补写会保留旧版本。`} action={<Button variant="ghost" size="icon-sm" aria-label="刷新日记" disabled={!!busy} onClick={() => run('refresh', load)}><RefreshCw size={15} /></Button>}>
        <div className="flex flex-wrap items-center gap-2 mb-4"><Input aria-label="日记日期" type="date" max={snapshot?.today} value={day} onChange={e => setDay(e.target.value)} className="w-auto" /><Button disabled={changed || writing || !day} onClick={() => run('write', async () => { const saved = await api('/diary/write', 'POST', { day }); setSelected(saved.id); setEntry(saved); await load() })}>{writing ? <LoaderCircle size={14} className="spin" /> : <BookOpen size={14} />}{writing ? '正在写…' : '写这一天'}</Button></div>
        {dirty && <p className="push-hint">先保存日记设置，再开始写作。</p>}
        {writing && <p className="push-hint" role="status">正在回顾当天的素材并写作，保存后会出现在日记本里。</p>}
        <div className="diary-list">{entries.items.map(item => <button type="button" className={`diary-list-item ${selected === item.id ? 'is-selected' : ''}`} key={item.id} onClick={() => setSelected(item.id)}><span className="flex items-center justify-between gap-3"><b>{item.day}</b><Badge variant="outline">{statuses[item.status] || item.status}</Badge></span><p>{item.preview || item.error || '还没有保存正文'}</p><small>第 {item.revision} 版</small></button>)}</div>
        {!entries.items.length && <p className="push-hint">还没有日记。可以先写今天，或等她在设定时间自己写。</p>}
        <div className="action-row mt-4"><Button variant="outline" size="sm" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 20))}>上一页</Button><Button variant="outline" size="sm" disabled={offset + 20 >= entries.total} onClick={() => setOffset(offset + 20)}>下一页</Button></div>
      </Panel>
      <Panel title={entry?.day || '翻开一页'} subtitle={entry ? `${entry.timezone} · 第 ${entry.revision} 版` : '选择左侧日期，阅读她留下的文字。'}>
        {!entry ? <p className="push-hint">{selected ? '正在读取…' : '日记只在当前 Bot 的日记本里保存。'}</p> : <>
          {entry.error && <Notice alert>{entry.error}{entry.content && '；上一次保存的正文仍在。'}</Notice>}
          <article className="diary-prose">{entry.content || '这一篇尚未完成，可以重新写作。'}</article>
          <p className="push-hint">素材：{entry.sources.message_count || 0} 条聊天。日程如有引用，仅作计划参考。</p>
          <div className="action-row mt-4"><Button variant="outline" size="sm" disabled={!!busy} onClick={() => run('versions', async () => setVersions((await api(`/diary/entries/${entry.id}/versions`)).items))}>查看修改记录</Button><Button variant="destructive-outline" size="sm" disabled={!!busy} onClick={() => setDeleteConfirm(true)}><Trash2 size={14} />删除</Button></div>
          {deleteConfirm && <div className="mt-4"><p>删除这篇日记及所有旧版本？删除后不会自动重新生成。</p><div className="action-row mt-3"><Button variant="outline" size="sm" onClick={() => setDeleteConfirm(false)}>取消</Button><Button variant="destructive" size="sm" disabled={!!busy} onClick={() => run('delete', async () => { await api(`/diary/entries/${entry.id}`, 'DELETE'); setEntries(old => ({...old,items:old.items.filter(item => item.id !== entry.id)})); setSelected(''); setEntry(null); setVersions(null); setDeleteConfirm(false); await load() })}>确认删除</Button></div></div>}
          {versions && <div className="mt-5">{versions.map(v => <details className="diary-version" key={v.revision}><summary>第 {v.revision} 版 · {new Date(v.created * 1000).toLocaleString('zh-CN', { timeZone: entry.timezone, hour12: false })} · {v.origin === 'automatic' ? '自动写作' : '手动写作'}</summary><p className="diary-prose">{v.content}</p></details>)}</div>}
        </>}
      </Panel>
    </div></Section>
  </div>
}
