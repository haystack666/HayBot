import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useSearchParams, useParams } from 'react-router-dom'
import { Bot, ChevronUp, Image as ImageIcon, List, LoaderCircle, MessageSquare, RefreshCw, Search, User, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'

const sources = { incoming: '用户消息', reply: '机器人回复', greeting: '定时问候', idle: '主动搭话', reminder: '提醒', test: '推送测试', image_notice: '图片提示', legacy_context: '旧上下文', schedule: '日程指令', reset: '重置指令', meme: '表情包' }
const showTime = at => at == null ? '时间未记录' : new Date(at * 1000).toLocaleString('zh-CN', { hour12: false })
const shortTime = at => new Date(at * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
function mergeMessages(previous, incoming) { return [...new Map([...previous, ...incoming].map(message => [message.id, message])).values()].sort((a, b) => a.id - b.id) }
function mergeConversations(previous, incoming) {
  const records = new Map(previous.map(conversation => [conversation.id, conversation]))
  for (const item of incoming) records.set(item.id, { ...records.get(item.id), ...item })
  return [...records.values()].sort((a, b) => b.updated - a.updated || b.id.localeCompare(a.id))
}

export default function ChatsPage({ api, botName }) {
  const { botId } = useParams()
  const [params, setParams] = useSearchParams()
  const conversationId = params.get('conversation') || ''
  const view = params.get('view') === 'chat' ? 'chat' : 'list'
  const [conversations, setConversations] = useState([]), [nextOffset, setNextOffset] = useState(null), [query, setQuery] = useState('')
  const [conversation, setConversation] = useState(null), [messages, setMessages] = useState([]), [loadedId, setLoadedId] = useState('')
  const [listError, setListError] = useState(''), [messageError, setMessageError] = useState('')
  const [loadingList, setLoadingList] = useState(true), [loadingMessages, setLoadingMessages] = useState(false), [loadingOlder, setLoadingOlder] = useState(false), [refreshing, setRefreshing] = useState(false)
  const [hasOlder, setHasOlder] = useState(false)
  const viewport = useRef(null), stickToBottom = useRef(true), preserveScroll = useRef(null), refreshMessages = useRef(async () => {})
  const currentId = useRef(conversationId), mounted = useRef(true)
  currentId.current = conversationId

  const loadConversations = useCallback(async (offset = 0) => {
    try {
      const result = await api(`/conversations?limit=50&offset=${offset}`)
      if (!mounted.current) return
      setConversations(old => mergeConversations(old, result.items))
      setNextOffset(old => offset > 0 || old == null ? result.next_offset : old)
      setListError(''); setLoadingList(false)
    } catch (error) { if (mounted.current) { setListError(error.message); setLoadingList(false) } }
  }, [api])
  useEffect(() => {
    mounted.current = true
    loadConversations()
    const timer = setInterval(() => loadConversations(), 5000)
    return () => { mounted.current = false; clearInterval(timer) }
  }, [loadConversations])
  useEffect(() => {
    if (!conversationId && conversations.length) {
      const next = new URLSearchParams(params); next.set('conversation', conversations[0].id)
      setParams(next, { replace: true })
    }
  }, [conversationId, conversations, params, setParams])

  useEffect(() => {
    let live = true, lastId = 0, fetching = false
    setMessages([]); setConversation(null); setLoadedId(''); setMessageError(''); setHasOlder(false); setLoadingOlder(false)
    stickToBottom.current = true; preserveScroll.current = null
    setLoadingMessages(!!conversationId)
    if (!conversationId) { refreshMessages.current = async () => {}; return () => { live = false } }
    async function load() {
      if (!live || fetching) return
      fetching = true
      try {
        const result = await api(`/conversations/${conversationId}/messages?limit=100${lastId ? `&after=${lastId}` : ''}`)
        if (!live) return
        if (!lastId) setHasOlder(result.has_more)
        setMessages(old => mergeMessages(old, result.items))
        if (result.items.length) lastId = result.items.at(-1).id
        setConversation(result.conversation); setLoadedId(conversationId); setLoadingMessages(false); setMessageError('')
      } catch (error) { if (live) { setMessageError(error.message); setLoadingMessages(false) } } finally { fetching = false }
    }
    refreshMessages.current = load
    load(); const timer = setInterval(load, 5000)
    return () => { live = false; clearInterval(timer) }
  }, [api, conversationId])

  const visibleMessages = loadedId === conversationId ? messages : []
  const selected = loadedId === conversationId ? conversation : null
  useLayoutEffect(() => {
    const container = viewport.current
    if (!container || view !== 'chat') return
    if (preserveScroll.current) {
      const { height, top } = preserveScroll.current
      container.scrollTop = top + container.scrollHeight - height
      preserveScroll.current = null
    } else if (stickToBottom.current) container.scrollTop = container.scrollHeight
  }, [visibleMessages.length, view, loadedId])

  function selectConversation(id) {
    const next = new URLSearchParams(params); next.set('conversation', id); setParams(next)
  }
  function selectView(value) {
    const next = new URLSearchParams(params); next.set('view', value); setParams(next, { replace: true }); stickToBottom.current = true
  }
  async function refresh() {
    setRefreshing(true)
    try { await Promise.all([loadConversations(), refreshMessages.current()]) } finally { if (mounted.current) setRefreshing(false) }
  }
  async function loadOlder() {
    if (!visibleMessages.length || loadingOlder) return
    const id = conversationId
    setLoadingOlder(true)
    try {
      const result = await api(`/conversations/${id}/messages?limit=100&before=${visibleMessages[0].id}`)
      if (currentId.current !== id || !mounted.current) return
      if (view === 'chat' && viewport.current) preserveScroll.current = { height: viewport.current.scrollHeight, top: viewport.current.scrollTop }
      setMessages(old => mergeMessages(old, result.items)); setHasOlder(result.has_more); setMessageError('')
    } catch (error) { if (currentId.current === id && mounted.current) setMessageError(error.message) } finally { if (currentId.current === id && mounted.current) setLoadingOlder(false) }
  }
  const author = message => message.role === 'assistant' ? botName || '机器人' : message.sender_name || (message.sender_id ? `用户 · ${message.sender_id.slice(-6)}` : '用户')
  const filtered = conversations.filter(item => `${item.title} ${item.target_id}`.toLowerCase().includes(query.trim().toLowerCase()))
  const olderButton = hasOlder && <Button className="older-messages" variant="ghost" size="sm" disabled={loadingOlder} onClick={loadOlder}>{loadingOlder ? <LoaderCircle className="spin" size={14} /> : <ChevronUp size={14} />}加载更早记录</Button>
  function content(message) {
    return <>{message.meme_id ? <img className="chat-meme-image" src={`/api/bots/${encodeURIComponent(botId)}/memes/${message.meme_id}/image?sent=${message.meme_original?'false':'true'}`} alt={message.content} loading="lazy" /> : <>{message.content && <div className="message-content">{message.content}</div>}{message.attachment_count > 0 && <div className="message-attachment"><ImageIcon size={14} /><span>图片 / 表情包 × {message.attachment_count} · 原图未保存</span></div>}</>}</>
  }
  return <div className="chat-page"><div className="chat-toolbar"><p>仅查看聊天记录 · 每 5 秒自动刷新</p><Button variant="outline" size="sm" disabled={refreshing} onClick={refresh}><RefreshCw size={14} className={refreshing ? 'spin' : ''} />刷新记录</Button></div>
    {listError && <div className="notice" role="alert">会话加载失败：{listError}</div>}
    <div className="chat-workspace"><Card className="conversation-sidebar"><div className="conversation-heading"><h2>会话</h2><Badge variant="secondary">{conversations.length}</Badge></div><div className="conversation-search"><Search size={14} /><Input aria-label="搜索会话" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索已加载会话" /></div><div className="conversation-list" aria-label="会话列表">
      {loadingList ? <div className="empty"><LoaderCircle className="spin inline-block" size={18} /> 正在加载</div> : filtered.length ? filtered.map(item => <button key={item.id} className={`conversation-button ${item.id === conversationId ? 'active' : ''}`} aria-pressed={item.id === conversationId} onClick={() => selectConversation(item.id)}><span className="conversation-icon">{item.kind === 'group' ? <Users size={16} /> : <User size={16} />}</span><span className="conversation-info"><span className="conversation-title">{item.title}</span><span className="conversation-preview">{item.preview?.replace(/\s+/g, ' ') || (item.attachment_count ? '[图片 / 表情包]' : '暂无文字')}</span><small>{item.message_count} 条记录</small></span><time>{shortTime(item.updated)}</time></button>) : <div className="empty">{query ? '没有匹配的会话' : '还没有聊天记录'}</div>}
      {nextOffset != null && <Button className="load-conversations" variant="ghost" size="sm" onClick={() => loadConversations(nextOffset)}>加载更多会话</Button>}
    </div></Card>
    <Card className="chat-detail"><div className="chat-detail-heading"><div><h2>{selected?.title || (loadingMessages ? '正在加载会话…' : '选择一个会话')}</h2><p>{selected ? `${selected.kind === 'group' ? '群聊' : '单聊'} · 已保存 ${selected.message_count} 条记录` : '从会话列表选择用户或群聊'}</p></div><div className="chat-view-switch" role="group" aria-label="聊天记录视图"><Button variant={view === 'list' ? 'secondary' : 'ghost'} size="sm" aria-pressed={view === 'list'} onClick={() => selectView('list')}><List size={14} />快捷查看</Button><Button variant={view === 'chat' ? 'secondary' : 'ghost'} size="sm" aria-pressed={view === 'chat'} onClick={() => selectView('chat')}><MessageSquare size={14} />气泡聊天</Button></div></div>
      {messageError && <div className="notice m-4" role="alert">记录加载失败：{messageError}</div>}
      <div className={`chat-scroll ${view}`} ref={viewport} onScroll={() => { if (viewport.current) stickToBottom.current = viewport.current.scrollHeight - viewport.current.scrollTop - viewport.current.clientHeight < 100 }}>
        {loadingMessages ? <div className="chat-empty"><LoaderCircle className="spin" size={22} /><p>正在加载聊天记录</p></div> : !visibleMessages.length ? <div className="chat-empty"><MessageSquare size={28} /><p>{conversationId ? '此会话暂无可显示的记录' : '收到 QQ 消息后，会在这里显示'}</p></div> : view === 'list' ? <><table className="chat-table" aria-label="快捷聊天记录"><thead><tr><th>发送方 / 时间</th><th>消息内容</th></tr></thead><tbody>{[...visibleMessages].reverse().map(message => <tr key={message.id} data-role={message.role}><td><strong>{author(message)}</strong><time>{showTime(message.at)}</time><Badge variant="outline">{sources[message.source] || '消息'}</Badge></td><td>{content(message)}</td></tr>)}</tbody></table>{olderButton}</> : <div className="bubble-thread">{olderButton}{visibleMessages.map(message => <div key={message.id} className={`message-row ${message.role}`} data-role={message.role}><div className="message-avatar">{message.role === 'assistant' ? <Bot size={17} /> : <User size={17} />}</div><div className="message-body"><div className="message-meta"><strong>{author(message)}</strong><time>{showTime(message.at)}</time></div><div className={`message-bubble ${message.role}`}>{content(message)}</div>{message.source !== 'incoming' && message.source !== 'reply' && <div className="message-source">{sources[message.source] || '消息'}</div>}</div></div>)}</div>}
      </div><div className="chat-detail-footer"><span>已加载 {visibleMessages.length} 条</span><span>用户在左 · 机器人在右</span></div>
    </Card></div><p className="push-hint">旧记录仅恢复升级时仍保留的模型上下文及已确认的主动消息，“旧上下文”的发送时间未保存。新记录独立留存，清空模型上下文不会删除聊天记录；收到的图片以占位说明显示，机器人发出的表情包可预览。</p>
  </div>
}
