"""Protocol contracts and QQ voice delivery, without calling paid APIs or QQ."""
import base64
import io
import json
import wave
from unittest.mock import AsyncMock

import httpx
import pytest
from app.config import Settings,OllamaConfig
from app.providers import ProviderConfig,ProviderStore,generate,headers
from app.provider_catalog import CATALOG
from app.speech import (SpeechError,pcm_wav,to_wav,to_silk,synthesize,transcribe,fetch_audio,wants_voice)
from test_providers import client
from test_reply_segments import make_bot,event

WAV=pcm_wav(b'\0\0'*3200,16000)
AUDIO=base64.b64encode(WAV).decode()


def test_catalog_and_defaults():
    assert len(CATALOG)==35
    assert {p:sum(v['purpose']==p for v in CATALOG.values()) for p in ('chat','tts','stt')}=={'chat':18,'tts':7,'stt':4}
    for kind,info in CATALOG.items():
        p=ProviderConfig(type=kind)
        assert p.purpose==info['purpose'] and p.base_url==info['url']
    assert not Settings().speech.stt.enabled and not Settings().speech.tts.enabled
    with pytest.raises(ValueError):ProviderConfig(type='openai_tts',purpose='stt')
    with pytest.raises(ValueError):ProviderConfig(type='xfyun_stt',base_url='https://wrong.test')
    with pytest.raises(ValueError):ProviderConfig(app_id='bad\nheader')


def test_two_secrets_are_encrypted_bound_to_endpoint_and_never_public(tmp_path):
    s=ProviderStore(tmp_path);p=ProviderConfig(type='xfyun_stt',api_key='private-api-key',api_secret='private-signing-secret',app_id='app')
    pid=s.save(p)
    assert s.public(pid)['api_secret_set'] and not ({'api_key','api_secret'}&s.public(pid).keys())
    stored=s.db.execute('SELECT value FROM providers').fetchone()[0]
    assert 'private-api-key' not in stored and 'private-signing-secret' not in stored
    copy=s.get(pid).model_copy(update={'api_key':'','api_secret':''})
    assert s.prepare(copy,pid).api_secret==p.api_secret
    copy.app_id='other'
    assert not s.prepare(copy,pid).api_secret and not s.prepare(copy,pid).api_key
    copy.app_id='app';copy.clear_api_secret=True
    assert not s.prepare(copy,pid).api_secret and s.prepare(copy,pid).api_key
    s.checked(pid,p,'verified');assert s.public(pid)['check_state']=='verified'
    copy=s.get(pid);copy.default_model='changed';s.save(copy,pid)
    assert s.public(pid)['check_state']=='untested'
    s.close()


@pytest.mark.parametrize('text,expected',[
    ('用语音回复我',True),('给我发条语音吧',True),('想听你的声音',True),('/语音 说晚安',True),
    ('respond in voice please',True),('晚安',False),('我今天听了一条语音',False),
    ('不要发语音，打字就好',False),('不用语音回复',False),('你会识别语音吗',False),('我刚发了条语音',False),('“用语音回复”是什么意思',False),
])
def test_voice_requires_explicit_current_request(text,expected):assert wants_voice(text)==expected


@pytest.mark.asyncio
async def test_real_ffmpeg_silk_roundtrip_and_invalid_audio():
    silk=await to_silk(WAV)
    assert silk.startswith(b'\x02#!SILK_V3')
    restored=await to_wav(silk)
    with wave.open(io.BytesIO(restored)) as w:
        assert w.getframerate()==16000 and w.getnchannels()==1
        assert len(w.readframes(w.getnframes()))>0
    with pytest.raises(SpeechError):await to_wav(b'not audio')
    with pytest.raises(SpeechError):await to_wav(pcm_wav(b'\0\0'*16000*3,16000),seconds=1)


@pytest.mark.parametrize('kind', [k for k,v in CATALOG.items() if v['purpose']=='tts'])
@pytest.mark.asyncio
async def test_tts_protocols(kind):
    seen=[]
    def handler(request):
        seen.append(request)
        if kind in ('openai_tts','azure_tts'):return httpx.Response(200,content=WAV,headers={'content-type':'audio/wav'})
        if kind=='xiaomi_tts':data={'choices':[{'message':{'audio':{'data':AUDIO}}}]}
        elif kind=='minimax_tts':data={'data':{'audio':WAV.hex()},'base_resp':{'status_code':0}}
        elif kind=='dashscope_tts':data={'output':{'audio':{'data':AUDIO}}}
        elif kind=='gemini_tts':data={'candidates':[{'content':{'parts':[{'inlineData':{'data':AUDIO,'mimeType':'audio/wav'}}]}}]}
        else:return httpx.Response(200,text=json.dumps({'code':0,'data':AUDIO})+'\n'+json.dumps({'code':20000000}))
        return httpx.Response(200,json=data)
    p=ProviderConfig(type=kind,api_key='private-key',default_voice='zh-CN-XiaoxiaoNeural')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        result=await synthesize(c,p,'model','你好<&',speed=1.2)
    assert result.data==WAV
    r=seen[0];body=r.content.decode()
    if kind=='azure_tts':
        assert r.headers['Ocp-Apim-Subscription-Key']=='private-key' and '你好&lt;&amp;' in body
    elif kind=='volcengine_tts':
        assert r.headers['X-Api-Key']=='private-key' and r.headers['X-Api-Resource-Id']=='seed-tts-2.0'
        assert json.loads(body)['req_params']['speaker']=='zh-CN-XiaoxiaoNeural'
    elif kind=='xiaomi_tts':
        assert r.headers['api-key']=='private-key' and json.loads(body)['messages'][-1]['role']=='assistant'
    elif kind=='gemini_tts':assert r.headers['x-goog-api-key']=='private-key' and r.url.path.endswith(':generateContent')
    else:assert r.headers['Authorization']=='Bearer private-key'


@pytest.mark.asyncio
async def test_gemini_pcm_and_volc_incomplete_are_handled():
    def handler(r):return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'inlineData':{'data':base64.b64encode(b'\0\0'*240).decode(),'mimeType':'audio/L16;rate=24000'}}]}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        result=await synthesize(c,ProviderConfig(type='gemini_tts'),'gemini-2.5-flash-preview-tts','hello')
        assert result.data.startswith(b'RIFF')
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,text=json.dumps({'code':0,'data':AUDIO})))) as c:
        with pytest.raises(SpeechError):await synthesize(c,ProviderConfig(type='volcengine_tts',default_voice='speaker'),'seed','hello')


@pytest.mark.parametrize('kind',['xiaomi_stt','whisper_local_stt','whisper_api_stt'])
@pytest.mark.asyncio
async def test_stt_protocols(kind):
    seen=[]
    def handler(r):
        seen.append(r)
        return httpx.Response(200,json={'choices':[{'message':{'content':'  明天见  '}}]} if kind=='xiaomi_stt' else {'text':'  明天见  '})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        assert await transcribe(c,ProviderConfig(type=kind,api_key='key'),'asr',WAV,language='zh')=='明天见'
    r=seen[0]
    if kind=='xiaomi_stt':
        data=json.loads(r.content);assert data['messages'][0]['content'][0]['input_audio']['data'].startswith('data:audio/wav;base64,')
        assert data['asr_options']['language']=='zh' and r.headers['api-key']=='key'
    else:
        assert r.url.path.endswith('/audio/transcriptions') and b'filename="speech.wav"' in r.content
        assert b'name="language"' in r.content and r.headers['Authorization']=='Bearer key'


@pytest.mark.asyncio
async def test_media_url_constraints_redirects_and_no_credentials():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=WAV))) as c:
        for url in ('file:///etc/passwd','https://localhost/a','https://qq.com.attacker.test/a','https://user:pw@qq.com/a'):
            with pytest.raises(SpeechError):await fetch_audio(c,url,qq=True)
    def redirect(r):
        assert 'Authorization' not in r.headers
        return httpx.Response(302,headers={'location':'http://127.0.0.1/private'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(redirect)) as c:
        with pytest.raises(SpeechError):await fetch_audio(c,'https://grouptalk.c2c.qq.com/voice',qq=True)


@pytest.mark.parametrize('kind',[k for k,v in CATALOG.items() if v['purpose']=='chat' and k not in ('ollama','anthropic')])
@pytest.mark.asyncio
async def test_new_chat_transports(kind):
    p=ProviderConfig(type=kind,api_key='key')
    data={'choices':[{'message':{'content':'hi'}}]}
    if kind in ('openai_responses','deepseek_responses'):data={'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'hi'}]}]}
    if kind=='gemini_compatible':data={'candidates':[{'content':{'parts':[{'text':'hi'}]}}]}
    request=AsyncMock(return_value=data)
    result=await generate(request,p,OllamaConfig(model='deployment'),[{'role':'system','content':'persona'},{'role':'user','content':'hi','images':['image']}],1024)
    assert result['message']['content']=='hi'
    call=request.await_args
    assert ('private-key' not in str(call))
    if kind.startswith('xiaomi'):assert call.kwargs['headers']['api-key']=='key'
    elif kind=='azure_openai':assert call.kwargs['headers']['api-key']=='key'
    elif kind=='gemini_compatible':
        assert call.kwargs['json']['contents'][-1]['parts'][1]['inlineData']['data']=='image'
        assert call.kwargs['headers']['x-goog-api-key']=='key'
    else:assert call.kwargs['headers']['Authorization']=='Bearer key'


def test_assignment_api_preserves_other_settings_and_guard(client):
    types=client.get('/api/provider-types');assert types.status_code==200 and len(types.json()['types'])==35
    p=client.post('/api/providers',json={'type':'openai_tts','default_model':'tts','api_key':'private-key'}).json()
    before=client.get('/api/bots/default/settings').json()
    assignments=client.get('/api/bots/default/model-assignments').json();assignments.pop('state')
    assignments['speech']['tts'].update(provider_id=p['id'],model='tts',enabled=True)
    r=client.put('/api/bots/default/model-assignments',json=assignments)
    assert r.status_code==200,r.text
    after=client.get('/api/bots/default/settings').json()
    assert {k:v for k,v in before.items() if k!='speech'}=={k:v for k,v in after.items() if k!='speech'}
    assert client.delete('/api/providers/'+p['id']).status_code==409
    runtime=client.portal.call(client.app.state.manager.get,'default');runtime.bot.state='connected'
    assert client.put('/api/bots/default/model-assignments',json=assignments).status_code==409
    runtime.bot.state='stopped'
    assignments['speech']['stt'].update(provider_id=p['id'],model='wrong')
    assert client.put('/api/bots/default/model-assignments',json=assignments).status_code==400


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario',['success','synthesis_failure','unknown_receipt','not_requested'])
async def test_qq_voice_requested_confirmation_and_text_fallback(tmp_path,scenario):
    store,bot,text=make_bot(tmp_path);c=store.load()
    c.speech.tts.provider_id='a'*32;c.speech.tts.model='tts';c.speech.tts.enabled=True;store.save(c)
    bot.speech.speak=AsyncMock(return_value=b'fake-silk')
    if scenario=='synthesis_failure':bot.speech.speak.side_effect=SpeechError('合成暂不可用')
    if scenario=='unknown_receipt':bot.api.side_effect=[{'file_info':'media'},httpx.ReadTimeout('uncertain')]
    else:bot.api.side_effect=lambda *a,**kw:{'file_info':'media'} if a[1].endswith('/files') else {'id':'voice-receipt'}
    incoming=event();incoming['d']['content']='用语音回复我' if scenario!='not_requested' else '晚安'
    await bot.handle(incoming)
    calls=bot.api.await_args_list
    if scenario=='success':
        assert [c.kwargs['json'].get('msg_type') for c in calls]==[None,7]
        assert len(store.history('user:alice:alice',6))==2
        assert store.db.execute("SELECT source FROM chat_messages WHERE role='assistant'").fetchone()[0]=='voice'
    elif scenario=='unknown_receipt':
        assert len(calls)==2 and not store.history('user:alice:alice',6)
        assert not store.db.execute("SELECT id FROM chat_messages WHERE role='assistant'").fetchall()
    else:
        assert all(c.kwargs['json'].get('msg_type')==0 for c in calls)
        if scenario=='not_requested':bot.speech.speak.assert_not_awaited()
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
async def test_voice_incoming_transcribes_then_defaults_to_text(tmp_path):
    store,bot,text=make_bot(tmp_path)
    async def listen(a,c):
        bot.speech.last_transcripts.set([('m1','今天有点累')]);return '今天有点累'
    bot.speech.listen=AsyncMock(side_effect=listen)
    incoming=event();incoming['d']['content']='';incoming['d']['attachments']=[{'content_type':'audio/silk','url':'https://grouptalk.c2c.qq.com/a'}]
    await bot.handle(incoming)
    assert bot.speech.listen.await_count==1
    assert '今天有点累' in bot.generate.await_args.args[1][-1]['content']
    assert all(call.kwargs['json']['msg_type']==0 for call in bot.api.await_args_list)
    row=store.db.execute("SELECT content FROM chat_messages WHERE role='user'").fetchone()
    assert '今天有点累' in row[0]
    await bot.client.aclose();store.close()


def test_speech_probe_uses_stored_key_without_qq_delivery(client,monkeypatch):
    import app.speech as speech
    mock=AsyncMock(return_value=speech.SpeechAudio(WAV));monkeypatch.setattr(speech,'synthesize',mock)
    p=client.post('/api/providers',json={'type':'openai_tts','default_model':'tts','api_key':'private-probe-key'}).json()
    public={k:v for k,v in p.items() if k in ProviderConfig.model_fields}
    response=client.post('/api/providers/test-speech?provider_id='+p['id'],json={**public,'model':'tts','text':'试听'})
    assert response.status_code==200,response.text
    assert base64.b64decode(response.json()['audio']).startswith(b'RIFF')
    assert mock.await_args.args[1].api_key=='private-probe-key' and 'private-probe-key' not in response.text
    assert client.get('/api/providers').json()['providers'][-1]['check_state']=='verified'
    mock.side_effect=SpeechError('上游暂不可用')
    assert client.post('/api/providers/test-speech?provider_id='+p['id'],json={**public,'model':'tts'}).status_code==400
    assert client.get('/api/providers').json()['providers'][-1]['check_state']=='failed'
    runtime=client.portal.call(client.app.state.manager.get,'default')
    assert client.portal.call(lambda:runtime.store.db.execute('SELECT count(*) FROM chat_messages').fetchone()[0])==0


@pytest.mark.asyncio
async def test_xfyun_signed_socket_and_dynamic_replacement(monkeypatch):
    from urllib.parse import urlsplit,parse_qs
    import app.speech as speech
    from contextlib import asynccontextmanager
    sent=[];signed=[]
    class Socket:
        async def send(self,data):sent.append(json.loads(data))
        def __aiter__(self):return self.responses()
        async def responses(self):
            for sn,text,replace,status in [(0,'识别错',False,1),(1,'明天见',True,2)]:
                result={'sn':sn,'ws':[{'cw':[{'w':text}]}],**({'pgs':'rpl','rg':[0,0]} if replace else {})}
                yield json.dumps({'header':{'code':0,'status':status},'payload':{'result':{'text':base64.b64encode(json.dumps(result).encode()).decode()}}})
    @asynccontextmanager
    async def socket(url,**kwargs):
        signed.append(url);yield Socket()
    monkeypatch.setattr(speech,'connect',socket)
    p=ProviderConfig(type='xfyun_stt',api_key='api-key',api_secret='sign-secret',app_id='app')
    assert await speech.xfyun_transcribe(p,WAV,3)=='明天见'
    auth=base64.b64decode(parse_qs(urlsplit(signed[0]).query)['authorization'][0]).decode()
    assert 'api_key="api-key"' in auth and 'signature=' in auth and 'sign-secret' not in signed[0]


@pytest.mark.asyncio
async def test_napcat_voice_delivery_uses_record_segment(tmp_path):
    from app.napcat import normalize_event
    store,bot,text=make_bot(tmp_path);c=store.load();c.transport='napcat';c.napcat.self_id='12345';c.napcat.ws_url='ws://localhost:3001'
    c.speech.tts.provider_id='a'*32;c.speech.tts.model='tts';c.speech.tts.enabled=True;store.save(c)
    p=normalize_event({'post_type':'message','self_id':12345,'message_type':'private','message_id':10,'user_id':23456,'message':[{'type':'record','data':{'url':'https://grouptalk.c2c.qq.com/a'}}]},c)
    assert p['d']['attachments'][0]['content_type']=='audio/qq'
    bot.speech.speak=AsyncMock(return_value=b'silk')
    bot.napcat.send_voice=AsyncMock(return_value={'id':'voice'})
    incoming={'t':'C2C_MESSAGE_CREATE','d':{'id':'11','content':'用语音回复我','author':{'user_openid':'23456'}}}
    await bot.handle(incoming)
    bot.napcat.send_voice.assert_awaited_once()
    assert bot.napcat.send_voice.await_args.args[:3]==(False,'23456',b'silk')
    bot.api.assert_not_awaited()
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
async def test_voice_disabled_keeps_visible_caption_instead_of_discarding_it(tmp_path):
    store,bot,text=make_bot(tmp_path)
    incoming=event();incoming['d']['content']='今天下雨了';incoming['d']['attachments']=[{'content_type':'audio/silk','url':'https://grouptalk.c2c.qq.com/a'}]
    await bot.handle(incoming)
    assert bot.generate.await_count==1
    assert '今天下雨了' in bot.generate.await_args.args[1][-1]['content']
    assert '无法读取' in bot.generate.await_args.args[1][-1]['content']
    assert bot.api.await_args_list[0].kwargs['json']['content']!='这条语音我暂时听不了，发文字给我吧。'
    await bot.client.aclose();store.close()


def test_invalid_assignment_never_echoes_existing_secrets(client):
    embedding=client.post('/api/providers',json={'type':'openai_embedding'}).json()['id']
    runtime=client.portal.call(client.app.state.manager.get,'default')
    def setup():
        c=runtime.store.load();c.qq.secret='never-return-qq-secret';c.memory.enabled=True
        c.memory.embedding.provider_id=embedding;c.memory.embedding.model='embed';runtime.store.save(c)
    client.portal.call(setup)
    assignment=client.get('/api/bots/default/model-assignments').json();assignment.pop('state')
    assignment['embedding']={'provider_id':'','model':''}
    r=client.put('/api/bots/default/model-assignments',json=assignment)
    assert r.status_code==400 and 'never-return-qq-secret' not in r.text
    assert client.portal.call(lambda:runtime.store.load().qq.secret)=='never-return-qq-secret'
