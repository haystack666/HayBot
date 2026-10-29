import { RuntimeError } from './environment.mjs'

const clean = (v,n=1000) => typeof v==='string'?v.slice(0,n):''
const id = v => typeof v==='string' && /^[A-Za-z0-9_-]{3,128}$/.test(v)
export const writeOps = new Set(['like','comment','reply_comment','reply_dm','share','share_note'])
export function editorTextDOM(e) {return (e.innerText||e.value||'').replace(/[\u200B\uFEFF]/g,'').trim()}
// Detail pages render a second interaction bar. Its visible heart has no e2e
// attribute; the e2e heart belongs to the hidden fullscreen player. Read only
// the rendered icon's public type/state, then use a normal pointer click.
export function likeControlDOM(videoId) {
  const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'}
  const root=document.querySelector(`[data-e2e="detail-video-info"][data-e2e-aweme-id="${videoId}"]`)
  const matches=[]
  if(root)for(const e of root.querySelectorAll('*')) {
    if(!visible(e))continue
    const k=Object.keys(e).find(k=>k.startsWith('__reactProps$')),p=k?e[k]:null
    if(typeof p?.onClick!=='function')continue
    if((Array.isArray(p.children)?p.children:[p.children]).some(c=>c?.props?.type==='digg'&&typeof c.props.userInteraction==='boolean'))matches.push(e)
  }
  if(matches.length)return matches.length===1?matches[0]:null
  const buttons=[...document.querySelectorAll('[data-e2e="video-player-digg"]')].filter(visible).filter(e=>{
    const owner=e.closest('[data-e2e-aweme-id]');return !owner||owner.getAttribute('data-e2e-aweme-id')===videoId
  })
  return buttons.length===1?buttons[0]:null
}
export function likeStateDOM(e) {
  const k=Object.keys(e).find(k=>k.startsWith('__reactProps$')),p=k?e[k]:null
  const icon=(Array.isArray(p?.children)?p.children:[p?.children]).find(c=>c?.props?.type==='digg'&&typeof c.props.userInteraction==='boolean')
  if(icon)return icon.props.userInteraction
  const state=e.getAttribute('data-e2e-state'),pressed=e.getAttribute('aria-pressed')
  if(['liked','active','video-player-is-digg','video-player-digged','video-player-is-digged'].includes(state)||pressed==='true')return true
  if(['unliked','inactive','false','0','video-player-no-digg','video-player-no-digged'].includes(state)||pressed==='false')return false
  return null
}
export function verificationDOM() {
  const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'}
  // Return only the kind, never phone numbers, codes, or verification text.
  return [...document.querySelectorAll('article,[role="dialog"],[class*="verify"],[class*="Verify"]')].some(e=>visible(e)&&/为确保是本人操作|本人验证|身份验证/.test(e.innerText||'')&&/短信|验证码/.test(e.innerText||''))?'account_verification':''
}
export function profile(payload) {
  const user=payload?.user || payload?.user_info
  if(!user || !id(user.sec_uid) || typeof user.nickname!=='string')return null
  return {id:user.sec_uid,uid:clean(user.uid,80),handle:clean(user.unique_id || user.short_id,80),nickname:clean(user.nickname,80),verified:true,
    follows_me:typeof user.follower_status==='number'?user.follower_status===1:null}
}
export function commentItems(payload) {
  return (Array.isArray(payload?.comments)?payload.comments:[]).slice(0,100).flatMap(c=>
    id(c.cid) && id(c.aweme_id) && id(c.user?.sec_uid)?[{id:c.cid,video_id:c.aweme_id,author_id:c.user.sec_uid,author:clean(c.user.nickname,80),text:clean(c.text),parent_id:clean(c.reply_to_reply_id && c.reply_to_reply_id!=='0'?c.reply_to_reply_id:c.reply_id,80),mentions:(c.text_extra||[]).filter(x=>id(x.sec_uid)||id(x.user_id)).map(x=>({id:clean(x.sec_uid,128),uid:clean(x.user_id,128)})).slice(0,20)}]:[])
}

// Resolve only public user fields attached to the rendered element. In
// particular, nickname text and the element's screen position never grant send
// permission. React data is read, never invoked or modified.
export function elementIdentity(element) {
  const result={id:element.getAttribute('data-sec-uid')||element.querySelector('a[href*="/user/"]')?.getAttribute('href')?.match(/\/user\/([^/?]+)/)?.[1]||'',
    uid:element.getAttribute('data-user-id')||element.getAttribute('data-userid')||'',handle:'',nickname:'',text:(element.innerText||'').slice(0,300)}
  const seen=new WeakSet()
  const walk=(value,depth)=>{
    if(!value||typeof value!=='object'||depth>5||seen.has(value))return
    seen.add(value)
    if(typeof value.sec_uid==='string'&&typeof value.nickname==='string') {
      result.id=value.sec_uid;result.uid=String(value.uid||'');result.handle=String(value.unique_id||value.short_id||'');result.nickname=value.nickname;return
    }
    for(const key of ['user','userInfo','user_info','item','data','props','children'])for(const child of Array.isArray(value[key])?value[key].slice(0,8):[value[key]])walk(child,depth+1)
  }
  let parent=element
  for(let i=0;i<3&&parent&&!result.nickname;i++,parent=parent.parentElement) {
    const key=Object.keys(parent).find(k=>k.startsWith('__reactProps$'))
    if(key)walk(parent[key],0)
  }
  return result
}

export function conversationDOM(element) {
  const seen=new WeakSet()
  const walk=(v,d)=>{
    if(!v||typeof v!=='object'||d>7||seen.has(v))return null
    seen.add(v)
    if(typeof v.toParticipantSecUserId==='string')return v
    for(const key of ['conversation','children','props'])for(const child of Array.isArray(v[key])?v[key].slice(0,10):[v[key]]){const found=walk(child,d+1);if(found)return found}
    return null
  }
  const key=Object.keys(element).find(k=>k.startsWith('__reactProps$')),c=key?walk(element[key],0):null
  const identifier=c?.toParticipantSecUserId||element.querySelector('a[href*="/user/"]')?.getAttribute('href')?.match(/\/user\/([^/?]+)/)?.[1]||element.getAttribute('data-peer-id')||element.getAttribute('data-user-id')||''
  return {id:identifier,conversation_id:typeof c?.id==='string'?c.id:'',nickname:((element.querySelector('[class*="ConversationItemtitle"]')||element).innerText||'').split('\n')[0].slice(0,80),
    preview:(element.innerText||'').slice(-240),
    unreadCount:typeof c?.unreadCount==='number'?c.unreadCount:null,
    unread:typeof c?.unreadCount==='number'?c.unreadCount>0:!!element.querySelector('[class*="badge"],[class*="Badge"],[class*="unread"],[data-unread="true"]'),
    selected:element.getAttribute('aria-selected')==='true'||element.getAttribute('data-active')==='true'||/curConversation|selected|Selected|active|Active/.test(element.className)}
}

// This function executes inside the actual page, reads only visible UI and
// whitelisted React message fields; it never invokes website stores or APIs.
export function socialDOM() {
  const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&s.visibility!=='hidden'&&s.display!=='none'}
  const short=(v,n=1000)=>typeof v==='string'?v.slice(0,n):''
  const identity=e=>e.querySelector('a[href*="/user/"]')?.getAttribute('href')?.match(/\/user\/([^/?]+)/)?.[1]||e.getAttribute('data-peer-id')||e.getAttribute('data-user-id')||''
  const conversations=[...document.querySelectorAll('[data-e2e="conversation-item"]')].filter(visible).slice(0,50).map(e=>({id:identity(e),nickname:short((e.querySelector('[class*="ConversationItemtitle"]')||e).innerText.split('\n')[0],80),unread:!!e.querySelector('[class*="badge"],[class*="Badge"],[class*="unread"],[data-unread="true"]')}))
  const messages=[]
  for(const e of [...document.querySelectorAll('[data-message-id],[data-msg-id],[class*="MessageItemTextbubbleContent"],[class*="MessageItemShareAwemecontainer"],[class*="MessageItemEmojiemojiBox"]')].filter(visible).slice(-80)) {
    let metadata=null
    let ancestor=e
    for(let n=0;n<6&&ancestor&&!metadata;n++,ancestor=ancestor.parentElement) {
      const props=Object.keys(ancestor).find(k=>k.startsWith('__reactProps$'))
      if(!props)continue
      const walk=(v,d)=>{if(!v||typeof v!=='object'||d>3)return null
        if((v.serverId||v.server_id||v.messageId) && (v.sender||v.senderId||v.sender_id||typeof v.isMyMessage==='boolean'))return v
        for(const key of ['message','msg','item','data','children','props']) {const values=Array.isArray(v[key])?v[key].slice(0,8):[v[key]];for(const x of values){const hit=walk(x,d+1);if(hit)return hit}}return null}
      metadata=walk(ancestor[props],0)
    }
    const mid=e.getAttribute('data-message-id')||e.getAttribute('data-msg-id')||String(metadata?.serverId||metadata?.server_id||metadata?.messageId||'')
    const self=e.getAttribute('data-is-self')||e.getAttribute('data-self')
    const direction=typeof metadata?.isMyMessage==='boolean'?(metadata.isMyMessage?'outbound':'inbound'):e.getAttribute('data-direction')||(['true','1'].includes(self)?'outbound':['false','0'].includes(self)?'inbound':'unknown')
    const sender=String(metadata?.sender||metadata?.senderId||metadata?.sender_id||'')
    const conversation=String(metadata?.conversationId||metadata?.conversation_id||'')
    if(!mid || messages.some(m=>m.id===mid))continue
    const card=e.querySelector('a[href*="/video/"]')
    // The real share card is a div, with no anchor. Read only its rendered
    // message's itemId; never pass arbitrary message content or assets onward.
    let parsed;try{parsed=metadata?.parsedContent}catch{}
    const cardId=typeof parsed?.itemId==='string'&&/^\d{6,30}$/.test(parsed.itemId)?parsed.itemId:''
    messages.push({id:short(mid,100),direction,sender:short(sender,100),conversation_id:short(conversation,100),text:short(e.innerText),video_id:cardId||card?.href.match(/\/video\/(\d+)/)?.[1]||'',sticker:e.querySelector('img')?.getAttribute('alt')||''})
  }
  const selected=[...document.querySelectorAll('[data-e2e="conversation-item"]')].filter(visible).filter(e=>e.getAttribute('aria-selected')==='true'||e.getAttribute('data-active')==='true'||/selected|Selected|active|Active/.test(e.className))
  const peer=selected.length===1?identity(selected[0]):''
  const stickers=[...document.querySelectorAll('[class*="componentsemoji"] img,.componentsemojiemojiPanel img')].filter(visible).map(e=>short(e.getAttribute('alt'),80)).filter(Boolean).slice(0,80)
  return {conversations,messages,peer,stickers}
}

export class DouyinSocial {
  constructor(automation) {this.auto=automation;this.operations=new Map()}
  ingest(run,url,data) {
    if(/\/user\/profile\/self\/?$/.test(url.pathname)) {
      const value=profile(data)
      if(value) {
        if(run.account && run.account.id!==value.id) {run.identityChanged=true;return}
        run.account=value
      }
    } else if(/\/user\/profile\/other\/?$/.test(url.pathname)) {
      const value=profile(data);if(value)run.people.set(value.id,value)
    } else if(/\/comment\/list(?:\/reply)?\/?$/.test(url.pathname)) {
      for(const c of commentItems(data))run.comments.set(c.id,c)
      while(run.comments.size>300)run.comments.delete(run.comments.keys().next().value)
    }
  }
  async ingestResponse(run,response) {
    try {
      const url=new URL(response.url())
      if(url.origin!=='https://www.douyin.com'||!/\/user\/profile\/(?:self|other)/.test(url.pathname)||! /json/i.test(response.headers()['content-type']||''))return
      const text=await response.text();if(text.length>2000000||run.cancelled||run.parent?.cancelled)return
      this.ingest(run,url,JSON.parse(text))
    }catch{}
  }
  async startMonitor(session,run) {
    if(!run.social.messages_enabled || run.inboxMonitor)return
    const page=await this.auto.engine.auxiliaryPage(session)
    try {this.auto.guard(session,run)}catch(error){await page.close().catch(()=>{});throw error}
    const monitor=run.inboxMonitor={page,checkedAt:null,error:'',pending:new Map(),opened:new Map(),version:0,waiters:new Set(),signature:''}
    const poll=async()=>{
      this.auto.guard(session,run)
      if(page.url()!=='https://www.douyin.com/chat?isPopup=1')return
      const rows=page.locator('[data-e2e="conversation-item"]').filter({visible:true}),people=[]
      for(let i=0;i<Math.min(await rows.count(),50);i++)people.push(await rows.nth(i).evaluate(conversationDOM))
      this.auto.guard(session,run)
      for(const person of people) {
        if(!person.id)continue
        if(person.unread && monitor.opened.get(person.id)!==JSON.stringify([person.unreadCount,person.preview]))monitor.pending.set(person.id,person)
        if(!person.unread){monitor.pending.delete(person.id);monitor.opened.delete(person.id)}
      }
      const messages=(await page.evaluate(socialDOM)).messages.slice(-10).map(m=>m.id).join('|')
      const signature=JSON.stringify([...monitor.pending.values()].map(p=>[p.id,p.unreadCount,p.preview]))+messages
      if(signature!==monitor.signature){monitor.signature=signature;monitor.version++;for(const wake of [...monitor.waiters])wake()}
      monitor.checkedAt=Date.now();monitor.error=''
    }
    // DOM changes wake the independent consumer immediately. There is no
    // periodic inbox scan; navigation/reload reattaches the observer and scans.
    const binding='__haybotInboxChanged'
    let scanning=false,scanAgain=false
    const changed=async()=>{
      if(run.cancelled)return
      if(scanning){scanAgain=true;return}
      scanning=true
      try{do{scanAgain=false;await poll()}while(scanAgain&&!run.cancelled)}catch{}finally{scanning=false}
    }
    await page.exposeBinding(binding,changed).catch(()=>{})
    // Register transport listeners before navigation: Douyin commonly creates
    // its long-lived IM WebSocket while the chat document is bootstrapping.
    // Attaching after goto can permanently miss that socket.
    page.on('websocket',socket=>socket.on('framereceived',()=>changed().catch(()=>{})))
    page.on('response',response=>{if(/(?:im|message|chat|conversation)/i.test(response.url()))changed().catch(()=>{})})
    try {
      await page.goto('https://www.douyin.com/chat?isPopup=1',{waitUntil:'domcontentloaded',timeout:15000})
      await this.auto.wait(session,run,500)
    } catch(error) {if(run.cancelled)throw error;monitor.error='消息页暂未加载完成'}
    // Douyin may replace the chat body during hydration, and incoming IM data
    // may arrive before React mutates the visible list. Both are event sources,
    // not interval scans; serialization above coalesces bursts safely.
    const observe=()=>page.evaluate(()=>{
      window.__haybotInboxObserver?.disconnect();let timer
      window.__haybotInboxObserver=new MutationObserver(()=>{if(timer)return;timer=setTimeout(()=>{timer=null;window.__haybotInboxChanged().catch(()=>{})},100)})
      window.__haybotInboxObserver.observe(document.documentElement,{childList:true,subtree:true,attributes:true,characterData:true})
    }).catch(()=>{})
    const reload=async()=>{await observe();try{await poll()}catch(error){if(!run.cancelled)monitor.error='消息页变化检查暂未完成'} }
    await reload();monitor.observe=observe;monitor.reload=reload
    page.on('domcontentloaded',reload)
  }
  stopMonitor(run) {
    if(!run.inboxMonitor)return
    if(run.inboxRun){run.inboxRun.cancelled=true;run.inboxRun.page.off('response',run.inboxRun.response)}
    for(const wake of [...run.inboxMonitor.waiters])wake()
    run.inboxMonitor.page.close().catch(()=>{})
  }
  async waitConversation(session,run,peerId,timeout=8000) {
    const deadline=Date.now()+timeout
    do {
      const social=await this.read(session,run);run.lastSocial=social
      if(social.conversations.some(c=>c.id===peerId))return social
      await this.auto.wait(session,run,250)
    }while(Date.now()<deadline)
    throw new RuntimeError('conversation_loading','消息列表尚未加载出目标会话，请稍后重新观察；未重新发送')
  }
  async read(session,run) {
    const data=await run.page.evaluate(socialDOM);this.auto.guard(session,run)
    if(run.identityChanged||run.parent?.identityChanged)throw new RuntimeError('account_changed','登录的抖音账号已变化，请重新发起任务')
    data.conversations=[]
    const rows=run.page.locator('[data-e2e="conversation-item"]').filter({visible:true})
    for(let i=0;i<Math.min(await rows.count(),50);i++)data.conversations.push(await rows.nth(i).evaluate(conversationDOM))
    const selected=data.conversations.filter(c=>c.selected)
    const currentPeer=selected.length===1?selected[0].id:''
    const peer=currentPeer?(run.people.get(currentPeer)||[...run.people.values()].find(p=>p.uid===currentPeer)):null
    const messages=data.messages.filter(m=>!m.conversation_id||m.conversation_id===selected[0]?.conversation_id).map(m=>({...m,direction:m.sender&&run.account?.uid?(m.sender===run.account.uid?'outbound':peer?.uid===m.sender?'inbound':'unknown'):m.direction}))
    if(peer) {if(!run.messageBaselines.has(peer.id))run.messageBaselines.set(peer.id,new Set());for(const message of messages)run.messageBaselines.get(peer.id).add(message.id)}
    // A DOM direction alone is not enough: require a resolved profile and an
    // actual server message identifier in the selected conversation.
    return {account:run.account||null,owner:[...run.people.values()].find(p=>p.handle===run.social.owner?.handle&&p.nickname===run.social.owner?.nickname)||null,
      conversation:peer||null,conversations:data.conversations,pendingUnread:[...(run.inboxMonitor?.pending.values()||[])],
      inboxMonitor:run.inboxMonitor?{event_driven:true,checked_at:run.inboxMonitor.checkedAt,error:run.inboxMonitor.error}:null,messages:peer?messages:[],stickers:data.stickers,comments:[...run.comments.values()].slice(-60)}
  }
  async navigate(session,run,input) {
    const page=run.page,op=input.op
    if(op==='account') {
      await page.goto('https://www.douyin.com/user/self?from_nav=1',{waitUntil:'domcontentloaded',timeout:25000})
      for(let i=0;i<15&&!run.account;i++)await this.auto.wait(session,run,400)
      if(run.account)await this.startMonitor(session,run)
    }
    if(op==='inbox') {await page.goto('https://www.douyin.com/chat?isPopup=1',{waitUntil:'domcontentloaded',timeout:25000});run.peer='';await this.auto.wait(session,run,1600)}
    if(op==='stickers') {
      if(!run.lastSocial?.conversation)throw new RuntimeError('missing_peer','请先打开已确认身份的消息会话')
      const icons=page.locator('[class*="messageMsgInputiconAction"]').filter({visible:true})
      if(!await page.locator('[class*="componentsemoji"] img,.componentsemojiemojiPanel img').filter({visible:true}).count())await this.click(session,run,icons)
      await this.auto.wait(session,run,500)
    }
    if(op==='profile') {
      if(!id(input.peer_id))throw new RuntimeError('invalid_peer','需要实际观察到的用户标识',400)
      const allowed=[...(run.lastSocial?.conversations||[]).map(p=>p.id),...run.comments.values()].map(p=>typeof p==='string'?p:p.author_id)
      const candidate=run.lastSocial?.conversations?.find(p=>p.id===input.peer_id)
      if(!allowed.includes(input.peer_id)&&!run.people.has(input.peer_id))throw new RuntimeError('unobserved_peer','请先从页面观察到用户身份')
      await page.goto('https://www.douyin.com/user/'+encodeURIComponent(input.peer_id),{waitUntil:'domcontentloaded',timeout:25000});await this.auto.wait(session,run,1500)
      if(candidate?.nickname && run.people.get(input.peer_id)?.nickname!==candidate.nickname)throw new RuntimeError('identity_changed','用户身份有变化，请重新核对')
    }
    if(op==='owner_profile') {
      if(!run.social.owner?.handle)throw new RuntimeError('owner_missing','请先填写 Owner 抖音号与昵称')
      await page.goto('https://www.douyin.com/search/'+encodeURIComponent(run.social.owner.handle)+'?type=user',{waitUntil:'domcontentloaded',timeout:25000});await this.auto.wait(session,run,1500)
      const links=page.locator('a[href*="/user/"]').filter({visible:true})
      const candidates=[]
      for(let i=0;i<Math.min(await links.count(),50);i++) {
        const link=links.nth(i),label=await link.innerText()
        const row=await link.evaluate(e=>(e.closest('li,[data-e2e="search-result-card"]')||e.parentElement)?.innerText||'')
        if((label.trim()===run.social.owner.nickname||row.split('\n').includes(run.social.owner.nickname))&&row.includes(run.social.owner.handle))candidates.push(await link.getAttribute('href'))
      }
      const urls=[...new Set(candidates)]
      if(urls.length!==1)throw new RuntimeError('owner_ambiguous','未找到唯一且抖音号匹配的 Owner，请核对设置')
      const url=new URL(urls[0],page.url())
      if(url.origin!=='https://www.douyin.com'||!/^\/user\/[A-Za-z0-9_-]+$/.test(url.pathname))throw new RuntimeError('invalid_peer','Owner 主页地址不符合预期')
      await page.goto(url.href,{waitUntil:'domcontentloaded',timeout:25000});await this.auto.wait(session,run,1500)
    }
    if(op==='conversation') {
      let known=run.lastSocial?.conversations?.find(p=>p.id===input.peer_id)||run.inboxMonitor?.pending.get(input.peer_id)
      if(!known)throw new RuntimeError('unobserved_peer','只能打开已观察到的消息会话')
      // Resolve the stable ID and relationship automatically before disclosing
      // messages. Opening a row alone never grants permission to reply.
      if(!run.people.has(input.peer_id)) {
        await page.goto('https://www.douyin.com/user/'+encodeURIComponent(input.peer_id),{waitUntil:'domcontentloaded',timeout:15000})
        for(let i=0;i<20&&!run.people.has(input.peer_id);i++)await this.auto.wait(session,run,250)
        const peer=run.people.get(input.peer_id)
        if(!peer||known.nickname&&peer.nickname!==known.nickname)throw new RuntimeError('identity_changed','未能核对会话账号身份，未读取或回复私信')
      }
      let rows=page.locator('[data-e2e="conversation-item"]').filter({visible:true})
      if(!/\/chat(?:\?|$)/.test(page.url())) {
        await page.goto('https://www.douyin.com/chat?isPopup=1',{waitUntil:'domcontentloaded',timeout:15000})
      }
      await this.waitConversation(session,run,input.peer_id)
      let found
      for(let i=0;i<await rows.count();i++) {const row=rows.nth(i),data=await row.evaluate(conversationDOM);if(data.id===input.peer_id){if(found)throw new RuntimeError('ambiguous_peer','会话身份不唯一');found=row}}
      if(!found)throw new RuntimeError('missing_peer','目标会话已不在当前列表中')
      this.auto.guard(session,run);await found.click({timeout:3000});run.peer=input.peer_id
      let openedView
      for(let i=0;i<16;i++) {
        const view=await this.read(session,run);run.lastSocial=view
        if(view.conversation?.id===input.peer_id&&view.messages.length){openedView=view;break}
        await this.auto.wait(session,run,250)
      }
      if(run.inboxMonitor){
        const opened=(openedView?.conversations||[]).find(item=>item.id===input.peer_id)||known
        run.inboxMonitor.pending.delete(input.peer_id);run.inboxMonitor.opened.set(input.peer_id,JSON.stringify([opened.unreadCount,opened.preview]))
      }
    }
  }

  async editor(session,run,kind) {
    const page=run.page
    const selector=kind==='comment'?'[contenteditable="true"][data-e2e*="comment"],.public-DraftEditor-content[contenteditable="true"],textarea[placeholder*="评论"],input[placeholder*="评论"]':'[contenteditable="true"],textarea[placeholder*="发送"],input[placeholder*="发送"]'
    let editors=page.locator(selector).filter({visible:true})
    if(!await editors.count()&&kind==='comment') {
      const placeholder=page.getByText(/留下你的精彩评论|写评论|善语结善缘|说点什么/).filter({visible:true}).first()
      if(await placeholder.count()){this.auto.guard(session,run);await placeholder.click({timeout:2500});await this.auto.wait(session,run,500)}
      editors=page.locator(selector).filter({visible:true})
    }
    if(await editors.count()!==1)throw new RuntimeError('editor_missing','无法确认唯一的输入框，未发送')
    const box=editors.first();this.auto.guard(session,run);await box.click({timeout:2500})
    // Preserve owner drafts rather than clearing text left by a person.
    const body=await box.evaluate(editorTextDOM)
    if(body)throw new RuntimeError('existing_draft','输入框已有草稿，未覆盖或发送')
    return box
  }
  async click(session,run,locator) {
    if(await locator.count()!==1)throw new RuntimeError('ambiguous_control','未找到唯一操作入口，未提交')
    this.auto.guard(session,run);await locator.click({timeout:2500,noWaitAfter:true})
  }
  async verifyLike(session,run,videoId) {
    const page=await this.auto.engine.auxiliaryPage(session)
    let state=null
    const listener=async response=>{try {
      const u=new URL(response.url())
      if(u.origin!=='https://www.douyin.com'||!/^\/aweme\/v\d+\/web\/aweme\/detail\/?$/.test(u.pathname))return
      const d=await response.json(),v=d.aweme_detail
      this.auto.guard(session,run)
      if(d.status_code===0&&v?.aweme_id===videoId&&[0,1].includes(v.user_digged))state={liked:v.user_digged===1,video_id:videoId,evidence:'fresh_video_detail'}
    }catch{}}
    page.on('response',listener)
    try {
      this.auto.guard(session,run)
      await page.goto('https://www.douyin.com/video/'+videoId,{waitUntil:'domcontentloaded',timeout:15000})
      for(let i=0;i<24&&!state;i++)await this.auto.wait(session,run,250)
      this.auto.guard(session,run)
      if(await page.evaluate(verificationDOM))return null
      return state
    }finally{page.off('response',listener);await page.close().catch(()=>{})}
  }
  async reconcile(session,run,grant) {
    this.auto.guard(session,run)
    if(!/^[a-f0-9]{32}$/.test(grant?.operation_id||'')||grant.account_id!==run.account?.id||!run.account?.verified)throw new RuntimeError('account_mismatch','当前抖音账号与原互动账号不同，未核对')
    const result={op:grant.op,status:'unknown',reconciled:true,operation_id:grant.operation_id,account_id:grant.account_id,reason:'没有找到可靠结果，保留待核对；未重新提交'}
    if(grant.op==='like') {
      const state=await this.verifyLike(session,run,grant.video_id)
      if(state?.liked)Object.assign(result,state,{status:'confirmed',reason:'平台视频详情确认当前账号已点赞'})
      else if(state)result.reason='平台当前显示未点赞；无法证明原操作是否曾成功，保留待核对，未重复点击'
      return result
    }
    const page=run.page
    if(['comment','reply_comment'].includes(grant.op)&&/^\d{6,30}$/.test(grant.video_id||'')) {
      run.comments.clear();run.currentItems.clear()
      await page.goto('https://www.douyin.com/video/'+grant.video_id,{waitUntil:'domcontentloaded',timeout:20000})
      await this.auto.wait(session,run,1500)
      for(let i=0;i<12;i++) {
        const view=await this.auto.snapshot(session,run)
        if(view.blocked)return {...result,blocked:view.blocked,reason:'页面要求验证或登录，请先接管完成后核对'}
        const matches=[...run.comments.values()].filter(c=>c.video_id===grant.video_id&&c.author_id===grant.account_id&&
          (grant.mention_owner?c.text.trim().endsWith((grant.text||'').trim()):c.text.trim()===(grant.text||'').trim())&&
          (grant.op==='reply_comment'?c.parent_id===grant.comment_id:['','0'].includes(c.parent_id)))
        if(matches.length===1) {
          const c=matches[0],mentioned=!!grant.mention_owner&&c.mentions.some(p=>p.id===grant.mention_id||p.uid===run.people.get(grant.mention_id)?.uid)
          return {...result,status:'confirmed',cid:c.id,video_id:c.video_id,parent_id:c.parent_id,mentioned_owner:mentioned,evidence:'own_published_comment',reason:'已查到当前账号在原视频发表的同一条评论'}
        }
        if(i===0) {
          const trigger=page.locator('[data-e2e="video-comment"],[data-e2e="feed-comment-icon"]').filter({visible:true}).first()
          if(await trigger.count())await this.click(session,run,trigger)
          else await page.getByText('全部评论',{exact:true}).first().scrollIntoViewIfNeeded({timeout:1500}).catch(()=>{})
        }
        await this.auto.wait(session,run,400)
      }
      return result
    }
    if(grant.op==='share'&&id(grant.peer_id)&&/^\d{6,30}$/.test(grant.video_id||'')) {
      await page.goto('https://www.douyin.com/user/'+grant.peer_id,{waitUntil:'domcontentloaded',timeout:20000})
      for(let i=0;i<20&&!run.people.has(grant.peer_id);i++)await this.auto.wait(session,run,250)
      const peer=run.people.get(grant.peer_id)
      if(!peer||peer.handle!==run.social.owner?.handle||peer.nickname!==run.social.owner?.nickname)return {...result,reason:'原接收账号与当前 Owner 设置不匹配，未读取消息'}
      await this.navigate(session,run,{op:'inbox'})
      await this.waitConversation(session,run,grant.peer_id)
      await this.navigate(session,run,{op:'conversation',peer_id:grant.peer_id})
      for(let i=0;i<12;i++) {
        const view=await this.read(session,run)
        const sent=view.messages.filter(m=>m.direction==='outbound'&&m.video_id===grant.video_id)
        if(sent.length===1)return {...result,status:'confirmed',message_id:sent[0].id,peer_id:peer.id,video_id:grant.video_id,evidence:'owner_conversation_card',reason:'已在 Owner 会话查到自己发出的原视频卡片'}
        await this.auto.wait(session,run,400)
      }
    }
    return result
  }
  async perform(session,run,input,before) {
    const a=this.auto,page=run.page,op=input.op,grant=input.authorization
    if(!grant || !/^[a-f0-9]{32}$/.test(grant.operation_id||'') || grant.account_id!==before.account?.id)throw new RuntimeError('write_permission','互动未取得当前账号授权')
    const switches={like:'likes_enabled',comment:'comments_enabled',reply_comment:'replies_enabled',reply_dm:'messages_enabled',share:'shares_enabled',share_note:'shares_enabled'}
    if(!run.social[switches[op]])throw new RuntimeError('write_disabled','此类互动未开启')
    const previous=this.operations.get(grant.operation_id)
    if(previous)return {...previous,replayed:true}
    const result={op,status:'failed',submitted:false}
    this.operations.set(grant.operation_id,result)
    while(this.operations.size>2000)this.operations.delete(this.operations.keys().next().value)
    const submit=()=>{a.guard(session,run);result.submitted=true;result.status='unknown'}
    try {
      if(op==='like'||op==='comment'||op==='reply_comment'||op==='share') {
        if(!before.current?.id || grant.video_id!==before.current.id)throw new RuntimeError('stale_video','视频已切换，未操作')
        if(op!=='reply_comment'&&!before.watched)throw new RuntimeError('not_watched','请先实际观看视频')
      }
      if(op==='like') {
        const handle=await page.evaluateHandle(likeControlDOM,grant.video_id),button=handle.asElement()
        try {
          if(!button)throw new RuntimeError('like_missing','未找到当前视频唯一可见的点赞按钮，未点击')
          const state=await button.evaluate(likeStateDOM)
          if(state===true)return Object.assign(result,{status:'confirmed',already:true,video_id:grant.video_id,evidence:'visible_like_state'})
          if(state!==false)throw new RuntimeError('like_unknown','无法判断是否已经点赞，未点击')
          let receipt=null
          const listener=async response=>{try{
            const u=new URL(response.url()),req=response.request()
            if(u.origin!=='https://www.douyin.com'||!/^\/aweme\/v\d+\/web\/commit\/item\/digg\/?$/.test(u.pathname)||req.method()!=='POST')return
            const params=new URLSearchParams(req.postData()||'')
            if(params.get('aweme_id')!==grant.video_id||params.get('type')!=='1')return
            const d=await response.json();a.guard(session,run)
            if(d.status_code===0)receipt={status:'confirmed',video_id:grant.video_id,evidence:'platform_like_receipt'}
            else if(Number.isInteger(d.status_code))receipt={status:'failed',reason:'平台拒绝点赞',platform_code:d.status_code}
          }catch{}}
          page.on('response',listener)
          try {
            submit();await button.click({timeout:2500})
            for(let i=0;i<24&&!receipt;i++) {
              await a.wait(session,run,250)
              if(await page.evaluate(verificationDOM)){result.reason='点赞触发账号本人验证，请接管完成验证后核对，勿重复点击';break}
            }
            if(receipt)return Object.assign(result,receipt)
            if(!result.reason) {
              const state=await this.verifyLike(session,run,grant.video_id)
              if(state?.liked)return Object.assign(result,state,{status:'confirmed'})
            }
            // Optimistic heart animation alone is not a server acknowledgement.
            result.reason??='已点击点赞，但未收到平台回执；请核对，勿重复点击'
          }finally{page.off('response',listener)}
        }finally{await handle.dispose()}
      } else if(op==='comment'||op==='reply_comment') {
        const trigger=page.locator('[data-e2e="video-comment"],[data-e2e="feed-comment-icon"]').filter({visible:true}).first()
        const open=await page.locator('[data-e2e="comment-list"],[data-e2e="comment-item"],[contenteditable="true"][data-e2e*="comment"]').filter({visible:true}).count()
        if(!open&&await trigger.count()){a.guard(session,run);await trigger.click({timeout:2500});await a.wait(session,run,500)}
        if(op==='reply_comment') {
          const target=before.comments?.find(c=>c.id===grant.comment_id&&c.video_id===before.current.id&&c.parent_id===grant.parent_id&&c.author_id!==before.account.id)
          if(!target || run.published.get(target.parent_id)?.account_id!==before.account.id)throw new RuntimeError('reply_missing','没有匹配自己已发布评论的真实回复')
          const rows=page.locator('[data-e2e="comment-item"],[data-comment-id]').filter({visible:true})
          const matches=[]
          for(let i=0;i<await rows.count();i++) {
            const row=rows.nth(i),meta=await row.evaluate(e=>({id:e.getAttribute('data-comment-id')||e.getAttribute('data-cid'),text:e.innerText,authors:[...e.querySelectorAll('a[href*="/user/"]')].map(x=>x.href.match(/\/user\/([^/?]+)/)?.[1])}))
            if(meta.id===target.id || meta.authors.includes(target.author_id)&&meta.text.includes(target.text))matches.push(row)
          }
          if(matches.length!==1)throw new RuntimeError('reply_ambiguous','评论身份或正文不唯一，未回复')
          await this.click(session,run,matches[0].getByText('回复',{exact:true}).filter({visible:true}))
          await a.wait(session,run,400)
        }
        const box=await this.editor(session,run,'comment')
        if(grant.mention_owner) {
          if(grant.mention_id!==before.owner?.id)throw new RuntimeError('owner_mismatch','@ 目标未确认')
          a.guard(session,run);await page.keyboard.insertText('@'+run.social.owner.handle);await a.wait(session,run,1200)
          let candidates=page.locator('[role="option"],[data-e2e*="mention"],[class*="mention"] li,[class*="Mention"] li').filter({visible:true})
          if(!await candidates.count())candidates=page.getByText(before.owner.nickname,{exact:true}).filter({visible:true})
          const matches=[]
          for(let i=0;i<await candidates.count();i++) {const row=candidates.nth(i),data=await row.evaluate(elementIdentity);if((data.id===before.owner.id||data.uid===before.owner.id||before.owner.uid&&data.uid===before.owner.uid)&&data.text.includes(before.owner.nickname))matches.push(row)}
          if(matches.length!==1)throw new RuntimeError('mention_ambiguous','没有匹配真实账号的唯一 @ 候选，未发布')
          await this.click(session,run,matches[0]);await a.wait(session,run,300)
          const token=await box.evaluate((e,owner)=>[...e.querySelectorAll('[data-user-id],[data-uid],a[href*="/user/"],[contenteditable="false"]')].some(n=>[owner.id,owner.uid].filter(Boolean).some(uid=>n.getAttribute('data-user-id')===uid||n.getAttribute('data-uid')===uid||n.getAttribute('href')?.includes('/user/'+uid))||n.getAttribute('contenteditable')==='false'&&(n.innerText||'').trim()==='@'+owner.nickname),before.owner)
          if(!token)throw new RuntimeError('mention_unverified','未确认真实 @ 标记，未发布')
          a.guard(session,run);await box.focus();await page.keyboard.press('ControlOrMeta+End')
        }
        if(typeof grant.text!=='string'||!grant.text.trim()||grant.text.length>1000)throw new RuntimeError('invalid_text','评论正文不正确',400)
        a.guard(session,run);await page.keyboard.insertText(grant.text)
        const knownCommentIds=new Set(run.comments.keys())
        let receipt=null
        const listener=async response=>{
          try {const u=new URL(response.url());if(u.origin!=='https://www.douyin.com'||!/^\/aweme\/v\d+\/web\/comment\/publish\/?$/.test(u.pathname))return
            const request=response.request();if(request.method()!=='POST')return
            const params=new URLSearchParams(request.postData()||'')
            if(params.get('aweme_id')!==grant.video_id || !(params.get('text')||'').includes(grant.text))return
            const d=await response.json();a.guard(session,run)
            const c=d.comment,parent=String(c?.reply_to_reply_id&&c.reply_to_reply_id!=='0'?c.reply_to_reply_id:c?.reply_id||'')
            if(Number.isInteger(d.status_code)&&d.status_code!==0)receipt={status:'failed',reason:'平台拒绝评论',platform_code:d.status_code}
            else if(d.status_code===0&&id(c?.cid)&&(!c.aweme_id||c.aweme_id===grant.video_id)&&
              (c.user?.sec_uid===grant.account_id||!c.user?.sec_uid&&before.account?.uid&&String(c.user?.uid)===before.account.uid)&&
              (typeof c.text!=='string'||c.text.includes(grant.text))&&
              (op==='reply_comment'?parent===grant.comment_id:['','0'].includes(parent)))receipt={status:'confirmed',cid:c.cid,video_id:grant.video_id,parent_id:parent,evidence:'platform_comment_receipt'}
          }catch{/* Uncorrelated or partial receipts never confirm a write. */}}
        page.on('response',listener)
        try {
          submit();await page.keyboard.press('Enter')
          for(let i=0;i<24&&!receipt;i++) {
            await a.wait(session,run,400)
            if(await page.evaluate(verificationDOM)){result.reason='评论触发短信本人验证，发布结果尚未确认；请接管完成验证后核对，勿重发';result.verification_required=true;break}
            const sent=[...run.comments.values()].filter(c=>!knownCommentIds.has(c.id)&&c.video_id===grant.video_id&&c.author_id===grant.account_id&&
              (grant.mention_owner?c.text.trim().endsWith(grant.text.trim()):c.text.trim()===grant.text.trim())&&
              (op==='reply_comment'?c.parent_id===grant.comment_id:['','0'].includes(c.parent_id)))
            if(sent.length===1)receipt={status:'confirmed',cid:sent[0].id,video_id:grant.video_id,parent_id:sent[0].parent_id,evidence:'fresh_own_comment_list'}
          }
          if(receipt) {
            Object.assign(result,receipt,{mentioned_owner:!!grant.mention_owner})
            if(receipt.status==='confirmed')run.published.set(receipt.cid,{cid:receipt.cid,account_id:before.account.id,video_id:grant.video_id})
          }
        }finally{page.off('response',listener)}
      } else if(op==='reply_dm'||op==='share_note') {
        const peer=before.conversation
        if(!peer?.id||peer.id!==grant.peer_id)throw new RuntimeError('peer_mismatch','当前私信会话身份不匹配')
        if(op==='reply_dm') {
          const incoming=before.messages?.find(m=>m.id===grant.message_id&&m.direction==='inbound')
          const white=run.social.whitelist?.some(p=>p.handle===peer.handle&&p.nickname===peer.nickname)
          if(!incoming||!white&&peer.follows_me!==true)throw new RuntimeError('dm_forbidden','仅可回复白名单或已关注自己且先发消息的人')
        } else if(before.owner?.id!==peer.id)throw new RuntimeError('owner_mismatch','分享附言只能发送给 Owner')
        const box=await this.editor(session,run,'message')
        const ids=new Set(before.messages.map(m=>m.id))
        if(grant.text){a.guard(session,run);await page.keyboard.insertText(grant.text);submit();await page.keyboard.press('Enter')}
        if(grant.sticker&&!grant.text) {
          const toggle=page.locator('[class*="messageMsgInputiconAction"]').filter({visible:true})
          if(await toggle.count()!==1)throw new RuntimeError('sticker_missing','未找到唯一表情面板入口')
          await this.click(session,run,toggle);await a.wait(session,run,500)
          const stickers=page.locator('[class*="componentsemoji"] img,.componentsemojiemojiPanel img').filter({visible:true})
          const hits=[];for(let i=0;i<await stickers.count();i++){const s=stickers.nth(i);if(await s.getAttribute('alt')===grant.sticker)hits.push(s)}
          if(hits.length!==1)throw new RuntimeError('sticker_missing','没有匹配的唯一表情，未发送')
          submit();await hits[0].click({timeout:2500})
        }
        for(let i=0;i<20;i++){await a.wait(session,run,400);const view=await this.read(session,run);const sent=view.messages.find(m=>!ids.has(m.id)&&m.direction==='outbound'&&(grant.text?m.text.replace(/[\u200B\uFEFF]/g,'').trim()===grant.text.replace(/[\u200B\uFEFF]/g,'').trim():m.sticker===grant.sticker));if(sent)return Object.assign(result,{status:'confirmed',message_id:sent.id,peer_id:peer.id})}
      } else if(op==='share') {
        if(!before.owner?.id||grant.peer_id!==before.owner.id)throw new RuntimeError('owner_mismatch','分享目标未确认')
        const baseline=run.messageBaselines.get(before.owner.id)
        if(!baseline)throw new RuntimeError('share_baseline_missing','分享前请先打开 Owner 会话读取已有消息，再返回视频')
        const beforeIds=new Set(baseline)
        const icon=page.locator('[data-e2e="video-share-icon-container"],[data-e2e="video-player-share"]').filter({visible:true}).first()
        if(!await icon.count())throw new RuntimeError('share_missing','没有找到抖音站内分享入口')
        a.guard(session,run);await icon.hover({timeout:2500});await a.wait(session,run,1000)
        const rows=page.locator('[data-e2e*="share"] [data-user-id],[data-e2e*="share"] li,[class*="share"] [data-user-id],[data-userid]').filter({visible:true})
        const matches=[]
        for(let i=0;i<await rows.count();i++) {const row=rows.nth(i),data=await row.evaluate(elementIdentity);if((data.id===before.owner.id||data.uid===before.owner.id||before.owner.uid&&data.uid===before.owner.uid)&&data.text.includes(before.owner.nickname))matches.push(row)}
        let button
        if(matches.length===1)button=(await matches[0].innerText()).trim()==='分享'?matches[0]:matches[0].getByText('分享',{exact:true}).filter({visible:true})
        else if(matches.length===0) {
          const buttons=page.getByText('分享',{exact:true}).filter({visible:true}),confirmed=[]
          for(let i=0;i<Math.min(await buttons.count(),30);i++) {
            let row=buttons.nth(i)
            for(let level=0;level<4;level++,row=row.locator('..')) {
              const data=await row.evaluate(elementIdentity)
              if((data.id===before.owner.id||before.owner.uid&&data.uid===before.owner.uid)&&data.text.includes(before.owner.nickname)) {confirmed.push(buttons.nth(i));break}
            }
          }
          if(confirmed.length===1)button=confirmed[0]
        }
        if(!button)throw new RuntimeError('share_target_missing','分享面板没有唯一匹配 Owner 账号的接收人，未分享')
        if(await button.count()!==1)throw new RuntimeError('share_button_missing','没有找到目标行的分享按钮')
        submit();await button.click({timeout:2500});await a.wait(session,run,1000)
        // A click/toast is not a delivery receipt. Read the exact owner's
        // conversation and require a fresh, outbound card with this video ID.
        await page.goto('https://www.douyin.com/chat?isPopup=1',{waitUntil:'domcontentloaded',timeout:25000});await a.wait(session,run,1000)
        await this.waitConversation(session,run,before.owner.id)
        await this.navigate(session,run,{op:'conversation',peer_id:before.owner.id})
        for(let i=0;i<15;i++){await a.wait(session,run,400);const v=await this.read(session,run);const sent=v.messages.find(m=>m.direction==='outbound'&&m.video_id===grant.video_id&&!beforeIds.has(m.id));if(sent)return Object.assign(result,{status:'confirmed',message_id:sent.id,peer_id:before.owner.id,video_id:grant.video_id})}
      }
      return result
    } catch(error) {
      if(error.code==='owner_control'||error.code==='owner_login'||error.code==='automation_revoked')throw error
      result.reason=error instanceof RuntimeError?error.message:'操作没有获得确认，请核对画面';return result
    }
  }
}
