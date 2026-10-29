import test from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { BrowserEngine } from '../src/engine.mjs'
import { contentItems, mergeRanges, playbackRanges, watchPolicy, previewPosition, viewingConfig } from '../src/douyin.mjs'

test('per-run viewing settings control thresholds, disabled preview and fixed skip intervals',()=>{
 const settings=viewingConfig({preview_after_minutes:2,max_video_minutes:90,segment_seconds:6,skip_seconds:75})
 assert.equal(watchPolicy(120,settings).mode,'normal')
 assert.equal(watchPolicy(120.1,settings).mode,'preview')
 assert.equal(watchPolicy(5400,settings).mode,'preview')
 assert.equal(watchPolicy(5400.1,settings).mode,'skip')
 assert.equal(watchPolicy(600,viewingConfig({preview_enabled:false})).mode,'normal')
 assert.equal(previewPosition(600,[],6,undefined,75),0)
 assert.equal(previewPosition(600,[[0,6]],6,undefined,75),81)
 assert.equal(previewPosition(600,[[0,6],[81,87]],6,undefined,75),162)
 assert.equal(previewPosition(600,[[500,550]],6,undefined,75),null)
 for(const invalid of [{segment_seconds:0},{skip_seconds:'10'},{preview_enabled:1},{preview_after_minutes:61},{max_video_minutes:121},{unexpected:1},null])assert.throws(()=>viewingConfig(invalid),{code:'invalid_viewing'})
})

test('duration boundaries use exact seconds: 3 minutes normal, 60 minutes preview, longer skipped',()=>{
 for(const duration of [0,null,undefined,NaN,Infinity])assert.equal(watchPolicy(duration).mode,'unknown')
 assert.equal(watchPolicy(180).mode,'normal')
 assert.equal(watchPolicy(180.001).mode,'preview')
 assert.equal(watchPolicy(3600).mode,'preview')
 assert.equal(watchPolicy(3600.001).mode,'skip')
 const items=contentItems({aweme_id:'1234567890123456789',desc:'边界视频',video:{duration:3600001}})
 assert.equal(watchPolicy(items[0].duration).mode,'skip','do not round a video over 60 minutes down to 60')
})

test('long video previews spread across unseen segments and allow a model selected position',()=>{
 assert.equal(previewPosition(600,[],15),0)
 assert.equal(previewPosition(600,[[0,15]],15),200)
 assert.equal(previewPosition(600,[[0,15],[200,215]],15),400)
 assert.equal(previewPosition(600,[[0,15],[200,215],[400,415]],15),585)
 assert.equal(previewPosition(600,[[0,15],[200,215],[400,415],[585,600]],15),null)
 assert.equal(previewPosition(600,[[0,15]],15,123),123)
 assert.equal(previewPosition(600,[],15,599),597)
})

test('watch ranges preserve gaps, merge overlaps and distinguish loops from seeks or changed sources',()=>{
 assert.deepEqual(mergeRanges([[5,8],[0,3],[2,4],[6,9]]),[[0,4],[5,9]])
 const sample=(currentTime,source='one')=>({currentTime,source,duration:10})
 assert.deepEqual(playbackRanges(sample(8),sample(1),3),[[8,10],[0,1]])
 assert.deepEqual(playbackRanges(sample(2),sample(8),3),[])
 assert.deepEqual(playbackRanges(sample(2),sample(3,'two'),3),[])
 assert.deepEqual(playbackRanges(sample(3),sample(3),3),[])
})

test('Douyin content parsing retains stable IDs and excludes ads, live, secrets and signed media URLs', () => {
 const payload={data:[{aweme_info:{aweme_id:'1234567890123456789',desc:'猫咪玩玩具',author:{nickname:'猫猫',uid:'private'},video:{duration:25000,play_addr:{url_list:['private-signed-url']}}}},
 {aweme_info:{aweme_id:'2234567890123456789',desc:'广告',is_ads:true}},
 {aweme_info:{aweme_id:'3234567890123456789',desc:'直播',aweme_type:101}}],token:'private-token'}
 const items=contentItems(payload)
 assert.equal(items.length,1);assert.equal(items[0].duration,25);assert.equal(items[0].id,'1234567890123456789')
 assert.doesNotMatch(JSON.stringify(items),/private/)
})

function fixture() {
 const engine=new BrowserEngine('/tmp/unused')
 engine.requireReady=()=>{}
 const page=new EventEmitter();page.url=()=> 'https://www.douyin.com/'; page.screencast={stop:async()=>{}}
 const session={id:'one',context:{},lease:null,controller:null,ownerLogin:false,generation:1,active:'tab',tabs:new Map([['tab',page]]),titles:new Map(),operation:Promise.resolve(),streamJob:Promise.resolve(),observers:0}
 engine.sessions.set('one',session)
 return {engine,session,page}
}

test('takeover revokes queued automation and login fences prevent new execution',async()=>{
 const {engine,session,page}=fixture()
 const grant=engine.douyin.begin('one')
 let release;session.operation=new Promise(resolve=>release=resolve)
 const queued=engine.douyin.act('one',{token:grant.token,generation:1,op:'next'})
 engine.claim('one','owner');release()
 await assert.rejects(queued,{code:'owner_control'})
 assert.equal(page.listenerCount('response'),0);assert.equal(session.automation,null)
 engine.release('one',session.lease);session.ownerLogin=true
 assert.throws(()=>engine.douyin.begin('one'),{code:'owner_login'})
})

test('cancellation before begin finishes cannot resurrect the task; in-flight watch stops promptly',async()=>{
 const {engine,session}=fixture()
 const token='cancel-before-begin-1234'
 engine.douyin.end('one',token)
 assert.throws(()=>engine.douyin.begin('one',{runId:token}),{code:'automation_revoked'})
 const grant=engine.douyin.begin('one'),run=session.automation
 const waiting=engine.douyin.wait(session,run,30000)
 engine.douyin.end('one',grant.token)
 await assert.rejects(waiting,{code:'automation_revoked'})
 assert.equal(session.automation,null)
})

test('automation exposes only read/browse operations and only previously observed video IDs',async()=>{
 const {engine}=fixture(),grant=engine.douyin.begin('one')
 await assert.rejects(engine.douyin.act('one',{token:grant.token,generation:1,op:'comment',text:'no'}),{code:'invalid_action'})
 await assert.rejects(engine.douyin.act('one',{token:grant.token,generation:1,op:'open',id:'1234567890123456789'}),{code:'unobserved_video'})
 await assert.rejects(engine.douyin.act('one',{token:grant.token,generation:0,op:'next'}),{code:'stale_observation'})
 engine.douyin.end('one',grant.token)
})
