import path from 'node:path'
import { promises as fs } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { EventEmitter } from 'node:events'
import { chromium } from 'playwright'
import { Environment, RuntimeError } from './environment.mjs'
import { BrowserOptions, DEFAULT_OPTIONS } from './options.mjs'
import { DouyinAutomation } from './douyin.mjs'

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
    this.options = new BrowserOptions(directory); this.configuring = new Set()
    this.douyin = new DouyinAutomation(this)
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
      // The short environment probe stays hidden regardless of the Bot's mode.
      context = await this.launch(temporary)
      await context.newPage(); this.environment.setLaunch(report, true)
    } catch { this.environment.setLaunch(report, false) }
    finally { await context?.close().catch(() => {}); await fs.rm(temporary, { recursive: true, force: true }) }
    return report
  }
  launch(profile) {
    return this.browserType.launchPersistentContext(profile, {
      channel: 'chrome', executablePath: this.environment.cached?.chrome.executable || undefined,
      headless: true, viewport: { width: 1600, height: 900 },
      acceptDownloads: false, timeout: 30000,
      args: ['--no-first-run', '--no-default-browser-check', '--mute-audio'],
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
    const options = { ...(session?.options || this.options.values.get(id) || DEFAULT_OPTIONS) }
    if (!session) return { id, state: 'stopped', tabs: [], activeTab: null, generation: 0, options }
    return { id, state: session.context ? session.lease ? 'owner_control' : 'ready' : 'stopped', automation: !!session.automation, owner_login: !!session.ownerLogin, controller: session.controller || null, generation: session.generation, activeTab: session.active, options, tabs: [...session.tabs].map(([tabId, page]) => ({ id: tabId, title: session.titles.get(tabId) || '新标签页', url: page.url() })) }
  }
  async settings(id) { return this.options.get(id) }
  async configure(id, input) {
    this.options.filename(id)
    if (this.closed || this.starting.has(id) || this.stopping.has(id) || this.configuring.has(id) || this.sessions.get(id)?.context) throw new RuntimeError('settings_busy', '请先停止浏览器再修改启动模式；登录资料会保留')
    this.configuring.add(id)
    try {
      const options = await this.options.save(id, input)
      const session = this.sessions.get(id)
      if (session) session.options = options
      this.emit('state', this.state(id))
      return this.state(id)
    } finally { this.configuring.delete(id) }
  }
  async start(id) {
    if (!validId(id)) throw new RuntimeError('invalid_session', '浏览器会话标识无效', 400)
    if (this.closed || this.stopping.has(id) || this.configuring.has(id)) throw new RuntimeError('busy', '运行时正在停止或保存设置，请稍后重试')
    if (this.starting.has(id)) return this.starting.get(id)
    if (this.sessions.get(id)?.context) return this.state(id)
    const job = this.startOnce(id).finally(() => this.starting.delete(id)); this.starting.set(id, job); return job
  }
  async startOnce(id) {
    const options = await this.settings(id)
    const report = await this.prepare()
    if (report.state !== 'ready') throw new RuntimeError(report.state, '请先完成环境检测并安装或修复 Google Chrome')
    const profile = path.join(this.directory, 'profiles', id)
    await fs.mkdir(profile, { recursive: true, mode: 0o700 })
    let ownerLogin = false
    try { ownerLogin = JSON.parse(await fs.readFile(path.join(profile, 'haybot-login.json'), 'utf8')).paused !== false }
    catch (error) { if (error.code !== 'ENOENT') ownerLogin = true }
    let context
    try { context = await this.launch(profile) } catch { throw new RuntimeError('launch_failed', 'Chrome 无头启动失败，请检查安装状态与资料目录占用') }
    if (this.closed || this.stopping.has(id)) { await context.close(); throw new RuntimeError('closed', '运行时正在停止') }
    const session = { id, context, options, ownerLogin, tabs: new Map(), titles: new Map(), active: null, generation: 1, lease: null, stream: null, streamJob: Promise.resolve(), operation: Promise.resolve(), observers: 0, frame: 0 }
    this.sessions.set(id, session)
    const register = page => {
      if (session.creatingAuxiliary) {session.auxiliaryPages ||= new Set();session.auxiliaryPages.add(page);page.once('close',()=>session.auxiliaryPages.delete(page));page.on('dialog',dialog=>dialog.dismiss().catch(()=>{}));return}
      if ([...session.tabs.values()].includes(page)) return
      this.cancelPointer(session)
      const tabId = randomUUID(); session.tabs.set(tabId, page); session.active = tabId; session.generation++
      page.on('dialog', dialog => dialog.dismiss().catch(() => {}))
      page.on('framenavigated', frame => {
        if (frame !== page.mainFrame()) return
        this.cancelPointer(session)
        session.generation++; this.changed(session)
        page.title().then(title => { session.titles.set(tabId, title); this.changed(session) }).catch(() => {})
      })
      page.on('close', () => {
        this.cancelPointer(session)
        session.tabs.delete(tabId); session.titles.delete(tabId)
        if (session.active === tabId) session.active = session.tabs.keys().next().value || null
        session.generation++; this.changed(session); this.refreshStream(session)
      })
      this.changed(session); this.refreshStream(session)
    }
    context.on('page', register)
    context.on('close', () => {
      this.douyin.revoke(session)
      this.cancelPointer(session)
      session.context = null; session.lease = null; session.controller = null; session.tabs.clear(); session.active = null; session.generation++
      this.changed(session)
    })
    for (const page of context.pages()) register(page)
    if (!session.tabs.size) await context.newPage()
    return this.state(id)
  }
  async auxiliaryPage(session) {
    // Created only at a serialized automation boundary. It shares this Bot's
    // login context, but cannot change the active tab, generation or live view.
    session.creatingAuxiliary = true
    try {return await session.context.newPage()}
    finally {session.creatingAuxiliary = false}
  }
  changed(session) { this.emit('state', this.state(session.id)); this.refreshStream(session) }
  async stop(id) {
    this.stopping.add(id)
    try {
      await this.starting.get(id)?.catch(() => {})
      const session = this.sessions.get(id)
      if (session?.context) { this.douyin.revoke(session); this.cancelPointer(session); session.lease = null; session.generation++; await session.context.close() }
      return this.state(id)
    } finally { this.stopping.delete(id) }
  }
  claim(id, controller = null) {
    this.requireReady()
    const session = this.get(id); this.douyin.revoke(session); this.cancelPointer(session); session.lease = randomUUID(); session.controller = controller; session.generation++; this.changed(session)
    return { lease: session.lease, generation: session.generation }
  }
  release(id, lease) {
    const session = this.get(id)
    if (lease !== session.lease) throw new RuntimeError('stale_control', '操作权限已失效，请重新接管')
    this.cancelPointer(session); session.lease = null; session.controller = null; session.generation++; this.changed(session); return this.state(id)
  }
  point(page, input) {
    const viewport = page.viewportSize()
    if (!Number.isFinite(input.x) || !Number.isFinite(input.y) || input.x < 0 || input.y < 0 || input.x >= viewport.width || input.y >= viewport.height) throw new RuntimeError('invalid_coordinates', '操作位置超出当前画面', 400)
    return { x: input.x, y: input.y }
  }
  async liftPointer(pointer, cancelled = false) {
    clearTimeout(pointer.timer)
    if (pointer.mode !== 'drag') return
    try {
      // Release outside the page on cancellation to avoid turning a lost tap into a click.
      if (cancelled) await pointer.page.mouse.move(-1, -1)
      await pointer.page.mouse.up()
    } catch { /* A closed/crashed page has already released its native input. */ }
  }
  cancelPointer(session) {
    const pointer = session.pointer
    if (!pointer) return
    session.pointer = null; clearTimeout(pointer.timer)
    // Queue the release after an in-flight mouse.down, before the next owner's input.
    session.operation = session.operation.catch(() => {}).then(() => this.liftPointer(pointer, true))
  }
  async pointerInput(session, page, input) {
    const { phase, gestureId } = input
    if (!validId(gestureId) || !['start', 'move', 'end', 'cancel'].includes(phase)) throw new RuntimeError('invalid_pointer', '手势参数无效', 400)
    const point = phase === 'cancel' ? null : this.point(page, input)
    let pointer = session.pointer
    if (phase === 'start') {
      if (!['drag', 'swipe'].includes(input.mode)) throw new RuntimeError('invalid_pointer', '手势模式无效', 400)
      if (pointer) throw new RuntimeError('pointer_busy', '前一次手势尚未结束')
      pointer = { id: gestureId, page, mode: input.mode, last: point, start: point, moved: false }
      session.pointer = pointer
      try {
        await page.mouse.move(point.x, point.y)
        if (session.pointer !== pointer) throw new RuntimeError('stale_control', '手势已取消，请重新操作')
        if (pointer.mode === 'drag') await page.mouse.down()
      } catch (error) {
        if (session.pointer === pointer) { session.pointer = null; await this.liftPointer(pointer, true) }
        throw error
      }
    } else {
      if (!pointer || pointer.id !== gestureId || pointer.page !== page) throw new RuntimeError('stale_pointer', '手势已结束或取消，请重新操作')
      if (phase === 'cancel') { session.pointer = null; await this.liftPointer(pointer, true); return }
      clearTimeout(pointer.timer)
      try {
        if (pointer.mode === 'drag') await page.mouse.move(point.x, point.y)
        else {
          if (Math.hypot(point.x - pointer.start.x, point.y - pointer.start.y) >= 4) pointer.moved = true
          // A swipe scrolls the desktop page under the original finger position.
          // Keeping the anchor fixed also routes scrolling into nested scroll containers.
          if (pointer.moved) {
            await page.mouse.move(pointer.start.x, pointer.start.y)
            if (session.pointer !== pointer) throw new RuntimeError('stale_control', '手势已取消，请重新操作')
            await page.mouse.wheel(pointer.last.x - point.x, pointer.last.y - point.y)
          }
        }
        if (session.pointer !== pointer) throw new RuntimeError('stale_control', '手势已取消，请重新操作')
        pointer.last = point
        if (phase === 'end') {
          session.pointer = null
          await this.liftPointer(pointer)
          if (pointer.mode === 'swipe' && !pointer.moved) await page.mouse.click(point.x, point.y)
          return
        }
      } catch (error) {
        if (session.pointer === pointer) { session.pointer = null; await this.liftPointer(pointer, true) }
        throw error
      }
    }
    if (session.pointer === pointer) {
      clearTimeout(pointer.timer)
      pointer.timer = setTimeout(() => this.cancelPointer(session), 10000); pointer.timer.unref()
    }
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
    if (kind === 'new_tab') {
      if (session.pointer) { const pointer = session.pointer; session.pointer = null; await this.liftPointer(pointer, true) }
      await session.context.newPage(); this.changed(session); return this.state(session.id)
    }
    const page = session.tabs.get(tabId)
    if (!page) throw new RuntimeError('tab_closed', '标签页已关闭')
    if (kind === 'pointer') {
      await this.pointerInput(session, page, input)
      return this.state(session.id)
    }
    if (session.pointer) {
      const pointer = session.pointer; session.pointer = null; await this.liftPointer(pointer, true)
    }
    if (kind === 'navigate') await page.goto(navigationURL(input.url), { waitUntil: 'domcontentloaded', timeout: 20000 })
    else if (kind === 'back') await page.goBack({ waitUntil: 'domcontentloaded', timeout: 20000 })
    else if (kind === 'forward') await page.goForward({ waitUntil: 'domcontentloaded', timeout: 20000 })
    else if (kind === 'reload') await page.reload({ waitUntil: 'domcontentloaded', timeout: 20000 })
    else if (kind === 'switch_tab') {
      if (!session.tabs.has(input.target)) throw new RuntimeError('tab_closed', '标签页已关闭')
      session.active = input.target; session.generation++; await this.refreshStream(session)
    } else if (kind === 'close_tab') await page.close()
    else if (kind === 'click') {
      const point = this.point(page, input)
      await page.mouse.click(point.x, point.y)
    } else if (kind === 'scroll') {
      if (![input.deltaX, input.deltaY].every(value => Number.isFinite(value) && Math.abs(value) <= 3000)) throw new RuntimeError('invalid_scroll', '滚动参数无效', 400)
      if (input.x !== undefined || input.y !== undefined) { const point = this.point(page, input); await page.mouse.move(point.x, point.y) }
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
    this.requireObservation(session)
    if (!page) throw new RuntimeError('tab_closed', '没有可用标签页')
    const generation = session.generation
    const aria = (await page.locator('body').ariaSnapshot()).slice(0, 24000)
    this.requireObservation(session)
    if (!session.context || generation !== session.generation || page !== session.tabs.get(session.active)) throw new RuntimeError('stale_observation', '页面已变化，请重新观察')
    return { ...this.state(id), aria, viewport: page.viewportSize() }
  }
  requireObservation(session) {
    if (session.ownerLogin) throw new RuntimeError('owner_login', '主人正在登录，已暂停模型读取页面')
    if (session.controller) throw new RuntimeError('owner_control', '主人正在接管，已暂停模型读取页面')
  }
  async setLogin(id, lease, paused) {
    const session = this.get(id)
    const job = session.operation.catch(() => {}).then(async () => {
      if (!session.context || !lease || lease !== session.lease) throw new RuntimeError('stale_control', '请先接管当前浏览器')
      // Begin closes the observation fence before touching the filesystem. Finish
      // opens it only after durable storage succeeds. Disconnect/stop never clears it.
      if (paused) session.ownerLogin = true
      this.cancelPointer(session)
      session.generation++; this.changed(session)
      const filename = path.join(this.directory, 'profiles', id, 'haybot-login.json')
      const temporary = filename + '.' + randomUUID()
      try {
        await fs.writeFile(temporary, JSON.stringify({ paused }), { mode: 0o600, flag: 'wx' })
        if (!session.context || lease !== session.lease) throw new Error('Control revoked while storing login state')
        await fs.rename(temporary, filename)
        if (!session.context || lease !== session.lease) {
          await fs.writeFile(filename, JSON.stringify({ paused: true }), { mode: 0o600 })
          throw new Error('Control revoked while committing login state')
        }
      } catch {
        session.ownerLogin = true; this.changed(session)
        throw new RuntimeError('login_state_failed', '登录隔离状态保存失败，请保持暂停并检查磁盘')
      } finally { await fs.unlink(temporary).catch(() => {}) }
      session.ownerLogin = paused; this.changed(session)
      return this.state(id)
    })
    session.operation = job
    return job
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
