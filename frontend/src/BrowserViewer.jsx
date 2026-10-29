import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, Maximize2, Minimize2, Plus, RefreshCw, X, MoreHorizontal, MousePointer2 } from 'lucide-react'
import { Dialog } from 'radix-ui'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { createBrowserSession } from './lib/browser-session'

const initial = { state: { state: 'stopped', tabs: [] }, owned: false, busy: false, connected: false, canControl: false, stream: '浏览器已停止' }

export default function BrowserViewer({ api, botId, ready, notify, onCheck }) {
  const viewer = useRef(null), canvas = useRef(null), mode = useRef(null), controller = useRef(null), expandButton = useRef(null)
  const [view, setView] = useState(initial), [expanded, setExpanded] = useState(false), [address, setAddress] = useState(''), [text, setText] = useState(''), [loginConfirm, setLoginConfirm] = useState(false), [menu, setMenu] = useState(false)
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
  useLayoutEffect(() => {
    const root = viewer.current, screen = canvas.current.parentElement
    let pending
    const fit = () => {
      pending = null
      if (expanded || !root.getClientRects().length) return
      // Keep the budget independent of document scrolling, otherwise scrolling
      // would enlarge the canvas and shift the page beneath the pointer.
      const rect = root.getBoundingClientRect()
      const controls = rect.height - screen.getBoundingClientRect().height
      const below = [...root.parentElement.querySelectorAll('.browser-current-task, .browser-auto-strip')]
        .reduce((height, element) => height + element.getBoundingClientRect().height, 0)
      const viewportHeight = window.visualViewport?.height || window.innerHeight
      const height = Math.max(64, Math.floor(viewportHeight - (rect.top + window.scrollY) - controls - below - 18))
      const value = `${height}px`
      if (root.style.getPropertyValue('--browser-screen-max-height') !== value) root.style.setProperty('--browser-screen-max-height', value)
    }
    const schedule = () => { if (!pending) pending = requestAnimationFrame(fit) }
    const observer = new ResizeObserver(schedule)
    observer.observe(root)
    observer.observe(root.parentElement)
    for (const element of root.children) if (element !== screen) observer.observe(element)
    for (const element of root.parentElement.children) if (element !== root) observer.observe(element)
    window.addEventListener('resize', schedule)
    window.visualViewport?.addEventListener('resize', schedule)
    fit()
    return () => { observer.disconnect(); cancelAnimationFrame(pending); window.removeEventListener('resize', schedule); window.visualViewport?.removeEventListener('resize', schedule) }
  }, [expanded, owned, state.owner_login])
  function act(value) { return controller.current?.act(value) }
  function keydown(event) {
    if (!canControl || event.isComposing || event.key === 'Escape' && expanded) return
    if (event.key.length === 1 && !event.ctrlKey && !event.metaKey) { event.preventDefault(); act({ kind: 'text', text: event.key }); return }
    const key = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a' ? 'ControlOrMeta+A' : event.shiftKey && event.key === 'Tab' ? 'Shift+Tab' : event.key
    if (['Enter', 'Tab', 'Shift+Tab', 'Escape', 'Backspace', 'Delete', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'ControlOrMeta+A'].includes(key)) { event.preventDefault(); act({ kind: 'key', key }) }
  }
  return <section ref={viewer} className={`browser-viewer ${expanded ? 'is-expanded' : ''} ${owned ? 'is-owned' : ''}`} aria-label="浏览器画面">
    <div className="browser-heading"><div><b>{state.owner_login ? '主人登录中' : owned ? '正在接管' : state.state === 'owner_control' ? '其他连接已接管' : state.automation ? 'Bot 正在浏览' : active ? '浏览器运行中' : '浏览器已停止'}</b><span role="status">{stream}</span></div><div className="action-row">
      {!active ? <Button size="sm" disabled={busy || !ready} onClick={() => controller.current.start()}>启动浏览器</Button> : <>
        <Button size="sm" variant={owned ? 'default' : 'outline'} disabled={busy || !connected || !ready} onClick={() => controller.current.claim()}><MousePointer2 size={14}/>{owned ? '结束接管' : '接管浏览器'}</Button>
      </>}
      <div className="browser-more"><Button size="icon-sm" variant="ghost" aria-label="更多浏览器操作" aria-expanded={menu} onClick={() => setMenu(v => !v)}><MoreHorizontal size={17}/></Button>{menu && <><button className="browser-menu-dismiss" aria-label="关闭操作菜单" onClick={() => setMenu(false)}/><div className="browser-menu">
        <Button size="sm" variant="ghost" disabled={busy || !active} onClick={() => { setMenu(false); controller.current.reconnect() }}>重新连接画面</Button>
        <Button size="sm" variant="ghost" onClick={() => { setMenu(false); onCheck() }}>重新检测环境</Button>
        <Button size="sm" variant="ghost" disabled={busy || !active} className="browser-danger" onClick={() => { setMenu(false); controller.current.stop() }}>停止浏览器</Button>
      </div></>}</div>
      <Button ref={expandButton} size="icon-sm" variant="ghost" disabled={!active && !expanded} aria-label={expanded ? '收起画面' : '放大画面'} onClick={() => { controller.current.cancel(); setExpanded(v => !v) }}>{expanded ? <Minimize2 size={16}/> : <Maximize2 size={16}/>}</Button>
    </div></div>
    {state.owner_login && <p className="browser-login-notice">登录隔离已开启。模型无法读取页面；关闭画面或停止浏览器后仍保持隔离，完成登录后请手动解除。</p>}
    <div className="browser-tabs" role="tablist" aria-label="浏览器标签页">{state.tabs.map(tab => <button type="button" key={tab.id} role="tab" aria-selected={tab.id === state.activeTab} disabled={!canControl} title={tab.url} onClick={() => act({ kind: 'switch_tab', target: tab.id })}>{tab.title}</button>)}<Button className="browser-control" size="icon-sm" variant="ghost" aria-label="新建标签页" disabled={!canControl} onClick={() => act({ kind: 'new_tab' })}><Plus size={15}/></Button><Button className="browser-control" size="icon-sm" variant="ghost" aria-label="关闭当前标签页" disabled={!canControl} onClick={() => act({ kind: 'close_tab' })}><X size={15}/></Button></div>
    <form className="browser-address" onSubmit={event => { event.preventDefault(); act({ kind: 'navigate', url: address }) }}>
      {[['back','后退',ArrowLeft],['forward','前进',ArrowRight],['reload','刷新页面',RefreshCw]].map(([kind,label,Icon]) => <Button className="browser-control" key={kind} type="button" size="icon-sm" variant="ghost" aria-label={label} disabled={!canControl} onClick={() => act({ kind })}><Icon size={15}/></Button>)}
      {[['抖音','https://www.douyin.com/'],['B站','https://www.bilibili.com/']].map(([label,url]) => <Button className="browser-control browser-site-shortcut" key={url} type="button" size="sm" variant="ghost" disabled={!canControl} onClick={() => act({ kind: 'navigate', url })}>{label}</Button>)}
      <Input aria-label="网页地址" type="url" placeholder="https://" readOnly={!canControl} value={address} onChange={event => setAddress(event.target.value)}/><Button className="browser-control" size="sm" disabled={!canControl || !address}>前往</Button><span className="browser-readonly">仅查看</span><Button className="browser-control" type="button" size="sm" variant="outline" disabled={busy || !canControl} onClick={() => state.owner_login ? setLoginConfirm(true) : controller.current.login()}>{state.owner_login ? '完成登录' : '主人登录'}</Button>
      <select className="browser-control" ref={mode} aria-label="画面操作模式" defaultValue="auto"><option value="auto">自动</option><option value="drag">拖动</option><option value="swipe">滑动</option></select>
    </form>
    <div className="browser-screen-wrap"><canvas ref={canvas} className="browser-screen" width="1280" height="800" tabIndex={canControl ? 0 : -1} aria-label="远程浏览器画面，接管后可点击、拖动或滑动" onKeyDown={keydown} onCompositionEnd={event => { if (canControl && event.data) act({ kind: 'text', text: event.data }) }}/>{!active && <div className="browser-screen-empty">启动 Chrome 后显示实时画面</div>}</div>
    <form className="browser-typing" onSubmit={async event => { event.preventDefault(); const value = text; if (!value) return; if (await act({ kind: 'text', text: value })) setText(current => current === value ? '' : current) }}><Input aria-label="输入到网页" placeholder="输入文字到网页…" disabled={!canControl} maxLength={5000} value={text} onChange={event => setText(event.target.value)}/><Button size="sm" disabled={!canControl || !text}>输入</Button><Button type="button" size="sm" variant="outline" disabled={!canControl} onClick={() => act({ kind: 'key', key: 'Enter' })}>回车</Button></form>
    <div className="browser-viewer-footer"><span>原始画质 · 按浏览器视口采集</span><span>{owned ? '模型已暂停操作' : '静音 · 接管后可操作页面'}</span></div>
    <Dialog.Root open={loginConfirm} onOpenChange={setLoginConfirm}><Dialog.Portal><Dialog.Overlay className="sheet-overlay"/><Dialog.Content className="provider-dialog"><Dialog.Title>完成主人登录？</Dialog.Title><Dialog.Description>请先离开密码、验证码等登录页面。确认后解除登录隔离；仍在接管时，模型继续暂停读取页面。</Dialog.Description><div className="dialog-actions"><Button variant="outline" onClick={() => setLoginConfirm(false)}>继续登录</Button><Button disabled={busy || !canControl} onClick={() => { setLoginConfirm(false); controller.current.login() }}>完成登录</Button></div></Dialog.Content></Dialog.Portal></Dialog.Root>

  </section>
}
