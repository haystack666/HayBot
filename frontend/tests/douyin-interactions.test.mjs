import test from 'node:test'
import assert from 'node:assert/strict'
import {interactionDefaults as defaults,interactionError} from '../src/lib/douyin-interactions.mjs'

test('interaction configuration validates quotas, owner identity and duplicate whitelist entries',()=>{
 assert.equal(interactionError(defaults),'')
 assert.equal(defaults.dm_monitor_mode,'task')
 assert.match(interactionError({...defaults,dm_monitor_mode:'poll'}),/私信监控方式/)
 assert.equal(interactionError({...defaults,dm_monitor_mode:'always'}),'')
 assert.match(interactionError({...defaults,comment_daily_limit:''}),/整数/)
 assert.match(interactionError({...defaults,other_probability:101}),/整数/)
 assert.match(interactionError({...defaults,shares_enabled:true}),/Owner/)
 assert.match(interactionError({...defaults,owner:{handle:'who',nickname:''}}),/同时/)
 assert.match(interactionError({...defaults,whitelist:[{handle:'a',nickname:'一'},{handle:'a',nickname:'二'}]}),/重复/)
 assert.equal(interactionError({...defaults,shares_enabled:true,owner:{handle:'owner_123',nickname:'主人'}}),'')
})
