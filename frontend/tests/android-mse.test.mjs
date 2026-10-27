import test from 'node:test'
import assert from 'node:assert/strict'
import JMuxer from 'jmuxer'
import { LiveVideoFeed, BufferedMseSink } from '../src/lib/android-mse.js'

const config = new Uint8Array([0,0,0,1,0x67,0x42,0xc0,0x29,0x8d,0x68,0x0b,0x40,0xa1,0xa4,0x20,0x20,0x20,0x20,0xf0,0x88,0x46,0xa0,0,0,0,1,0x68,0xce,0x01,0xa8,0x35,0xc8])
const picture = new Uint8Array([0,0,0,1,0x65,0xb8,0,4,5,0x9f,0xc6,0x3f])
test('first GOP is retained until asynchronous MSE sourceopen', () => {
 let options, received=[]
 class Muxer {constructor(o){options=o} feed(x){received.push(x)} destroy(){}}
 const sink=new BufferedMseSink(Muxer,{})
 const first={video:picture,duration:33};sink.feed(first)
 assert.equal(received.length,0)
 options.onReady();assert.deepEqual(received,[first])
 sink.feed(first);assert.equal(received.length,2)
 sink.destroy();options.onReady();assert.equal(received.length,2)
})
test('complete access unit primes real MSE muxer with SPS PPS and IDR in one feed', () => {
 const muxer = new JMuxer({mode:'video',fps:30})
 try {
  const feed = new LiveVideoFeed(()=>muxer)
  feed.push({config:true,payload:config})
  feed.push({keyframe:true,pts:1000,payload:picture})
  assert.equal(muxer.remuxController.tracks.video.readyToDecode,true)
  assert.ok(muxer.remuxController.tracks.video.mp4track.width>0)
 } finally {muxer.destroy()}
})
test('new parameter sets recreate playback and wait for keyframe without dropping dependencies', () => {
 const generations=[]
 const feed=new LiveVideoFeed(()=>{const m={frames:[],feed(x){this.frames.push(x)},destroy(){this.closed=true}};generations.push(m);return m})
 feed.push({config:true,payload:config})
 feed.push({keyframe:false,pts:1000,payload:picture});assert.equal(generations.length,0)
 feed.push({keyframe:true,pts:2000,payload:picture})
 for(let i=1;i<=20;i++)feed.push({keyframe:false,pts:2000+i*33000,payload:picture})
 assert.equal(generations[0].frames.length,21)
 feed.push({config:true,payload:config.slice()});assert.equal(generations[0].closed,undefined)
 const rotated=config.slice();rotated[8]^=1
 feed.push({config:true,payload:rotated});assert.equal(generations[0].closed,true)
 feed.push({keyframe:false,pts:800000,payload:picture});assert.equal(generations.length,1)
 feed.push({keyframe:true,pts:900000,payload:picture});assert.equal(generations.length,2)
 feed.destroy();assert.equal(generations[1].closed,true)
})
