import test from 'node:test'
import assert from 'node:assert/strict'
import { promises as fs } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { chromium } from 'playwright'
import { createRuntimeServer } from '../src/server.mjs'

// Opt-in: an isolated backend container serves frontend/dist on this URL and
// connects to host port 17323. Never point this test at production Bot data.
test('formal workbench through Docker relay: login, gestures, privacy, Bot switching and logout', {
  skip: !process.env.HAYBOT_WORKBENCH_URL, timeout: 120000,
}, async t => {
  const environment = Object.fromEntries((await fs.readFile(process.env.HAYBOT_WORKBENCH_TEST_ENV, 'utf8')).trim().split('\n').map(line => {
    const split = line.indexOf('='); return [line.slice(0, split), line.slice(split + 1)]
  }))
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'haybot-workbench-test-'))
  const runtime = await createRuntimeServer({ directory, token: environment.BROWSER_RUNTIME_TOKEN, port: 17323 })
  let browser
  try {
    const report = await runtime.engine.prepare(); assert.equal(report.state, 'ready')
    browser = await chromium.launch({ channel: 'chrome', executablePath: report.chrome.executable, headless: true })
    const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, hasTouch: true })
    const viewer = await context.newPage(), errors = []
    viewer.on('pageerror', error => errors.push(error.message))
    await viewer.goto(process.env.HAYBOT_WORKBENCH_URL + '/bots/default/browser')
    await viewer.getByLabel('管理密码').fill(environment.ADMIN_PASSWORD)
    await viewer.getByRole('button', { name: '登录 HayBot', exact: true }).click()
    await viewer.getByText('环境就绪', { exact: true }).waitFor()
    await viewer.locator('.browser-experiments summary').click()
    const headlessSwitch = viewer.getByRole('switch', { name: '无头模式（headless）' })
    assert.equal(await headlessSwitch.isChecked(), false)
    await viewer.getByRole('button', { name: '启动浏览器', exact: true }).click()
    await viewer.getByRole('button', { name: '接管', exact: true }).click()
    await viewer.getByLabel('网页地址').fill(runtime.origin + '/fixture')
    await viewer.getByRole('button', { name: '前往', exact: true }).click()
    const session = runtime.engine.get('bot-default')
    const target = session.tabs.get(session.active)
    await target.locator('#range').waitFor()
    await target.waitForTimeout(500)
    await viewer.waitForFunction(generation => document.querySelector('.browser-screen').dataset.frameGeneration === String(generation), session.generation)
    async function localPoint(x, y) {
      return viewer.locator('.browser-screen').evaluate((canvas, point) => {
        const rect = canvas.getBoundingClientRect(), width = rect.width - canvas.clientLeft * 2, height = rect.height - canvas.clientTop * 2
        const scale = Math.min(width / canvas.width, height / canvas.height)
        return { x: rect.left + canvas.clientLeft + (width - canvas.width * scale) / 2 + point.x / Number(canvas.dataset.viewportWidth) * canvas.width * scale, y: rect.top + canvas.clientTop + (height - canvas.height * scale) / 2 + point.y / Number(canvas.dataset.viewportHeight) * canvas.height * scale }
      }, { x, y })
    }
    async function drag(from, to) {
      await viewer.mouse.move(from.x, from.y); await viewer.mouse.down()
      await viewer.mouse.move(to.x, to.y, { steps: 12 }); await viewer.mouse.up()
      await viewer.waitForFunction(() => !document.querySelector('.browser-screen').dataset.inputBusy)
    }
    const range = await target.locator('#range').boundingBox()
    await drag(await localPoint(range.x + range.width * .2, range.y + range.height / 2), await localPoint(range.x + range.width * .8, range.y + range.height / 2))
    await target.waitForFunction(() => Number(document.querySelector('#range').value) >= 70)
    assert.equal(session.options.headless, false)
    assert.equal(await headlessSwitch.isEnabled(), false)
    t.diagnostic('Native slider drag succeeded through management HTTP and Docker relay')
    // Switching modes must not bypass consent, lose the profile, or remove controls.
    await target.evaluate(() => { localStorage.setItem('mode-test', 'preserved') })
    await viewer.getByRole('button', { name: '停止', exact: true }).click()
    await headlessSwitch.click()
    await viewer.getByRole('dialog').getByRole('button', { name: '保持普通模式' }).click()
    assert.equal(await headlessSwitch.isChecked(), false)
    assert.equal((await runtime.engine.settings('bot-default')).headless, false)
    await headlessSwitch.click()
    await viewer.getByRole('dialog').getByRole('button', { name: '了解风险并开启' }).click()
    await viewer.waitForFunction(() => document.querySelector('[role="switch"]').getAttribute('aria-checked') === 'true')
    await viewer.reload()
    await viewer.getByText('环境就绪', { exact: true }).waitFor()
    await viewer.getByRole('button', { name: '启动浏览器', exact: true }).click()
    await viewer.getByRole('button', { name: '接管', exact: true }).click()
    assert.equal(runtime.engine.get('bot-default').options.headless, true)
    await viewer.getByLabel('网页地址').fill(runtime.origin + '/fixture')
    await viewer.getByRole('button', { name: '前往', exact: true }).click()
    const restarted = runtime.engine.get('bot-default'), hiddenTarget = restarted.tabs.get(restarted.active)
    await hiddenTarget.locator('#range').waitFor()
    assert.equal(await hiddenTarget.evaluate(() => localStorage.getItem('mode-test')), 'preserved')
    await viewer.waitForFunction(generation => document.querySelector('.browser-screen').dataset.frameGeneration === String(generation), restarted.generation)
    const hiddenRange = await hiddenTarget.locator('#range').boundingBox()
    await drag(await localPoint(hiddenRange.x + hiddenRange.width * .2, hiddenRange.y + hiddenRange.height / 2), await localPoint(hiddenRange.x + hiddenRange.width * .8, hiddenRange.y + hiddenRange.height / 2))
    await hiddenTarget.waitForFunction(() => Number(document.querySelector('#range').value) >= 70)
    t.diagnostic('Risk cancellation, persisted headless opt-in, shared profile and remote drag in both modes passed')
    await viewer.getByRole('button', { name: '主人登录', exact: true }).click()
    await viewer.getByText('主人登录中', { exact: true }).waitFor()
    await assert.rejects(runtime.engine.observe('bot-default'), { code: 'owner_login' })
    await viewer.getByRole('button', { name: '结束接管', exact: true }).click()
    await assert.rejects(runtime.engine.observe('bot-default'), { code: 'owner_login' })
    await viewer.getByRole('button', { name: '停止', exact: true }).click()
    await viewer.getByRole('button', { name: '启动浏览器', exact: true }).click()
    await viewer.getByText('主人登录中', { exact: true }).waitFor()
    assert.equal(runtime.engine.state('bot-default').owner_login, true)
    await viewer.getByRole('button', { name: '接管', exact: true }).click()
    await viewer.getByRole('button', { name: '完成登录', exact: true }).click()
    await viewer.getByRole('dialog').getByRole('button', { name: '完成登录', exact: true }).click()
    await viewer.getByRole('button', { name: '主人登录', exact: true }).waitFor()
    assert.equal(runtime.engine.state('bot-default').owner_login, false)
    const second = await (await context.request.post(process.env.HAYBOT_WORKBENCH_URL + '/api/bots', { data: { name: '浏览器验收 B' } })).json()
    await viewer.getByLabel('切换机器人', { exact: true }).first().selectOption(second.id)
    await viewer.getByRole('button', { name: '启动浏览器', exact: true }).click()
    await viewer.getByRole('button', { name: '接管', exact: true }).click()
    const secondSession = runtime.engine.get('bot-' + second.id)
    assert.equal(secondSession.options.headless, false, 'the second Bot keeps the normal default')
    assert.equal(secondSession.tabs.get(secondSession.active).url(), 'about:blank')
    await viewer.getByLabel('网页地址').fill(runtime.origin + '/fixture?bot=b')
    await viewer.getByRole('button', { name: '前往', exact: true }).click()
    const secondTarget = secondSession.tabs.get(secondSession.active)
    await secondTarget.locator('#message').waitFor()
    assert.equal(await secondTarget.locator('#message').inputValue(), '')
    await viewer.waitForFunction(generation => document.querySelector('.browser-screen').dataset.frameGeneration === String(generation) && !document.querySelector('[aria-label="网页地址"]').disabled, secondSession.generation)
    await viewer.getByRole('button', { name: '放大画面', exact: true }).click()
    assert.equal(await viewer.locator('.browser-viewer').evaluate(element => getComputedStyle(element).position), 'fixed')
    assert.equal(await viewer.getByLabel('网页地址').isEnabled(), true, 'expanded mode retains control')
    await viewer.keyboard.press('Escape')
    await viewer.getByRole('button', { name: '放大画面', exact: true }).waitFor()
    assert.equal(await viewer.getByLabel('网页地址').isEnabled(), true, 'Escape retains control')
    await viewer.evaluate(() => document.documentElement.classList.add('dark'))
    assert.equal(await viewer.getByLabel('网页地址').isEnabled(), true, 'dark theme retains control')
    await viewer.screenshot({ path: new URL('../../design/browser-runtime-20261028/prototype/browser-workbench-dark.png', import.meta.url).pathname, fullPage: true })
    await viewer.evaluate(() => document.documentElement.classList.remove('dark'))
    await viewer.screenshot({ path: new URL('../../design/browser-runtime-20261028/prototype/browser-workbench-light.png', import.meta.url).pathname, fullPage: true })
    await viewer.setViewportSize({ width: 390, height: 844 })
    assert.ok(await viewer.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    await viewer.setViewportSize({ width: 1440, height: 1100 })
    await viewer.getByRole('button', { name: '退出登录', exact: true }).click()
    await viewer.getByRole('button', { name: '登录 HayBot', exact: true }).waitFor()
    await new Promise(resolve => setTimeout(resolve, 350))
    assert.equal(secondSession.lease, null)
    assert.equal((await context.request.get(process.env.HAYBOT_WORKBENCH_URL + '/api/bots/' + second.id + '/browser')).status(), 401)
    assert.deepEqual(errors, [])
    t.diagnostic('Owner login fence survives stop/start; A/B isolated; enlarge/Escape, dark/light/mobile and logout passed')
  } finally {
    await browser?.close(); await runtime.close(); await fs.rm(directory, { recursive: true, force: true })
  }
})
