import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { BrowserEngine } from '../src/engine.mjs'

const video='7566833210012345678',self='MS4_self_12345',owner='MS4_owner_12345',peer='MS4_peer_12345'
const interactions={comments_enabled:true,replies_enabled:true,likes_enabled:true,messages_enabled:true,shares_enabled:true,owner:{handle:'owner_handle',nickname:'主人'},whitelist:[]}
const html=`<!doctype html><meta charset="utf-8"><title>抖音互动隔离测试</title>
<section data-e2e="detail-video-info" data-e2e-aweme-id="${video}"><h1>DeepSeek 模型演示</h1></section>
<button data-e2e="video-player-digg" data-e2e-state="video-player-no-digg" onclick="this.dataset.e2eState='video-player-is-digg';window.likeCount++">点赞</button>
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
  run.coverage.set(video+':fixture',[[0,3]])
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
  ${shared?`<p data-message-id="new-card-id" data-direction="outbound"><a href="/video/${video}">视频卡片</a></p>`:''}
  <section id="messages">${outbound.map(m=>`<p data-message-id="${m.id}" data-direction="outbound">${m.text}</p>`).join('')}</section>
  <div contenteditable="true"></div><button class="messageMsgInputiconAction" onclick="document.querySelector('.componentsemojiemojiPanel').hidden=false">表情</button>
  <div class="componentsemojiemojiPanel" hidden><img alt="好耶" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='30' height='30'%3E%3C/svg%3E" onclick="sendSticker()"></div>
  <script>const box=document.querySelector('[contenteditable]');let count=${outbound.length};
   async function append(text,sticker=''){const id='outbound-server-'+(++count);await fetch('/fixture/message',{method:'POST',body:JSON.stringify({id,text})});const p=document.createElement('p');p.dataset.messageId=id;p.dataset.direction='outbound';p.innerText=text;if(sticker)p.innerHTML='<img alt="'+sticker+'" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">';document.querySelector('#messages').append(p)}
   box.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();append(box.innerText);box.innerHTML=''}});function sendSticker(){append('','好耶')}
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
   if(u.pathname==='/chat')return route.fulfill({contentType:'text/html',body:chat()})
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
  run.items.set(video,{id:video,title:'DeepSeek',url:'https://www.douyin.com/video/'+video});run.coverage.set(video+':fixture',[[0,4]])
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
