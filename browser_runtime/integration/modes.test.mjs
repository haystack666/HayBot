import test from 'node:test'
import assert from 'node:assert/strict'
import { once } from 'node:events'
import { promises as fs } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { WebSocket } from 'ws'
import { createRuntimeServer } from '../src/server.mjs'

test('both launch modes retain live streaming, manual input, login fence, profile and 300012 diagnostics', { skip: process.platform !== 'darwin', timeout: 90000 }, async t => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'haybot-modes-'))
  const token = 'mode-test-'.repeat(8), runtime = await createRuntimeServer({ directory, token, port: 0 })
  const engine = runtime.engine, sockets = []
  try {
    assert.equal((await engine.prepare()).state, 'ready')
    for (const headless of [false, true]) {
      await engine.configure('a', { headless, acknowledgeHeadlessRisk: headless })
      await engine.start('a')
      const session = engine.get('a'), page = session.tabs.get(session.active)
      const socket = new WebSocket(runtime.origin.replace('http:', 'ws:') + '/api/sessions/a/live', { headers: { Authorization: `Bearer ${token}` } }); sockets.push(socket)
      const hello = once(socket, 'message')
      await once(socket, 'open')
      const viewer = JSON.parse((await hello)[0]).connectionId
      const frames = []; socket.on('message', bytes => { const message = JSON.parse(bytes); if (message.type === 'frame') frames.push(message) })
      const { lease } = engine.claim('a', viewer)
      const act = input => { const state = engine.state('a'); return engine.action('a', { ...input, lease, generation: state.generation, tabId: state.activeTab }) }
      await act({ kind: 'navigate', url: runtime.origin + '/fixture' })
      const input = await page.locator('#message').boundingBox()
      await act({ kind: 'click', x: input.x + 10, y: input.y + 10 })
      await act({ kind: 'key', key: 'ControlOrMeta+A' })
      await act({ kind: 'text', text: '模式验收' + headless })
      assert.equal(await page.locator('#message').inputValue(), '模式验收' + headless)
      if (headless) assert.equal(await page.evaluate(() => localStorage.getItem('mode-preserved')), 'yes')
      await page.evaluate(() => localStorage.setItem('mode-preserved', 'yes'))
      const slider = await page.locator('#range').boundingBox()
      const gestureId = 'drag-' + headless
      await act({ kind: 'pointer', phase: 'start', mode: 'drag', gestureId, x: slider.x + slider.width * .2, y: slider.y + slider.height / 2 })
      await act({ kind: 'pointer', phase: 'end', gestureId, x: slider.x + slider.width * .8, y: slider.y + slider.height / 2 })
      assert.ok(Number(await page.locator('#range').inputValue()) >= 70)
      await page.waitForTimeout(500)
      assert.ok(frames.length > 0, 'real frames in ' + (headless ? 'headless' : 'headed') + ' mode')
      assert.equal(Buffer.from(frames.at(-1).data, 'base64').readUInt16BE(0), 0xffd8)
      assert.equal(engine.state('a').options.headless, headless)
      await assert.rejects(engine.configure('a', { headless: !headless, acknowledgeHeadlessRisk: true }), { code: 'settings_busy' })
      await engine.setLogin('a', lease, true)
      await assert.rejects(engine.observe('a'), { code: 'owner_login' })
      await engine.setLogin('a', lease, false)
      await page.route('https://www.xiaohongshu.com/**', route => route.fulfill({ contentType: 'text/html', body: '<h1>访问异常</h1><p>错误代码：300012</p>' }))
      await act({ kind: 'navigate', url: 'https://www.xiaohongshu.com/website-login/error?error_code=300012' })
      assert.equal(engine.state('a').access_issue.code, '300012')
      engine.release('a', lease)
      await assert.rejects(engine.observe('a'), { code: 'site_access_blocked' })
      const newLease = engine.claim('a', viewer).lease
      await engine.action('a', { kind: 'navigate', url: runtime.origin + '/fixture', lease: newLease, generation: session.generation, tabId: session.active })
      assert.equal(engine.state('a').access_issue, null)
      socket.close(); await once(socket, 'close')
      await engine.stop('a')
      t.diagnostic(`${headless ? 'headless' : 'headed'}: stream, text, drag, owner login and simulated site error passed`)
    }
  } finally { for (const socket of sockets) socket.terminate(); await runtime.close(); await fs.rm(directory, { recursive: true, force: true }) }
})
