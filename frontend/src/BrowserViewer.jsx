import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, Maximize2, Minimize2, Plus, RefreshCw, X } from 'lucide-react'
import { Dialog } from 'radix-ui'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { createBrowserSession } from './lib/browser-session'

const initial = { state: { state: 'stopped', tabs: [] }, owned: false, busy: false, connected: false, canControl: false, stream: '浏览器已停止' }

export default function BrowserViewer({ api, botId, ready, notify }) {
  const canvas = useRef(null), mode = useRef(null), controller = useRef(null), expandButton = useRef(null)
  const [view, setView] = useState(initial), [expanded, setExpanded] = useState(false), [address, setAddress] = useState(''), [text, setText] = useState(''), [loginConfirm, setLoginConfirm] = useState(false)
  const { state, owned, connected, canControl, busy, stream } = view
  const active = state.state !== 'stopped'
  useEffect(() => {
    const value = createBrowserSession({ api, botId, canvas: canvas.current, mode: mode.current, change: setView, report: message => notify(message, true) })
    controller.current = value; value.open()
    return () => { value.dispose(); controller.current = null }
  }, [api, botId, notify])
  useEffect(() => { controller.current?.setReady(ready) }, [ready])
  const currentURL = state.tabs.find(tab => tab.id === state.activeTab)?.url || ''
  useEffect(() => { setAddress(currentURL === 'about:blank' ? '' : currentURL) }, [currentURL])
  useEffect(() => {
    if (!expanded) return
    const old = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const escape = event => { if (event.key === 'Escape') { event.preventDefault(); controller.current?.cancel(); setExpanded(false); expandButton.current?.focus() } }
    document.addEventListener('keydown', escape, true)
    return () => { document.body.style.overflow = old; document.removeEventListener('keydown', escape, true) }
  }, [expanded])
  function act(value) { return controller.current?.act(value) }
  function keydown(event) {
    if (!canControl || event.isComposing || event.key === 'Escape' && expanded) return
    if (event.key.length === 1 && !event.ctrlKey && !event.metaKey) { event.preventDefault(); act({ kind: 'text', text: event.key }); return }
    const key = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a' ? 'ControlOrMeta+A' : event.shiftKey && event.key === 'Tab' ? 'Shift+Tab' : event.key
    if (['Enter', 'Tab', 'Shift+Tab', 'Escape', 'Backspace', 'Delete', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'ControlOrMeta+A'].includes(key)) { event.preventDefault(); act({ kind: 'key', key }) }
  }
  return <section className={`browser-viewer ${expanded ? 'is-expanded' : ''}`} aria-label="浏览器画面">
    <div className="browser-heading"><div><b>{state.owner_login ? '主人登录中' : owned ? '正在接管' : state.state === 'owner_control' ? '其他连接已接管' : active ? '浏览器运行中' : '浏览器已停止'}</b><span role="status">{stream}</span></div><div className="action-row">
      {!active ? <Button size="sm" disabled={busy || !ready} onClick={() => controller.current.start()}>启动浏览器</Button> : <>
        <Button size="sm" variant={owned ? 'default' : 'outline'} disabled={busy || !connected || !ready} onClick={() => controller.current.claim()}>{owned ? '结束接管' : '接管'}</Button>
        <Button size="sm" variant="outline" disabled={busy || !canControl} onClick={() => state.owner_login ? setLoginConfirm(true) : controller.current.login()}>{state.owner_login ? '完成登录' : '主人登录'}</Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => controller.current.stop()}>停止</Button>
      </>}
      <Button size="icon-sm" variant="ghost" disabled={busy || !active} aria-label="重新连接画面" onClick={() => controller.current.reconnect()}><RefreshCw size={15}/></Button>
      <Button ref={expandButton} size="icon-sm" variant="ghost" disabled={!active && !expanded} aria-label={expanded ? '收起画面' : '放大画面'} onClick={() => { controller.current.cancel(); setExpanded(v => !v) }}>{expanded ? <Minimize2 size={16}/> : <Maximize2 size={16}/>}</Button>
    </div></div>
    {state.owner_login && <p className="browser-login-notice">登录隔离已开启。模型无法读取页面；关闭画面或停止浏览器后仍保持隔离，完成登录后请手动解除。</p>}
    <div className="browser-tabs" role="tablist" aria-label="浏览器标签页">{state.tabs.map(tab => <button type="button" key={tab.id} role="tab" aria-selected={tab.id === state.activeTab} disabled={!canControl} title={tab.url} onClick={() => act({ kind: 'switch_tab', target: tab.id })}>{tab.title}</button>)}<Button size="icon-sm" variant="ghost" aria-label="新建标签页" disabled={!canControl} onClick={() => act({ kind: 'new_tab' })}><Plus size={15}/></Button><Button size="icon-sm" variant="ghost" aria-label="关闭当前标签页" disabled={!canControl} onClick={() => act({ kind: 'close_tab' })}><X size={15}/></Button></div>
    <form className="browser-address" onSubmit={event => { event.preventDefault(); act({ kind: 'navigate', url: address }) }}>
      {[['back','后退',ArrowLeft],['forward','前进',ArrowRight],['reload','刷新页面',RefreshCw]].map(([kind,label,Icon]) => <Button key={kind} type="button" size="icon-sm" variant="ghost" aria-label={label} disabled={!canControl} onClick={() => act({ kind })}><Icon size={15}/></Button>)}
      {[['抖音','https://www.douyin.com/'],['B站','https://www.bilibili.com/']].map(([label,url]) => <Button key={url} type="button" size="sm" variant="ghost" disabled={!canControl} onClick={() => act({ kind: 'navigate', url })}>{label}</Button>)}
      <Input aria-label="网页地址" type="url" placeholder="https://" disabled={!canControl} value={address} onChange={event => setAddress(event.target.value)}/><Button size="sm" disabled={!canControl || !address}>前往</Button>
      <select ref={mode} aria-label="画面操作模式" defaultValue="auto"><option value="auto">自动</option><option value="drag">拖动</option><option value="swipe">滑动</option></select>
    </form>
    <div className="browser-screen-wrap"><canvas ref={canvas} className="browser-screen" width="1280" height="800" tabIndex={canControl ? 0 : -1} aria-label="远程浏览器画面，接管后可点击、拖动或滑动" onKeyDown={keydown} onCompositionEnd={event => { if (canControl && event.data) act({ kind: 'text', text: event.data }) }}/>{!active && <div className="browser-screen-empty">启动 Chrome 后显示实时画面</div>}</div>
    <form className="browser-typing" onSubmit={async event => { event.preventDefault(); const value = text; if (!value) return; if (await act({ kind: 'text', text: value })) setText(current => current === value ? '' : current) }}><Input aria-label="输入到网页" placeholder="输入文字到网页…" disabled={!canControl} maxLength={5000} value={text} onChange={event => setText(event.target.value)}/><Button size="sm" disabled={!canControl || !text}>输入</Button><Button type="button" size="sm" variant="outline" disabled={!canControl} onClick={() => act({ kind: 'key', key: 'Enter' })}>回车</Button></form>
    <Dialog.Root open={loginConfirm} onOpenChange={setLoginConfirm}><Dialog.Portal><Dialog.Overlay className="sheet-overlay"/><Dialog.Content className="provider-dialog"><Dialog.Title>完成主人登录？</Dialog.Title><Dialog.Description>请先离开密码、验证码等登录页面。确认后解除登录隔离；仍在接管时，模型继续暂停读取页面。</Dialog.Description><div className="dialog-actions"><Button variant="outline" onClick={() => setLoginConfirm(false)}>继续登录</Button><Button disabled={busy || !canControl} onClick={() => { setLoginConfirm(false); controller.current.login() }}>完成登录</Button></div></Dialog.Content></Dialog.Portal></Dialog.Root>

  </section>
}
