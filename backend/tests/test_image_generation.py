"""No paid requests: image contracts, account isolation, quotas and QQ receipts."""
import base64
import io
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image

from app.config import ImageGenerationConfig
from app.image_generation import (ImageGenerationError, checked_picture, generate_image, image_request)
from app.providers import ProviderConfig, ProviderStore
from test_providers import client, body
from test_reply_segments import make_bot, event


def picture():
    out=io.BytesIO();Image.new('RGB',(64,96),'blue').save(out,'PNG');return out.getvalue()


@pytest.mark.parametrize('text,expected',[
    ('帮我画一张海边照片',True),('给我发张你的自拍',True),('生成一张穿白色连衣裙的角色图',True),
    ('画个可爱的小猫',True),('请生成一张风景图',True),('create a picture of a cat',True),
    ('我今天画了一张图',False),('你支持生图吗',False),('怎么配置生图 API',False),
    ('“帮我画一张猫”是什么意思',False),('不要生成图片',False),('帮我画一张猫，但不用画了',False),
    ('不用给我发自拍',False),('draw a picture of a cat, do not generate it',False),
    ('这张照片真好看',False),('你能不能生成一张照片',False),
])
def test_explicit_current_request(text,expected):
    assert (image_request(text) is not None)==expected


def test_command_and_disabled_natural():
    assert image_request('/画图 海边照片',False)=='海边照片'
    assert image_request('/生图')==''
    assert image_request('帮我画一张猫',False) is None
    assert image_request('/画图教程') is None
    assert image_request('/画图 海边照片\n不用画了') is None


def test_config_and_image_validation():
    assert not ImageGenerationConfig().enabled and ImageGenerationConfig().require_reference
    for values in ({'enabled':True},{'provider_id':'a'*32},{'timeout':181},{'daily_limit':0},{'aspect':'bad'}):
        with pytest.raises(ValueError):ImageGenerationConfig(**values)
    raw,w,h=checked_picture(picture(),reference=True)
    assert (w,h)==(64,96) and raw.startswith(b'\xff\xd8')
    for raw in (b'bad',b'x'*(6*1024*1024+1)):
        with pytest.raises(ImageGenerationError):checked_picture(raw,reference=True)
    out=io.BytesIO();Image.new('RGB',(10,10)).save(out,'PNG')
    with pytest.raises(ImageGenerationError):checked_picture(out.getvalue())


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['openai_image','volcengine_image'])
@pytest.mark.parametrize('references',[False,True])
async def test_vendor_payload_references_and_real_image(kind,references):
    calls=[]
    async def remote(request):
        calls.append(request);assert request.headers['authorization']=='Bearer key-sentinel'
        payload=await request.aread()
        if kind=='openai_image' and references:
            assert request.url.path.endswith('/images/edits')
            assert payload.count(b'name="image[]"')==3 and b'image/jpeg' in payload
            assert b'name="size"\r\n\r\n1024x1536' in payload
        else:
            assert request.url.path.endswith('/images/generations')
            data=json.loads(payload);assert data['prompt']=='style and scene'
            if kind=='volcengine_image':
                assert data['response_format']=='b64_json' and data['size']=='1440x2560' and data['watermark'] is True
                assert len(data.get('image',[]))==(3 if references else 0)
                if references: assert all(x.startswith('data:image/jpeg;base64,') for x in data['image'])
            else: assert data['n']==1 and data['size']=='1024x1536' and 'response_format' not in data
        return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(picture()).decode()}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as client:
        image=await generate_image(client,ProviderConfig(type=kind,api_key='key-sentinel'),'image-model','style and scene',
            [checked_picture(picture())[0]]*3 if references else [],aspect='portrait')
    assert image.startswith(b'\xff\xd8') and len(calls)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('response',[
    {'data':[{'url':'http://127.0.0.1/private'}]}, {'data':[{'b64_json':'invalid'}]},
    {'data':[]}, {'error':{'message':'secret-sentinel'}}, {'data':[{'b64_json':base64.b64encode(b'bad').decode()}]},
])
async def test_reject_remote_urls_invalid_images_and_unsafe_errors(response):
    calls=[]
    def remote(request):calls.append(request);return httpx.Response(200,json=response)
    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as client:
        with pytest.raises(ImageGenerationError) as error:
            await generate_image(client,ProviderConfig(type='openai_image',api_key='key'),'image','cat')
    assert 'secret-sentinel' not in str(error.value) and len(calls)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[401,429,500,302])
async def test_vendor_failure_never_retries_or_exposes_remote_body(status):
    calls=[]
    def remote(request):calls.append(request);return httpx.Response(status,json={'error':'secret-sentinel'},headers={'Location':'http://127.0.0.1/private'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as client:
        with pytest.raises(ImageGenerationError) as error:
            await generate_image(client,ProviderConfig(type='volcengine_image',api_key='key'),'image','cat')
    assert len(calls)==1 and 'secret-sentinel' not in str(error.value)


@pytest.mark.asyncio
async def test_timeout_is_single_attempt_and_warns_about_charge():
    calls=[]
    def remote(request):calls.append(request);raise httpx.ReadTimeout('private-upstream-sentinel')
    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as client:
        with pytest.raises(ImageGenerationError) as error:
            await generate_image(client,ProviderConfig(type='openai_image',api_key='key'),'image','cat')
    assert len(calls)==1 and '计费' in str(error.value) and 'private-upstream-sentinel' not in str(error.value)


def setup_generation(tmp_path,group=False,napcat=False):
    store,bot,_=make_bot(tmp_path,group)
    providers=ProviderStore(tmp_path)
    pid=providers.save(ProviderConfig(type='openai_image',api_key='key',default_model='image-model'))
    bot.providers=providers
    c=store.load();c.image_generation=ImageGenerationConfig(provider_id=pid,model='image-model',base_prompt='日光摄影',enabled=True,scope='private_and_group')
    if napcat:c.transport='napcat';c.napcat.self_id='123456'
    store.save(c)
    bot.image_generation.add_reference('sheet',checked_picture(picture(),reference=True))
    return store,bot,providers


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario',['success','unknown','timeout','upload_failure','changed','reset','duplicate','group','napcat','cancel'])
async def test_qq_image_chain_confirmed_only_and_no_second_generation(tmp_path,monkeypatch,scenario):
    store,bot,providers=setup_generation(tmp_path,group=scenario=='group',napcat=scenario=='napcat')
    request=event(group=scenario=='group');request['d']['content']='/画图 给我发张你的自拍'
    calls=[]
    bot.generate.return_value={'message':{'content':json.dumps({'visual_description':'蓝色纯色画面','reply':'这张发给你啦，看看喜不喜欢。'},ensure_ascii=False)}}
    async def generate(*args,**kwargs):
        calls.append(args)
        assert '日光摄影' in args[3] and '三视图合图' in args[3] and len(args[4])==1
        if scenario=='changed':
            c=store.load();c.image_generation.enabled=False;store.save(c)
        if scenario=='reset':
            sid=store.scopes.ensure(store.load().account_id,'user','alice','alice')['id'];bot.memory.data.reset_scope(sid)
        if scenario=='cancel':raise __import__('asyncio').CancelledError
        return checked_picture(picture())[0]
    monkeypatch.setattr('app.image_generation.generate_image',generate)
    async def api(method,path,**kwargs):
        if path.endswith('/files'):
            assert kwargs['json']['srv_send_msg'] is False
            assert base64.b64decode(kwargs['json']['file_data']).startswith(b'\xff\xd8')
            if scenario=='upload_failure':return {}
            return {'file_info':'media'}
        if scenario=='timeout':raise httpx.ReadTimeout('uncertain')
        return {} if scenario=='unknown' else {'id':'sent'}
    bot.api.side_effect=api
    bot.napcat.send_picture=AsyncMock(return_value={'id':'sent'})
    if scenario=='cancel':
        with pytest.raises(__import__('asyncio').CancelledError):await bot.handle(request)
    else:await bot.handle(request)
    if scenario=='duplicate':await bot.handle(request)
    assert len(calls)==1
    assert bot.generate.await_count==1+int(scenario not in ('changed','reset','cancel'))
    rows=store.db.execute("SELECT * FROM chat_messages WHERE role='assistant' AND source='generated_image'").fetchall()
    sent=scenario in ('success','duplicate','group','napcat')
    assert len(rows)==int(sent)
    if sent:
        assert rows[0]['attachment_count']==1 and rows[0]['status']=='sent' and store.stats()['sent']==3
        assert store.history('group:g1:alice' if scenario=='group' else 'user:alice:alice',6)[-1]['content'].startswith('[已发送')
    if scenario=='napcat':assert bot.napcat.send_picture.await_count==1 and bot.api.await_count==2
    status=store.db.execute('SELECT status FROM image_generation_jobs').fetchone()[0]
    assert status==('sent' if sent else 'unknown' if scenario in ('unknown','timeout') else 'failed' if scenario=='upload_failure' else 'cancelled')
    if scenario in ('unknown','timeout'):assert len(bot.api.await_args_list)==3
    assert not bot.pending
    await bot.client.aclose();providers.close();store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('reason',['disabled','reference','scope','quota','cooldown','busy'])
async def test_no_paid_call_when_not_allowed(tmp_path,monkeypatch,reason):
    store,bot,providers=setup_generation(tmp_path,group=reason=='scope');c=store.load()
    if reason=='disabled':c.image_generation.enabled=False
    if reason=='scope':c.image_generation.scope='private'
    if reason=='reference':bot.image_generation.remove_reference(bot.image_generation.references()[0]['id'])
    if reason=='quota':c.image_generation.daily_limit=1
    store.save(c)
    if reason in ('quota','cooldown'):
        sid=store.scopes.ensure(c.account_id,'user','alice','alice')['id'];bot.image_generation.reserve(c,sid,'earlier')
    if reason=='busy':await bot.image_generation.lock.acquire()
    generate=AsyncMock();monkeypatch.setattr('app.image_generation.generate_image',generate)
    request=event(group=reason=='scope');request['d']['content']='/画图 海边照片'
    await bot.handle(request)
    assert not generate.await_count and not bot.generate.await_count
    assert bot.api.await_args.kwargs['json']['msg_type']==0
    if reason=='busy':bot.image_generation.lock.release()
    await bot.client.aclose();providers.close();store.close()


@pytest.mark.asyncio
async def test_persistent_source_dedup_and_cross_conversation_user_quota(tmp_path):
    store,bot,providers=setup_generation(tmp_path)
    c=store.load();c.image_generation.cooldown_seconds=0;c.image_generation.user_daily_limit=1;store.save(c)
    first=store.scopes.ensure(c.account_id,'user','alice','alice')['id']
    group=store.scopes.ensure(c.account_id,'group','group-a','alice')['id']
    second=store.scopes.ensure(c.account_id,'user','bob','bob')['id']
    jid=bot.image_generation.reserve(c,first,'old-batch',[123,124])
    assert jid
    assert bot.image_generation.reserve(c,first,'new-batch-with-new-tail',[123,124,125]) is None
    with pytest.raises(ImageGenerationError,match='上限'):bot.image_generation.reserve(c,group,'different-message',[126])
    assert bot.image_generation.reserve(c,second,'new-user',[127])
    from app.image_generation import ImageGenerationService
    service=ImageGenerationService(bot)
    assert store.db.execute('SELECT status FROM image_generation_jobs WHERE id=?',(jid,)).fetchone()[0]=='unknown'
    assert service.reserve(c,first,'recovered-batch',[123]) is None
    await bot.client.aclose();providers.close();store.close()


def test_reference_api_auth_account_isolation_locks_and_model_assignments(client):
    c=body(client);c['qq']['app_id']='111'
    assert client.put('/api/bots/default/settings',json=c).status_code==200
    raw={'slot':'sheet','image':base64.b64encode(picture()).decode()}
    result=client.post('/api/bots/default/image-generation/references',json=raw)
    assert result.status_code==200
    rid=result.json()['references'][0]['id']
    image=client.get(f'/api/bots/default/image-generation/references/{rid}')
    assert image.status_code==200 and image.content.startswith(b'\xff\xd8')
    assert image.headers['cache-control']=='no-store'
    other=client.post('/api/bots',json={'name':'other'}).json()['id']
    assert client.get(f'/api/bots/{other}/image-generation/references/{rid}').status_code==400
    assert client.post('/api/bots/default/image-generation/references',json={**raw,'slot':'front'}).status_code==400
    app=client.app.state.manager.runtimes['default'];app.bot.state='connected'
    assert client.delete(f'/api/bots/default/image-generation/references/{rid}').status_code==409
    app.bot.state='stopped'
    for kind in ('openai_image','volcengine_image'):
        p=client.post('/api/providers',json={'type':kind,'api_key':'key','default_model':'image-model'}).json()
        assert p['purpose']=='image' and 'api_key' not in p
        assignments=client.get('/api/bots/default/model-assignments').json();assignments.pop('state')
        assignments['image_generation'].update(provider_id=p['id'],model='image-model')
        assert client.put('/api/bots/default/model-assignments',json=assignments).status_code==200
        assert client.delete('/api/providers/'+p['id']).status_code==409
    c=body(client);c['qq']['app_id']='222';assert client.put('/api/bots/default/settings',json=c).status_code==200
    assert not client.get('/api/bots/default/image-generation').json()['references']
    assert client.get(f'/api/bots/default/image-generation/references/{rid}').status_code==400
    client.post('/api/logout')
    assert client.get(f'/api/bots/default/image-generation/references/{rid}').status_code==401


def test_image_probe_reuses_encrypted_key_without_sending_qq(client,monkeypatch):
    async def generate(http,provider,model,prompt,*args,**kwargs):
        assert provider.api_key=='key-sentinel' and model=='image-model'
        return checked_picture(picture())[0]
    monkeypatch.setattr('app.image_generation.generate_image',generate)
    p=client.post('/api/providers',json={'type':'openai_image','api_key':'key-sentinel'}).json()
    payload={'type':'openai_image','api_key':'','model':'image-model','prompt':'cat'}
    result=client.post('/api/providers/test-image?provider_id='+p['id'],json=payload)
    assert result.status_code==200 and result.json()['image'] and 'key-sentinel' not in result.text
    assert client.get('/api/providers').json()['providers'][-1]['check_state']=='verified'
    result=client.post('/api/providers/test-generation?provider_id='+p['id'],json={'type':'openai_image','model':'image-model'})
    assert result.status_code==400
