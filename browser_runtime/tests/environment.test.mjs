import test from 'node:test'
import assert from 'node:assert/strict'
import { promises as fs } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { findChrome, Environment, CHROME_INSTALL_URL } from '../src/environment.mjs'
import { BrowserEngine, navigationURL } from '../src/engine.mjs'

test('missing Chrome does not launch or fall back to another browser', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'haybot-env-'))
  let launches = 0
  const env = new Environment(directory, { discover: () => findChrome({ candidates: ['/missing'], stat: async () => { throw new Error('missing') } }) })
  const engine = new BrowserEngine(directory, { environment: env, browserType: { launchPersistentContext: () => { launches++; throw new Error('must not launch') } } })
  try {
    const report = await engine.prepare()
    assert.equal(report.state, 'needs_install'); assert.equal(report.installUrl, CHROME_INSTALL_URL)
    assert.equal(report.checks.find(check => check.id === 'launch').state, 'pending')
    await assert.rejects(engine.start('one'), { code: 'needs_install' }); assert.equal(launches, 0)
    assert.equal('chrome' in env.public(report), false)
  } finally { await engine.close(); await fs.rm(directory, { recursive: true, force: true }) }
})

test('invalid signatures are repair failures, never missing Chrome', async () => {
  const result = await findChrome({ platform: 'darwin', candidates: ['/Chrome.app'], stat: async () => ({}), run: async (_file, args) => {
    if (args.includes('CFBundleIdentifier')) return { stdout: 'com.google.Chrome\n' }
    if (args.includes('CFBundleShortVersionString')) return { stdout: '156.0.1.2\n' }
    throw new Error('signature invalid')
  } })
  assert.equal(result.state, 'needs_repair'); assert.equal(result.executable, null)
})

function chromeRun({ description = 'Mach-O universal binary with 2 architectures: [x86_64:Mach-O 64-bit executable x86_64] [arm64:Mach-O 64-bit executable arm64]', team = 'EQHXZ8M8AV', fileError = false } = {}) {
  const calls = []
  const run = async (file, args) => {
    calls.push([file, args])
    assert.notEqual(file, '/usr/bin/lipo', 'Chrome verification must not depend on Xcode license state')
    if (args.includes('CFBundleIdentifier')) return { stdout: 'com.google.Chrome\n' }
    if (args.includes('CFBundleShortVersionString')) return { stdout: '156.0.1.2\n' }
    if (file === '/usr/bin/codesign') return { stdout: '', stderr: args.includes('--display') ? `TeamIdentifier=${team}\n` : '' }
    if (file === '/usr/bin/file') {
      if (fileError) throw new Error('private-error-sentinel')
      return { stdout: description }
    }
    throw new Error('unexpected tool')
  }
  return { run, calls }
}

test('Google signed universal Chrome passes arm64 and Intel without any Xcode tool', async () => {
  for (const arch of ['arm64', 'x64']) {
    const { run, calls } = chromeRun()
    const result = await findChrome({ platform: 'darwin', arch, candidates: ['/Chrome.app'], stat: async () => ({}), run })
    assert.equal(result.state, 'passed')
    assert.deepEqual(result.architectures, ['x86_64', 'arm64'])
    assert.equal(result.executable, '/Chrome.app/Contents/MacOS/Google Chrome')
    assert.ok(calls.some(([file, args]) => file === '/usr/bin/codesign' && args.includes('--verify') && args.some(arg => arg.includes('anchor apple generic'))))
    assert.ok(calls.some(([file]) => file === '/usr/bin/file'))
  }
})

test('thin Mach-O passes only matching architectures; scripts cannot spoof an architecture label', async () => {
  for (const [description, arch, passed] of [
    ['Mach-O 64-bit executable arm64', 'arm64', true],
    ['Mach-O 64-bit executable x86_64', 'x64', true],
    ['Mach-O 64-bit executable x86_64', 'arm64', false],
    ['shell script text arm64', 'arm64', false],
    ['Mach-O 64-bit executable arm64e', 'arm64', false],
  ]) {
    const { run } = chromeRun({ description })
    const result = await findChrome({ platform: 'darwin', arch, candidates: ['/Chrome.app'], stat: async () => ({}), run })
    assert.equal(result.state === 'passed', passed)
    if (!passed) assert.equal(result.executable, null)
  }
})

test('architecture tool failure is explicit and sanitized; foreign signer still fails closed', async () => {
  const failed = await findChrome({ platform: 'darwin', candidates: ['/Chrome.app'], stat: async () => ({}), run: chromeRun({ fileError: true }).run })
  assert.equal(failed.state, 'needs_repair')
  assert.match(failed.detail, /检测工具执行失败/)
  assert.doesNotMatch(JSON.stringify(failed), /private-error-sentinel/)
  const { run, calls } = chromeRun({ team: 'NOTGOOGLE' })
  const foreign = await findChrome({ platform: 'darwin', candidates: ['/Chrome.app'], stat: async () => ({}), run })
  assert.equal(foreign.state, 'needs_repair'); assert.equal(foreign.executable, null)
  assert.equal(calls.some(([file]) => file === '/usr/bin/file'), false)
})

test('environment checks coalesce and leave launch unverified until a real handshake', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'haybot-env-')); let discoveries = 0
  const env = new Environment(directory, { discover: async () => { discoveries++; await new Promise(resolve => setTimeout(resolve, 20)); return { state: 'passed', detail: 'Chrome' } } })
  try {
    const [a, b] = await Promise.all([env.check({ force: true }), env.check({ force: true })])
    assert.equal(a, b); assert.equal(discoveries, 1); assert.equal(a.state, 'checking')
    env.setLaunch(a, false); assert.equal(a.state, 'needs_repair')
    env.setLaunch(a, true); assert.equal(a.state, 'ready')
  } finally { await fs.rm(directory, { recursive: true, force: true }) }
})

test('unsafe navigation and path traversal session names are rejected', async () => {
  for (const url of ['file:///etc/passwd', 'javascript:alert(1)', 'chrome://settings', 'https://user:pass@example.com']) assert.throws(() => navigationURL(url), { code: 'invalid_url' })
  assert.equal(navigationURL('https://example.com'), 'https://example.com/')
  const engine = new BrowserEngine('/tmp/unused')
  await assert.rejects(engine.start('../private'), { code: 'invalid_session' }); await engine.close()
})

test('queued inputs recheck control before executing and do not replay after takeover', async () => {
  const engine = new BrowserEngine('/tmp/unused'); let clicks = 0
  engine.environment.cached = { state: 'ready' }
  const session = { id: 'one', context: {}, lease: 'first', generation: 1, active: 'tab', tabs: new Map([['tab', { viewportSize: () => ({ width: 100, height: 100 }), mouse: { click: async () => { clicks++ } } }]]), operation: Promise.resolve(), titles: new Map(), observers: 0, streamJob: Promise.resolve() }
  engine.sessions.set('one', session)
  const pending = engine.action('one', { kind: 'click', x: 5, y: 5, lease: 'first', generation: 1, tabId: 'tab' })
  session.lease = 'second'; session.generation++
  await assert.rejects(pending, { code: 'stale_control' }); assert.equal(clicks, 0)
  session.context = null; await engine.close()
})
