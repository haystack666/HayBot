import test from 'node:test'
import assert from 'node:assert/strict'
import { promises as fs } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { BrowserEngine } from '../src/engine.mjs'

test('login fence discards an in-flight observation and manual ownership blocks model reads', async () => {
  const engine = new BrowserEngine('/tmp/unused')
  let complete
  const page = { viewportSize: () => ({ width: 1280, height: 800 }), locator: () => ({ ariaSnapshot: () => new Promise(resolve => { complete = resolve }) }) }
  const session = { context: {}, ownerLogin: false, controller: null, generation: 1, active: 'tab', tabs: new Map([['tab', page]]) }
  engine.sessions.set('one', session)
  const pending = engine.observe('one')
  session.ownerLogin = true
  complete('private password page')
  await assert.rejects(pending, { code: 'owner_login' })
  session.ownerLogin = false; session.controller = 'owner-viewer'
  await assert.rejects(engine.observe('one'), { code: 'owner_control' })
  session.context = null
  await engine.close()
})

test('login state is durably stored, explicit finish is required, and a stale lease cannot change it', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'haybot-login-'))
  const engine = new BrowserEngine(directory)
  const session = { id: 'one', context: {}, ownerLogin: false, lease: 'current', generation: 1, active: null, tabs: new Map(), titles: new Map(), operation: Promise.resolve(), streamJob: Promise.resolve(), observers: 0 }
  engine.sessions.set('one', session)
  await fs.mkdir(path.join(directory, 'profiles', 'one'), { recursive: true })
  const filename = path.join(directory, 'profiles', 'one', 'haybot-login.json')
  try {
    await engine.setLogin('one', 'current', true)
    assert.equal(session.ownerLogin, true)
    assert.deepEqual(JSON.parse(await fs.readFile(filename)), { paused: true })
    await assert.rejects(engine.setLogin('one', 'stale', false), { code: 'stale_control' })
    assert.equal(session.ownerLogin, true)
    await engine.setLogin('one', 'current', false)
    assert.deepEqual(JSON.parse(await fs.readFile(filename)), { paused: false })
  } finally { session.context = null; await engine.close(); await fs.rm(directory, { recursive: true, force: true }) }
})
