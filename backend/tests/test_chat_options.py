"""Bot-local enhancement switches, metadata boundaries and QQ typewriter receipts."""
from datetime import datetime,timezone
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.chat_options import user_prompt_suffix,explanation_instruction
from app.config import Settings
from app.chat_stream import supports_stream
from app.providers import ProviderHTTPError
from test_providers import client
from test_reply_segments import make_bot,event


def test_defaults_and_trusted_metadata_timezone():
    c=Settings();data=event()['d'];now=datetime(2026,10,30,1,2,3,tzinfo=timezone.utc)
    assert not any(getattr(c.rules,key) for key in ('show_thinking','stream_output','user_identification','real_world_time'))
    assert user_prompt_suffix(c,data,now=now)=='' and explanation_instruction(c.rules)==''
    c.rules.user_identification=True
    suffix=user_prompt_suffix(c,data,now=now)
    assert json.loads(suffix.split('\n')[-1])=={'sender_id':'alice','identifier_type':'qq_openid'}
    c.rules.real_world_time=True
    meta=json.loads(user_prompt_suffix(c,data,now=now).split('\n')[-1])
    assert meta['current_time']=='2026-10-30T09:02:03+08:00' and meta['weekday']=='星期五'
    c.rules.user_identification=False;c.schedule.timezone='America/New_York'
    meta=json.loads(user_prompt_suffix(c,data,now=now).split('\n')[-1])
    assert 'sender_id' not in meta and meta['current_time']=='2026-10-29T21:02:03-04:00'
    c.transport='napcat';c.rules.user_identification=True
    assert json.loads(user_prompt_suffix(c,event(group=True)['d'],True,now=now).split('\n')[-1])['identifier_type']=='qq_number'


def test_switches_roundtrip_without_resetting_history(client):
    runtime=client.portal.call(client.app.state.manager.get,'default')
    client.portal.call(runtime.store.save_history,'user:alice:alice',[{'role':'user','content':'keep'}],6)
    settings=client.get('/api/bots/default/settings').json();settings['qq'].pop('secret_set')
    settings['rules'].update(show_thinking=True,stream_output=True,user_identification=True,real_world_time=True)
    response=client.put('/api/bots/default/settings',json=settings)
    assert response.status_code==200,response.text
    assert all(response.json()['rules'][key] for key in ('show_thinking','stream_output','user_identification','real_world_time'))
    assert client.portal.call(runtime.store.history,'user:alice:alice',6)


@pytest.mark.asyncio
@pytest.mark.parametrize('group',[False,True])
@pytest.mark.parametrize('enabled',[False,True])
async def test_prompt_enhancements_are_current_turn_only(tmp_path,group,enabled):
    store,bot,text=make_bot(tmp_path,group);c=store.load()
    c.rules.user_identification=enabled;c.rules.real_world_time=enabled;c.rules.show_thinking=enabled
    store.save(c);await bot.handle(event(group=group))
    messages=bot.generate.await_args.args[1]
    assert ('[后台附加的本轮信息' in messages[-1]['content']) is enabled
    assert ('[可公开的思考摘要]' in messages[0]['content']) is enabled
    if enabled:
        metadata=json.loads(messages[-1]['content'].split('\n')[-1])
        assert metadata['sender_id']=='alice' and metadata['timezone']=='Asia/Shanghai'
        assert '不要输出隐藏思维链' in messages[0]['content']
    key='group:g1:alice' if group else 'user:alice:alice'
    assert store.history(key,6)[0]['content']==event()['d']['content']
    assert not any('[后台附加的本轮信息' in row['content'] for row in store.db.execute('SELECT content FROM chat_messages'))
    assert store.history(key,6)[-1]['content']==text
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario',['success','short','first_unknown','later_unknown','timeout','changed','reset','voice','unsupported','forbidden_after_start'])
async def test_typewriter_one_bubble_receipt_and_cancellation(tmp_path,monkeypatch,scenario):
    store,bot,text=make_bot(tmp_path);c=store.load();c.rules.stream_output=True;store.save(c)
    monkeypatch.setattr('app.chat_stream.asyncio.sleep',AsyncMock())
    if scenario=='short':text='你好';bot.generate.return_value={'message':{'content':text}}
    if scenario=='voice':
        c.speech.tts.provider_id='a'*32;c.speech.tts.model='tts';c.speech.tts.enabled=True;store.save(c)
        bot.speech.speak=AsyncMock(return_value=b'voice')
    async def api(method,path,**kwargs):
        if not path.endswith('/stream_messages'):
            return {'file_info':'media'} if path.endswith('/files') else {'id':'voice'}
        body=kwargs['json'];index=body['index']
        if scenario=='unsupported':raise ProviderHTTPError(403)
        if scenario=='first_unknown':return {}
        if index==1:
            if scenario=='later_unknown':return {}
            if scenario=='timeout':raise httpx.ReadTimeout('uncertain')
            if scenario=='forbidden_after_start':raise ProviderHTTPError(403)
        if index==0:
            if scenario=='changed':
                latest=store.load();latest.rules.stream_output=False;store.save(latest)
            if scenario=='reset':
                    scope=store.scopes.ensure(c.account_id,'user','alice','alice')['id'];bot.memory.data.invalidate(scope)
        return {'id':'stream-one'}
    bot.api.side_effect=api
    incoming=event();incoming['d']['content']='用语音回复我' if scenario=='voice' else '你好'
    await bot.handle(incoming)
    calls=bot.api.await_args_list
    rows=store.db.execute("SELECT content FROM chat_messages WHERE role='assistant'").fetchall()
    history=store.history('user:alice:alice',6)
    if scenario=='voice':
        assert not any(call.args[1].endswith('/stream_messages') for call in calls)
    elif scenario=='unsupported':
        assert calls[0].args[1].endswith('/stream_messages')
        assert all(call.args[1].endswith('/messages') for call in calls[1:])
        assert ''.join(call.kwargs['json']['content'] for call in calls[1:])==text
        assert history[-1]['content']==text
    else:
        assert all(call.args[1].endswith('/stream_messages') for call in calls)
        frames=[call.kwargs['json'] for call in calls]
        assert all(frame['msg_seq']==1 and frame['input_mode']=='replace' for frame in frames)
        assert [frame['index'] for frame in frames]==list(range(len(frames)))
        assert all(frame['stream_msg_id']=='stream-one' for frame in frames[1:])
        if scenario in ('success','short'):
            assert frames[-1]['input_state']==10 and frames[-1]['content_raw']==text
            assert len(rows)==1 and rows[0]['content']==text and history[-1]['content']==text
            assert store.stats()['sent']==1
        elif scenario=='first_unknown':
            assert len(frames)==1 and not rows and not history
        else:
            assert len(frames)==(2 if scenario in ('later_unknown','timeout','forbidden_after_start') else 1)
            assert len(rows)==1 and rows[0]['content']==frames[0]['content_raw']
            if scenario=='reset':assert not history
            else:assert history[-1]['content']==frames[0]['content_raw']
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
async def test_stream_group_falls_back_to_normal_segments(tmp_path):
    store,bot,text=make_bot(tmp_path,True);c=store.load();c.rules.stream_output=True;store.save(c)
    assert not supports_stream(c,True)
    c.transport='napcat';assert not supports_stream(c,False)
    await bot.handle(event(group=True))
    assert all(call.args[1].endswith('/messages') for call in bot.api.await_args_list)
    assert ''.join(call.kwargs['json']['content'] for call in bot.api.await_args_list)==text
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
async def test_stream_never_exposes_transport_json_or_hidden_reasoning(tmp_path,monkeypatch):
    store,bot,_=make_bot(tmp_path);c=store.load();c.rules.stream_output=True;c.rules.show_thinking=True;store.save(c)
    monkeypatch.setattr('app.chat_stream.asyncio.sleep',AsyncMock())
    text='【思考摘要】先确认你的需要。\n【回复】你好呀，今天有什么安排？'
    bot.generate.return_value={'message':{'content':json.dumps({'reply':text,'schedule_update':None,'meme_id':None},ensure_ascii=False),'thinking':'PRIVATE INTERNAL REASONING'}}
    await bot.handle(event())
    frames=[call.kwargs['json'] for call in bot.api.await_args_list]
    assert frames[-1]['content_raw']==text
    assert all('schedule_update' not in frame['content_raw'] and 'PRIVATE' not in frame['content_raw'] for frame in frames)
    assert len(store.db.execute("SELECT id FROM chat_messages WHERE role='assistant'").fetchall())==1
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('fail_last',[False,True])
async def test_stream_schedule_commits_only_on_completion(tmp_path,monkeypatch,fail_last):
    from app.bot import Bot
    from app.store import Store
    from test_schedule import configured,DAY,NOW
    from test_schedule_dialogue import UPDATE
    store=Store(tmp_path);c=configured(store);c.rules.stream_output=True;store.save(c)
    bot=Bot(store);bot.schedule.clock=lambda:NOW
    sid=store.scopes.ensure(c.account_id,'user','alice','alice')['id'];day=bot.schedule.for_scope(sid)
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps(DAY,ensure_ascii=False)}})
    plan=await day.ensure()
    text='好，我现在出发去你家复习，我们可以把课上的内容再过一遍。'
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps({'reply':text,'schedule_update':UPDATE},ensure_ascii=False)}})
    monkeypatch.setattr('app.chat_stream.asyncio.sleep',AsyncMock())
    async def api(method,path,**kwargs):
        assert day.saved(c)['revision']==plan['revision']
        if kwargs['json']['input_state']==10 and fail_last:raise httpx.ReadTimeout('uncertain')
        return {'id':'stream-one'}
    bot.api=AsyncMock(side_effect=api);await bot.handle(event())
    assert (day.saved(c)['revision']!=plan['revision']) is (not fail_last)
    assert len(day.dialogue.records()['items'])==int(not fail_last)
    assert (store.history('user:alice:alice',6)[-1]['content']==text) is (not fail_last)
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
async def test_napcat_stream_toggle_keeps_normal_socket_send(tmp_path):
    from app.bot import Bot
    from app.store import Store
    from test_napcat import configure,napcat_server
    async with napcat_server() as (url,calls,_):
        store=Store(tmp_path);c=configure(store,url);c.rules.stream_output=True;store.save(c)
        bot=Bot(store);await bot.napcat.start()
        bot.generate=AsyncMock(return_value={'message':{'content':'你好，晚上好。'}})
        incoming=event(user='20002');await bot.handle(incoming)
        sent=[call for call in calls if call['action'].startswith('send_')]
        assert len(sent)==1 and sent[0]['params']['message']==[{'type':'text','data':{'text':'你好，晚上好。'}}]
        await bot.napcat.close();await bot.client.aclose();store.close()
