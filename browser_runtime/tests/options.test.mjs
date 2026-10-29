import test from 'node:test'
import assert from 'node:assert/strict'
import { promises as fs } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { BrowserOptions } from '../src/options.mjs'
import { BrowserEngine } from '../src/engine.mjs'

test('headless default migrates headed and experimental settings without changing profile data', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'haybot-options-'))
  const options = new BrowserOptions(directory)
  try {
    await fs.mkdir(path.join(directory, 'settings'), { recursive: true })
    await fs.mkdir(path.join(directory, 'profiles/a'), { recursive: true })
    await fs.writeFile(path.join(directory, 'profiles/a/haybot-login.json'), '{"paused":true}')
    for (const [id, old] of [['a', { headless: false, headlessRiskVersion: null }], ['b', { headless: true, headlessRiskVersion: 1 }], ['c', { headless: true }]]) {
      await fs.writeFile(path.join(directory, 'settings', id + '.json'), JSON.stringify(old))
      assert.deepEqual(await options.get(id), { headless: true })
      assert.deepEqual(JSON.parse(await fs.readFile(path.join(directory, 'settings', id + '.json'), 'utf8')), { version: 2, headless: true })
    }
    assert.deepEqual(await options.get('new'), { headless: true })
    assert.equal(await fs.readFile(path.join(directory, 'profiles/a/haybot-login.json'), 'utf8'), '{"paused":true}')
    for (const input of [{ headless: false }, { headless: 'true' }, { headless: true, args: [] }]) await assert.rejects(options.save('a', input))
    assert.deepEqual(await options.save('a', { headless: true }), { headless: true })
    assert.deepEqual(await new BrowserOptions(directory).get('a'), { headless: true })
    assert.equal((await fs.stat(path.join(directory, 'settings/a.json'))).mode & 0o777, 0o600)
    await assert.rejects(options.get('../private'), { code: 'invalid_session' })
    await fs.writeFile(path.join(directory, 'settings/bad.json'), 'null')
    await assert.rejects(options.get('bad'), { code: 'invalid_settings' })
  } finally { await fs.rm(directory, { recursive: true, force: true }) }
})

test('engine enforces headless Chrome, uses same profile, and fences launch/settings races', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'haybot-mode-'))
  const launches = []
  const engine = new BrowserEngine(directory, { browserType: { launchPersistentContext: async (profile, options) => { launches.push({ profile, options }) } } })
  try {
    await engine.launch('/same-profile')
    await engine.launch('/same-profile', { headless: false })
    assert.equal(launches[0].options.headless, true)
    assert.equal(launches[1].options.headless, true)
    for (const { options } of launches) assert.ok(options.args.includes('--mute-audio'))
    assert.equal(launches[0].profile, launches[1].profile)
    engine.sessions.set('a', { context: {} })
    await assert.rejects(engine.configure('a', { headless: true }), { code: 'settings_busy' })
    engine.sessions.delete('a')
    const pending = engine.configure('a', { headless: true })
    await assert.rejects(engine.start('a'), { code: 'busy' })
    await pending
    engine.starting.set('a', Promise.resolve())
    await assert.rejects(engine.configure('a', { headless: true }), { code: 'settings_busy' })
    engine.starting.delete('a')
    assert.equal((await engine.configure('a', { headless: true, acknowledgeHeadlessRisk: true })).options.headless, true)
  } finally { await engine.close(); await fs.rm(directory, { recursive: true, force: true }) }
})
