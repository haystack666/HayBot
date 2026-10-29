import test from 'node:test'
import assert from 'node:assert/strict'
import { promises as fs } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { execFile as execFileCallback } from 'node:child_process'
import { promisify } from 'node:util'
import { setTimeout as delay } from 'node:timers/promises'
import { createRuntimeServer } from '../src/server.mjs'
const execFile = promisify(execFileCallback)

async function waitFor(predicate) {
  const deadline = Date.now() + 5000
  while (!await predicate()) {
    if (Date.now() >= deadline) throw new Error('Timed out waiting for quiet browser state')
    await delay(25)
  }
}

test('headed Chrome stays minimized through tabs, navigation, popup and streamed manual input', { skip: process.platform !== 'darwin', timeout: 90000 }, async t => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'haybot-quiet-'))
  const runtime = await createRuntimeServer({ directory, token: 'quiet-test-'.repeat(8), port: 0 })
  const engine = runtime.engine, frames = []
  try {
    await engine.start('quiet')
    const session = engine.get('quiet'), first = session.active
    const page = session.tabs.get(first), cdp = await session.context.newCDPSession(page)
    const ps = await execFile('/bin/ps', ['-axo', 'pid=,command='])
    const command = ps.stdout.split('\n').find(line => line.includes('--user-data-dir=' + path.join(directory, 'profiles', 'quiet')) && line.includes('Contents/MacOS/Google Chrome'))
    assert.ok(command, 'identify only the test-owned browser process')
    assert.match(command, /--mute-audio/, 'actual headed Chrome process has audio output muted')
    const { windowId } = await cdp.send('Browser.getWindowForTarget')
    const state = async () => (await cdp.send('Browser.getWindowBounds', { windowId })).bounds.windowState
    const setState = windowState => cdp.send('Browser.setWindowBounds', { windowId, bounds: { windowState } })
    const { lease } = engine.claim('quiet')
    const act = input => { const current = engine.state('quiet'); return engine.action('quiet', { ...input, lease, tabId: current.activeTab, generation: current.generation }) }
    const assertMinimized = () => waitFor(async () => await state() === 'minimized')
    await act({ kind: 'navigate', url: runtime.origin + '/fixture' })
    engine.on('frame', frame => frames.push(frame))
    engine.watch('quiet', 1)
    await setState('minimized')
    await assertMinimized()

    await act({ kind: 'new_tab' })
    const second = session.active
    assert.notEqual(second, first)
    await assertMinimized()
    await act({ kind: 'navigate', url: runtime.origin + '/fixture?second=1' })
    await assertMinimized()
    await act({ kind: 'switch_tab', target: first })
    await assertMinimized()
    await waitFor(() => frames.some(frame => frame.tabId === first && frame.generation === session.generation))
    const input = await page.locator('#message').boundingBox()
    await act({ kind: 'click', x: input.x + 10, y: input.y + 10 })
    await act({ kind: 'key', key: 'ControlOrMeta+A' })
    await act({ kind: 'text', text: '最小化后接管输入' })
    assert.equal(await page.locator('#message').inputValue(), '最小化后接管输入')
    const slider = await page.locator('#range').boundingBox()
    await act({ kind: 'pointer', phase: 'start', mode: 'drag', gestureId: 'quiet-drag', x: slider.x + slider.width * .2, y: slider.y + slider.height / 2 })
    await act({ kind: 'pointer', phase: 'end', gestureId: 'quiet-drag', x: slider.x + slider.width * .8, y: slider.y + slider.height / 2 })
    assert.ok(Number(await page.locator('#range').inputValue()) >= 70)
    await assertMinimized()

    // The fixture's target=_blank link opens a real popup through a manual click.
    await page.locator('a[target="_blank"]').evaluate(a => { a.style.position = 'fixed'; a.style.top = '20px'; a.style.left = '800px'; a.style.zIndex = '9999' })
    const link = await page.locator('a[target="_blank"]').boundingBox()
    await act({ kind: 'click', x: link.x + 10, y: link.y + 10 })
    await waitFor(() => session.tabs.size === 3)
    await assertMinimized()
    const popup = session.active
    assert.notEqual(popup, first)
    await waitFor(() => frames.some(frame => frame.tabId === popup && frame.generation === session.generation))
    await act({ kind: 'close_tab' })
    assert.equal(session.tabs.size, 2)
    await assertMinimized()
    await act({ kind: 'switch_tab', target: second })
    await waitFor(() => frames.some(frame => frame.tabId === second && frame.generation === session.generation))
    await assertMinimized()

    // An explicit native restore remains respected on subsequent workbench actions.
    await setState('normal')
    await waitFor(async () => await state() === 'normal')
    await act({ kind: 'switch_tab', target: first })
    assert.equal(await state(), 'normal')
    await act({ kind: 'new_tab' })
    assert.equal(await state(), 'normal')
    t.diagnostic(`Muted launch; minimized navigation, new tab, switching, popup, close, stream, text and drag passed (${frames.length} frames). Native restore respected. No system audio loopback assertion.`)
  } finally { await runtime.close(); await fs.rm(directory, { recursive: true, force: true }) }
})
