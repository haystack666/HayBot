"""Semantic routing, actual-pixel grounding and receipt-ordered replies; no paid calls."""
import base64
import io
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image

from app.image_conversation import classify, recent_dialogue
from test_image_generation import setup_generation, picture
from test_reply_segments import event


def output(value):
    return {'message':{'content':json.dumps(value,ensure_ascii=False)},'prompt_eval_count':2,'eval_count':3}


def caption():
    return output({'requirements_met':True,'violations':[],'visual_description':'蓝色纯色画面，没有人物或海滩','reply':'这张的效果不太对，没拍出你想要的那种感觉。'})


@pytest.mark.asyncio
@pytest.mark.parametrize('transport',['qq_official','napcat'])
async def test_long_natural_request_sees_actual_picture_and_replies_only_after_receipt(tmp_path,monkeypatch,transport):
    store,bot,providers=setup_generation(tmp_path,napcat=transport=='napcat')
    request=event();request['d']['content']='宝宝，给我发张我们上次去海南，你穿洛丽塔的那个自拍，我当屏保'
    order=[];llm=[]
    async def model(selection,messages,tokens,**kwargs):
        if '后台即将开始创作' in messages[0]['content']:
            return {'message':{'content':'等我一下呀。'}}
        llm.append(messages)
        if len(llm)==1:
            assert request['d']['content'] in messages[-1]['content']
            return output({'action':'generate','prompt':'海南海边，角色穿洛丽塔的自拍，适合手机屏保'})
        assert messages[-1]['images']
        frame=Image.open(io.BytesIO(base64.b64decode(messages[-1]['images'][0])))
        assert frame.getpixel((0,0))[2]>200  # Actual blue pixels, not the requested beach.
        order.append('look_at_actual_picture')
        return caption()
    bot.generate=AsyncMock(side_effect=model)
    bot.memes.candidates=AsyncMock()
    async def generate(*args,**kwargs):
        order.append('generate_picture');return picture()
    monkeypatch.setattr('app.image_generation.generate_image',generate)
    async def api(method,path,**kwargs):
        body=kwargs['json']
        if path.endswith('/files'):return {'file_info':'media'}
        order.append('picture_receipt' if body['msg_type']==7 else 'waiting' if body['msg_seq']==1 else 'text_reply')
        return {'id':'confirmed'}
    bot.api.side_effect=api
    async def napcat(*args,**kwargs):order.append('picture_receipt');return {'id':'confirmed'}
    bot.napcat.send_picture=AsyncMock(side_effect=napcat)
    try:
        await bot.handle(request)
        assert order==['waiting','generate_picture','look_at_actual_picture','picture_receipt','text_reply']
        assert len(llm)==2 and not bot.memes.candidates.await_count
        rows=store.db.execute("SELECT content,source FROM chat_messages WHERE source IN ('generated_image','image_reply') ORDER BY id").fetchall()
        assert [r['source'] for r in rows]==['generated_image','image_reply']
        assert '蓝色纯色' in rows[0]['content'] and '效果不太对' in rows[1]['content']
        history=store.history('user:alice:alice',6)
        assert history[-2]['content']==request['d']['content']
        assert '蓝色纯色' in history[-1]['content'] and '效果不太对' in history[-1]['content']
    finally:
        await bot.client.aclose();providers.close();store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('text,action',[
    ('能给我看看你的自拍吗','generate'),
    ('换成蓝裙子，再来张侧脸','generate'),
    ('这张照片真好看','none'),
    ('不要再画了','none'),
    ('朋友说“给我发张自拍”，这句话怎么回','none'),
    ('你支持哪些图片模型','none'),
    ('再来一个','clarify'),
])
async def test_semantic_routing_uses_only_current_conversation_history(tmp_path,text,action):
    store,bot,providers=setup_generation(tmp_path)
    cfg=store.load();key='user:alice:alice';sid=store.scopes.ensure(cfg.account_id,'user','alice','alice')['id']
    store.save_history(key,[{'role':'user','content':'海边，洛丽塔自拍'},{'role':'assistant','content':'[已发送本轮生成的图片；画面：海边白裙自拍]'}],6)
    store.save_history('user:bob:bob',[{'role':'user','content':'other-user-secret'},{'role':'assistant','content':'private'}],6)
    decision={'action':action,'prompt':'海边蓝裙侧脸自拍' if action=='generate' else '',
              'clarification':'你想再来一张什么样的图片呀？' if action=='clarify' else ''}
    bot.generate.return_value=output(decision)
    try:
        result=await bot.image_generation.resolve_request(text,cfg,{'id':'new'},False,sid,key)
        assert (result.action if result else 'none')==action
        messages=bot.generate.call_args.args[1]
        assert 'other-user-secret' not in json.dumps(messages,ensure_ascii=False)
        assert '海边白裙自拍' in messages[-1]['content']
        cfg.rules.rounds=0
        assert recent_dialogue(store,key,cfg.rules.rounds)==[]
    finally:
        await bot.client.aclose();providers.close();store.close()


@pytest.mark.asyncio
async def test_clarification_does_not_generate_picture_or_send_meme(tmp_path,monkeypatch):
    store,bot,providers=setup_generation(tmp_path)
    bot.generate.return_value=output({'action':'clarify','clarification':'你想把哪张图片换成什么样呀？'})
    remote=AsyncMock();monkeypatch.setattr('app.image_generation.generate_image',remote)
    request=event();request['d']['content']='再来一个'
    try:
        await bot.handle(request)
        assert not remote.await_count
        assert bot.api.await_count==1 and bot.api.call_args.kwargs['json']['msg_type']==0
        assert store.db.execute('SELECT COUNT(*) FROM image_generation_jobs').fetchone()[0]==0
        assert '换成什么样' in store.history('user:alice:alice',6)[-1]['content']
    finally:
        await bot.client.aclose();providers.close();store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',['unknown_picture','text_failure','text_unknown','caption_failure','reset_while_looking'])
async def test_failure_does_not_fabricate_delivery_or_resend_picture(tmp_path,monkeypatch,failure):
    store,bot,providers=setup_generation(tmp_path)
    request=event();request['d']['content']='/画图 海边自拍'
    generated=AsyncMock(return_value=picture());monkeypatch.setattr('app.image_generation.generate_image',generated)
    async def model(*args,**kwargs):
        if failure=='caption_failure':raise ValueError('vision failed')
        if failure=='reset_while_looking':
            sid=store.scopes.ensure(store.load().account_id,'user','alice','alice')['id'];bot.memory.data.reset_scope(sid)
        return caption()
    bot.generate.side_effect=model
    sent=[]
    async def api(method,path,**kwargs):
        body=kwargs['json'];sent.append(body)
        if path.endswith('/files'):return {'file_info':'media'}
        if body['msg_type']==7:return {} if failure=='unknown_picture' else {'id':'picture-confirmed'}
        if failure=='text_failure' and body['msg_seq']==3:raise httpx.ReadTimeout('unknown')
        return {} if failure=='text_unknown' and body['msg_seq']==3 else {'id':'text-confirmed'}
    bot.api.side_effect=api
    monkeypatch.setattr('app.image_conversation.acknowledgement',AsyncMock(return_value='等一下呀。'))
    try:
        await bot.handle(request)
        assert generated.await_count==1
        pictures=[x for x in sent if x.get('msg_type')==7];texts=[x for x in sent if x.get('msg_type')==0 and x.get('msg_seq')==3]
        status=store.db.execute('SELECT status FROM image_generation_jobs').fetchone()[0]
        if failure=='unknown_picture':
            assert len(pictures)==1 and texts==[] and status=='unknown'
        elif failure in ('reset_while_looking','caption_failure'):
            assert not pictures and status==('cancelled' if failure=='reset_while_looking' else 'failed')
        else:
            assert len(pictures)==1 and len(texts)==1 and status=='sent'
            history=store.history('user:alice:alice',6)[-1]['content']
            if failure in ('text_failure','text_unknown'):assert '效果不太对' not in history
            if failure=='caption_failure':assert '画面细节尚未确认' in history and '蓝色' not in history
    finally:
        await bot.client.aclose();providers.close();store.close()


@pytest.fixture(autouse=True)
def isolated_composition_compiler(monkeypatch):
    # These tests isolate delivery/intent behavior; compiler contracts have their own suite.
    monkeypatch.setattr('app.image_constraints.compile_constraints',AsyncMock(return_value=''))
