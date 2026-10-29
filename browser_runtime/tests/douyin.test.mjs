import test from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { BrowserEngine } from '../src/engine.mjs'
import { contentItems } from '../src/douyin.mjs'

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
