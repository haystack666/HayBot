import test from 'node:test'
import assert from 'node:assert/strict'
import { once } from 'node:events'
import { promises as fs } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { execFile as execFileCallback } from 'node:child_process'
import { promisify } from 'node:util'
import { setTimeout as delay } from 'node:timers/promises'
import { WebSocket } from 'ws'
import { createRuntimeServer } from '../src/server.mjs'
const execFile = promisify(execFileCallback)
async function waitFor(predicate) {
  const deadline = Date.now() + 3000
  while (!predicate()) { if (Date.now() >= deadline) throw new Error('Timed out waiting for runtime state'); await delay(10) }
}

test('real macOS Chrome: hidden launch, streaming, controls, tabs, media and persistent isolated profiles', { timeout: 120000, skip: process.platform !== 'darwin' }, async t => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'haybot-chrome-test-'))
  const inspector = path.join(directory, 'macos-state')
  await execFile('/usr/bin/swiftc', [new URL('./macos-state.swift', import.meta.url).pathname, '-o', inspector], { timeout: 60000 })
  const token = 'integration-'.repeat(6), runtime = await createRuntimeServer({ directory, token, port: 0 })
  const engine = runtime.engine, sockets = []
  const action = (id, lease, input) => {
    const state = engine.state(id)
    return engine.action(id, { lease, generation: state.generation, tabId: state.activeTab, ...input })
  }
  async function inspectHidden(id) {
    const processes = (await execFile('/bin/ps', ['-axo', 'pid=,command='])).stdout
    const command = processes.split('\n').find(line => line.includes('--user-data-dir=' + path.join(directory, 'profiles', id)) && line.includes('Contents/MacOS/Google Chrome'))
    assert.ok(command, 'identify only the test-owned browser process')
    assert.match(command, /--headless(?:\s|=)/); assert.match(command, /--remote-debugging-pipe/); assert.match(command, /--mute-audio/)
    const pid = Number(command.trim().split(/\s+/)[0])
    const native = JSON.parse((await execFile(inspector, [String(pid)])).stdout)
    assert.equal(native.activationPolicy, 2, 'prohibited application activation: no Dock or app-switcher entry')
    assert.equal(native.visibleWindowCount, 0)
    assert.equal(native.active, false)
    t.diagnostic(`Native hidden state ${JSON.stringify(native)}`)
    return pid
  }
  try {
    const report = await engine.prepare(); assert.equal(report.state, 'ready', JSON.stringify(report))
    t.diagnostic(`Chrome ${report.chrome.version}; Node ${process.versions.node}; ${process.platform}/${process.arch}`)
    for (const id of ['a', 'b']) await engine.configure(id, { headless: true, acknowledgeHeadlessRisk: true })
    await Promise.all([engine.start('a'), engine.start('a')]); assert.equal(engine.sessions.size, 1)
    const session = engine.get('a'), page = session.tabs.get(session.active)
    // Browser.getVersion confirms the actual branded browser; launch options are not the evidence.
    const cdp = await session.context.newCDPSession(page)
    const version = await cdp.send('Browser.getVersion'); assert.match(version.product, /Chrome\//)
    await inspectHidden('a')
    await cdp.detach()
    let lease = engine.claim('a').lease
    await action('a', lease, { kind: 'navigate', url: runtime.origin + '/fixture' })
    assert.match((await engine.observe('a')).aria, /浏览器基础验收/)
    const ws = new WebSocket(runtime.origin.replace('http:', 'ws:') + '/api/sessions/a/live', { headers: { Authorization: `Bearer ${token}` } }); sockets.push(ws)
    const frames = []; let viewerConnection
    ws.on('message', data => { const message = JSON.parse(data); if (message.type === 'frame') frames.push(message); if (message.connectionId) viewerConnection = message.connectionId })
    await once(ws, 'open')
    await page.waitForTimeout(1400)
    assert.ok(frames.length >= 3, `received ${frames.length} frames`)
    assert.equal(frames[0].viewportWidth, 1280); assert.equal(frames[0].viewportHeight, 800)
    assert.equal(Buffer.from(frames[0].data, 'base64').readUInt16BE(0), 0xffd8)
    const frameCount = frames.length
    const claimed = await fetch(runtime.origin + '/api/sessions/a/claim', { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ connectionId: viewerConnection }) })
    assert.equal(claimed.status, 200); lease = (await claimed.json()).lease
    const ws2 = new WebSocket(runtime.origin.replace('http:', 'ws:') + '/api/sessions/a/live', { headers: { Authorization: `Bearer ${token}` } }); sockets.push(ws2)
    await once(ws2, 'open'); assert.equal(session.observers, 2); assert.ok(session.stream)
    ws2.close(); await once(ws2, 'close'); await waitFor(() => session.observers === 1); assert.equal(session.lease, lease)
    const input = await page.locator('#message').boundingBox()
    await action('a', lease, { kind: 'click', x: input.x + 20, y: input.y + 10 })
    await action('a', lease, { kind: 'text', text: '独立浏览器中文验收' })
    const save = await page.locator('#save').boundingBox()
    await action('a', lease, { kind: 'click', x: save.x + 10, y: save.y + 10 })
    assert.equal(await page.locator('#result').innerText(), '已保存：独立浏览器中文验收')
    await assert.rejects(engine.observe('a'), { code: 'owner_control' })
    engine.release('a', lease)
    const observed = await engine.observe('a'); assert.match(observed.aria, /独立浏览器中文验收/)
    lease = engine.claim('a').lease
    const before = await page.locator('#video').evaluate(video => video.currentTime)
    await page.waitForTimeout(400)
    const after = await page.locator('#video').evaluate(video => video.currentTime)
    assert.ok(after > before, 'synthetic video must actually advance')
    t.diagnostic('Local canvas video time advances; no audio capability claimed')
    const stale = { lease, generation: engine.state('a').generation, tabId: engine.state('a').activeTab, kind: 'text', text: 'must not arrive' }
    lease = engine.claim('a').lease
    await assert.rejects(engine.action('a', stale), { code: 'stale_control' })
    await action('a', lease, { kind: 'scroll', deltaX: 0, deltaY: 400 }); await page.waitForTimeout(150)
    assert.ok(await page.evaluate(() => window.scrollY) > 0)
    await action('a', lease, { kind: 'new_tab' }); const newTab = engine.state('a').activeTab
    assert.equal(engine.state('a').tabs.length, 2)
    await action('a', lease, { kind: 'navigate', url: runtime.origin + '/fixture?second=1' })
    await inspectHidden('a')
    await assert.rejects(engine.action('a', { ...stale, lease }), { code: 'stale_control' })
    await engine.setLogin('a', lease, true)
    await assert.rejects(engine.observe('a'), { code: 'owner_login' })
    await action('a', lease, { kind: 'close_tab' }); assert.notEqual(engine.state('a').activeTab, newTab)
    await page.waitForTimeout(600); assert.ok(frames.length > frameCount)
    await engine.stop('a'); await engine.start('a'); lease = engine.claim('a').lease
    assert.equal(engine.state('a').owner_login, true, 'login fence survives browser stop/start')
    await assert.rejects(engine.observe('a'), { code: 'owner_login' })
    await engine.setLogin('a', lease, false)
    await action('a', lease, { kind: 'navigate', url: runtime.origin + '/fixture' })
    let current = engine.get('a'); let currentPage = current.tabs.get(current.active)
    assert.equal(await currentPage.locator('#message').inputValue(), '独立浏览器中文验收')
    assert.ok((await current.context.cookies(runtime.origin)).some(cookie => cookie.name === 'fixture'))
    await engine.start('b'); const leaseB = engine.claim('b').lease
    await action('b', leaseB, { kind: 'navigate', url: runtime.origin + '/fixture' })
    current = engine.get('b'); currentPage = current.tabs.get(current.active)
    assert.equal(await currentPage.locator('#message').inputValue(), '')
    assert.ok(!(await current.context.cookies(runtime.origin)).some(cookie => cookie.name === 'fixture'))
    const pidB = await inspectHidden('b')
    const competing = new (engine.constructor)(directory)
    try { await assert.rejects(competing.start('b'), { code: 'launch_failed' }) } finally { await competing.close() }
    const disconnected = once(current.context, 'close')
    process.kill(pidB, 'SIGKILL'); await disconnected
    assert.equal(engine.state('b').state, 'stopped'); await engine.start('b'); await inspectHidden('b')
    const recoveredLease = engine.claim('b').lease
    await action('b', recoveredLease, { kind: 'close_tab' })
    assert.equal(engine.state('b').tabs.length, 0)
    await action('b', recoveredLease, { kind: 'new_tab' }); assert.equal(engine.state('b').tabs.length, 1)
    const controlSocket = new WebSocket(runtime.origin.replace('http:', 'ws:') + '/api/sessions/b/live', { headers: { Authorization: `Bearer ${token}` } }); sockets.push(controlSocket)
    const firstState = once(controlSocket, 'message')
    await once(controlSocket, 'open'); const controlId = JSON.parse((await firstState)[0]).connectionId
    const grant = await fetch(runtime.origin + '/api/sessions/b/claim', { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ connectionId: controlId }) })
    assert.equal(grant.status, 200); const lostLease = (await grant.json()).lease
    controlSocket.close(); await once(controlSocket, 'close'); await waitFor(() => engine.get('b').lease === null)
    assert.equal(engine.get('b').lease, null)
    await assert.rejects(action('b', lostLease, { kind: 'text', text: 'no replay' }), { code: 'stale_control' })
    t.diagnostic(`Received ${frames.length} frames; first sample ${frameCount} frames / 1.4s; persistent storage isolated; crash recovered`)
    const noAuth = new WebSocket(runtime.origin.replace('http:', 'ws:') + '/api/sessions/b/live')
    noAuth.on('error', () => {}); await once(noAuth, 'unexpected-response').then(([, response]) => { assert.equal(response.statusCode, 403); response.destroy() })
  } finally {
    for (const ws of sockets) ws.terminate()
    await runtime.close(); await fs.rm(directory, { recursive: true, force: true })
  }
})
