import test from 'node:test'
import assert from 'node:assert/strict'
import { promises as fs } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { chromium } from 'playwright'
import { createRuntimeServer } from '../src/server.mjs'

test('viewer gestures: scaled drag, nested wheel, swipe, touch, expanded coordinates and disconnect cleanup', { timeout: 120000, skip: process.platform !== 'darwin' }, async t => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'haybot-gestures-'))
  const token = 'gesture-test-'.repeat(6), runtime = await createRuntimeServer({ directory, token, port: 0 })
  let browser
  try {
    const report = await runtime.engine.prepare(); assert.equal(report.state, 'ready')
    browser = await chromium.launch({ channel: 'chrome', executablePath: report.chrome.executable, headless: true })
    const context = await browser.newContext({ viewport: { width: 1200, height: 1400 }, hasTouch: true })
    const viewer = await context.newPage(), errors = []
    viewer.on('pageerror', error => errors.push(error.message))
    await viewer.goto(runtime.origin)
    await viewer.getByLabel('宿主访问码').fill(token); await viewer.getByRole('button', { name: '连接', exact: true }).click()
    await viewer.getByRole('button', { name: '启动', exact: true }).click()
    await viewer.getByRole('button', { name: '接管', exact: true }).click()
    await viewer.getByRole('button', { name: '测试页', exact: true }).click()
    await viewer.waitForFunction(() => document.querySelector('#address').value.endsWith('/fixture') && document.querySelector('#stream-state').textContent === '实时画面 · 观看中')
    const session = runtime.engine.get('prototype-a'), target = session.tabs.get(session.active)
    await target.locator('#range').waitFor()
    await target.waitForTimeout(500)
    await viewer.waitForFunction(generation => {
      const screen = document.querySelector('#screen')
      return screen.dataset.frameGeneration === String(generation) && screen.dataset.viewportWidth === '1280' && screen.dataset.viewportHeight === '800'
    }, session.generation, { timeout: 5000 })
    const requests = []
    viewer.on('request', request => { if (request.url().endsWith('/action')) { const { kind, phase, x, y } = JSON.parse(request.postData()); requests.push({ kind, phase, x, y }) } })
    async function localPoint(x, y) {
      return viewer.locator('#screen').evaluate((canvas, point) => {
        const rect = canvas.getBoundingClientRect(), width = rect.width - canvas.clientLeft * 2, height = rect.height - canvas.clientTop * 2
        const scale = Math.min(width / canvas.width, height / canvas.height)
        return { x: rect.left + canvas.clientLeft + (width - canvas.width * scale) / 2 + point.x / Number(canvas.dataset.viewportWidth) * canvas.width * scale, y: rect.top + canvas.clientTop + (height - canvas.height * scale) / 2 + point.y / Number(canvas.dataset.viewportHeight) * canvas.height * scale }
      }, { x, y })
    }
    async function drag(from, to) {
      await viewer.mouse.move(from.x, from.y); await viewer.mouse.down()
      await viewer.mouse.move(to.x, to.y, { steps: 16 }); await viewer.mouse.up()
      await viewer.waitForFunction(() => !document.querySelector('#screen').dataset.inputBusy)
    }
    let range = await target.locator('#range').boundingBox()
    await drag(await localPoint(range.x + range.width * .2, range.y + range.height / 2), await localPoint(range.x + range.width * .8, range.y + range.height / 2))
    try { await target.waitForFunction(() => Number(document.querySelector('#range').value) >= 70, null, { timeout: 5000 }) }
    catch (error) {
      t.diagnostic(JSON.stringify({ requests, initialRange: range, currentRange: await target.locator('#range').boundingBox(), currentValue: await target.locator('#range').inputValue(), notice: await viewer.locator('#notice').innerText(), canvas: await viewer.locator('#screen').evaluate(canvas => ({ width: canvas.width, height: canvas.height, rect: canvas.getBoundingClientRect().toJSON(), generation: canvas.dataset.frameGeneration })) }))
      throw error
    }
    t.diagnostic('normal viewport slider drag reaches >=70')
    const handle = await target.locator('#drag-handle').boundingBox()
    await drag(await localPoint(handle.x + 20, handle.y + 15), await localPoint(handle.x + 160, handle.y + 15))
    await target.waitForFunction(() => document.querySelector('#drag-handle').offsetLeft > 100)
    const nested = await target.locator('#nested-scroll').boundingBox(), anchor = await localPoint(nested.x + 60, nested.y + 80)
    await viewer.mouse.move(anchor.x, anchor.y); await viewer.mouse.wheel(120, 180)
    await target.waitForFunction(() => document.querySelector('#nested-scroll').scrollTop > 100 && document.querySelector('#nested-scroll').scrollLeft > 80)
    assert.equal(await target.evaluate(() => window.scrollY), 0, 'nested scrolling must not scroll the root page')
    await viewer.getByLabel('画面操作模式').selectOption('swipe')
    const nestedBefore = await target.locator('#nested-scroll').evaluate(element => element.scrollTop)
    await drag(await localPoint(nested.x + 90, nested.y + 120), await localPoint(nested.x + 90, nested.y + 30))
    await target.waitForFunction(before => document.querySelector('#nested-scroll').scrollTop > before + 50, nestedBefore)
    await viewer.getByLabel('画面操作模式').selectOption('auto')
    // Real touch events reach the viewer's pointer path; automatic mode scrolls on touch.
    const touch = await context.newCDPSession(viewer)
    const from = await localPoint(nested.x + 90, nested.y + 120), to = await localPoint(nested.x + 90, nested.y + 30)
    const touchBefore = await target.locator('#nested-scroll').evaluate(element => element.scrollTop)
    await touch.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: from.x, y: from.y }] })
    for (let index = 1; index <= 6; index++) await touch.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: from.x, y: from.y + (to.y - from.y) * index / 6 }] })
    await touch.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
    await target.waitForFunction(before => document.querySelector('#nested-scroll').scrollTop > before + 50, touchBefore)
    await touch.detach()
    t.diagnostic('nested horizontal/vertical wheel, swipe mode and real touch scroll passed')
    await viewer.getByRole('button', { name: '放大画面', exact: true }).click()
    range = await target.locator('#range').boundingBox()
    await drag(await localPoint(range.x + range.width * .8, range.y + range.height / 2), await localPoint(range.x + range.width * .3, range.y + range.height / 2))
    await target.waitForFunction(() => Number(document.querySelector('#range').value) < 40)
    // Letterboxed space must neither acquire input nor click content.
    const canvas = await viewer.locator('#screen').boundingBox()
    await viewer.mouse.click(canvas.x + 5, canvas.y + 5)
    assert.equal(session.pointer, null)
    // Release during an in-flight pointer.down when the viewing connection disappears.
    const start = await localPoint(range.x + range.width * .3, range.y + range.height / 2)
    await viewer.mouse.move(start.x, start.y); await viewer.mouse.down()
    await target.waitForFunction(() => document.querySelector('#range').matches(':active'))
    await viewer.close()
    const deadline = Date.now() + 3000
    while ((session.lease || session.pointer) && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 10))
    await session.operation.catch(() => {})
    assert.equal(session.lease, null); assert.equal(session.pointer, null)
    assert.deepEqual(errors, [])
    t.diagnostic('expanded slider, letterbox rejection and disconnect held-button cleanup passed')
  } finally {
    await browser?.close(); await runtime.close(); await fs.rm(directory, { recursive: true, force: true })
  }
})
