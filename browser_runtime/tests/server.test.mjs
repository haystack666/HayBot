import test from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import http from 'node:http'
import { createRuntimeServer } from '../src/server.mjs'

class FakeEngine extends EventEmitter {
  constructor() { super(); this.calls = 0; this.environment = { public: value => value }; this.report = { state: 'needs_install', checks: [], installUrl: 'https://www.google.cn/chrome/' } }
  prepare() { this.calls++; return this.report }
  state() { return { state: 'stopped' } }
  async settings() { return { headless: false } }
  async close() {}
}
test('runtime rejects anonymous, cross-origin, and oversized mutations; HTTP cookie is protected', async () => {
  const token = 'a'.repeat(64), engine = new FakeEngine(), runtime = await createRuntimeServer({ token, engine, port: 0 })
  const request = (route, init) => fetch(runtime.origin + route, init)
  try {
    assert.equal((await request('/api/environment')).status, 401)
    assert.equal((await request('/api/environment', { headers: { Authorization: `Bearer ${token}`, Origin: 'https://untrusted.example' } })).status, 403)
    assert.equal(engine.calls, 0)
    const connected = await request('/api/connect', { method: 'POST', headers: { Authorization: `Bearer ${token}`, Origin: runtime.origin } })
    assert.equal(connected.status, 200)
    const cookie = connected.headers.get('set-cookie'); assert.match(cookie, /HttpOnly/); assert.match(cookie, /SameSite=Strict/)
    const headers = { Cookie: cookie.split(';')[0], Origin: runtime.origin }
    const report = await request('/api/environment', { headers }); assert.equal(report.status, 200); assert.equal((await report.json()).state, 'needs_install')
    assert.equal((await request('/api/sessions/one/action', { method: 'POST', headers, body: 'x'.repeat(33000) })).status, 413)
    assert.equal((await request('/api/sessions/one/action', { method: 'POST', headers, body: 'broken' })).status, 400)
    assert.equal((await request('/api/sessions/one/action', { method: 'POST', headers, body: 'null' })).status, 400)
    assert.equal((await request('/api/sessions/one/claim', { method: 'POST', headers, body: '{}' })).status, 409)
    assert.equal((await request('/api/sessions/../private', { headers })).status, 404)
  } finally { await runtime.close() }
})

test('Chinese input survives UTF-8 characters split across request chunks', async () => {
  const token = 'a'.repeat(64), engine = new FakeEngine()
  engine.action = async (_id, input) => input
  const runtime = await createRuntimeServer({ token, engine, port: 0 })
  try {
    const payload = Buffer.from(JSON.stringify({ kind: 'text', text: '你好，世界' }))
    const split = payload.indexOf(Buffer.from('你')) + 1
    const result = await new Promise((resolve, reject) => {
      const request = http.request(runtime.origin + '/api/sessions/one/action', { method: 'POST', headers: { Authorization: `Bearer ${token}` } }, response => {
        const chunks = []; response.on('data', chunk => chunks.push(chunk)); response.on('error', reject)
        response.on('end', () => resolve({ status: response.statusCode, value: JSON.parse(Buffer.concat(chunks).toString('utf8')) }))
      })
      request.on('error', reject); request.write(payload.subarray(0, split))
      setTimeout(() => request.end(payload.subarray(split)), 20)
    })
    assert.equal(result.status, 200); assert.equal(result.value.text, '你好，世界')
  } finally { await runtime.close() }
})

test('runtime settings require authentication and explicit headless risk acknowledgement', async () => {
  const { promises: fs } = await import('node:fs')
  const os = await import('node:os'), path = await import('node:path')
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'haybot-settings-api-'))
  const token = 'settings-'.repeat(8), runtime = await createRuntimeServer({ directory, token, port: 0 })
  const request = (method, value, headers = { Authorization: `Bearer ${token}` }) => fetch(runtime.origin + '/api/sessions/one/settings', { method, headers, body: value === undefined ? undefined : JSON.stringify(value) })
  try {
    assert.equal((await request('GET', undefined, {})).status, 401)
    assert.deepEqual(await (await request('GET')).json(), { headless: false })
    assert.equal((await request('POST', { headless: true })).status, 400)
    assert.equal((await request('POST', { headless: 'false' })).status, 400)
    const result = await request('POST', { headless: true, acknowledgeHeadlessRisk: true })
    assert.equal(result.status, 200); assert.equal((await result.json()).options.headless, true)
    const state = await fetch(runtime.origin + '/api/sessions/one', { headers: { Authorization: `Bearer ${token}` } })
    assert.equal((await state.json()).options.headless, true)
    assert.equal((await request('POST', { headless: false })).status, 200)
  } finally { await runtime.close(); await fs.rm(directory, { recursive: true, force: true }) }
})
