import test from 'node:test'
import assert from 'node:assert/strict'
import { promises as fs } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { BrowserOptions } from '../src/options.mjs'
import { BrowserEngine } from '../src/engine.mjs'
import { xiaohongshuAccessIssue } from '../src/access-issues.mjs'

test('headed default, explicit experimental consent, persistence, and Bot isolation', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'haybot-options-'))
  const options = new BrowserOptions(directory)
  try {
    assert.deepEqual(await options.get('a'), { headless: false })
    for (const input of [{ headless: 'false' }, { headless: true }, { headless: true, acknowledgeHeadlessRisk: false }, { headless: false, args: ['--custom'] }]) await assert.rejects(options.save('a', input))
    assert.deepEqual(await options.save('a', { headless: true, acknowledgeHeadlessRisk: true }), { headless: true })
    const fresh = new BrowserOptions(directory)
    assert.deepEqual(await fresh.get('a'), { headless: true })
    assert.deepEqual(await fresh.get('b'), { headless: false })
    assert.equal((await fs.stat(path.join(directory, 'settings/a.json'))).mode & 0o777, 0o600)
    await assert.rejects(options.get('../private'), { code: 'invalid_session' })
    await fresh.save('a', { headless: false })
    assert.deepEqual(await new BrowserOptions(directory).get('a'), { headless: false })
    await fs.writeFile(path.join(directory, 'settings/c.json'), JSON.stringify({ headless: true }))
    await assert.rejects(fresh.get('c'), { code: 'invalid_settings' })
    await fs.writeFile(path.join(directory, 'settings/d.json'), 'null')
    await assert.rejects(fresh.get('d'), { code: 'invalid_settings' })
  } finally { await fs.rm(directory, { recursive: true, force: true }) }
})

test('engine passes actual mode to Chrome, uses same profile, and fences launch/settings races', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'haybot-mode-'))
  const launches = []
  const engine = new BrowserEngine(directory, { browserType: { launchPersistentContext: async (profile, options) => { launches.push({ profile, options }) } } })
  try {
    await engine.launch('/same-profile')
    await engine.launch('/same-profile', { headless: true })
    assert.equal(launches[0].options.headless, false)
    assert.equal(launches[1].options.headless, true)
    for (const { options } of launches) assert.ok(options.args.includes('--mute-audio'))
    assert.equal(launches[0].profile, launches[1].profile)
    engine.sessions.set('a', { context: {} })
    await assert.rejects(engine.configure('a', { headless: false }), { code: 'settings_busy' })
    engine.sessions.delete('a')
    const pending = engine.configure('a', { headless: false })
    await assert.rejects(engine.start('a'), { code: 'busy' })
    await pending
    engine.starting.set('a', Promise.resolve())
    await assert.rejects(engine.configure('a', { headless: false }), { code: 'settings_busy' })
    engine.starting.delete('a')
    assert.equal((await engine.configure('a', { headless: true, acknowledgeHeadlessRisk: true })).options.headless, true)
  } finally { await engine.close(); await fs.rm(directory, { recursive: true, force: true }) }
})

test('300012 detection is restricted to Xiaohongshu and does not label unrelated page text as blocked', () => {
  assert.equal(xiaohongshuAccessIssue('https://www.xiaohongshu.com/website-login/error?error_code=300012').code, '300012')
  assert.equal(xiaohongshuAccessIssue('https://www.xiaohongshu.com/', '错误代码：300012').code, '300012')
  assert.equal(xiaohongshuAccessIssue('https://www.xiaohongshu.com/', '300012').code, '300012')
  assert.equal(xiaohongshuAccessIssue('https://xiaohongshu.com/', 'error_code:300012').code, '300012')
  assert.equal(xiaohongshuAccessIssue('https://xiaohongshu.com.evil.test/?error_code=300012'), null)
  assert.equal(xiaohongshuAccessIssue('https://bilibili.com/?error_code=300012'), null)
  assert.equal(xiaohongshuAccessIssue('https://www.xiaohongshu.com/explore/300012', '笔记编号 300012，正常内容'), null)
})
