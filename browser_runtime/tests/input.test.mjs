import test from 'node:test'
import assert from 'node:assert/strict'
import { framePoint, wheelPixels } from '../public/input.js'
import { BrowserEngine } from '../src/engine.mjs'
import { readFile } from 'node:fs/promises'

test('prototype and formal workbench use the same gesture implementation', async () => {
  assert.equal(await readFile(new URL('../public/input.js', import.meta.url), 'utf8'), await readFile(new URL('../../frontend/src/lib/browser-input.js', import.meta.url), 'utf8'))
})

test('frame mapping accounts for letterboxing, borders, enlargement and out-of-frame moves', () => {
  const canvas = { width: 1280, height: 800, clientLeft: 1, clientTop: 1, getBoundingClientRect: () => ({ left: 10, top: 20, width: 802, height: 802 }) }
  const view = { width: 1280, height: 800 }
  assert.deepEqual(framePoint(canvas, view, 411, 421), { x: 640, y: 400 })
  assert.equal(framePoint(canvas, view, 411, 40), null)
  assert.equal(framePoint(canvas, view, 411, 21), null)
  assert.equal(framePoint(canvas, view, 411, 1000, true).y, 799.99)
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1282, height: 802 })
  assert.deepEqual(framePoint(canvas, view, 641, 401), { x: 640, y: 400 })
})

test('wheel line/page units are normalized and bounded in both directions', () => {
  assert.deepEqual(wheelPixels({ deltaMode: 1, deltaX: 2, deltaY: -3 }, 800), { deltaX: 32, deltaY: -48 })
  assert.deepEqual(wheelPixels({ deltaMode: 2, deltaX: 1, deltaY: 10 }, 800), { deltaX: 800, deltaY: 3000 })
})

function fakeSession() {
  const engine = new BrowserEngine('/tmp/unused'); engine.environment.cached = { state: 'ready' }
  const events = [], page = { viewportSize: () => ({ width: 1280, height: 800 }), url: () => 'about:blank', mouse: {} }
  for (const name of ['move', 'down', 'up', 'wheel', 'click']) page.mouse[name] = async (...args) => { events.push([name, ...args]) }
  const session = { id: 'one', context: {}, lease: 'lease', generation: 1, active: 'tab', tabs: new Map([['tab', page]]), titles: new Map(), operation: Promise.resolve(), streamJob: Promise.resolve(), observers: 0 }
  engine.sessions.set('one', session)
  const send = input => engine.action('one', { lease: session.lease, generation: session.generation, tabId: session.active, kind: 'pointer', gestureId: 'gesture', ...input })
  return { engine, session, events, page, send, close: async () => { engine.cancelPointer(session); await session.operation.catch(() => {}); session.context = null; await engine.close() } }
}

test('drag is down/move/up and takeover releases held input before a new owner', async () => {
  const fixture = fakeSession(), { send, events, engine, session } = fixture
  try {
    await send({ phase: 'start', mode: 'drag', x: 10, y: 20 })
    await send({ phase: 'move', x: 90, y: 40 })
    await send({ phase: 'end', x: 120, y: 40 })
    assert.deepEqual(events.map(event => event[0]), ['move', 'down', 'move', 'move', 'up'])
    assert.equal(session.pointer, null)
    await send({ phase: 'start', mode: 'drag', x: 10, y: 20 })
    const previous = { lease: session.lease, generation: session.generation, tabId: session.active, kind: 'pointer', gestureId: 'gesture', phase: 'end', x: 10, y: 20 }
    engine.claim('one', 'other'); await session.operation
    assert.deepEqual(events.slice(-2), [['move', -1, -1], ['up']])
    await assert.rejects(engine.action('one', previous), { code: 'stale_control' })
    await assert.rejects(send({ phase: 'end', x: 10, y: 20 }), { code: 'stale_pointer' })
  } finally { await fixture.close() }
})

test('swipe routes wheel to its anchor and cancellation never becomes a click', async () => {
  const fixture = fakeSession(), { send, events } = fixture
  try {
    await send({ phase: 'start', mode: 'swipe', x: 200, y: 300 })
    await send({ phase: 'move', x: 180, y: 200 })
    await send({ phase: 'end', x: 160, y: 180 })
    assert.ok(events.some(event => event[0] === 'wheel' && event[1] === 20 && event[2] === 100))
    assert.equal(events.some(event => ['down', 'click'].includes(event[0])), false)
    await send({ phase: 'start', mode: 'swipe', x: 10, y: 20 })
    await send({ phase: 'cancel' })
    assert.equal(events.some(event => event[0] === 'click'), false)
    await assert.rejects(send({ phase: 'start', mode: 'drag', x: NaN, y: 0 }), { code: 'invalid_coordinates' })
    await assert.rejects(send({ phase: 'start', mode: 'arbitrary', x: 0, y: 0 }), { code: 'invalid_pointer' })
  } finally { await fixture.close() }
})
