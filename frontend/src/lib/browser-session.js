import { bindScreenInput } from './browser-input.js'

// One controller per mounted Bot workspace. Frames and inputs carry a connection
// epoch, tab ID and generation so remounts/navigation cannot replay old gestures.
export function createBrowserSession({ api, botId, canvas, mode, change, report }) {
  let state = { state: 'stopped', tabs: [] }, lease = null, connectionId = null
  let socket, epoch = 0, connected = false, ready = false, busy = false, disposed = false
  let viewport, pendingFrame, drawing = false, queue = Promise.resolve(), stream = '浏览器已停止'
  const snapshot = () => ({ state, connected, busy, owned: !!lease, canControl: !!lease && connected && ready && !busy, stream })
  const notify = () => { input.sync(); if (!disposed) change(snapshot()) }
  function clearFrame() {
    input.reset(); viewport = null; pendingFrame = null
    delete canvas.dataset.frameGeneration
    canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height)
  }
  function apply(next) {
    if (next.generation < state.generation && next.id === state.id) return
    if (next.generation !== state.generation || next.activeTab !== state.activeTab || next.id !== state.id) {
      clearFrame(); stream = '等待最新画面…'
    }
    state = next
    if (state.state !== 'owner_control' || state.controller !== connectionId) lease = null
    notify()
  }
  async function draw() {
    if (drawing) return
    drawing = true
    try {
      while (pendingFrame && !disposed) {
        const frame = pendingFrame; pendingFrame = null
        const bytes = Uint8Array.from(atob(frame.data), char => char.charCodeAt(0))
        const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/jpeg' }))
        if (disposed || frame.epoch !== epoch || frame.generation !== state.generation || frame.tabId !== state.activeTab) { bitmap.close(); continue }
        canvas.width = bitmap.width; canvas.height = bitmap.height
        canvas.getContext('2d').drawImage(bitmap, 0, 0); bitmap.close()
        canvas.dataset.frameGeneration = frame.generation
        canvas.dataset.viewportWidth = frame.viewportWidth; canvas.dataset.viewportHeight = frame.viewportHeight
        viewport = { width: frame.viewportWidth, height: frame.viewportHeight, generation: frame.generation, tabId: frame.tabId }
        if (stream !== '实时画面') { stream = '实时画面'; notify() }
      }
    } catch { if (!disposed) report('画面解码失败，请重新连接') }
    finally { drawing = false; if (pendingFrame && !disposed) draw() }
  }
  function connect() {
    const current = ++epoch
    socket?.close(); clearFrame(); connected = false; lease = null; connectionId = null
    if (disposed || state.state === 'stopped') { stream = '浏览器已停止'; notify(); return }
    stream = '正在连接画面…'; notify()
    const url = new URL(`/api/bots/${encodeURIComponent(botId)}/browser/live`, location.href)
    url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    socket = new WebSocket(url)
    socket.onmessage = event => {
      if (current !== epoch || disposed) return
      try {
        const message = JSON.parse(event.data)
        if (message.type === 'state') {
          if (message.connectionId) { connectionId = message.connectionId; connected = true }
          apply(message.state)
        } else if (message.type === 'frame') { pendingFrame = { ...message, epoch: current }; draw() }
        else if (message.type === 'stream_error') { stream = message.detail; notify() }
      } catch { report('浏览器画面响应无效，请重新连接') }
    }
    socket.onclose = () => {
      if (current !== epoch || disposed) return
      connected = false; lease = null; connectionId = null; clearFrame()
      stream = state.state === 'stopped' ? '浏览器已停止' : '画面已断开，请重新连接'; notify()
    }
  }
  const context = () => lease && connected && ready && !busy && !disposed ? { session: botId, lease, connectionId, generation: state.generation, tabId: state.activeTab, epoch } : null
  function dispatch(action, captured = context()) {
    const result = queue.catch(() => {}).then(async () => {
      if (!captured || disposed || captured.epoch !== epoch || captured.lease !== lease || !connected || !ready) throw new Error('请先接管当前浏览器')
      const next = await api('/browser/control/action', 'POST', { ...action, connectionId: captured.connectionId, lease: captured.lease, generation: captured.generation, tabId: captured.tabId })
      if (!disposed && captured.epoch === epoch) apply(next)
    })
    queue = result
    return result
  }
  const input = bindScreenInput({ canvas, mode, getView: () => viewport, getContext: context, send: dispatch, report })
  async function run(callback) {
    if (busy || disposed) return
    input.cancel(); busy = true; notify()
    try { await callback() } catch (error) { if (!disposed) report(error.message) }
    finally { busy = false; notify() }
  }
  async function refresh() {
    const result = await api('/browser')
    if (disposed) return
    if (!result.configured) throw new Error('宿主浏览器运行时尚未配置')
    // A restarted host can reset generation counters. The old stream is already
    // revoked before accepting a fresh snapshot.
    state = result.session; connect()
  }
  return {
    open: () => run(refresh),
    setReady(value) { ready = value; if (!ready) input.cancel(); notify() },
    start: () => run(async () => { state = await api('/browser/start', 'POST', {}); if (!disposed) connect() }),
    configure: options => run(async () => {
      apply(await api('/browser/settings', 'POST', options))
    }),
    stop: () => run(async () => { apply(await api('/browser/stop', 'POST', {})); lease = null; clearFrame() }),
    reconnect: () => run(async () => { ++epoch; socket?.close(); lease = null; connected = false; clearFrame(); await refresh() }),
    claim: () => run(async () => {
      const current = epoch
      if (!connectionId || !connected) throw new Error('请先连接当前浏览器画面')
      if (lease) { apply(await api('/browser/control/release', 'POST', { connectionId, lease })); lease = null }
      else {
        const grant = await api('/browser/control/claim', 'POST', { connectionId })
        if (disposed || current !== epoch || !connected) return
        lease = grant.lease
        const fresh = await api('/browser')
        if (!disposed && current === epoch) apply(fresh.session)
      }
    }),
    login: () => run(async () => { apply(await api(`/browser/login/${state.owner_login ? 'finish' : 'begin'}`, 'POST', { connectionId, lease })) }),
    act: action => dispatch(action).then(() => true).catch(error => { if (!disposed) report(error.message); return false }),
    cancel: () => input.cancel(),
    dispose() { input.dispose(); disposed = true; ++epoch; socket?.close(); lease = null; clearFrame() },
  }
}
