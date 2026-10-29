import test from 'node:test'
import assert from 'node:assert/strict'
import { BrowserWindows } from '../src/windows.mjs'
import { BrowserEngine } from '../src/engine.mjs'

test('window restore uses captured window/opener state and leaves normal windows alone', async () => {
  const bounds = new Map([[1, 'minimized'], [2, 'normal']]), changes = []
  const page = (windowId, opener = null) => ({ windowId, isClosed: () => false, opener: async () => opener })
  const minimized = page(1), normal = page(2), pages = [minimized, normal]
  const windows = new BrowserWindows({
    pages: () => pages,
    newCDPSession: async page => ({ send: async (method, input) => {
      if (method === 'Browser.getWindowForTarget') return { windowId: page.windowId, bounds: { windowState: bounds.get(page.windowId) } }
      changes.push(input.windowId)
      bounds.set(input.windowId, input.bounds.windowState)
    } }),
  })
  await windows.capture()
  bounds.set(1, 'normal')
  bounds.set(3, 'normal'); pages.push(page(3, minimized))
  bounds.set(4, 'normal'); pages.push(page(4, normal))
  bounds.set(5, 'normal'); pages.push(page(5))
  await windows.restore()
  assert.deepEqual(changes.sort(), [1, 3])
  assert.equal(bounds.get(2), 'normal')
  assert.equal(bounds.get(4), 'normal')
  assert.equal(bounds.get(5), 'normal')
  bounds.set(1, 'normal')
  await windows.capture(); await windows.restore()
  assert.equal(bounds.get(1), 'normal', 'the next action respects explicit native restore')
})

test('takeover while reading native window state blocks the pending click', async () => {
  const engine = new BrowserEngine('/tmp/unused'); engine.environment.cached = { state: 'ready' }
  let unblock, captured, clicked = false
  const reading = new Promise(resolve => { captured = resolve })
  const blocked = new Promise(resolve => { unblock = resolve })
  const session = { id: 'one', context: {}, lease: 'old', active: 'tab', generation: 1, tabs: new Map([['tab', { url: () => 'about:blank', mouse: { click: async () => { clicked = true } } }]]), titles: new Map(), observers: 0, operation: Promise.resolve(), streamJob: Promise.resolve(), windows: { capture: async () => { captured(); await blocked } } }
  engine.sessions.set('one', session)
  try {
    const pending = engine.action('one', { lease: 'old', tabId: 'tab', generation: 1, kind: 'click', x: 10, y: 10 })
    await reading
    engine.claim('one', 'other-owner')
    unblock()
    await assert.rejects(pending, { code: 'stale_control' })
    assert.equal(clicked, false)
  } finally { session.context = null; await engine.close() }
})
