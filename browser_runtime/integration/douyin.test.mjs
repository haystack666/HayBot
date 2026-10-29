import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { BrowserEngine } from '../src/engine.mjs'

const aid='7566833210012345678'
const html=`<!doctype html><meta charset="utf-8"><title>抖音测试</title><a href="/video/${aid}">猫咪玩积木 @小猫</a><canvas width="640" height="360"></canvas><video autoplay muted width="640" height="360"></video><button data-e2e="video-comment" onclick="document.querySelector('#comments').textContent='真可爱'">评论</button><p id="comments"></p><script>
const c=document.querySelector('canvas'),x=c.getContext('2d');let n=0;setInterval(()=>{x.fillStyle=n++%2?'pink':'lightblue';x.fillRect(0,0,640,360);x.fillStyle='black';x.font='32px sans-serif';x.fillText('猫咪玩积木 '+n,20,80)},80);
const v=document.querySelector('video');v.srcObject=c.captureStream(24);v.play();
fetch('/aweme/v1/web/tab/feed/').then(r=>r.json());window.moves=0;addEventListener('keydown',e=>{if(e.key==='ArrowDown')window.moves++});
</script>`
test('real Chrome Douyin adapter: observed IDs, search, playback evidence, comments, challenge and takeover', {timeout:90000,skip:process.platform!=='darwin'}, async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'haybot-douyin-fixture-')),engine=new BrowserEngine(dir)
 try{
  await engine.start('fixture');const session=engine.get('fixture'),page=session.tabs.get(session.active)
  await session.context.route('https://www.douyin.com/**',route=>route.fulfill(route.request().url().includes('/aweme/')?{json:{aweme_list:[{aweme_id:aid,desc:'猫咪玩积木',author:{nickname:'小猫'},video:{duration:12000}}]}}:{contentType:'text/html',body:html}))
  const grant=engine.douyin.begin('fixture')
  const act=input=>engine.douyin.act('fixture',{token:grant.token,generation:session.generation,...input})
  let result=await act({op:'home'});assert.equal(result.blocked,'');assert.equal(result.items[0].id,aid);assert.equal(result.items[0].author,'小猫')
  await act({op:'search',query:'猫咪积木'});assert.match(page.url(),/\/search\//)
  result=await act({op:'open',id:aid});assert.equal(result.current.id,aid)
  assert.equal(await page.locator('video').evaluate(v=>v.paused),true)
  result=await act({op:'watch',seconds:3});assert.ok(result.watch.advancedSeconds>1);assert.equal(result.images.length,3);assert.equal(result.watch.audioAvailable,false)
  assert.equal(result.playback.paused,true);assert.equal(result.watch.partial,true);assert.ok(result.watch.sampledRanges.length>0)
  const stopped=result.playback.currentTime
  await new Promise(r=>setTimeout(r,700))
  assert.ok(Math.abs(await page.locator('video').evaluate(v=>v.currentTime)-stopped)<0.1,'model thinking does not advance the video')
  result=await act({op:'watch',seconds:3})
  assert.ok(result.watch.coverageRanges[0][1]-result.watch.coverageRanges[0][0]>5,'successive watches preserve cumulative ranges')
  await page.locator('video').evaluate(v=>{Object.defineProperty(v,'ended',{value:true,configurable:true});window.playCalls=0;v.play=()=>{window.playCalls++;return Promise.resolve()}})
  const endCheck=Date.now()
  result=await act({op:'watch',seconds:30})
  assert.equal(result.watch.ended,true);assert.equal(result.images.length,1);assert.ok(Date.now()-endCheck<2500)
  assert.equal(await page.evaluate(()=>window.playCalls),0,'ended video is not restarted automatically')
  await page.locator('video').evaluate(v=>{delete v.ended;delete v.play})
  result=await act({op:'comments'});assert.match(result.body,/真可爱/)
  await act({op:'next'});assert.equal(await page.evaluate(()=>window.moves),1)
  const watching=act({op:'watch',seconds:30});await new Promise(r=>setTimeout(r,400));const lease=engine.claim('fixture','owner').lease
  await assert.rejects(watching,{code:'owner_control'});assert.equal(session.automation,null)
  await page.locator('video').evaluate(v=>v.play())
  await new Promise(r=>setTimeout(r,400))
  assert.equal(await page.locator('video').evaluate(v=>v.paused),false,'revoked automation does not pause the owner playback')
  engine.release('fixture',lease)
  const second=engine.douyin.begin('fixture')
  await page.setContent('<title>验证码中间页</title><iframe></iframe><p>private challenge content</p>')
  result=await engine.douyin.act('fixture',{token:second.token,generation:session.generation,op:'observe'})
  assert.equal(result.blocked,'captcha');assert.equal(result.body,'');assert.deepEqual(result.items,[])
  await page.setContent('<meta charset="utf-8"><title>登录</title><input type="password" value="private-password"><p>登录敏感内容</p>')
  result=await engine.douyin.act('fixture',{token:second.token,generation:session.generation,op:'observe'})
  assert.equal(result.blocked,'login');assert.equal(result.body,'')
  engine.douyin.end('fixture',second.token)
 }finally{await engine.close();await fs.rm(dir,{recursive:true,force:true})}
})

test('Chrome duration policy: long content rejected, disjoint previews, failed seek and takeover', {timeout:60000,skip:process.platform!=='darwin'},async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'haybot-douyin-duration-')),engine=new BrowserEngine(dir)
 try{
  await engine.start('duration');const session=engine.get('duration'),page=session.tabs.get(session.active)
  await session.context.route('https://www.douyin.com/**',route=>route.fulfill(route.request().url().includes('/aweme/')?{json:{aweme_list:[{aweme_id:aid,desc:'长视频',video:{duration:3600001}}]}}:{contentType:'text/html',body:html}))
  const grant=engine.douyin.begin('duration')
  const act=input=>engine.douyin.act('duration',{token:grant.token,generation:session.generation,...input})
  await act({op:'home'});const original=page.url()
  let result=await act({op:'open',id:aid})
  assert.equal(result.skipped.duration,3600.001);assert.equal(page.url(),original,'known over-limit video is not opened')
  // A synthetic timeline on a real, playing canvas stream isolates seeking
  // policy from website/network behaviour. Existing tests cover native playback.
  await page.evaluate(id=>{
   history.replaceState(null,'','/video/'+id)
   const v=document.querySelector('video'),nativeTime=Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype,'currentTime')
   window.fixtureDuration=3601;window.seekAllowed=true;window.seekCount=0;let offset=0
   Object.defineProperty(v,'duration',{get:()=>window.fixtureDuration})
   Object.defineProperty(v,'currentTime',{get:()=>nativeTime.get.call(v)+offset,set:t=>{window.seekCount++;if(window.seekAllowed)offset=t-nativeTime.get.call(v)}})
  },aid)
  result=await act({op:'watch',seconds:3})
  assert.ok(result.skipped);assert.equal(result.watch,undefined)
  assert.equal(await page.locator('video').evaluate(v=>v.paused),true)
  await page.evaluate(()=>window.fixtureDuration=600)
  result=await act({op:'watch',seconds:3})
  assert.equal(result.watch.mode,'preview');assert.ok(result.watch.coverageRanges[0][0]<1)
  result=await act({op:'watch',seconds:3})
  assert.equal(result.watch.seek.requested,200);assert.equal(result.watch.partial,true)
  assert.equal(result.watch.coverageRanges.length,2)
  assert.ok(result.watch.coverageRanges[1][0]>=200 && result.watch.advancedSeconds<5,'seeking does not count skipped time as watching')
  result=await act({op:'watch',seconds:3,start_at:450})
  assert.equal(result.watch.seek.requested,450);assert.equal(result.watch.coverageRanges.length,3)
  const seekCount=await page.evaluate(()=>window.seekCount)
  result=await act({op:'watch',seconds:3,continue_segment:true})
  assert.equal(await page.evaluate(()=>window.seekCount),seekCount,'buffer waiting continues the same segment without another seek')
  assert.equal(result.watch.seek,null);assert.ok(result.watch.sampledRanges[0][0]>450)
  await page.evaluate(()=>window.seekAllowed=false)
  result=await act({op:'watch',seconds:3,start_at:300})
  assert.ok(result.seekFailed);assert.equal(result.watch,undefined);assert.equal(result.images,undefined)
  assert.equal(await page.locator('video').evaluate(v=>v.paused),true)
  const pending=act({op:'watch',seconds:3,start_at:300})
  await new Promise(r=>setTimeout(r,250));engine.claim('duration','owner')
  await assert.rejects(pending,{code:'owner_control'})
 }finally{await engine.close();await fs.rm(dir,{recursive:true,force:true})}
})
