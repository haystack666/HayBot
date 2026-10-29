import { randomUUID } from 'node:crypto'
import { RuntimeError } from './environment.mjs'

const platform = value => { try { const u = new URL(value); return u.protocol === 'https:' && (u.hostname === 'douyin.com' || u.hostname === 'www.douyin.com') } catch { return false } }
const videoId = value => typeof value === 'string' && /^\d{6,30}$/.test(value)
const text = (value, limit = 500) => typeof value === 'string' ? value.slice(0, limit) : ''

// Only content fields from responses requested by the real page are retained.
// No cookies, signed URLs, user messages or arbitrary API execution enter the model.
export function contentItems(payload) {
  const found = new Map()
  const walk = (value, depth) => {
    if (!value || typeof value !== 'object' || depth > 7 || found.size >= 60) return
    if (videoId(value.aweme_id) && typeof value.desc === 'string' && !value.is_ads && !value.live_room && value.aweme_type !== 101) {
      found.set(value.aweme_id, { id: value.aweme_id, title: text(value.desc), author: text(value.author?.nickname, 80),
        duration: Number(value.video?.duration) > 0 ? Math.round(value.video.duration / 1000) : null,
        url: 'https://www.douyin.com/video/' + value.aweme_id, source: 'page_response' })
    }
    for (const item of (Array.isArray(value) ? value.slice(0,60) : Object.values(value).slice(0,60))) walk(item, depth + 1)
  }
  walk(payload, 0); return [...found.values()]
}

export class DouyinAutomation {
  constructor(engine) { this.engine = engine; this.ended = new Set() }
  begin(id, input = {}) {
    const session = this.engine.get(id)
    this.engine.requireObservation(session)
    if (session.lease || session.automation) throw new RuntimeError('automation_busy', '当前浏览器正在被接管或执行任务')
    const page = session.tabs.get(session.active)
    if (!page) throw new RuntimeError('tab_closed', '请先创建浏览器标签页')
    const token = input.runId || randomUUID()
    if (typeof token !== 'string' || !/^[a-zA-Z0-9-]{16,64}$/.test(token)) throw new RuntimeError('invalid_run', '任务标识无效', 400)
    if (this.ended.has(token)) throw new RuntimeError('automation_revoked', '本次任务已停止')
    const run = { token, page, tab: session.active, items: new Map(), currentItems: new Map(), pending: new Set(), cancelled: false }
    run.response = response => {
      let url
      try { url = new URL(response.url()) } catch { return }
      if (!platform(url.href) || !/\/aweme\/v\d+\/web\/(?:tab\/feed|module\/feed|aweme\/detail|general\/search|search\/item)/.test(url.pathname)) return
      if (!/json/i.test(response.headers()['content-type'] || '') || Number(response.headers()['content-length']) > 2000000) return
      const generation = session.generation
      const work = (async () => {
        try {
          const body = await response.text()
          if (body.length > 2000000 || session.automation !== run || session.generation !== generation || !platform(page.url())) return
          for (const item of contentItems(JSON.parse(body))) { run.items.set(item.id, item); run.currentItems.set(item.id,item) }
          while (run.items.size > 200) run.items.delete(run.items.keys().next().value)
          while (run.currentItems.size > 60) run.currentItems.delete(run.currentItems.keys().next().value)
        } catch { /* An incomplete response is not content evidence. */ }
      })()
      run.pending.add(work); work.finally(() => run.pending.delete(work))
    }
    page.on('response', run.response); session.automation = run; this.engine.changed(session)
    this.renew(session, run)
    return { token: run.token }
  }
  renew(session, run) {
    clearTimeout(run.expiryTimer)
    run.expires = Date.now() + 120000
    run.expiryTimer = setTimeout(() => { if (session.automation === run) this.revoke(session) }, 120000)
    run.expiryTimer.unref()
  }
  end(id, token) {
    if (typeof token !== 'string' || !/^[a-zA-Z0-9-]{16,64}$/.test(token)) throw new RuntimeError('invalid_run', '任务标识无效', 400)
    this.ended.add(token)
    while (this.ended.size > 1000) this.ended.delete(this.ended.values().next().value)
    const session = this.engine.sessions.get(id), run = session?.automation
    if (run && run.token === token) this.revoke(session)
    return { stopped: true }
  }
  revoke(session) {
    const run = session.automation
    if (!run) return
    this.ended.add(run.token)
    while (this.ended.size > 1000) this.ended.delete(this.ended.values().next().value)
    clearTimeout(run.expiryTimer)
    run.cancelled = true; run.page.off('response', run.response); session.automation = null
    this.engine.changed(session)
  }
  guard(session, run) {
    this.engine.requireReady(); this.engine.requireObservation(session)
    if (run && Date.now() >= run.expires && session.automation === run) this.revoke(session)
    if (!session.context || session.lease || !run || run.cancelled || session.automation !== run || session.active !== run.tab || session.tabs.get(run.tab) !== run.page) throw new RuntimeError('automation_revoked', '任务操作权已撤销，请查看画面后重新发起任务')
  }
  async act(id, input) {
    const session = this.engine.get(id), run = session.automation
    if (!run || input.token !== run.token) throw new RuntimeError('automation_revoked', '任务操作权已失效')
    const job = session.operation.catch(() => {}).then(() => this.perform(session, run, input))
    session.operation = job; return job
  }
  async perform(session, run, input) {
    this.guard(session, run)
    this.renew(session, run)
    const page = run.page, op = input.op
    if (!['observe', 'home', 'search', 'open', 'next', 'scroll', 'watch', 'comments'].includes(op)) throw new RuntimeError('invalid_action', '不支持此抖音操作', 400)
    if (input.generation !== session.generation) throw new RuntimeError('stale_observation', '页面已变化，请重新观察')
    if (!['home', 'search'].includes(op) && !platform(page.url())) throw new RuntimeError('wrong_platform', '当前已离开抖音，请先返回抖音')
    if (op === 'home' || op === 'search' || op === 'open') {
      let url = 'https://www.douyin.com/'
      if (op === 'search') {
        if (typeof input.query !== 'string' || !input.query.trim() || input.query.length > 100) throw new RuntimeError('invalid_query', '搜索关键词须为 1–100 字', 400)
        url += 'search/' + encodeURIComponent(input.query.trim()) + '?type=video'
      }
      if (op === 'open') {
        if (!videoId(input.id) || !run.items.has(input.id)) throw new RuntimeError('unobserved_video', '只能打开当前任务真实观察到的视频', 400)
        url += 'video/' + input.id
      }
      run.currentItems.clear()
      this.guard(session, run)
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 25000 }).catch(error => { if (error.name !== 'TimeoutError') throw error })
      await this.wait(session, run, 2000)
    } else if (op === 'next' || op === 'scroll') {
      this.guard(session, run)
      if (op === 'next') await page.keyboard.press('ArrowDown')
      else { await page.mouse.move(750, 550); this.guard(session, run); await page.mouse.wheel(0, 650) }
      await this.wait(session, run, 1200)
    } else if (op === 'comments') {
      // Reading visible comments only; opening the comment panel cannot submit text.
      const trigger = page.locator('[data-e2e="video-comment"],[data-e2e="feed-comment-icon"]').filter({visible:true}).first()
      if (await trigger.count()) { this.guard(session, run); await trigger.click({ timeout: 2000, noWaitAfter: true }) }
      await this.wait(session, run, 800)
    }
    let playback, images
    if (op === 'watch') {
      if (!Number.isInteger(input.seconds) || input.seconds < 3 || input.seconds > 30) throw new RuntimeError('invalid_duration', '每次观看支持 3–30 秒，可连续观看', 400)
      const before = await this.snapshot(session, run)
      if (before.blocked) return before
      // Starting playback is reversible. Never call a like/comment/share element.
      this.guard(session, run)
      await page.locator('video').evaluateAll(videos => {
        const video = videos.filter(v => {const r=v.getBoundingClientRect();return r.width>100&&r.height>100&&r.bottom>0&&r.top<innerHeight}).sort((a,b)=>b.getBoundingClientRect().width*b.getBoundingClientRect().height-a.getBoundingClientRect().width*a.getBoundingClientRect().height)[0]
        if (video) { video.muted = true; video.play().catch(()=>{}) }
      })
      images = []; const samples = []; let advancedSeconds = 0, previous = before.playback
      for (let i = 0; i < 3; i++) {
        await this.wait(session, run, Math.round(input.seconds * 1000 / 3))
        const shot = await this.snapshot(session, run)
        if (shot.blocked) return shot
        if (before.current?.id && shot.current?.id && before.current.id !== shot.current.id) throw new RuntimeError('stale_observation', '页面已变化，请重新观察')
        samples.push(shot.playback)
        const current = shot.playback
        if (previous && current && previous.source === current.source && current.currentTime > previous.currentTime) advancedSeconds += Math.min(input.seconds / 3 + 1, current.currentTime - previous.currentTime)
        previous = current
        this.guard(session, run)
        const image = await page.screenshot({ type: 'jpeg', quality: 55, scale: 'css', timeout: 3000 })
        this.guard(session, run); images.push(image.toString('base64'))
      }
      playback = { requestedSeconds: input.seconds, advancedSeconds: Math.round(advancedSeconds * 10) / 10, samples, visualOnly: true, audioAvailable: false }
    }
    const result = await this.snapshot(session, run)
    if (playback) result.watch = playback
    if (images) result.images = images
    return result
  }
  async wait(session, run, milliseconds) {
    const deadline = Date.now() + milliseconds
    while (Date.now() < deadline) { this.guard(session, run); await new Promise(resolve => setTimeout(resolve, Math.min(200, deadline - Date.now()))) }
    this.guard(session, run)
  }
  async snapshot(session, run) {
    this.guard(session, run)
    const generation = session.generation, page = run.page
    if (!platform(page.url())) throw new RuntimeError('wrong_platform', '当前已离开抖音，已停止读取页面')
    const data = await page.evaluate(() => {
      const visible = el => { const r = el.getBoundingClientRect(), s=getComputedStyle(el); return r.width>0 && r.height>0 && r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth && s.visibility!=='hidden' && s.display!=='none' }
      const items = new Map()
      for (const a of document.querySelectorAll('a[href*="/video/"]')) {
        if (!visible(a)) continue
        const match = a.href.match(/\/video\/(\d{6,30})/)
        if (!match || items.has(match[1])) continue
        const card = a.closest('li,[data-e2e="search-result-card"]') || a
        items.set(match[1], { id:match[1], title:(card.innerText||a.querySelector('img')?.alt||'').trim().slice(0,500), author:'', source:'visible_dom', url:'https://www.douyin.com/video/'+match[1] })
        if(items.size>=30)break
      }
      const videos = [...document.querySelectorAll('video')].filter(visible).sort((a,b)=>{const x=a.getBoundingClientRect(),y=b.getBoundingClientRect();return y.width*y.height-x.width*x.height})
      const v = videos[0]
      const info = [...document.querySelectorAll('[data-e2e="detail-video-info"],[data-e2e-aweme-id]')].find(visible)
      const detail = info ? { id: info.getAttribute('data-e2e-aweme-id') || '', title:(info.querySelector('h1')?.innerText||info.innerText||'').slice(0,500), author:document.querySelector('[data-e2e="user-info"] img[alt]')?.alt||'', source:'visible_dom' } : null
      const modal = [...document.querySelectorAll('[role="dialog"],[class*="captcha"],[id*="captcha"],[data-e2e*="login"]')].filter(visible).map(el=>(el.innerText||'').slice(0,1200)).join('\n')
      const loginForm = [...document.querySelectorAll('input[type="password"],input[placeholder*="手机号"],input[placeholder*="验证码"]')].some(visible)
      const challenge = /验证码|安全验证|中间页/.test(document.title) || [...document.querySelectorAll('iframe')].filter(visible).some(f => /captcha|verify|验证/i.test(f.src+' '+f.title))
      return { items:[...items.values()], detail, modal, challenge, loginForm, body:(document.body?.innerText||'').slice(0,14000),
        playback:v ? {currentTime:Number(v.currentTime)||0,duration:Number.isFinite(v.duration)?v.duration:null,paused:v.paused,readyState:v.readyState,ended:v.ended,source:(v.currentSrc||'').split('?')[0].slice(-150)} : null }
    })
    this.guard(session, run)
    if (!platform(page.url())) throw new RuntimeError('wrong_platform', '当前已离开抖音，已停止读取页面')
    if (generation !== session.generation) throw new RuntimeError('stale_observation', '页面已变化，请重新观察')
    for (const item of data.items) { if (!run.items.has(item.id)) run.items.set(item.id,item); run.currentItems.set(item.id,run.items.get(item.id)) }
    while(run.items.size>200)run.items.delete(run.items.keys().next().value)
    const url = page.url(), match = url.match(/(?:\/video\/|[?&]modal_id=)(\d{6,30})/)
    const currentId = videoId(data.detail?.id) ? data.detail.id : match?.[1]
    const current = currentId ? run.items.get(currentId) || { id:currentId, url:'https://www.douyin.com/video/'+currentId, title:data.detail?.title || '', author:data.detail?.author || '' } : null
    if (current) run.items.set(current.id,current)
    const blocked = data.challenge || /验证码|安全验证|完成验证|拖动滑块|验证后继续/.test(data.modal) ? 'captcha' : data.loginForm || /登录后(?:即可|查看|搜索)|扫码登录|手机号登录/.test(data.modal) ? 'login' : ''
    return { platform:'douyin', generation, url, blocked, body:blocked ? '' : data.body, items:blocked ? [] : [...run.currentItems.values()].slice(-40), current:blocked ? null : current, playback:blocked ? null : data.playback }
  }
}
