import { randomUUID } from 'node:crypto'
import { RuntimeError } from './environment.mjs'
import { DouyinSocial, writeOps, verificationDOM } from './douyin-social.mjs'

const platform = value => { try { const u = new URL(value); return u.protocol === 'https:' && (u.hostname === 'douyin.com' || u.hostname === 'www.douyin.com') } catch { return false } }
const videoId = value => typeof value === 'string' && /^\d{6,30}$/.test(value)
const text = (value, limit = 500) => typeof value === 'string' ? value.slice(0, limit) : ''

export const defaultViewing = Object.freeze({preview_enabled:true,preview_after_minutes:3,max_video_minutes:60,segment_seconds:15,skip_seconds:0})

export function viewingConfig(value = {}) {
  if (!value || typeof value!=='object' || Array.isArray(value) || Object.keys(value).some(key=>!Object.hasOwn(defaultViewing,key))) throw new RuntimeError('invalid_viewing','观看策略格式不正确',400)
  const config={...defaultViewing,...value}
  if(typeof config.preview_enabled!=='boolean' || ![['preview_after_minutes',1,120],['max_video_minutes',1,120],['segment_seconds',3,30],['skip_seconds',0,3600]].every(([key,min,max])=>Number.isInteger(config[key])&&config[key]>=min&&config[key]<=max) || config.preview_enabled&&config.preview_after_minutes>config.max_video_minutes)throw new RuntimeError('invalid_viewing','请检查观看策略范围，跳看起始时长不能大于最长视频时长',400)
  return Object.freeze(config)
}

export function watchPolicy(duration, config = defaultViewing) {
  if (!Number.isFinite(duration) || duration <= 0) return { mode:'unknown', duration:null }
  return { mode:duration>config.max_video_minutes*60?'skip':config.preview_enabled&&duration>config.preview_after_minutes*60?'preview':'normal', duration }
}

export function previewPosition(duration, coverage, seconds, requested, skipSeconds = 0) {
  if (requested !== undefined) return Math.min(requested, duration - 3)
  if(skipSeconds>0) {
    if(!coverage.length)return 0
    const next=Math.max(...coverage.map(([,end])=>end))+skipSeconds
    return next<=duration-3?next:null
  }
  // A default spread supports exploration without dictating what the model
  // must watch. It may choose another position or leave after any segment.
  return [0, duration/3, duration*2/3, Math.max(0,duration-seconds)]
    .find(at => !coverage.some(([a,b]) => a <= at+0.5 && b >= Math.min(at+3,duration)-0.25)) ?? null
}

export function mergeRanges(ranges) {
  const result = []
  for (const [start, end] of ranges.filter(([a,b]) => Number.isFinite(a) && Number.isFinite(b) && b > a).sort((a,b) => a[0]-b[0])) {
    const previous = result.at(-1)
    if (previous && start <= previous[1] + 0.15) previous[1] = Math.max(previous[1], end)
    else result.push([start,end])
  }
  return result.map(pair => pair.map(n => Math.round(n * 100) / 100))
}

// A CDN URL may change on reload or rendition switch. Coverage belongs to the
// stable video ID and timeline; source equality is required only within a sample.
export function videoCoverage(run, current, duration) {
  if (!current?.id) return []
  const known = run.coverageDurations.get(current.id)
  if (Number.isFinite(duration) && duration > 0) {
    if (known && Math.abs(known-duration) > Math.max(1, known*0.01)) run.coverage.delete(current.id)
    run.coverageDurations.set(current.id, duration)
  }
  return run.coverage.get(current.id) || []
}

export function playbackRanges(previous, current, seconds) {
  if (!previous || !current || previous.source !== current.source) return []
  const start=previous.currentTime,end=current.currentTime,duration=current.duration
  if (end > start && end-start <= seconds+1) return [[start,end]]
  // A natural loop is progress, not buffering. Only accept a plausible wrap;
  // arbitrary seeking must not become evidence of watching skipped content.
  if (end < start && duration > 0 && duration-start+end <= seconds+1) return [[start,duration],[0,end]]
  return []
}

// Only content fields from responses requested by the real page are retained.
// No cookies, signed URLs, user messages or arbitrary API execution enter the model.
export function contentItems(payload) {
  const found = new Map()
  const walk = (value, depth) => {
    if (!value || typeof value !== 'object' || depth > 7 || found.size >= 60) return
    if (videoId(value.aweme_id) && typeof value.desc === 'string' && !value.is_ads && !value.live_room && value.aweme_type !== 101) {
      found.set(value.aweme_id, { id: value.aweme_id, title: text(value.desc), author: text(value.author?.nickname, 80),
        duration: Number(value.video?.duration) > 0 ? value.video.duration / 1000 : null,
        url: 'https://www.douyin.com/video/' + value.aweme_id, source: 'page_response' })
    }
    for (const item of (Array.isArray(value) ? value.slice(0,60) : Object.values(value).slice(0,60))) walk(item, depth + 1)
  }
  walk(payload, 0); return [...found.values()]
}

export class DouyinAutomation {
  constructor(engine) { this.engine = engine; this.ended = new Set(); this.social = new DouyinSocial(this) }
  begin(id, input = {}) {
    const session = this.engine.get(id)
    this.engine.requireObservation(session)
    if (session.lease || session.automation) throw new RuntimeError('automation_busy', '当前浏览器正在被接管或执行任务')
    const page = session.tabs.get(session.active)
    if (!page) throw new RuntimeError('tab_closed', '请先创建浏览器标签页')
    const token = input.runId || randomUUID()
    if (typeof token !== 'string' || !/^[a-zA-Z0-9-]{16,64}$/.test(token)) throw new RuntimeError('invalid_run', '任务标识无效', 400)
    if (this.ended.has(token)) throw new RuntimeError('automation_revoked', '本次任务已停止')
    const run = { token, page, tab: session.active, viewing:viewingConfig(input.viewing), items: new Map(), currentItems: new Map(), coverage: new Map(), coverageDurations: new Map(), pending: new Set(), social:input.interactions || {}, people:new Map(), comments:new Map(), account:null, messageBaselines:new Map(), peer:'', cancelled: false }
    run.published=new Map((input.published||[]).filter(p=>typeof p.cid==='string'&&videoId(p.video_id)&&typeof p.account_id==='string').map(p=>[p.cid,p]))
    run.response = response => {
      let url
      try { url = new URL(response.url()) } catch { return }
      if (!platform(url.href) || !/\/aweme\/v\d+\/web\/(?:tab\/feed|module\/feed|aweme\/detail|general\/search|search\/item|user\/profile\/(?:self|other)|comment\/list)/.test(url.pathname)) return
      if (!/json/i.test(response.headers()['content-type'] || '') || Number(response.headers()['content-length']) > 2000000) return
      const generation = session.generation
      const work = (async () => {
        try {
          const body = await response.text()
          if (body.length > 2000000 || session.automation !== run || session.generation !== generation || !platform(page.url())) return
          const payload=JSON.parse(body); this.social.ingest(run,url,payload)
          for (const item of contentItems(payload)) { run.items.set(item.id, item); run.currentItems.set(item.id,item) }
          while (run.items.size > 200) run.items.delete(run.items.keys().next().value)
          while (run.currentItems.size > 60) run.currentItems.delete(run.currentItems.keys().next().value)
        } catch { /* An incomplete response is not content evidence. */ }
      })()
      run.pending.add(work); work.finally(() => run.pending.delete(work))
    }
    page.on('response', run.response); session.automation = run; this.engine.changed(session)
    this.renew(session, run)
    return { token: run.token, viewing: run.viewing, interactions:run.social }
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
    run.cancelled = true; this.social.stopMonitor(run); run.page.off('response', run.response); session.automation = null
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
    if (!['observe', 'home', 'search', 'open', 'next', 'scroll', 'watch', 'comments', 'account', 'inbox', 'profile', 'owner_profile', 'conversation', 'stickers', 'reconcile', ...writeOps].includes(op)) throw new RuntimeError('invalid_action', '不支持此抖音操作', 400)
    if (input.generation !== session.generation) throw new RuntimeError('stale_observation', '页面已变化，请重新观察')
    if(input.reconciling) {
      const drafts=await page.locator('[contenteditable="true"],textarea').evaluateAll(nodes=>nodes.some(e=>e.getClientRects().length&&(e.innerText||e.value||'').trim()))
      if(drafts)throw new RuntimeError('existing_draft','页面已有未发送草稿，请先保存草稿后核对')
    }
    if (!['home', 'search', 'account', 'inbox'].includes(op) && !platform(page.url())) throw new RuntimeError('wrong_platform', '当前已离开抖音，请先返回抖音')
    if(op==='reconcile') {
      const before=await this.snapshot(session,run)
      if(before.blocked)return before
      const interaction=await this.social.reconcile(session,run,input.authorization)
      await this.pause(session,run)
      return {...await this.snapshot(session,run),interaction}
    }
    if(writeOps.has(op)) {
      const before=await this.snapshot(session,run)
      if(before.blocked)return before
      const interaction=await this.social.perform(session,run,input,before)
      await this.pause(session,run)
      return {...await this.snapshot(session,run),interaction}
    }
    if(['account','inbox','profile','owner_profile','conversation','stickers'].includes(op)) {
      if(platform(page.url())) {
        const before=await this.snapshot(session,run)
        if(before.blocked)return before
      }
      try {await this.social.navigate(session,run,input)}
      catch(error) {
        if(!['conversation_loading','missing_peer','identity_changed','unobserved_peer','owner_ambiguous'].includes(error.code))throw error
        await this.pause(session,run)
        return {...await this.snapshot(session,run),actionError:{code:error.code,recoverable:true,submitted:false,reason:error.message}}
      }
    } else if (op === 'home' || op === 'search' || op === 'open') {
      let url = 'https://www.douyin.com/'
      if (op === 'search') {
        if (typeof input.query !== 'string' || !input.query.trim() || input.query.length > 100) throw new RuntimeError('invalid_query', '搜索关键词须为 1–100 字', 400)
        url += 'search/' + encodeURIComponent(input.query.trim()) + '?type=video'
      }
      if (op === 'open') {
        const previous=[...run.published.values()].find(p=>p.video_id===input.id&&p.account_id===run.account?.id)
        if (!videoId(input.id) || !run.items.has(input.id)&&!previous) throw new RuntimeError('unobserved_video', '只能打开实际观察或自己已发表评论的视频', 400)
        const candidate = run.items.get(input.id)||{id:input.id,duration:null}
        if (watchPolicy(candidate.duration,run.viewing).mode === 'skip') {
          await this.pause(session,run)
          return {...await this.snapshot(session,run), skipped:{id:candidate.id,title:candidate.title,duration:candidate.duration,reason:`超过 ${run.viewing.max_video_minutes} 分钟，未打开观看`}}
        }
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
      let before = await this.snapshot(session, run)
      if (before.blocked) return before
      const policy = before.watchPolicy
      const seconds = policy.mode==='preview' ? run.viewing.segment_seconds : input.seconds
      if (policy.mode === 'skip') {
        await this.pause(session,run)
        return {...await this.snapshot(session,run), skipped:{id:before.current?.id,duration:policy.duration,reason:`超过 ${run.viewing.max_video_minutes} 分钟，已跳过观看`}}
      }
      if (input.start_at !== undefined && (typeof input.start_at !== 'number' || !Number.isFinite(input.start_at) || input.start_at < 0 || input.start_at >= (policy.duration || 0) || policy.mode !== 'preview')) {
        await this.pause(session,run)
        return {...before, actionError:{code:'invalid_position', recoverable:true, submitted:false,
          reason:policy.mode==='normal'?'当前视频按正常模式观看，请省略 start_at，从 playback.currentTime 继续播放。':'指定位置不适用于当前观看策略，请按 watchPolicy 和真实时长重新选择操作。'}}
      }
      const key = before.current?.id || null
      videoCoverage(run,before.current,policy.duration)
      let seek = null
      if (policy.mode === 'preview' && input.continue_segment !== true) {
        const target=previewPosition(policy.duration,key?run.coverage.get(key)||[]:[],seconds,run.viewing.skip_seconds>0?undefined:input.start_at,run.viewing.skip_seconds)
        if (target === null) {
          await this.pause(session,run)
          return {...before, previewComplete:true, hint:'默认分段预览已结束；可换视频，或在有具体理由时用 start_at 查看其他片段。分段预览不代表看完。'}
        }
        const original=before
        this.guard(session,run)
        const assigned=await page.locator('video').evaluateAll((videos,at)=>{
          const video=videos.filter(v=>{const r=v.getBoundingClientRect();return r.width>100&&r.height>100&&r.bottom>0&&r.top<innerHeight}).sort((a,b)=>b.getBoundingClientRect().width*b.getBoundingClientRect().height-a.getBoundingClientRect().width*a.getBoundingClientRect().height)[0]
          if(!video || !Number.isFinite(video.duration))return false
          video.pause();try{video.currentTime=at;return true}catch{return false}
        },target)
        const deadline=Date.now()+5000
        do {
          await this.wait(session,run,100)
          before=await this.snapshot(session,run)
          if(before.blocked)return before
          if(original.current?.id!==before.current?.id || original.playback?.source!==before.playback?.source)throw new RuntimeError('stale_observation','页面已变化，请重新观察')
          if(!before.playback?.seeking && Math.abs((before.playback?.currentTime??-100)-target)<1)break
        } while(assigned && Date.now()<deadline)
        seek={requested:target,actual:before.playback?.currentTime??null}
        if(!assigned || before.playback?.seeking || Math.abs((seek.actual??-100)-target)>=1) {
          await this.pause(session,run)
          return {...before, seekFailed:seek, hint:'未能确认播放器跳转成功，未播放；可重新观察、稍后尝试或换视频。'}
        }
      }
      // Starting playback is reversible. Never call a like/comment/share element.
      this.guard(session, run)
      await page.locator('video').evaluateAll(videos => {
        const video = videos.filter(v => {const r=v.getBoundingClientRect();return r.width>100&&r.height>100&&r.bottom>0&&r.top<innerHeight}).sort((a,b)=>b.getBoundingClientRect().width*b.getBoundingClientRect().height-a.getBoundingClientRect().width*a.getBoundingClientRect().height)[0]
        if (video && !video.ended) { video.muted = true; video.play().catch(()=>{}) }
      })
      images = []; const samples = [], ranges = []; let previous = before.playback
      for (let i = 0; i < 3; i++) {
        if (!previous?.ended) await this.wait(session, run, Math.round(seconds * 1000 / 3))
        const shot = await this.snapshot(session, run)
        if (shot.blocked) return shot
        if (before.current?.id && shot.current?.id && before.current.id !== shot.current.id) throw new RuntimeError('stale_observation', '页面已变化，请重新观察')
        samples.push(shot.playback)
        const current = shot.playback
        if (previous && current && previous.source !== current.source) throw new RuntimeError('stale_observation', '页面已变化，请重新观察')
        ranges.push(...playbackRanges(previous,current,seconds/3))
        previous = current
        this.guard(session, run)
        const image = await page.screenshot({ type: 'jpeg', quality: 55, scale: 'css', timeout: 3000 })
        this.guard(session, run); images.push(image.toString('base64'))
        if (current?.ended) break
      }
      const sampledRanges=mergeRanges(ranges), coverageRanges=mergeRanges([...(key ? run.coverage.get(key) || [] : []),...ranges])
      if (key) run.coverage.set(key,coverageRanges)
      while(run.coverage.size>200) {const oldest=run.coverage.keys().next().value;run.coverage.delete(oldest);run.coverageDurations.delete(oldest)}
      const fullDuration=previous?.duration || before.current?.duration || null
      playback = { requestedSeconds: seconds, advancedSeconds: Math.round(ranges.reduce((sum,[a,b])=>sum+b-a,0)*10)/10,
        sampledRanges, coverageRanges, fullDuration, partial: !fullDuration || coverageRanges.length!==1 || coverageRanges[0][0]>0.25 || coverageRanges[0][1]<fullDuration-0.25,
        mode:policy.mode, seek, ended:!!previous?.ended, samples, visualOnly: true, audioAvailable: false }
    }
    // Finish playback mutations within the same serialized operation as the
    // watch. Owner input is queued after it; revoked actions never pause later.
    await this.pause(session,run)
    const result = await this.snapshot(session, run)
    if (playback) result.watch = playback
    if (images) result.images = images
    return result
  }
  async pause(session, run) {
    this.guard(session,run)
    await run.page.locator('video').evaluateAll(videos => { for (const video of videos) video.pause() })
    this.guard(session,run)
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
        playback:v ? {currentTime:Number(v.currentTime)||0,duration:Number.isFinite(v.duration)?v.duration:null,paused:v.paused,seeking:v.seeking,readyState:v.readyState,ended:v.ended,source:(v.currentSrc||'').split('?')[0].slice(-150)} : null }
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
    const blocked = await page.evaluate(verificationDOM) || (data.challenge || /验证码|安全验证|完成验证|拖动滑块|验证后继续/.test(data.modal) ? 'captcha' : data.loginForm || /登录后(?:即可|查看|搜索)|扫码登录|手机号登录/.test(data.modal) ? 'login' : '')
    const policy=watchPolicy(data.playback?.duration || current?.duration,run.viewing)
    const social=blocked?{}:await this.social.read(session,run)
    if(!blocked)run.lastSocial=social
    const coverageRanges=videoCoverage(run,current,policy.duration)
    const watched=!!current&&coverageRanges.reduce((n,[a,b])=>n+b-a,0)>=1
    return { ...social, coverageRanges:blocked?[]:coverageRanges, watched:!blocked&&watched, platform:'douyin', generation, url, blocked, viewing:run.viewing, body:blocked ? '' : data.body, items:blocked ? [] : [...run.currentItems.values()].slice(-40).map(item=>({...item,watchPolicy:watchPolicy(item.duration,run.viewing)})), current:blocked ? null : current, playback:blocked ? null : data.playback, watchPolicy:blocked ? watchPolicy(null) : policy }
  }
}
