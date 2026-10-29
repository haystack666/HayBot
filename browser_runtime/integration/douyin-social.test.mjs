import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { BrowserEngine } from '../src/engine.mjs'
import {likeControlDOM,likeStateDOM} from '../src/douyin-social.mjs'

const video='7566833210012345678',self='MS4_self_12345',owner='MS4_owner_12345',peer='MS4_peer_12345'
const interactions={comments_enabled:true,replies_enabled:true,likes_enabled:true,messages_enabled:true,shares_enabled:true,owner:{handle:'owner_handle',nickname:'主人'},whitelist:[]}
const html=`<!doctype html><meta charset="utf-8"><title>抖音互动隔离测试</title>
<section data-e2e="detail-video-info" data-e2e-aweme-id="${video}"><h1>DeepSeek 模型演示</h1></section>
<button data-e2e="video-player-digg" data-e2e-state="video-player-no-digged" onclick="this.dataset.e2eState='video-player-is-digged';window.likeCount++;fetch('/aweme/v1/web/commit/item/digg/',{method:'POST',body:new URLSearchParams({aweme_id:'${video}',type:'1'})})">点赞</button>
<button data-e2e="video-comment">评论</button><div contenteditable="true" data-e2e="comment-input"></div>
<div data-e2e="comment-item" data-comment-id="incoming_comment"><a href="/user/${peer}">粉丝</a><span>刚才那条说得好</span><button onclick="window.reply='incoming_comment'">回复</button></div>
<div role="option" data-user-id="${owner}" onclick="document.querySelector('[contenteditable]').innerHTML='<span contenteditable=false data-user-id=${owner}>@主人</span>';window.mention=true">主人</div>
<div data-e2e="conversation-item" data-peer-id="${owner}" aria-selected="true"><span class="ConversationItemtitle">主人</span><a href="/user/${owner}">主页</a><b data-unread="true">1</b></div>
<p data-message-id="existing" data-direction="inbound">你好</p>
<div data-e2e="video-share-icon-container">分享入口</div><div data-e2e="share-panel"><li data-user-id="${owner}">主人<button onclick="window.shareCount++;window.shared=true">分享</button></li></div>
<script>
window.commentCount=0;window.likeCount=0;window.shareCount=0;window.reply='';window.mention=false;
fetch('/aweme/v1/web/user/profile/self/').then(r=>r.json());fetch('/aweme/v1/web/user/profile/other/').then(r=>r.json());fetch('/aweme/v1/web/comment/list/').then(r=>r.json());
const box=document.querySelector('[contenteditable]');box.addEventListener('keydown',async e=>{if(e.key!=='Enter')return;e.preventDefault();window.commentCount++;if(window.noReceipt)return;
const text=box.innerText.replace('@owner_handle','').replace('@主人','');const body=new URLSearchParams({aweme_id:'${video}',text,reply_id:window.reply});
await fetch('/aweme/v1/web/comment/publish/',{method:'POST',body});box.innerHTML='';});
</script>`

test('detail interaction bar uses visible React digg state, correlated receipts and read-only reconciliation',{timeout:90000,skip:process.platform!=='darwin'},async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'haybot-social-detail-')),engine=new BrowserEngine(dir)
 let liked=false,published=false,challenge=false,rejectLike=false,noLikeReceipt=false,wrongComment=false
 try {
  await engine.start('detail');const session=engine.get('detail'),page=session.tabs.get(session.active)
  const fixture=()=>`<meta charset="utf-8"><section data-e2e="detail-video-info" data-e2e-aweme-id="${video}"><h1>猫咪</h1><div id="visible-heart" style="width:80px;height:40px">点赞</div><div id="collect">收藏</div></section>
  <button hidden data-e2e="video-player-digg" data-e2e-state="video-player-no-digged" onclick="window.hiddenClicks++">隐藏按钮</button>
  <div contenteditable="true" data-e2e="comment-input"></div><script>
  window.hiddenClicks=0;window.clicks=0;
  const heart=document.querySelector('#visible-heart'),collect=document.querySelector('#collect');
  heart.__reactProps$fixture={onClick:()=>{},children:[{props:{type:'digg',userInteraction:${liked}}}]};
  collect.__reactProps$fixture={onClick:()=>{},children:[{props:{type:'collect',userInteraction:false}}]};
  heart.onclick=()=>{window.clicks++;heart.__reactProps$fixture.children[0].props.userInteraction=true;fetch('/aweme/v1/web/commit/item/digg/',{method:'POST',body:new URLSearchParams({aweme_id:'${video}',type:'1'})})};
  fetch('/aweme/v1/web/user/profile/self/');fetch('/aweme/v1/web/aweme/detail/?aweme_id=${video}');fetch('/aweme/v1/web/comment/list/');
  const box=document.querySelector('[contenteditable]');box.onkeydown=async e=>{if(e.key!=='Enter')return;e.preventDefault();await fetch('/aweme/v1/web/comment/publish/',{method:'POST',body:new URLSearchParams({aweme_id:'${video}',text:box.innerText})});box.innerText=''};
  </script>`
  await session.context.route('https://www.douyin.com/**',async route=>{
   const u=new URL(route.request().url())
   if(u.pathname.includes('profile/self'))return route.fulfill({json:{user:{sec_uid:self,uid:'10001',nickname:'自己'}}})
   if(u.pathname.includes('aweme/detail'))return route.fulfill({json:{status_code:0,aweme_detail:{aweme_id:video,desc:'猫咪',user_digged:liked?1:0}}})
   if(u.pathname.includes('commit/item/digg')){if(!rejectLike)liked=true;return route.fulfill({json:noLikeReceipt?{}:{status_code:rejectLike?4:0}})}
   if(u.pathname.includes('comment/list'))return route.fulfill({json:{comments:published?[{cid:'own-published',aweme_id:video,user:{sec_uid:self},text:'真实评论',reply_id:'0'}]:[]}})
   if(u.pathname.includes('comment/publish')) {
    if(challenge){await page.evaluate(()=>{const e=document.createElement('article');e.innerHTML='为确保是本人操作抖音账号，请输入短信验证码<input placeholder="验证码">';document.body.append(e)});return route.fulfill({json:{}})}
    published=true
    return route.fulfill({json:{status_code:0,comment:{cid:'server-comment',reply_id:'0',text:'真实评论',user:{uid:wrongComment?'9999':'10001'}}}})
   }
   return route.fulfill({contentType:'text/html',body:fixture()})
  })
  const g=engine.douyin.begin('detail',{interactions}),run=session.automation
  const act=input=>engine.douyin.act('detail',{token:g.token,generation:session.generation,...input})
  await page.goto('https://www.douyin.com/video/'+video);await page.waitForTimeout(350);run.coverage.set(video,[[0,3]])
  const auth=(n,more={})=>({operation_id:n.toString(16).padStart(32,'0'),account_id:self,video_id:video,text:'真实评论',...more})
  const h=await page.evaluateHandle(likeControlDOM,video);assert.equal(await h.asElement().getAttribute('id'),'visible-heart');assert.equal(await h.asElement().evaluate(likeStateDOM),false);await h.dispose()
  let result=await act({op:'like',authorization:auth(101)})
  assert.equal(result.interaction.status,'confirmed');assert.equal(await page.evaluate(()=>window.clicks),1);assert.equal(await page.evaluate(()=>window.hiddenClicks),0)
  result=await act({op:'like',authorization:auth(102)});assert.equal(result.interaction.already,true);assert.equal(await page.evaluate(()=>window.clicks),1)
  result=await act({op:'reconcile',authorization:auth(103,{op:'like'})});assert.equal(result.interaction.status,'confirmed');assert.equal(result.interaction.evidence,'fresh_video_detail');assert.equal(await page.evaluate(()=>window.clicks),1)
  liked=false;rejectLike=true;await page.reload();await page.waitForTimeout(300)
  result=await act({op:'like',authorization:auth(104)});assert.equal(result.interaction.status,'failed');assert.equal(result.interaction.platform_code,4)
  rejectLike=false;noLikeReceipt=true;await page.reload();await page.waitForTimeout(300)
  result=await act({op:'like',authorization:auth(105)});assert.equal(result.interaction.status,'confirmed');assert.equal(result.interaction.evidence,'fresh_video_detail')
  result=await act({op:'comment',authorization:auth(106)});assert.equal(result.interaction.status,'confirmed');assert.equal(result.interaction.video_id,video)
  result=await act({op:'reconcile',authorization:auth(107,{op:'comment'})});assert.equal(result.interaction.cid,'own-published');assert.equal(result.interaction.status,'confirmed')
  wrongComment=true;result=await act({op:'comment',authorization:auth(108)});assert.equal(result.interaction.status,'unknown')
  await page.locator('[contenteditable]').fill('');challenge=true
  result=await act({op:'comment',authorization:auth(109)})
  assert.equal(result.interaction.status,'unknown');assert.equal(result.interaction.verification_required,true);assert.equal(result.blocked,'account_verification');assert.equal(result.body,'')
  result=await act({op:'reconcile',authorization:auth(110,{op:'like'})});assert.equal(result.blocked,'account_verification')
  await page.locator('article').evaluate(e=>e.remove())
  await assert.rejects(act({op:'reconcile',authorization:auth(111,{op:'like',account_id:'wrong'})}),{code:'account_mismatch'})
  engine.douyin.end('detail',g.token)
 }finally{await engine.close();await fs.rm(dir,{recursive:true,force:true})}
})

test('Chrome social writes correlate receipts, preserve drafts, verify mentions and never repeat unknown submissions', {timeout:90000,skip:process.platform!=='darwin'},async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'haybot-social-')),engine=new BrowserEngine(dir)
 try {
  await engine.start('social');const session=engine.get('social'),page=session.tabs.get(session.active)
  let rejected=false
  await session.context.route('https://www.douyin.com/**',async route=>{
   const req=route.request(),u=new URL(req.url())
   if(u.pathname.includes('profile/self'))return route.fulfill({json:{user:{sec_uid:self,uid:'10001',nickname:'自己',unique_id:'self_handle'}}})
   if(u.pathname.includes('profile/other'))return route.fulfill({json:{user:{sec_uid:owner,uid:'10002',nickname:'主人',unique_id:'owner_handle',follower_status:1}}})
   if(u.pathname.includes('comment/list'))return route.fulfill({json:{comments:[{cid:'incoming_comment',aweme_id:video,text:'刚才那条说得好',reply_id:'own_comment',user:{sec_uid:peer,nickname:'粉丝'}}]}})
   if(u.pathname.includes('/commit/item/digg/'))return route.fulfill({json:{status_code:0}})
   if(u.pathname.includes('comment/publish')) {
    const body=new URLSearchParams(req.postData()||'')
    return route.fulfill({json:rejected?{status_code:1}:{status_code:0,comment:{cid:'new_comment_'+Date.now(),aweme_id:video,reply_id:body.get('reply_id'),text:body.get('text'),user:{sec_uid:self}}}})
   }
   return route.fulfill({contentType:'text/html',body:html})
  })
  const grant=engine.douyin.begin('social',{interactions,published:[{cid:'own_comment',account_id:self,video_id:video}]})
  const run=session.automation
  const act=input=>engine.douyin.act('social',{token:grant.token,generation:session.generation,...input})
  await page.goto('https://www.douyin.com/video/'+video);await page.waitForTimeout(500)
  run.coverage.set(video,[[0,3]])
  let state=await act({op:'observe'});assert.equal(state.account.id,self);assert.equal(state.owner.id,owner);assert.equal(state.comments[0].parent_id,'own_comment');assert.equal(state.watched,true)
  const authorization=(n,p={})=>({operation_id:n.toString(16).padStart(32,'0'),account_id:self,video_id:video,text:'这个演示很清楚',...p})
  let result=await act({op:'comment',authorization:authorization(1)})
  assert.equal(result.interaction.status,'confirmed');assert.ok(result.interaction.cid);assert.equal(await page.evaluate(()=>window.commentCount),1)
  result=await act({op:'comment',authorization:authorization(1)});assert.equal(result.interaction.replayed,true);assert.equal(await page.evaluate(()=>window.commentCount),1)
  result=await act({op:'like',authorization:authorization(2)});assert.equal(result.interaction.status,'confirmed');assert.equal(await page.evaluate(()=>window.likeCount),1)
  result=await act({op:'like',authorization:authorization(3)});assert.equal(result.interaction.already,true);assert.equal(await page.evaluate(()=>window.likeCount),1)
  result=await act({op:'comment',authorization:authorization(4,{mention_owner:true,mention_id:owner})})
  assert.equal(result.interaction.status,'confirmed');assert.equal(result.interaction.mentioned_owner,true)
  await page.locator('[contenteditable]').fill('主人尚未发送的草稿')
  result=await act({op:'comment',authorization:authorization(5)})
  assert.equal(result.interaction.status,'failed');assert.equal(result.interaction.submitted,false);assert.match(result.interaction.reason,/草稿/);assert.equal(await page.locator('[contenteditable]').innerText(),'主人尚未发送的草稿')
  await page.locator('[contenteditable]').fill('')
  result=await act({op:'reply_comment',authorization:authorization(6,{comment_id:'incoming_comment',parent_id:'own_comment'})})
  assert.equal(result.interaction.status,'confirmed');assert.equal(result.interaction.parent_id,'incoming_comment')
  rejected=true
  result=await act({op:'comment',authorization:authorization(7)})
  assert.equal(result.interaction.status,'failed');assert.equal(result.interaction.submitted,true)
  rejected=false;await page.evaluate(()=>window.noReceipt=true)
  result=await act({op:'comment',authorization:authorization(8)})
  assert.equal(result.interaction.status,'unknown');const count=await page.evaluate(()=>window.commentCount)
  result=await act({op:'comment',authorization:authorization(8)})
  assert.equal(result.interaction.status,'unknown');assert.equal(await page.evaluate(()=>window.commentCount),count)
  await assert.rejects(act({op:'comment',authorization:authorization(9,{account_id:'wrong-account'})}),{code:'write_permission'})
  await page.locator('[contenteditable]').fill('');const writing=act({op:'comment',authorization:authorization(10)})
  await page.waitForTimeout(350);const lease=engine.claim('social','owner').lease
  await assert.rejects(writing,{code:'owner_control'});assert.equal(session.automation,null)
  engine.release('social',lease)
 } finally {await engine.close();await fs.rm(dir,{recursive:true,force:true})}
})

test('Chrome inbox enforces inbound/follower identity, sends owner cards and confirms text/sticker separately',{timeout:90000,skip:process.platform!=='darwin'},async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'haybot-douyin-inbox-')),engine=new BrowserEngine(dir)
 let shared=false,outbound=[]
 const chat=()=>`<!doctype html><meta charset="utf-8"><title>消息</title>
  <div data-e2e="conversation-item" data-peer-id="${owner}" aria-selected="true"><span class="ConversationItemtitle">主人</span><a href="/user/${owner}">主页</a><i data-unread="true">1</i></div>
  <p data-message-id="inbound-server-1" data-direction="inbound">这个视频好看吗</p>
  ${shared?`<div class="MessageItemShareAwemecontainer" id="shared-card">视频卡片</div>`:''}
  <section id="messages">${outbound.map(m=>`<p data-message-id="${m.id}" data-direction="outbound">${m.text}</p>`).join('')}</section>
  <div contenteditable="true"></div><button class="messageMsgInputiconAction" onclick="document.querySelector('.componentsemojiemojiPanel').hidden=false">表情</button>
  <div class="componentsemojiemojiPanel" hidden><img alt="好耶" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='30' height='30'%3E%3C/svg%3E" onclick="sendSticker()"></div>
  <script>const box=document.querySelector('[contenteditable]');let count=${outbound.length};
   async function append(text,sticker=''){const id='outbound-server-'+(++count);await fetch('/fixture/message',{method:'POST',body:JSON.stringify({id,text})});const p=document.createElement('p');p.dataset.messageId=id;p.dataset.direction='outbound';p.innerText=text;if(sticker)p.innerHTML='<img alt="'+sticker+'" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">';document.querySelector('#messages').append(p)}
   box.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();append(box.innerText);box.innerHTML=''}});function sendSticker(){append('','好耶')}
   const card=document.querySelector('#shared-card');if(card)card.__reactProps$fixture={children:{props:{message:Object.assign(Object.create({serverId:'new-card-id',sender:'10001',conversationId:''}),{isMyMessage:true,parsedContent:{itemId:'${video}'}})}}};
   fetch('/aweme/v1/web/user/profile/self/');fetch('/aweme/v1/web/user/profile/other/');
  </script>`
 try {
  await engine.start('inbox');const session=engine.get('inbox'),page=session.tabs.get(session.active)
  await session.context.route('https://www.douyin.com/**',async route=>{
   const u=new URL(route.request().url())
   if(u.pathname.includes('profile/self'))return route.fulfill({json:{user:{sec_uid:self,uid:'10001',nickname:'自己',unique_id:'self_handle'}}})
   if(u.pathname.includes('profile/other'))return route.fulfill({json:{user:{sec_uid:owner,uid:'10002',nickname:'主人',unique_id:'owner_handle',follower_status:1}}})
   if(u.pathname==='/fixture/share'){shared=true;return route.fulfill({json:{ok:true}})}
   if(u.pathname==='/fixture/message'){outbound.push(JSON.parse(route.request().postData()));return route.fulfill({json:{ok:true}})}
   if(u.pathname==='/chat') {
    let body=chat()
    if(shared)body=body.replace('<script>',`<script>const rows=[...document.querySelectorAll('[data-e2e="conversation-item"]')];rows.forEach(e=>e.remove());setTimeout(()=>rows.forEach(e=>document.body.prepend(e)),2400);`)
    return route.fulfill({contentType:'text/html',body})
   }
   return route.fulfill({contentType:'text/html',body:html.replace('window.shared=true','fetch(\'/fixture/share\',{method:\'POST\'});window.shared=true')})
  })
  const grant=engine.douyin.begin('inbox',{interactions}),run=session.automation
  const act=input=>engine.douyin.act('inbox',{token:grant.token,generation:session.generation,...input})
  let state=await act({op:'inbox'});assert.equal(state.conversations[0].unread,true);assert.equal(state.conversation.id,owner);assert.equal(state.messages[0].direction,'inbound')
  const auth=(n,more={})=>({operation_id:n.toString(16).padStart(32,'0'),account_id:self,peer_id:owner,message_id:'inbound-server-1',text:'画面很有意思',...more})
  let result=await act({op:'reply_dm',authorization:auth(21)})
  assert.equal(result.interaction.status,'confirmed');assert.equal(outbound.length,1)
  await page.locator('[data-e2e="conversation-item"]').evaluate((e,id)=>{
    e.removeAttribute('data-peer-id');e.removeAttribute('aria-selected');e.className='conversationConversationItemwrapper conversationConversationItemcurConversation'
    e.querySelector('a').remove()
    e.__reactProps$fixture={children:{props:{conversation:{toParticipantSecUserId:id,id:'conversation-server-id',unreadCount:2}}}}
  },owner)
  state=await act({op:'observe'});assert.equal(state.conversations[0].id,owner);assert.equal(state.conversation.id,owner)
  await page.locator('[data-e2e="conversation-item"]').evaluate((e,id)=>{delete e.__reactProps$fixture;e.className='';e.dataset.peerId=id;e.setAttribute('aria-selected','true')},owner)
  result=await act({op:'reply_dm',authorization:auth(22,{message_id:'nonexistent'})})
  assert.equal(result.interaction.status,'failed');assert.equal(result.interaction.submitted,false);assert.equal(outbound.length,1)
  run.people.set(owner,{...run.people.get(owner),follows_me:false})
  result=await act({op:'reply_dm',authorization:auth(23)})
  assert.equal(result.interaction.status,'failed');assert.equal(outbound.length,1)
  run.people.set(owner,{...run.people.get(owner),follows_me:true})
  run.items.set(video,{id:video,title:'DeepSeek',url:'https://www.douyin.com/video/'+video});run.coverage.set(video,[[0,4]])
  await act({op:'open',id:video})
  result=await act({op:'share',authorization:auth(24,{video_id:video,text:''})})
  assert.equal(result.interaction.status,'confirmed');assert.equal(result.interaction.message_id,'new-card-id');assert.equal(shared,true)
  result=await act({op:'share_note',authorization:auth(25,{share_id:'new-card-id',text:'这段给你看'})})
  assert.equal(result.interaction.status,'confirmed');assert.equal(outbound.at(-1).text,'这段给你看')
  result=await act({op:'share_note',authorization:auth(26,{share_id:'new-card-id',text:'',sticker:'好耶'})})
  assert.equal(result.interaction.status,'confirmed');assert.equal(outbound.length,3)
  // Clearing selection must not silently retain a previous recipient.
  await page.locator('[aria-selected]').evaluate(e=>e.removeAttribute('aria-selected'))
  state=await act({op:'observe'});assert.equal(state.conversation,null);assert.deepEqual(state.messages,[])
  engine.douyin.end('inbox',grant.token)
 } finally {await engine.close();await fs.rm(dir,{recursive:true,force:true})}
})

test('background inbox polls configured interval, opens unread verified peers and closes immediately on takeover',{timeout:45000,skip:process.platform!=='darwin'},async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'haybot-douyin-poll-')),engine=new BrowserEngine(dir)
 try {
  await engine.start('poll');const session=engine.get('poll'),page=session.tabs.get(session.active)
  const account=`<script>fetch('/aweme/v1/web/user/profile/self/')</script>`
  const peerProfile=`<script>fetch('/aweme/v1/web/user/profile/other/')</script>`
  const inbox=`<meta charset="utf-8"><div data-e2e="conversation-item" data-peer-id="${owner}" onclick="this.setAttribute('aria-selected','true')"><span class="ConversationItemtitle">主人</span><i data-unread="true">2</i></div><p data-message-id="real-inbound-id" data-direction="inbound">你好</p><script>const row=document.querySelector('[data-e2e]');row.__reactProps$fixture={conversation:{toParticipantSecUserId:'${owner}',id:'cid',unreadCount:2}}</script>`
  await session.context.route('https://www.douyin.com/**',async route=>{
   const u=new URL(route.request().url())
   if(u.pathname.includes('profile/self'))return route.fulfill({json:{user:{sec_uid:self,uid:'10001',nickname:'自己',unique_id:'self_handle'}}})
   if(u.pathname.includes('profile/other'))return route.fulfill({json:{user:{sec_uid:owner,uid:'10002',nickname:'主人',unique_id:'owner_handle',follower_status:1}}})
   return route.fulfill({contentType:'text/html',body:u.pathname==='/chat'?inbox:u.pathname==='/user/'+owner?peerProfile:account})
  })
  let grant=engine.douyin.begin('poll',{interactions})
  const act=input=>engine.douyin.act('poll',{token:grant.token,generation:session.generation,...input})
  let result=await act({op:'account'});assert.equal(result.inboxMonitor.interval_seconds,5);assert.equal(result.pendingUnread[0].id,owner)
  assert.equal(session.tabs.size,1);assert.equal(session.tabs.get(session.active),page);assert.match(page.url(),/user\/self/)
  const old=session.automation.inboxMonitor.page
  engine.douyin.end('poll',grant.token);await old.waitForEvent('close').catch(()=>{});assert.ok(old.isClosed())
  grant=engine.douyin.begin('poll',{interactions:{...interactions,dm_check_interval_seconds:1}})
  result=await act({op:'account'});const monitor=session.automation.inboxMonitor
  const before=monitor.checkedAt,generation=session.generation,active=session.active
  await monitor.page.locator('[data-e2e]').evaluate(e=>{e.__reactProps$fixture.conversation.unreadCount=3})
  await page.waitForTimeout(1300)
  assert.ok(monitor.checkedAt>before);assert.equal(monitor.pending.get(owner).unreadCount,3)
  assert.equal(session.generation,generation);assert.equal(session.active,active)
  assert.equal(session.automation.people.has(owner),false)
  result=await act({op:'conversation',peer_id:owner})
  assert.equal(result.conversation.id,owner);assert.equal(result.conversation.follows_me,true)
  assert.equal(result.messages[0].id,'real-inbound-id');assert.deepEqual(result.pendingUnread,[])
  result=await act({op:'conversation',peer_id:'MS4_not_observed'});assert.equal(result.actionError.code,'unobserved_peer');assert.equal(result.actionError.submitted,false)
  const lease=engine.claim('poll','owner').lease;await monitor.page.waitForEvent('close').catch(()=>{})
  assert.ok(monitor.page.isClosed());assert.equal(session.automation,null);engine.release('poll',lease)
 } finally{await engine.close();await fs.rm(dir,{recursive:true,force:true})}
})
