"""Protocol contracts and QQ voice delivery, without calling paid APIs or QQ."""
import base64
import io
import json
import wave
from unittest.mock import AsyncMock

import httpx
import pytest
from app.config import Settings,OllamaConfig,SpeechConfig
from app.providers import ProviderConfig,ProviderStore,generate,headers
from app.provider_catalog import CATALOG
from app.speech import (SpeechError,pcm_wav,to_wav,to_silk,synthesize,transcribe,fetch_audio,wants_voice,decide_voice,split_voice_actions)
from test_providers import client
from test_reply_segments import make_bot,event

WAV=pcm_wav(b'\0\0'*3200,16000)
AUDIO=base64.b64encode(WAV).decode()


def test_catalog_and_defaults():
    assert len(CATALOG)==37
    assert {p:sum(v['purpose']==p for v in CATALOG.values()) for p in ('chat','tts','stt')}=={'chat':18,'tts':7,'stt':4}
    for kind,info in CATALOG.items():
        p=ProviderConfig(type=kind)
        assert p.purpose==info['purpose'] and p.base_url==info['url']
    speech=Settings().speech
    assert not speech.stt.enabled and not speech.tts.enabled
    assert speech.tts.scope=='private' and speech.tts.command_trigger and speech.tts.imperative_trigger
    assert not speech.tts.voice_follow_trigger and speech.tts.auto_probability==0 and speech.tts.max_reply_chars==600
    assert not speech.tts.separate_actions
    assert speech.stt.scope=='private_and_group' and speech.stt.auto_transcribe and speech.stt.max_audio_seconds==120
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


def test_legacy_speech_config_migrates_without_changing_request_behavior():
    speech=SpeechConfig.model_validate({'tts':{'provider_id':'','model':'','enabled':False,'voice':'','language':'auto','speed':1},
        'stt':{'provider_id':'','model':'','enabled':False,'voice':'','language':'zh','speed':1},
        'reply_mode':'on_request','max_reply_chars':420})
    assert speech.tts.scope=='private_and_group' and speech.tts.max_reply_chars==420
    assert speech.tts.command_trigger and speech.tts.imperative_trigger and not speech.tts.voice_follow_trigger
    assert speech.stt.language=='zh' and not hasattr(speech.stt,'voice') and not hasattr(speech.tts,'language')


def test_tts_trigger_precedence_probability_scope_and_cooldown():
    c=Settings().speech.tts;c.enabled=True;c.auto_probability=100
    assert decide_voice(c,'不要发语音，用文字说',event_key='1',now=1000).reason=='denied'
    assert decide_voice(c,'/语音 晚安',event_key='2',last_auto_voice=999,now=1000).reason=='command'
    assert decide_voice(c,'用语音回复我',event_key='3',last_auto_voice=999,now=1000).reason=='imperative'
    c.command_trigger=False;c.imperative_trigger=False;c.voice_follow_trigger=True
    assert decide_voice(c,'今天有点累',has_audio=True,event_key='4',last_auto_voice=999,now=1000).reason=='incoming_voice'
    c.voice_follow_trigger=False;c.scope='private'
    assert decide_voice(c,'晚安',group=True,event_key='5',now=1000).reason=='scope'
    assert decide_voice(c,'晚安',event_key='6',last_auto_voice=900,now=1000).reason=='cooldown'
    decision=decide_voice(c,'晚安',event_key='same-message',last_auto_voice=0,now=1000)
    assert decision.enabled and decision.reason=='automatic'
    assert decide_voice(c,'晚安',event_key='same-message',last_auto_voice=0,now=1000)==decision


@pytest.mark.parametrize('text,actions,spoken',[
    ('（拽住衣袖）怎么才回来？（抬头）等你好久了。','（拽住衣袖）\n（抬头）','怎么才回来？\n等你好久了。'),
    ('你好(smiles)呀（挥手）','(smiles)\n（挥手）','你好\n呀'),
    ('（笑着(轻轻挥手)）你好','（笑着(轻轻挥手)）','你好'),
    ('（笑）（挥手）','（笑）\n（挥手）',''),
    ('你好呀！','','你好呀！'),
    ('（笑）\n Hello there! (waves)\nGood night.','（笑）\n(waves)','Hello there!\nGood night.'),
])
def test_split_voice_actions(text,actions,spoken):
    assert split_voice_actions(text)==(actions,spoken)


@pytest.mark.parametrize('text',['（笑','笑）','(笑）你好','（笑)你好','（笑）你好（挥手','（(笑）)'])
def test_split_voice_actions_rejects_unbalanced_brackets(text):
    with pytest.raises(SpeechError):split_voice_actions(text)


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario',[
    'success','no_actions','actions_only','unbalanced','synthesis_failure','upload_failure',
    'action_unknown','action_timeout','voice_unknown','voice_timeout','disabled','text_only','changed',
])
async def test_separate_actions_delivery_and_safe_fallback(tmp_path,scenario):
    store,bot,_=make_bot(tmp_path);c=store.load()
    c.rules.split_enabled=False
    c.speech.tts.provider_id='a'*32;c.speech.tts.model='tts';c.speech.tts.enabled=True
    c.speech.tts.separate_actions=scenario!='disabled';store.save(c)
    content={'no_actions':'你好呀！','actions_only':'（挥手）','unbalanced':'（挥手你好'}.get(scenario,'（挥手）你好呀！(笑)等你好久了。')
    bot.generate.return_value={'message':{'content':content}}
    spoken='你好呀！\n等你好久了。'
    async def speak(text,config):
        assert not bot.api.await_count
        if scenario=='synthesis_failure':raise SpeechError('测试合成失败')
        if scenario=='changed':
            latest=store.load();latest.speech.tts.separate_actions=False;store.save(latest)
        return b'fake-silk'
    bot.speech.speak=AsyncMock(side_effect=speak)
    async def api(method,path,**kwargs):
        if path.endswith('/files'):
            assert not any(call.kwargs['json'].get('msg_type')==0 for call in bot.api.await_args_list)
            if scenario=='upload_failure':raise httpx.ConnectError('test upload failure')
            return {'file_info':'media'}
        voice=kwargs['json']['msg_type']==7
        if scenario==('voice_timeout' if voice else 'action_timeout'):raise httpx.ReadTimeout('test uncertain receipt')
        if scenario==('voice_unknown' if voice else 'action_unknown'):return {}
        return {'id':'voice' if voice else 'text'}
    bot.api.side_effect=api
    incoming=event();incoming['d']['content']='你好' if scenario=='text_only' else '用语音回复我'
    await bot.handle(incoming)
    calls=[call.kwargs['json'] for call in bot.api.await_args_list if not call.args[1].endswith('/files')]
    rows=store.db.execute("SELECT content,source FROM chat_messages WHERE role='assistant' ORDER BY id").fetchall()
    history=store.history('user:alice:alice',6)
    if scenario=='success':
        assert [call['msg_type'] for call in calls]==[0,7]
        assert [call['msg_seq'] for call in calls]==[1,2]
        assert calls[0]['content']=='（挥手）\n(笑)'
        assert [tuple(row) for row in rows]==[('（挥手）\n(笑)','reply'),(spoken,'voice')]
        assert history[-1]['content']==content
        assert '本轮采用动作文字与语音台词分离' in bot.generate.await_args.args[1][0]['content']
    elif scenario in ('voice_timeout','voice_unknown'):
        assert [call['msg_type'] for call in calls]==[0,7]
        assert len(rows)==1 and history[-1]['content']=='（挥手）\n(笑)'
    elif scenario in ('action_timeout','action_unknown'):
        assert len(calls)==1 and not rows and not history
    elif scenario=='changed':
        assert not calls and not rows and not history
    elif scenario in ('no_actions','disabled'):
        assert len(calls)==1 and calls[0]['msg_type']==7 and calls[0]['msg_seq']==1
        assert rows[0]['content']==content and history[-1]['content']==content
    else:
        assert len(calls)==1 and calls[0]['msg_type']==0 and calls[0]['content']==content
        assert history[-1]['content']==content
    if scenario not in ('actions_only','unbalanced','text_only'):
        expected=content if scenario in ('disabled','no_actions') else spoken
        assert bot.speech.speak.await_args.args[0]==expected
    else:bot.speech.speak.assert_not_awaited()
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('fail_voice',[False,True])
async def test_separate_actions_schedule_commits_only_after_voice_receipt(tmp_path,fail_voice):
    from app.bot import Bot
    from app.store import Store
    from test_schedule import configured,DAY,NOW
    from test_schedule_dialogue import UPDATE
    store=Store(tmp_path);c=configured(store)
    c.speech.tts.provider_id='a'*32;c.speech.tts.model='tts';c.speech.tts.enabled=True;c.speech.tts.separate_actions=True;store.save(c)
    bot=Bot(store);bot.schedule.clock=lambda:NOW
    sid=store.scopes.ensure(c.account_id,'user','alice','alice')['id'];day=bot.schedule.for_scope(sid)
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps(DAY,ensure_ascii=False)}})
    plan=await day.ensure()
    text='（拿起书包）好，我现在出发去你家复习。'
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps({'reply':text,'schedule_update':UPDATE},ensure_ascii=False)}})
    bot.speech.speak=AsyncMock(return_value=b'fake-silk')
    async def api(method,path,**kwargs):
        assert day.saved(c)['revision']==plan['revision']
        if path.endswith('/files'):return {'file_info':'media'}
        if kwargs['json']['msg_type']==7 and fail_voice:raise httpx.ReadTimeout('uncertain')
        return {'id':str(kwargs['json']['msg_seq'])}
    bot.api=AsyncMock(side_effect=api)
    incoming=event();incoming['d']['content']='用语音回复我';await bot.handle(incoming)
    assert (day.saved(c)['revision']!=plan['revision']) is (not fail_voice)
    assert len(day.dialogue.records()['items'])==int(not fail_voice)
    assert store.history('user:alice:alice',6)[-1]['content']==('（拿起书包）' if fail_voice else text)
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('group',[False,True])
async def test_separate_actions_over_napcat_socket(tmp_path,group):
    from app.bot import Bot
    from app.store import Store
    from test_napcat import configure,napcat_server
    async with napcat_server() as (url,calls,_):
        store=Store(tmp_path);c=configure(store,url);c.qq.group_reply=group
        c.speech.tts.provider_id='a'*32;c.speech.tts.model='tts';c.speech.tts.enabled=True
        c.speech.tts.separate_actions=True;c.speech.tts.scope='private_and_group';store.save(c)
        bot=Bot(store);await bot.napcat.start()
        text='（挥手）晚上好！(笑)'
        bot.generate=AsyncMock(return_value={'message':{'content':text}})
        bot.speech.speak=AsyncMock(return_value=b'fake-silk')
        incoming=event(user='20002',group=group);incoming['d']['content']='用语音回复我'
        if group:incoming['d']['group_openid']='30003'
        await bot.handle(incoming)
        sent=[call for call in calls if call['action'].startswith('send_')]
        assert len(sent)==2
        assert all(call['action']==('send_group_msg' if group else 'send_private_msg') for call in sent)
        assert sent[0]['params']['message']==[{'type':'text','data':{'text':'（挥手）\n(笑)'}}]
        assert sent[1]['params']['message'][0]['type']=='record'
        bot.speech.speak.assert_awaited_once()
        assert bot.speech.speak.await_args.args[0]=='晚上好！'
        assert store.db.execute("SELECT count(*) FROM chat_messages WHERE role='assistant'").fetchone()[0]==2
        await bot.napcat.close();await bot.client.aclose();store.close()


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
    types=client.get('/api/provider-types');assert types.status_code==200 and len(types.json()['types'])==37
    p=client.post('/api/providers',json={'type':'openai_tts','default_model':'tts','api_key':'private-key'}).json()
    before=client.get('/api/bots/default/settings').json()
    assignments=client.get('/api/bots/default/model-assignments').json();assignments.pop('state')
    assignments['speech']['tts'].update(provider_id=p['id'],model='tts',enabled=True,separate_actions=True)
    r=client.put('/api/bots/default/model-assignments',json=assignments)
    assert r.status_code==200,r.text
    after=client.get('/api/bots/default/settings').json()
    assert after['speech']['tts']['separate_actions'] is True
    assert client.get('/api/bots/default/model-assignments').json()['speech']['tts']['separate_actions'] is True
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
    async def listen(a,c,group=False):
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


@pytest.mark.asyncio
async def test_automatic_tts_cooldown_starts_only_after_confirmed_voice(tmp_path):
    store,bot,text=make_bot(tmp_path);c=store.load()
    c.speech.tts.provider_id='a'*32;c.speech.tts.model='tts';c.speech.tts.enabled=True
    c.speech.tts.command_trigger=False;c.speech.tts.imperative_trigger=False;c.speech.tts.auto_probability=100;c.speech.tts.auto_cooldown_seconds=300
    store.save(c);bot.speech.speak=AsyncMock(return_value=b'fake-silk')
    bot.api.side_effect=lambda *a,**kw:{'file_info':'media'} if a[1].endswith('/files') else {'id':'confirmed'}
    first=event('auto-1');first['d']['content']='晚安';await bot.handle(first)
    assert bot.speech.speak.await_count==1 and store.last_auto_voice(c.account_id,store.scopes.ensure(c.account_id,'user','alice','alice')['id'])>0
    bot.api.reset_mock();second=event('auto-2');second['d']['content']='再聊一句';await bot.handle(second)
    assert bot.speech.speak.await_count==1
    assert bot.api.await_args_list and all(call.kwargs['json'].get('msg_type')==0 for call in bot.api.await_args_list)
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
async def test_stt_ask_for_text_policy_does_not_guess_visible_caption(tmp_path):
    store,bot,text=make_bot(tmp_path);c=store.load();c.speech.stt.failure_policy='ask_for_text';store.save(c)
    incoming=event();incoming['d']['content']='今天下雨了';incoming['d']['attachments']=[{'content_type':'audio/silk','url':'https://grouptalk.c2c.qq.com/a'}]
    await bot.handle(incoming)
    bot.generate.assert_not_awaited()
    assert bot.api.await_args.kwargs['json']['content']=='这条语音我暂时听不了，发文字给我吧。'
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
    store,bot,text=make_bot(tmp_path);c=store.load()
    c.speech.tts.provider_id='a'*32;c.speech.tts.model='tts';c.speech.tts.enabled=True;c.speech.tts.voice_follow_trigger=True
    store.save(c);bot.speech.speak=AsyncMock(return_value=b'should-not-send')
    incoming=event();incoming['d']['content']='今天下雨了';incoming['d']['attachments']=[{'content_type':'audio/silk','url':'https://grouptalk.c2c.qq.com/a'}]
    await bot.handle(incoming)
    assert bot.generate.await_count==1
    assert '今天下雨了' in bot.generate.await_args.args[1][-1]['content']
    assert '无法读取' in bot.generate.await_args.args[1][-1]['content']
    assert bot.api.await_args_list[0].kwargs['json']['content']!='这条语音我暂时听不了，发文字给我吧。'
    bot.speech.speak.assert_not_awaited()
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
