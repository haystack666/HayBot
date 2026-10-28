const $ = id => document.getElementById(id)
let environment, state = { state: 'stopped', tabs: [] }, lease = null, socket, epoch = 0, session = 'prototype-a', busy = false, drawing = false, pendingFrame, viewport, lastFrameAt = 0, expanded = false, connected = false
let actionQueue = Promise.resolve(), connectionId = null
const controls = document.querySelectorAll('[data-control]')
function notice(message = '') { $('notice').textContent = message }
async function api(url, method = 'GET', value, token) {
  let response
  try { response = await fetch('/api' + url, { method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) }, body: value === undefined ? undefined : JSON.stringify(value) }) }
  catch { throw new Error('宿主运行时未连接，请启动服务后重新连接') }
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || '操作失败')
  return data
}
function render() {
  const active = state.state !== 'stopped', canControl = active && connected && !!lease && environment?.state === 'ready'
  $('start').disabled = busy || active || environment?.state !== 'ready'
  $('stop').disabled = busy || !active; $('session').disabled = busy
  $('claim').disabled = busy || !active || !connected || environment?.state !== 'ready'; $('claim').textContent = lease ? '结束接管' : '接管'
  $('observe').disabled = !active; $('expand').disabled = !active && !expanded
  $('reconnect').disabled = busy || !active
  $('address').disabled = !canControl; $('text').disabled = !canControl
  for (const control of controls) control.disabled = busy || !canControl
  $('session-state').textContent = active && !connected ? '画面未连接' : state.state === 'owner_control' && !lease ? '其他连接已接管' : ({ stopped: '已停止', ready: '运行中', owner_control: '已接管' })[state.state] || state.state
  if (document.activeElement !== $('address')) $('address').value = state.tabs.find(tab => tab.id === state.activeTab)?.url || ''
  $('tabs').replaceChildren(...state.tabs.map(tab => {
    const button = document.createElement('button'); button.textContent = tab.title; button.title = tab.url; button.setAttribute('role', 'tab'); button.setAttribute('aria-selected', tab.id === state.activeTab); button.disabled = !canControl
    button.onclick = () => act({ kind: 'switch_tab', target: tab.id }); return button
  }))
}
async function check(force = false) {
  $('environment').hidden = false; $('environment-state').textContent = '检测中'; $('check').disabled = true
  try {
    environment = await api('/environment', force ? 'POST' : 'GET')
    $('environment-state').textContent = ({ ready: '环境就绪', needs_install: '待安装', needs_repair: '待修复', checking: '检测中' })[environment.state]
    $('checks').replaceChildren(...environment.checks.map(check => {
      const row = document.createElement('div'); row.className = 'check'
      for (const [text, className] of [[check.label, ''], [check.detail, 'check-detail'], [({ passed: '通过', failed: '未通过', pending: '待检查' })[check.state], check.state]]) { const span = document.createElement('span'); span.textContent = text; span.className = className; row.append(span) }
      return row
    }))
    $('install').hidden = environment.state !== 'needs_install'
    $('checks').hidden = environment.state === 'ready'; $('details').hidden = false
    $('details').textContent = $('checks').hidden ? '查看检测项' : '收起检测项'; $('details').setAttribute('aria-expanded', !$('checks').hidden)
    $('workspace').hidden = false; render()
  } catch (error) { environment = null; $('environment-state').textContent = '宿主未连接'; notice(error.message); render() }
  finally { $('check').disabled = false }
}
function clearFrame() { pendingFrame = null; viewport = null; lastFrameAt = 0; const context = $('screen').getContext('2d'); context.clearRect(0, 0, $('screen').width, $('screen').height) }
function connectStream() {
  socket?.close(); clearFrame(); connected = false; connectionId = null; const current = ++epoch
  if (state.state === 'stopped') { render(); return }
  $('stream-state').textContent = '正在连接画面…'
  socket = new WebSocket(location.origin.replace('http:', 'ws:') + `/api/sessions/${session}/live`)
  socket.onopen = () => { if (current === epoch) { connected = true; render() } }
  socket.onmessage = event => {
    if (current !== epoch) return
    const message = JSON.parse(event.data)
    if (message.type === 'state') {
      if (message.connectionId) connectionId = message.connectionId
      if (state.generation !== message.state.generation) { pendingFrame = null; viewport = null }
      if (message.state.state !== 'owner_control' || message.state.controller !== connectionId) lease = null
      state = message.state; render()
    } else if (message.type === 'frame') { pendingFrame = { ...message, connectionEpoch: current }; draw() }
    else if (message.type === 'stream_error') $('stream-state').textContent = message.detail
  }
  socket.onclose = () => { if (current === epoch) { connected = false; lease = null; $('stream-state').textContent = state.state === 'stopped' ? '浏览器已停止' : '画面连接已断开，请重新连接'; viewport = null; render() } }
}
async function draw() {
  if (drawing) return
  drawing = true
  try {
    while (pendingFrame) {
      const frame = pendingFrame; pendingFrame = null
      const bytes = Uint8Array.from(atob(frame.data), char => char.charCodeAt(0))
      const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/jpeg' }))
      if (frame.connectionEpoch !== epoch || frame.tabId !== state.activeTab || frame.generation !== state.generation) { bitmap.close(); continue }
      const canvas = $('screen'); canvas.width = bitmap.width; canvas.height = bitmap.height; canvas.getContext('2d').drawImage(bitmap, 0, 0); bitmap.close()
      viewport = { width: frame.viewportWidth, height: frame.viewportHeight, generation: frame.generation, tabId: frame.tabId }; lastFrameAt = Date.now(); $('stream-state').textContent = '实时画面 · 观看中'
    }
  } catch { notice('画面解码失败，请重新连接') }
  finally { drawing = false; if (pendingFrame) draw() }
}
function act(input) {
  const expectedSession = session, capturedLease = lease, generation = input.generation ?? state.generation, tabId = input.tabId ?? state.activeTab
  const run = actionQueue.catch(() => {}).then(async () => {
    if (expectedSession !== session || capturedLease !== lease || !lease || !connected) throw new Error('请先接管当前浏览器')
    const result = await api(`/sessions/${session}/action`, 'POST', { ...input, lease, generation, tabId })
    if (expectedSession === session) { state = result; render() }
  }).catch(error => notice(error.message))
  actionQueue = run; return run
}
async function run(callback) { busy = true; notice(); render(); try { await callback() } catch (error) { notice(error.message) } finally { busy = false; render() } }
$('connect').onsubmit = event => { event.preventDefault(); run(async () => { await api('/connect', 'POST', {}, $('token').value); $('token').value = ''; $('connect').hidden = true; await enter() }) }
async function enter() { await check(); state = await api(`/sessions/${session}`); render(); connectStream() }
$('check').onclick = () => check(true)
$('reconnect').onclick = () => run(async () => { lease = null; state = await api(`/sessions/${session}`); connectStream() })
$('details').onclick = () => { $('checks').hidden = !$('checks').hidden; $('details').textContent = $('checks').hidden ? '查看检测项' : '收起检测项'; $('details').setAttribute('aria-expanded', !$('checks').hidden) }
$('start').onclick = () => run(async () => { state = await api(`/sessions/${session}/start`, 'POST', {}); render(); connectStream() })
$('stop').onclick = () => run(async () => { state = await api(`/sessions/${session}/stop`, 'POST', {}); lease = null; clearFrame(); render() })
$('claim').onclick = () => run(async () => {
  if (lease) { state = await api(`/sessions/${session}/release`, 'POST', { lease }); lease = null }
  else { const grant = await api(`/sessions/${session}/claim`, 'POST', { connectionId }); lease = grant.lease; state = await api(`/sessions/${session}`) }
})
$('session').onchange = () => run(async () => {
  if (lease) await api(`/sessions/${session}/release`, 'POST', { lease })
  lease = null; session = $('session').value; state = await api(`/sessions/${session}`); render(); connectStream()
})
$('navigate').onclick = () => act({ kind: 'navigate', url: $('address').value })
$('address').onkeydown = event => { if (event.key === 'Enter') $('navigate').click() }
$('fixture').onclick = () => act({ kind: 'navigate', url: location.origin + '/fixture' })
for (const id of ['back', 'forward', 'reload']) $(id).onclick = () => act({ kind: id })
$('new-tab').onclick = () => act({ kind: 'new_tab' }); $('close-tab').onclick = () => act({ kind: 'close_tab' })
$('insert').onclick = () => { const text = $('text').value; $('text').value = ''; act({ kind: 'text', text }) }
$('observe').onclick = () => run(async () => { const result = await api(`/sessions/${session}/observe`); $('structure').textContent = result.aria; $('structure').hidden = false })
$('screen').onclick = event => {
  if (!lease || !viewport) return
  const rect = $('screen').getBoundingClientRect(), scale = Math.min(rect.width / $('screen').width, rect.height / $('screen').height)
  const x = (event.clientX - rect.left - (rect.width - $('screen').width * scale) / 2) / scale / $('screen').width * viewport.width
  const y = (event.clientY - rect.top - (rect.height - $('screen').height * scale) / 2) / scale / $('screen').height * viewport.height
  if (x < 0 || y < 0 || x >= viewport.width || y >= viewport.height) return
  $('screen').focus(); act({ kind: 'click', x, y, tabId: viewport.tabId, generation: viewport.generation })
}
$('screen').addEventListener('wheel', event => { if (!lease || !viewport) return; event.preventDefault(); act({ kind: 'scroll', deltaX: Math.max(-3000, Math.min(3000, event.deltaX)), deltaY: Math.max(-3000, Math.min(3000, event.deltaY)) }) }, { passive: false })
$('screen').onkeydown = event => {
  if (!lease || event.isComposing || event.key === 'Escape' && expanded) return
  if (event.key.length === 1 && !event.ctrlKey && !event.metaKey) { event.preventDefault(); act({ kind: 'text', text: event.key }) }
  else {
    const key = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a' ? 'ControlOrMeta+A' : event.shiftKey && event.key === 'Tab' ? 'Shift+Tab' : event.key
    if (['Enter', 'Tab', 'Shift+Tab', 'Escape', 'Backspace', 'Delete', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'ControlOrMeta+A'].includes(key)) { event.preventDefault(); act({ kind: 'key', key }) }
  }
}
$('screen').addEventListener('compositionend', event => { if (lease && event.data) act({ kind: 'text', text: event.data }) })
function expand(value) { expanded = value; $('viewer').classList.toggle('expanded', value); $('expand').textContent = value ? '收起画面' : '放大画面'; document.body.style.overflow = value ? 'hidden' : ''; $('expand').focus() }
$('expand').onclick = () => expand(!expanded)
document.addEventListener('keydown', event => { if (expanded && event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); expand(false) } }, true)
$('theme').onclick = () => {
  const theme = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
  document.documentElement.dataset.theme = theme === 'dark' ? 'light' : 'dark'
}
setInterval(() => { if (socket?.readyState === WebSocket.OPEN && lastFrameAt && Date.now() - lastFrameAt > 15000) $('stream-state').textContent = '连接正常 · 15 秒无新画面' }, 5000)
api('/health').then(() => { $('connect').hidden = true; return enter() }).catch(() => {})
