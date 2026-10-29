// Shared by mouse, trackpad and touch; all coordinates refer to the displayed frame.
export function framePoint(canvas, view, clientX, clientY, clamp = false) {
  if (!view) return null
  const rect = canvas.getBoundingClientRect()
  const width = rect.width - canvas.clientLeft * 2, height = rect.height - canvas.clientTop * 2
  const scale = Math.min(width / canvas.width, height / canvas.height)
  if (!(scale > 0)) return null
  const x = (clientX - rect.left - canvas.clientLeft - (width - canvas.width * scale) / 2) / (canvas.width * scale) * view.width
  const y = (clientY - rect.top - canvas.clientTop - (height - canvas.height * scale) / 2) / (canvas.height * scale) * view.height
  if (!clamp && (x < 0 || y < 0 || x >= view.width || y >= view.height)) return null
  return { x: Math.max(0, Math.min(view.width - 0.01, x)), y: Math.max(0, Math.min(view.height - 0.01, y)) }
}

export function wheelPixels(event, height) {
  const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? height : 1
  return { deltaX: Math.max(-3000, Math.min(3000, event.deltaX * unit)), deltaY: Math.max(-3000, Math.min(3000, event.deltaY * unit)) }
}

export function bindScreenInput({ canvas, mode, getView, getContext, send, report }) {
  const events = new AbortController()
  const on = (target, name, listener, options = {}) => target.addEventListener(name, listener, { ...options, signal: events.signal })
  let gesture = null, wheel = null, wheelRunning = false
  const sameContext = expected => {
    const current = getContext()
    return current && ['session', 'lease', 'generation', 'tabId', 'epoch'].every(key => current[key] === expected[key])
  }
  function capture() {
    const context = getContext(), view = getView()
    return context && view && context.generation === view.generation && context.tabId === view.tabId ? { context: { ...context }, view: { ...view } } : null
  }
  function releaseCapture(pointerId) {
    if (canvas.hasPointerCapture(pointerId)) canvas.releasePointerCapture(pointerId)
  }
  function reset() {
    const previous = gesture; gesture = null; wheel = null
    if (previous) { previous.pending = null; previous.terminal = null; releaseCapture(previous.pointerId) }
    canvas.classList.remove('dragging')
    delete canvas.dataset.inputBusy
  }
  async function pump(current) {
    if (current.running) return
    current.running = true
    try {
      while (gesture === current && sameContext(current.context)) {
        const next = current.pending || current.terminal
        if (!next) break
        if (current.pending) current.pending = null
        else current.terminal = null
        await send({ kind: 'pointer', gestureId: current.id, mode: current.mode, ...next }, current.context)
        if (next.phase === 'end' || next.phase === 'cancel') { if (gesture === current) reset(); break }
      }
    } catch (error) {
      if (gesture === current) {
        reset(); report(error.message)
        // Release a successfully delivered down after a later transport failure, never replay it.
        if (sameContext(current.context)) send({ kind: 'pointer', gestureId: current.id, phase: 'cancel' }, current.context).catch(() => {})
      }
    } finally { current.running = false }
  }
  function finish(event, cancelled = false) {
    const current = gesture
    if (!current || current.pointerId !== event.pointerId || current.finishing) return
    if (!sameContext(current.context)) { reset(); return }
    const point = cancelled ? null : framePoint(canvas, current.view, event.clientX, event.clientY, true)
    current.finishing = true
    current.terminal = cancelled ? { phase: 'cancel' } : { phase: 'end', ...point }
    if (cancelled) current.pending = null
    canvas.classList.remove('dragging'); releaseCapture(current.pointerId); pump(current)
  }
  on(canvas, 'pointerdown', event => {
    if (event.button !== 0 || !event.isPrimary || gesture) return
    const captured = capture(), point = captured && framePoint(canvas, captured.view, event.clientX, event.clientY)
    if (!point) return
    event.preventDefault(); canvas.focus({ preventScroll: true }); canvas.setPointerCapture(event.pointerId)
    gesture = { ...captured, id: crypto.randomUUID(), pointerId: event.pointerId, mode: mode.value === 'swipe' || mode.value === 'auto' && event.pointerType === 'touch' ? 'swipe' : 'drag', pending: { phase: 'start', ...point }, terminal: null, running: false }
    canvas.classList.add('dragging'); canvas.dataset.inputBusy = 'true'; pump(gesture)
  })
  on(canvas, 'pointermove', event => {
    const current = gesture
    if (!current || current.pointerId !== event.pointerId || current.finishing) return
    if (!sameContext(current.context)) { reset(); return }
    event.preventDefault()
    current.pending = { phase: 'move', ...framePoint(canvas, current.view, event.clientX, event.clientY, true) }
    pump(current)
  })
  on(canvas, 'pointerup', event => finish(event))
  on(canvas, 'pointercancel', event => finish(event, true))
  on(canvas, 'lostpointercapture', event => {
    if (gesture && !gesture.terminal && !gesture.finishing) finish(event, true)
  })
  // Moves are coalesced to one pending position, wheels to one pending delta;
  // never append an unbounded stream of HTTP requests while the receiver is slow.
  async function pumpWheel() {
    if (wheelRunning) return
    wheelRunning = true
    try {
      while (wheel) {
        const current = wheel; wheel = null
        if (sameContext(current.context)) await send({ kind: 'scroll', ...current.point, ...current.delta }, current.context)
      }
    } catch (error) { wheel = null; report(error.message) }
    finally { wheelRunning = false }
  }
  on(canvas, 'wheel', event => {
    const captured = capture(), point = captured && framePoint(canvas, captured.view, event.clientX, event.clientY)
    if (!point || event.ctrlKey) return
    event.preventDefault()
    if (gesture) return
    const delta = wheelPixels(event, captured.view.height)
    if (wheel && ['session', 'lease', 'generation', 'tabId', 'epoch'].every(key => wheel.context[key] === captured.context[key])) {
      wheel.delta.deltaX = Math.max(-3000, Math.min(3000, wheel.delta.deltaX + delta.deltaX))
      wheel.delta.deltaY = Math.max(-3000, Math.min(3000, wheel.delta.deltaY + delta.deltaY)); wheel.point = point
    } else wheel = { context: captured.context, point, delta }
    pumpWheel()
  }, { passive: false })
  function cancel() {
    wheel = null
    const current = gesture
    if (!current) return
    reset()
    if (sameContext(current.context)) send({ kind: 'pointer', gestureId: current.id, phase: 'cancel' }, current.context).catch(error => report(error.message))
  }
  on(mode, 'change', cancel)
  on(window, 'blur', cancel)
  on(document, 'visibilitychange', () => { if (document.hidden) cancel() })
  return { reset, cancel, dispose: () => { cancel(); events.abort() }, sync: () => { if (gesture && !sameContext(gesture.context)) reset() } }
}
