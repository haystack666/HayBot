import test from 'node:test'
import assert from 'node:assert/strict'
import { parseLiveFrame, livePoint, splitAnnexB, avcDecoderConfig, avcAccessUnit } from '../src/lib/android-live.js'
test('parse timestamped scrcpy frames and reject invalid lengths', () => {
 const raw=new ArrayBuffer(16), view=new DataView(raw);view.setBigUint64(0,(1n<<62n)|1000000n);view.setUint32(8,4)
 const f=parseLiveFrame(raw);assert.equal(f.pts,1000000);assert.equal(f.keyframe,true);assert.equal(f.payload.length,4)
 assert.throws(()=>parseLiveFrame(new ArrayBuffer(2)))
 view.setUint32(8,5000000);assert.throws(()=>parseLiveFrame(raw))
})
test('touch mapping uses actual video dimensions including landscape', () => {
 assert.deepEqual(livePoint(370,210,{left:10,top:10,width:720,height:400},1280,720),{x:640,y:360,width:1280,height:720})
})
test('landscape video inside portrait element maps only its visible content', () => {
 const rect={left:0,top:0,width:360,height:640}
 assert.deepEqual(livePoint(180,230,rect,1280,720),{x:640,y:40,width:1280,height:720})
 assert.equal(livePoint(180,100,rect,1280,720),null)
})
test('splits scrcpy Annex-B SPS/PPS into an avcC decoder config', () => {
  const sps=[0x67,0x42,0xc0,0x29,0x8d,0x68,0x0b,0x40,0xa1,0xa4,0x20,0x20,0x20,0x20,0xf0,0x88,0x46,0xa0]
  const pps=[0x68,0xce,0x01,0xa8,0x35,0xc8]
  const annexB=new Uint8Array([0,0,0,1,...sps,0,0,0,1,...pps])
  const nalus=splitAnnexB(annexB)
  assert.deepEqual(nalus.map(nalu=>nalu.length),[18,6])
  const config=avcDecoderConfig(nalus)
  assert.equal(config.codec,'avc1.42c029')
  assert.equal(config.description.length,35)
  assert.deepEqual([...config.description.slice(0,6)],[1,0x42,0xc0,0x29,0xff,0xe1])
  assert.equal(config.description[8+sps.length],1)
  assert.deepEqual([...config.description.slice(9+sps.length,11+sps.length)],[0,6])
  assert.equal(avcDecoderConfig(nalus.slice(0,1)),null)
})
test('length-prefixes slice NALs for WebCodecs and drops parameter sets', () => {
  const annexB=new Uint8Array([0,0,0,1,0x65,0x88,0x84,0x01,0,0,1,0x61,0x21])
  const nalus=splitAnnexB(annexB)
  assert.deepEqual([...avcAccessUnit(nalus)],[0,0,0,4,0x65,0x88,0x84,0x01,0,0,0,2,0x61,0x21])
  assert.equal(avcAccessUnit([new Uint8Array([0x67,0x42])]),null)
})
