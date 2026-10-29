import test from 'node:test'
import assert from 'node:assert/strict'
import {profile,commentItems} from '../src/douyin-social.mjs'

test('profile identity and inbound comment parsing retain stable fields without credentials',()=>{
 assert.equal(profile({user:{nickname:'同名'}}),null)
 const p=profile({user:{sec_uid:'MS4_xxx',uid:'123',nickname:'人',unique_id:'handle',follower_status:0,cookie:'secret'}})
 assert.equal(p.follows_me,false);assert.equal(p.handle,'handle');assert.doesNotMatch(JSON.stringify(p),/secret/)
 const c=commentItems({comments:[{cid:'123456',aweme_id:'7654321',user:{sec_uid:'MS4_other',nickname:'粉丝'},text:'回复',reply_id:'root',reply_to_reply_id:'parent',token:'secret'}]})
 assert.equal(c[0].parent_id,'parent');assert.doesNotMatch(JSON.stringify(c),/secret/)
 assert.deepEqual(commentItems({comments:[{text:'没有稳定身份不能操作'}]}),[])
})
