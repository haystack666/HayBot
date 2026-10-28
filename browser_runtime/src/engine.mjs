import path from 'node:path'
import { promises as fs } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { EventEmitter } from 'node:events'
import { chromium } from 'playwright'
import { Environment, RuntimeError } from './environment.mjs'

const validId = id => typeof id === 'string' && /^[a-zA-Z0-9_-]{1,64}$/.test(id)
export function navigationURL(value) {
  let url
  try { url = new URL(value) } catch { throw new RuntimeError('invalid_url', '请输入完整的 HTTP 或 HTTPS 地址', 400) }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new RuntimeError('invalid_url', '只支持不含账号密码的 HTTP 或 HTTPS 地址', 400)
  return url.href
}

export class BrowserEngine extends EventEmitter {
  constructor(directory, { environment = new Environment(directory), browserType = chromium } = {}) {
    super(); this.directory = directory; this.environment = environment; this.browserType = browserType
    this.sessions = new Map(); this.starting = new Map(); this.stopping = new Set(); this.environmentJob = null; this.closed = false
  }
  async prepare({ force = false } = {}) {
    if (this.closed) throw new RuntimeError('closed', '运行时已停止')
    if (this.environmentJob) return this.environmentJob
    this.environmentJob = this.prepareOnce(force).finally(() => { this.environmentJob = null })
    return this.environmentJob
  }
  async prepareOnce(force) {
    const report = await this.environment.check({ force })
    if (report.state === 'needs_install' || report.checks.some(check => check.id !== 'launch' && check.state === 'failed')) return report
    if (report.state === 'ready') return report
    if ([...this.sessions.values()].some(session => session.context)) return this.environment.setLaunch(report, true)
    const temporary = await fs.mkdtemp(path.join(this.directory, 'launch-check-'))
    let context
    try {
      context = await this.launch(temporary)
      await context.newPage(); this.environment.setLaunch(report, true)
    } catch { this.environment.setLaunch(report, false) }
    finally { await context?.close().catch(() => {}); await fs.rm(temporary, { recursive: true, force: true }) }
    return report
  }
  launch(profile) {
    return this.browserType.launchPersistentContext(profile, {
      channel: 'chrome', executablePath: this.environment.cached?.chrome.executable || undefined,
      headless: true, viewport: { width: 1280, height: 800 },
      acceptDownloads: false, timeout: 30000,
      args: ['--no-first-run', '--no-default-browser-check'],
    })
  }
  get(id) {
    if (!validId(id)) throw new RuntimeError('invalid_session', '浏览器会话标识无效', 400)
    const session = this.sessions.get(id)
    if (!session?.context) throw new RuntimeError('session_stopped', '浏览器尚未启动')
    return session
  }
  state(id) {
    const session = this.sessions.get(id)
    if (!session) return { id, state: 'stopped', tabs: [], activeTab: null, generation: 0 }
    return { id, state: session.context ? session.lease ? 'owner_control' : 'ready' : 'stopped', controller: session.controller || null, generation: session.generation, activeTab: session.active, tabs: [...session.tabs].map(([tabId, page]) => ({ id: tabId, title: session.titles.get(tabId) || '新标签页', url: page.url() })) }
  }
  async start(id) {
    if (!validId(id)) throw new RuntimeError('invalid_session', '浏览器会话标识无效', 400)
    if (this.closed || this.stopping.has(id)) throw new RuntimeError('busy', '运行时正在停止')
    if (this.starting.has(id)) return this.starting.get(id)
    if (this.sessions.get(id)?.context) return this.state(id)
    const job = this.startOnce(id).finally(() => this.starting.delete(id)); this.starting.set(id, job); return job
  }
  async startOnce(id) {
    const report = await this.prepare()
    if (report.state !== 'ready') throw new RuntimeError(report.state, '请先完成环境检测并安装或修复 Google Chrome')
    const profile = path.join(this.directory, 'profiles', id)
    await fs.mkdir(profile, { recursive: true, mode: 0o700 })
    let context
    try { context = await this.launch(profile) } catch { throw new RuntimeError('launch_failed', 'Chrome 启动失败，资料可能已被另一进程占用') }
    if (this.closed || this.stopping.has(id)) { await context.close(); throw new RuntimeError('closed', '运行时正在停止') }
    const session = { id, context, tabs: new Map(), titles: new Map(), active: null, generation: 1, lease: null, stream: null, streamJob: Promise.resolve(), operation: Promise.resolve(), observers: 0, frame: 0 }
    this.sessions.set(id, session)
    const register = page => {
      if ([...session.tabs.values()].includes(page)) return
      const tabId = randomUUID(); session.tabs.set(tabId, page); session.active = tabId; session.generation++
      page.on('dialog', dialog => dialog.dismiss().catch(() => {}))
      page.on('framenavigated', frame => {
        if (frame !== page.mainFrame()) return
        session.generation++; this.changed(session)
        page.title().then(title => { session.titles.set(tabId, title); this.changed(session) }).catch(() => {})
      })
      page.on('close', () => {
        session.tabs.delete(tabId); session.titles.delete(tabId)
        if (session.active === tabId) session.active = session.tabs.keys().next().value || null
        session.generation++; this.changed(session); this.refreshStream(session)
      })
      this.changed(session); this.refreshStream(session)
    }
    context.on('page', register)
    context.on('close', () => {
      session.context = null; session.lease = null; session.controller = null; session.tabs.clear(); session.active = null; session.generation++
      this.changed(session)
    })
    for (const page of context.pages()) register(page)
    if (!session.tabs.size) await context.newPage()
    return this.state(id)
  }
  changed(session) { this.emit('state', this.state(session.id)); this.refreshStream(session) }
  async stop(id) {
    this.stopping.add(id)
    try {
      await this.starting.get(id)?.catch(() => {})
      const session = this.sessions.get(id)
      if (session?.context) { session.lease = null; session.generation++; await session.context.close() }
      return this.state(id)
    } finally { this.stopping.delete(id) }
  }
  claim(id, controller = null) {
    this.requireReady()
    const session = this.get(id); session.lease = randomUUID(); session.controller = controller; session.generation++; this.changed(session)
    return { lease: session.lease, generation: session.generation }
  }
  release(id, lease) {
    const session = this.get(id)
    if (lease !== session.lease) throw new RuntimeError('stale_control', '操作权限已失效，请重新接管')
    session.lease = null; session.controller = null; session.generation++; this.changed(session); return this.state(id)
  }
  watch(id, delta) {
    const session = this.get(id); session.observers = Math.max(0, session.observers + delta); this.refreshStream(session)
  }
  refreshStream(session) {
    session.streamJob = session.streamJob.catch(() => {}).then(async () => {
      const page = session.tabs.get(session.active)
      if (session.stream && (session.stream.page !== page || session.stream.generation !== session.generation || !session.observers || !session.context)) {
        await session.stream.page.screencast.stop().catch(() => {}); session.stream = null
      }
      if (!session.context || !page || !session.observers || session.stream) return
      if (!page.screencast?.start) { this.emit('streamError', { id: session.id, detail: '当前驱动不支持页面实时采集' }); return }
      const stream = { page, tab: session.active, generation: session.generation }; session.stream = stream
      try {
        await page.screencast.start({ onFrame: frame => {
          if (session.stream !== stream || session.active !== stream.tab || stream.generation !== session.generation || !session.context) return
          this.emit('frame', { id: session.id, tabId: stream.tab, generation: stream.generation, sequence: ++session.frame, timestamp: frame.timestamp, viewportWidth: frame.viewportWidth, viewportHeight: frame.viewportHeight, data: frame.data })
        } })
      } catch { session.stream = null; this.emit('streamError', { id: session.id, detail: '实时采集失败，请重新连接' }) }
    })
    return session.streamJob
  }
  async action(id, input) {
    const session = this.get(id)
    // Serialize all inputs; recheck ownership when queued input actually executes.
    const job = session.operation.catch(() => {}).then(() => this.perform(session, input))
    session.operation = job; return job
  }
  async perform(session, input) {
    this.requireReady()
    const { lease, generation, tabId, kind } = input || {}
    if (!session.context || !session.lease || lease !== session.lease || generation !== session.generation || tabId !== session.active) throw new RuntimeError('stale_control', '页面或操作权限已变化，请等待最新画面后重试')
    if (kind === 'new_tab') { await session.context.newPage(); this.changed(session); return this.state(session.id) }
    const page = session.tabs.get(tabId)
    if (!page) throw new RuntimeError('tab_closed', '标签页已关闭')
    if (kind === 'navigate') await page.goto(navigationURL(input.url), { waitUntil: 'domcontentloaded', timeout: 20000 })
    else if (kind === 'back') await page.goBack({ waitUntil: 'domcontentloaded', timeout: 20000 })
    else if (kind === 'forward') await page.goForward({ waitUntil: 'domcontentloaded', timeout: 20000 })
    else if (kind === 'reload') await page.reload({ waitUntil: 'domcontentloaded', timeout: 20000 })
    else if (kind === 'switch_tab') {
      if (!session.tabs.has(input.target)) throw new RuntimeError('tab_closed', '标签页已关闭')
      session.active = input.target; session.generation++; await session.tabs.get(input.target).bringToFront(); await this.refreshStream(session)
    } else if (kind === 'close_tab') await page.close()
    else if (kind === 'click') {
      const viewport = page.viewportSize()
      if (!Number.isFinite(input.x) || !Number.isFinite(input.y) || input.x < 0 || input.y < 0 || input.x >= viewport.width || input.y >= viewport.height) throw new RuntimeError('invalid_coordinates', '点击位置超出当前画面', 400)
      await page.mouse.click(input.x, input.y)
    } else if (kind === 'scroll') {
      if (![input.deltaX, input.deltaY].every(value => Number.isFinite(value) && Math.abs(value) <= 3000)) throw new RuntimeError('invalid_scroll', '滚动参数无效', 400)
      await page.mouse.wheel(input.deltaX, input.deltaY)
    } else if (kind === 'text') {
      if (typeof input.text !== 'string' || input.text.length > 5000) throw new RuntimeError('invalid_text', '输入文字过长', 400)
      await page.keyboard.insertText(input.text)
    } else if (kind === 'key') {
      if (!['Enter', 'Tab', 'Shift+Tab', 'Escape', 'Backspace', 'Delete', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'ControlOrMeta+A'].includes(input.key)) throw new RuntimeError('invalid_key', '不支持此按键', 400)
      await page.keyboard.press(input.key)
    } else throw new RuntimeError('invalid_action', '不支持此操作', 400)
    this.changed(session); return this.state(session.id)
  }
  async observe(id) {
    const session = this.get(id), page = session.tabs.get(session.active)
    if (!page) throw new RuntimeError('tab_closed', '没有可用标签页')
    return { ...this.state(id), aria: (await page.locator('body').ariaSnapshot()).slice(0, 24000), viewport: page.viewportSize() }
  }
  requireReady() {
    if (this.closed || this.environment.cached?.state !== 'ready') throw new RuntimeError('environment_not_ready', '环境尚未就绪，请重新检测并修复前置条件')
  }
  async close() {
    this.closed = true
    await this.environmentJob?.catch(() => {})
    await Promise.allSettled([...new Set([...this.sessions.keys(), ...this.starting.keys()])].map(id => this.stop(id)))
  }
}
