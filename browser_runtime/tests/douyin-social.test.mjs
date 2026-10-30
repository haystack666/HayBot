import test from 'node:test'
import assert from 'node:assert/strict'
import {profile,commentItems,editorTextDOM} from '../src/douyin-social.mjs'

test('empty Slate placeholder does not block writes but actual owner drafts remain protected',()=>{
 assert.equal(editorTextDOM({innerText:'\u200B\uFEFF\n'}),'')
 assert.equal(editorTextDOM({innerText:'\u200B主人的草稿\u200B'}),'主人的草稿')
 assert.equal(editorTextDOM({value:'真实评论'}),'真实评论')
})

test('profile identity and inbound comment parsing retain stable fields without credentials',()=>{
 assert.equal(profile({user:{nickname:'同名'}}),null)
 const p=profile({user:{sec_uid:'MS4_xxx',uid:'123',nickname:'人',unique_id:'handle',follower_status:0,cookie:'secret'}})
 assert.equal(p.follows_me,false);assert.equal(p.handle,'handle');assert.doesNotMatch(JSON.stringify(p),/secret/)
 const c=commentItems({comments:[{cid:'123456',aweme_id:'7654321',user:{sec_uid:'MS4_other',nickname:'粉丝'},text:'回复',reply_id:'root',reply_to_reply_id:'parent',token:'secret'}]})
 assert.equal(c[0].parent_id,'parent');assert.doesNotMatch(JSON.stringify(c),/secret/)
 assert.deepEqual(commentItems({comments:[{text:'没有稳定身份不能操作'}]}),[])
})

test('sticker downloads restrict redirects, response types and streamed size',async()=>{
 const {downloadSticker}=await import('../src/douyin-social.mjs')
 const image=Buffer.from('image-bytes')
 const good=async()=>new Response(image,{headers:{'content-type':'image/png'}})
 assert.deepEqual(await downloadSticker('https://p3.douyinpic.com/sticker.png',good),image)
 await assert.rejects(downloadSticker('http://p3.douyinpic.com/x',good))
 await assert.rejects(downloadSticker('https://douyinpic.com.attacker.invalid/x',good))
 await assert.rejects(downloadSticker('https://p3.douyinpic.com/x',async()=>new Response('',{status:302,headers:{location:'http://127.0.0.1/private'}})))
 await assert.rejects(downloadSticker('https://p3.douyinpic.com/x',async()=>new Response('html',{headers:{'content-type':'text/html'}})))
 await assert.rejects(downloadSticker('https://p3.douyinpic.com/x',async()=>new Response(new Uint8Array(5*1024*1024+1),{headers:{'content-type':'image/png'}})))
})
