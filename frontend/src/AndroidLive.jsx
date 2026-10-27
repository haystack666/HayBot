import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import JMuxer from 'jmuxer'
import { livePoint, parseLiveFrame } from './lib/android-live'
import { LiveVideoFeed, BufferedMseSink } from './lib/android-mse'

const keyNames = { Enter: 'enter', Backspace: 'delete', Tab: 'tab', ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down', Escape: 'back' }
export default forwardRef(function AndroidLive({ botId, device, onTakeover, onFallback, disabled }, ref) {
  const video = useRef(null), socket = useRef(null), ownedRef = useRef(false), pointer = useRef(null), lastMove = useRef(0), lastPoint = useRef(null)
  const [generation, reconnect] = useState(0), [status, setStatus] = useState('connecting'), [owned, setOwned] = useState(false), [error, setError] = useState('')
  const [size, setSize] = useState({ width: device.config.width, height: device.config.height })
  const [taking, setTaking] = useState(false), [visible, setVisible] = useState(!document.hidden)
  useEffect(() => { const update = () => setVisible(!document.hidden); document.addEventListener('visibilitychange', update); return () => document.removeEventListener('visibilitychange', update) }, [])
  function send(value) {
    const ws = socket.current
    if (!ownedRef.current || !ws || ws.readyState !== WebSocket.OPEN) return false
    if (ws.bufferedAmount > 65536) { ws.close(); return false }
    ws.send(JSON.stringify(value)); return true
  }
  function key(value) { send({ type: 'key', key: value, action: 'down' }); send({ type: 'key', key: value, action: 'up' }) }
  useImperativeHandle(ref, () => ({
    reconnect() { reconnect(v => v + 1) },
    get controlOwned() { return ownedRef.current },
    sendAction(action) {
      if (!ownedRef.current) return false
      if (action.kind === 'key') { key(action.key); return true }
      if (action.kind === 'text') return send({ type: 'text', text: action.text })
      return false
    },
  }))
  useEffect(() => {
    if (!visible) { setStatus('paused'); setOwned(false); ownedRef.current = false; return }
    let alive = true, ws, timer, startupTimer, lagTimer
    let feed
    ownedRef.current = false; setOwned(false); setStatus('connecting'); setError('')
    const fail = message => { if (alive) { setError(message); setStatus('error'); ownedRef.current = false; setOwned(false) } }
    const failAndClose = message => { fail(message); ws?.close() }
    try {
      const mediaSource = window.MediaSource || window.ManagedMediaSource
      if (!mediaSource || !mediaSource.isTypeSupported('video/mp4; codecs="avc1.42c029"')) throw new Error('当前浏览器不支持 H.264 视频，请切换截图模式')
      feed = new LiveVideoFeed(() => {
        setStatus('buffering')
        pointer.current = null; lastPoint.current = null
        return new BufferedMseSink(JMuxer, { node: video.current, mode: 'video', fps: 30, flushingTime: 0, maxDelay: 150,
          clearBuffer: true, debug: false,
          onError: () => failAndClose('视频解码失败，请重新连接或切换截图模式'),
          onReady: () => { video.current?.play()?.catch(() => {}) },
        })
      })
      startupTimer = setTimeout(() => { if (!video.current || video.current.readyState < 2) failAndClose('视频启动超时，请重新连接或切换截图模式') }, 45000)
      lagTimer = setInterval(() => {
        const node = video.current
        if (!node || !node.buffered.length || node.readyState < 2) return
        const end = node.buffered.end(node.buffered.length - 1)
        // Seek in the decoded buffer; never discard dependent compressed frames.
        if (end - node.currentTime > .6) node.currentTime = Math.max(node.buffered.start(node.buffered.length - 1), end - .1)
      }, 500)
      const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const url = scheme + '//' + location.host + '/api/bots/' + encodeURIComponent(botId || 'default') + '/android/devices/' + device.id + '/live'
      ws = new WebSocket(url)
      ws.binaryType = 'arraybuffer'; socket.current = ws
      ws.onmessage = event => {
        if (!alive) return
        try {
          if (typeof event.data === 'string') {
            const message = JSON.parse(event.data)
            if (message.type === 'config') { setSize({ width: message.width, height: message.height }); setStatus('buffering') }
            if (message.type === 'control') { ownedRef.current = !!message.owned; setOwned(!!message.owned) }
            if (message.type === 'error') fail(message.message || '实时连接已结束，请重新连接或切换截图模式')
            return
          }
          feed.push(parseLiveFrame(event.data))
        } catch { fail('实时画面格式异常，请重新连接'); ws.close() }
      }
      ws.onerror = () => fail('实时连接失败，可重试或切换截图模式')
      ws.onclose = () => fail('实时连接已结束，重新连接不会重放之前的输入')
      timer = setInterval(() => { if (ws.readyState === WebSocket.OPEN) ws.send('{"type":"ping"}') }, 10000)
    } catch (reason) { fail(reason.message || '当前浏览器不支持视频流，请使用截图模式') }
    return () => {
      alive = false; clearInterval(timer); clearInterval(lagTimer); clearTimeout(startupTimer); ownedRef.current = false; pointer.current = null; lastPoint.current = null; ws?.close(); if (socket.current === ws) socket.current = null
      feed?.destroy()
    }
  }, [device.id, botId, generation, visible])
  async function claim() {
    if (taking || disabled) return
    setTaking(true); setError('')
    try {
      await onTakeover()
      const ws = socket.current
      if (!ws || ws.readyState !== WebSocket.OPEN) throw new Error('请先重新连接实时画面')
      ws.send('{"type":"claim"}')
    } catch (e) { setError(e.message) }
    finally { setTaking(false) }
  }
  function point(event) {
    const element = video.current
    return livePoint(event.clientX, event.clientY, element.getBoundingClientRect(), element.videoWidth || size.width, element.videoHeight || size.height)
  }
  function down(event) {
    if (!ownedRef.current || disabled || pointer.current !== null) return
    const value = point(event)
    if (!value) return
    event.preventDefault(); event.currentTarget.focus(); event.currentTarget.setPointerCapture(event.pointerId); pointer.current = event.pointerId
    lastPoint.current = value
    send({ type: 'pointer', action: 'down', ...value })
  }
  function move(event) {
    if (pointer.current !== event.pointerId || !ownedRef.current) return
    const value = point(event)
    if (!value) return
    event.preventDefault(); const now = performance.now(); if (now - lastMove.current < 16) return
    lastMove.current = now; lastPoint.current = value; send({ type: 'pointer', action: 'move', ...value })
  }
  function up(event) {
    if (pointer.current !== event.pointerId) return
    event.preventDefault()
    const value = point(event) || lastPoint.current
    if (value) send({ type: 'pointer', action: event.type === 'pointercancel' ? 'cancel' : 'up', ...value })
    pointer.current = null; lastPoint.current = null
  }
  return <div className="page-stack android-live">
    <div className="action-row justify-between"><Badge variant="outline">{owned ? '已接管 · 实时操作' : status === 'playing' ? '实时视频 · 观看中' : status === 'buffering' ? '正在缓冲实时画面…' : status === 'paused' ? '后台已暂停' : status === 'error' ? '连接已停止' : '正在连接实时画面…'}</Badge><span className="push-hint">H.264 · 最高 30 fps</span></div>
    <div className="android-screen android-live-screen" style={{ aspectRatio: size.width + '/' + size.height }}>
      <video data-testid="android-live-video" ref={video} muted autoPlay playsInline disablePictureInPicture
        onPlaying={() => setStatus('playing')} onResize={() => { const node = video.current; if (node?.videoWidth) setSize({ width: node.videoWidth, height: node.videoHeight }) }} style={{ touchAction: owned ? 'none' : 'pan-y' }} tabIndex={owned ? 0 : -1} aria-label="安卓实时画面" role="img"
        onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onContextMenu={e => e.preventDefault()}
        onKeyDown={e => { if (!ownedRef.current || e.isComposing || e.ctrlKey || e.metaKey || e.altKey) return; if (keyNames[e.key]) { e.preventDefault(); key(keyNames[e.key]) } else if (e.key.length === 1) { e.preventDefault(); send({ type: 'text', text: e.key }) } }}
        onCompositionEnd={e => { if (ownedRef.current && e.data) send({ type: 'text', text: e.data }) }} />
    </div>
    {error && <p role="status" className="push-hint">{error}</p>}
    <div className="action-row">
      {owned ? <Button size="sm" variant="outline" onClick={() => reconnect(v => v + 1)}>结束操作，继续观看</Button> : <Button size="sm" variant="outline" disabled={taking || disabled || status !== 'playing'} onClick={claim}>{taking ? '正在接管…' : '接管实时操作'}</Button>}
      <Button size="sm" variant="ghost" onClick={() => reconnect(v => v + 1)}>重新连接</Button>
      <Button size="sm" variant="ghost" onClick={onFallback}>截图模式</Button>
    </div>
    <p className="push-hint">观看不会占用 Bot。接管后可点击、拖动和键盘输入；Bot 手机任务会暂停。断线不重放输入，应用登录仍由 owner 完成。</p>
  </div>
})
