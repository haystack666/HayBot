import io
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from app.bot import Bot
from app.store import Store
from app.providers import ProviderConfig, ProviderStore
from test_reply_segments import event
from test_providers import client


def catalog(tmp_path):
    from app.memes import MemeCatalog, MemeDescription
    library = MemeCatalog(tmp_path / 'library')
    image = io.BytesIO(); Image.new('RGB', (32, 32), 'blue').save(image, 'PNG')
    item = library.add(image.getvalue(), '开心', MemeDescription(visual='蓝色小鲸鱼开心地笑', text='好耶',
        scenarios=['对方分享开心的事时一起庆祝'], avoid_scenarios=['对方正在伤心'], emotions=['开心'], tone='庆祝'))
    return library, item


def test_catalog_edits_invalidate_vectors_and_delete_retains_archive_asset(tmp_path):
    from app.memes import MemeDescription
    library, item = catalog(tmp_path)
    library.save_vectors('model-a', [item], [[1., 0.]])
    assert library.index_status('model-a')['indexed'] == 1
    changed = library.update(item['id'], {'description': MemeDescription(visual='蓝色小鲸鱼手舞足蹈', text='好耶',
        scenarios=['庆祝好消息'], emotions=['高兴'], tone='欢快').model_dump()})
    assert changed['revision'] != item['revision']
    assert library.index_status('model-a')['indexed'] == 0
    assert library.index_status('model-b')['indexed'] == 0
    library.delete(item['id'])
    assert library.list()['total'] == 0
    assert library.image(item['id']).exists()
    library.close()


@pytest.mark.asyncio
async def test_embedding_ranking_cooldown_and_description_revision_fencing(tmp_path):
    from app.meme_service import MemeService
    library, item = catalog(tmp_path)
    providers = ProviderStore(tmp_path)
    pid = providers.save(ProviderConfig(type='openai_embedding', base_url='https://embed.test', default_model='embed-test'))
    store = Store(tmp_path / 'bot'); c = store.load(); c.qq.app_id='111'
    c.memes.enabled=True;c.memes.local_enabled=True; c.memes.chance=1; c.memes.embedding.provider_id=pid; c.memes.embedding.model='embed-test';store.save(c)
    bot=Bot(store, providers=providers, memes=library)
    bot.request=AsyncMock(return_value={'data':[{'index':0,'embedding':[1,0]}], 'usage':{'prompt_tokens':3}})
    await bot.memes.rebuild()
    found=await bot.memes.candidates('alice','今天好开心')
    assert [r['id'] for r in found]==[item['id']]
    assert bot.memes.current(found[0])
    bot.memes.sent('alice',found[0])
    assert await bot.memes.candidates('alice','今天好开心')==[]
    library.update(item['id'], {'enabled':False})
    assert not bot.memes.current(found[0])
    assert store.stats()['input_tokens']==6
    await bot.client.aclose();store.close();providers.close();library.close()


def test_meme_response_ignores_fabricated_ids_without_leaking_json():
    from app.meme_service import decode_reply
    assert decode_reply('{"reply":"好呀","meme_id":"invented","schedule_update":null}', []) == ('好呀',None,None)
    assert decode_reply('普通文字',[]) == ('普通文字',None,None)
    with pytest.raises(ValueError):decode_reply('{"reply":"断了',[])


def test_meme_api_requires_auth_and_valid_description(client):
    response=client.get('/api/bots/default/memes')
    assert response.status_code==200 and response.json()['total']==0
    image=io.BytesIO();Image.new('RGB',(16,16),'white').save(image,'PNG')
    response=client.post('/api/bots/default/memes/upload?name=测试图',content=image.getvalue(),headers={'Content-Type':'image/png'})
    assert response.status_code==201
    mid=response.json()['id']
    assert client.get(f'/api/bots/default/memes/{mid}/image').status_code==200
    assert client.patch(f'/api/bots/default/memes/{mid}',json={'description':{'visual':''}}).status_code==422
    assert client.get('/api/bots/default/memes/config').json()['enabled'] is False
    assert client.delete(f'/api/bots/default/memes/{mid}').status_code==200
    assert client.get('/api/bots/default/memes').json()['total']==0
    client.cookies.clear()
    assert client.get(f'/api/bots/default/memes/{mid}/image').status_code==401


def test_chat_preview_matches_static_image_sent_for_gif(client):
    raw=io.BytesIO();Image.new('RGB',(16,16),'red').save(raw,'GIF',save_all=True,append_images=[Image.new('RGB',(16,16),'blue')])
    response=client.post('/api/bots/default/memes/upload?name=动图',content=raw.getvalue())
    mid=response.json()['id'];preview=client.get(f'/api/bots/default/memes/{mid}/image?sent=true')
    assert preview.headers['content-type']=='image/png'
    with Image.open(io.BytesIO(preview.content)) as im:assert getattr(im,'n_frames',1)==1


async def delivery_bot(tmp_path):
    library,item=catalog(tmp_path);store=Store(tmp_path/'bot');c=store.load();c.qq.app_id='111';c.rules.cooldown=0
    c.rules.split_length=20;c.rules.split_delay=0;c.memes.enabled=True;c.memes.local_enabled=True;c.memes.chance=1;store.save(c)
    bot=Bot(store,memes=library);picked={**item,'selection_stamp':bot.memes.config_stamp()}
    bot.memes.candidates=AsyncMock(return_value=[picked])
    text='今天真开心，我们一起去吃点好吃的吧。吃完可以去公园逛一逛，看看小花和小鸟。晚上回家再看会儿电影，放松一下。'
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps({'reply':text,'meme_id':item['id']})}})
    calls=[]
    async def api(method,path,**kwargs):
        if kwargs.get('before_send') and not kwargs['before_send']():raise ValueError('stale')
        calls.append((path,kwargs['json']))
        return {'file_info':'file-sentinel','ttl':600} if path.endswith('/files') else {'id':'accepted'}
    bot.api=api
    return library,store,bot,item,text,calls


@pytest.mark.asyncio
async def test_meme_uses_single_llm_and_four_bubbles_with_archived_preview(tmp_path):
    library,store,bot,item,text,calls=await delivery_bot(tmp_path)
    await bot.handle(event())
    messages=[body for path,body in calls if path.endswith('/messages')]
    assert len(messages)==4 and [b['msg_seq'] for b in messages]==[1,2,3,4]
    assert messages[-1]['msg_type']==7 and messages[-1]['media']['file_info']=='file-sentinel'
    assert ''.join(b['content'] for b in messages[:-1])==text
    assert bot.generate.await_count==1 and store.stats()['sent']==4
    row=store.db.execute("SELECT * FROM chat_messages WHERE source='meme'").fetchone()
    assert row and row['meme_id']==item['id'] and row['reply_to']=='in:111:alice:m1'
    history=store.history('user:alice:alice',6)[-1]['content']
    assert text in history and '表情包' in history and 'file-sentinel' not in history
    await bot.client.aclose();store.close();library.close()


@pytest.mark.asyncio
async def test_optional_upload_failure_does_not_lose_text(tmp_path):
    library,store,bot,item,text,calls=await delivery_bot(tmp_path)
    original=bot.api
    async def api(method,path,**kw):
        if path.endswith('/files'):raise TimeoutError()
        return await original(method,path,**kw)
    bot.api=api
    assert await bot.handle(event()) is True
    assert ''.join(body['content'] for path,body in calls)==text
    assert store.history('user:alice:alice',6)[-1]['content']==text
    assert store.db.execute("SELECT COUNT(*) FROM chat_messages WHERE source='meme'").fetchone()[0]==0
    await bot.client.aclose();store.close();library.close()


@pytest.mark.asyncio
async def test_reset_after_text_prevents_meme_upload_and_history_resurrection(tmp_path):
    library,store,bot,item,text,calls=await delivery_bot(tmp_path)
    original=bot.api
    async def api(method,path,**kw):
        result=await original(method,path,**kw)
        if path.endswith('/messages'):
            sid=store.scopes.ensure('111','user','alice','alice')['id'];bot.memory.data.reset_scope(sid)
        return result
    bot.api=api;await bot.handle(event())
    assert len(calls)==1 and not store.history('user:alice:alice',6)
    await bot.client.aclose();store.close();library.close()


@pytest.mark.asyncio
async def test_reset_during_retrieval_stops_before_main_llm(tmp_path):
    library,store,bot,item,text,calls=await delivery_bot(tmp_path)
    async def candidates(sid,query):
        bot.memory.data.reset_scope(sid)
        return []
    bot.memes.candidates= candidates
    await bot.handle(event())
    assert not bot.generate.called and not calls
    await bot.client.aclose();store.close();library.close()


@pytest.mark.asyncio
async def test_cancel_during_optional_upload_preserves_confirmed_text(tmp_path):
    import asyncio
    library,store,bot,item,text,calls=await delivery_bot(tmp_path)
    async def upload(*args):raise asyncio.CancelledError()
    bot.memes.upload=upload
    with pytest.raises(asyncio.CancelledError):await bot.handle(event())
    assert store.history('user:alice:alice',6)[-1]['content'].replace('\n\n','')==text
    assert store.db.execute("SELECT COUNT(*) FROM chat_messages WHERE source='meme'").fetchone()[0]==0
    await bot.client.aclose();store.close();library.close()


def test_import_pack_validates_all_hashes_before_writing_and_is_idempotent(tmp_path):
    import hashlib
    from app.memes import MemeCatalog
    source=tmp_path/'pack';source.mkdir();descriptions=tmp_path/'descriptions';descriptions.mkdir()
    raw=io.BytesIO();Image.new('RGB',(20,20),'red').save(raw,'PNG');raw=raw.getvalue();sha=hashlib.sha256(raw).hexdigest()
    (source/'one.png').write_bytes(raw)
    (source/'source_index.json').write_text(json.dumps({'images':[{'path':'one.png','sha256':sha,'filename':'one.png','category':'happy'}]}))
    for name in ('LICENSE','README.md','manifest.json'):(source/name).write_text('test fixture')
    (descriptions/(sha+'.json')).write_text(json.dumps({'sha256':sha,'model':'deepseek-flash','generated_at':1,
        'description':{'visual':'红色背景测试图','scenarios':['庆祝好消息']}}))
    library=MemeCatalog(tmp_path/'library')
    (source/'one.png').write_bytes(b'bad')
    with pytest.raises(ValueError):library.import_pack(source,descriptions)
    assert library.list()['total']==0
    (source/'one.png').write_bytes(raw)
    assert library.import_pack(source,descriptions)==1 and library.import_pack(source,descriptions)==1
    assert library.list()['total']==1
    assert (tmp_path/'library/meme-sources/deepseek-fanart-v1/LICENSE').read_text()=='test fixture'
    library.close()


@pytest.mark.asyncio
async def test_group_meme_archive_belongs_only_to_triggering_member(tmp_path):
    library,store,bot,item,text,calls=await delivery_bot(tmp_path)
    c=store.load();c.qq.group_reply=True;store.save(c)
    # Selection stamp includes config, including AppID and meme policy only.
    await bot.handle(event(group=True))
    row=store.db.execute("SELECT * FROM chat_messages WHERE source='meme'").fetchone()
    assert row and row['reply_to']=='in:111:g1:m1'
    alice=store.scopes.ensure('111','group','g1','alice')['id'];bob=store.scopes.ensure('111','group','g1','bob')['id']
    assert store.scopes.source(alice,row['id']) and store.scopes.source(bob,row['id']) is None
    assert all('/groups/g1/' in path for path,_ in calls)
    await bot.client.aclose();store.close();library.close()


@pytest.mark.asyncio
async def test_explicit_meme_request_bypasses_chance_but_not_cooldown(tmp_path):
    library,item=catalog(tmp_path);providers=ProviderStore(tmp_path)
    pid=providers.save(ProviderConfig(type='openai_embedding',base_url='https://embed.test'))
    store=Store(tmp_path/'bot');c=store.load();c.qq.app_id='111';c.memes.enabled=True;c.memes.local_enabled=True;c.memes.chance=0
    c.memes.embedding.provider_id=pid;c.memes.embedding.model='embed-test';store.save(c)
    bot=Bot(store,providers=providers,memes=library)
    bot.request=AsyncMock(return_value={'data':[{'index':0,'embedding':[1,0]}]})
    await bot.memes.rebuild()
    assert await bot.memes.candidates('alice','今天很开心')==[]
    assert await bot.memes.candidates('alice','发个表情包\n今天很开心')==[]
    found=await bot.memes.candidates('alice','给我发个开心的表情包')
    assert [r['id'] for r in found]==[item['id']]
    bot.memes.sent('alice',found[0])
    assert await bot.memes.candidates('alice','发个表情包')==[]
    await bot.client.aclose();store.close();providers.close();library.close()


def test_explicit_request_detection_and_transport_instruction():
    from app.meme_service import requested
    for text in ('发个表情包','来张开心的表情包','给我一个表情包','能不能发表情包给我','send me a sticker'):
        assert requested(text)
    for text in ('别发表情包','不要给我发表情包','这张表情包真好看','发个表情包\n不用了'):
        assert not requested(text)


@pytest.mark.asyncio
async def test_plain_persona_reply_can_still_select_and_send_meme(tmp_path):
    library,store,bot,item,text,calls=await delivery_bot(tmp_path)
    async def generate(selection,messages,*args,**kwargs):
        if '表情包选择器' in messages[0]['content']:
            assert any(body.get('msg_type')==0 for path,body in calls)  # text already delivered
            return {'message':{'content':'{"choice":1}'},'prompt_eval_count':2,'eval_count':1}
        return {'message':{'content':text}}
    bot.generate=AsyncMock(side_effect=generate)
    await bot.handle(event())
    assert store.db.execute("SELECT COUNT(*) FROM chat_messages WHERE source='meme' AND status='sent'").fetchone()[0]==1
    assert bot.generate.await_count==2
    assert any(body.get('msg_type')==7 for path,body in calls)
    await bot.client.aclose();store.close();library.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('answer',['{"choice":0}','{"choice":999}','not-json'])
async def test_optional_selector_cannot_force_unmatched_or_invalid_meme(tmp_path,answer):
    library,store,bot,item,text,calls=await delivery_bot(tmp_path)
    bot.generate=AsyncMock(side_effect=[{'message':{'content':text}},{'message':{'content':answer}}])
    await bot.handle(event())
    assert not any(body.get('msg_type')==7 for path,body in calls)
    assert store.db.execute("SELECT COUNT(*) FROM chat_messages WHERE role='assistant' AND source='reply'").fetchone()[0]>0
    await bot.client.aclose();store.close();library.close()


@pytest.mark.asyncio
async def test_reset_while_fallback_selector_waits_cannot_send_image(tmp_path):
    library,store,bot,item,text,calls=await delivery_bot(tmp_path)
    async def generate(selection,messages,*args,**kwargs):
        if '表情包选择器' in messages[0]['content']:
            sid=store.scopes.list()[0]['id'];bot.memory.data.reset_scope(sid)
            return {'message':{'content':'{"choice":1}'}}
        return {'message':{'content':text}}
    bot.generate=generate
    await bot.handle(event())
    assert not any(body.get('msg_type')==7 for path,body in calls)
    assert store.history('user:alice:alice',6)==[]
    await bot.client.aclose();store.close();library.close()


@pytest.mark.asyncio
async def test_unconfirmed_text_stops_before_fallback_model(tmp_path):
    library,store,bot,item,text,calls=await delivery_bot(tmp_path)
    original=bot.api
    async def api(method,path,**kwargs):
        if kwargs.get('json',{}).get('msg_seq')==2:return {}
        return await original(method,path,**kwargs)
    bot.api=api;bot.generate=AsyncMock(return_value={'message':{'content':text}})
    await bot.handle(event())
    assert bot.generate.await_count==1
    assert not any(body.get('msg_type')==7 for path,body in calls)
    await bot.client.aclose();store.close();library.close()
