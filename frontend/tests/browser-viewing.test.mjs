import test from 'node:test'
import assert from 'node:assert/strict'
import {viewingDefaults,viewingError} from '../src/lib/browser-viewing.mjs'

test('viewing numbers remain clearable but cannot be saved empty, fractional or inconsistent',()=>{
 assert.equal(viewingError(viewingDefaults),'')
 assert.match(viewingError({...viewingDefaults,segment_seconds:''}),/整数/)
 assert.match(viewingError({...viewingDefaults,segment_seconds:3.5}),/整数/)
 assert.match(viewingError({...viewingDefaults,skip_seconds:-1}),/整数/)
 assert.match(viewingError({...viewingDefaults,max_video_minutes:2}),/不能大于/)
 assert.equal(viewingError({...viewingDefaults,preview_enabled:false,max_video_minutes:1}),'')
})
