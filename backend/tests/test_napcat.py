import asyncio
import json
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from websockets.asyncio.server import serve

from app.config import Settings
from app.store import Store
from app.bot import Bot
from test_providers import client,body


def configure(store,url='ws://127.0.0.1:3001'):
    c=store.load();c.transport='napcat';c.napcat.self_id='10001';c.napcat.ws_url=url;c.napcat.token='fixture-napcat-secret'
    c.rules.cooldown=0;c.rules.debounce_enabled=False;store.save(c);return c


@asynccontextmanager
async def napcat_server(online=True,account=10001,disconnect_on_send=False):
    calls=[];connections=[]
    async def handler(ws):
        connections.append(ws)
        async for raw in ws:
            r=json.loads(raw);calls.append(r)
            if r['action']=='never_reply':continue
            if disconnect_on_send and r['action'].startswith('send_'):
                await ws.close();return
            data={'user_id':account,'nickname':'测试 NapCat'} if r['action']=='get_login_info' else {'online':online,'good':True} if r['action']=='get_status' else {'message_id':456}
            await ws.send(json.dumps({'status':'ok','retcode':0,'data':data,'echo':r['echo']}))
    async with serve(handler,'127.0.0.1',0) as server:
        yield 'ws://127.0.0.1:'+str(server.sockets[0].getsockname()[1]),calls,connections


def test_napcat_config_and_encrypted_token(tmp_path):
    s=Store(tmp_path);c=configure(s)
    assert c.account_id=='napcat:10001'
    raw=s.db.execute('SELECT value FROM settings').fetchone()[0]
    assert 'fixture-napcat-secret' not in raw and s.load().napcat.token=='fixture-napcat-secret'
    assert Settings().transport=='qq_official'
    for url in ('http://localhost:3001','ws://user:pass@test','ws://test?token=secret','ws://test#fragment'):
        with pytest.raises(ValidationError):c.napcat.__class__(ws_url=url)
    s.close()


def test_api_keeps_token_only_for_same_endpoint_and_account(client):
    c=body(client);c['transport']='napcat';c['napcat'].update(self_id='10001',ws_url='ws://napcat.test:3001',token='token-secret-sentinel')
    r=client.put('/api/bots/default/settings',json=c)
    assert r.status_code==200 and r.json()['napcat']['token_set'] and 'token-secret-sentinel' not in r.text
    c=body(client);c['napcat'].pop('token_set');c['napcat']['token']=''
    assert client.put('/api/bots/default/settings',json=c).json()['napcat']['token_set']
    c['napcat']['ws_url']='ws://another.test:3001'
    assert not client.put('/api/bots/default/settings',json=c).json()['napcat']['token_set']


@pytest.mark.asyncio
async def test_real_websocket_login_echo_and_native_sticker(tmp_path):
    from app.napcat import NapCatTransport
    async with napcat_server() as (url,calls,connections):
        s=Store(tmp_path);configure(s,url);b=Bot(s);t=b.napcat
        await t.start()
        assert connections[0].request.headers['Authorization']=='Bearer fixture-napcat-secret'
        receipt=await t.send_text(False,'20002','你好')
        assert receipt=={'id':'456'}
        await t.send_image(True,'30003',b'fake-image',before_send=lambda:True)
        message=calls[-1]['params']['message'][0]
        assert calls[-1]['action']=='send_group_msg' and message['data']['sub_type']==1
        assert message['data']['file'].startswith('base64://')
        await t.close();await b.client.aclose();s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('online,account',[(False,10001),(True,99999)])
async def test_wrong_login_or_offline_is_rejected(tmp_path,online,account):
    async with napcat_server(online,account) as (url,_,__):
        s=Store(tmp_path);configure(s,url);b=Bot(s)
        with pytest.raises(ValueError):await b.napcat.start()
        assert b.napcat.ws is None
        await b.client.aclose();s.close()


@pytest.mark.asyncio
async def test_request_timeout_and_disconnect_do_not_resend(tmp_path):
    async with napcat_server(disconnect_on_send=True) as (url,calls,_):
        s=Store(tmp_path);configure(s,url);b=Bot(s);await b.napcat.start()
        with pytest.raises(ValueError):await b.napcat.call('never_reply',{},timeout=.02)
        assert not b.napcat.pending
        with pytest.raises(ValueError):await b.napcat.send_text(False,'20002','只发一次')
        assert sum(r['action']=='send_private_msg' for r in calls)==1
        await b.napcat.close();await b.client.aclose();s.close()


def message(group=False,at=True,self_id=10001,mid=123,sender=20002):
    parts=([{'type':'at','data':{'qq':'10001'}}] if group and at else [])+[{'type':'text','data':{'text':'你好'}}]
    return {'self_id':self_id,'post_type':'message','message_type':'group' if group else 'private','user_id':sender,
        'group_id':30003,'message_id':mid,'time':int(time.time()),'message':parts,'sender':{'nickname':'测试用户'}}


def test_normalization_filters_self_wrong_account_and_group_without_at(tmp_path):
    from app.napcat import normalize_event
    s=Store(tmp_path);c=configure(s);c.qq.group_reply=True
    p=normalize_event(message(),c)
    assert p['t']=='C2C_MESSAGE_CREATE' and p['d']['author']['user_openid']=='20002'
    assert normalize_event(message(group=True,at=False),c) is None
    assert normalize_event(message(self_id=99999),c) is None
    assert normalize_event(message(sender=10001),c) is None
    assert normalize_event(message(group=True),c)['d']['content']=='你好'
    s.close()


@pytest.mark.asyncio
async def test_inbound_event_runs_existing_pipeline_once(tmp_path):
    async with napcat_server() as (url,calls,connections):
        s=Store(tmp_path);configure(s,url);b=Bot(s)
        b.models=AsyncMock(return_value=['test']);b.provider=lambda selection:__import__('app.providers',fromlist=['ProviderConfig']).ProviderConfig(type='deepseek')
        b.generate=AsyncMock(return_value={'message':{'content':'你好呀'}})
        await b.start()
        raw=json.dumps(message());await connections[0].send(raw);await connections[0].send(raw)
        for _ in range(100):
            if s.stats()['sent']:break
            await asyncio.sleep(.02)
        assert s.stats()['received']==1 and s.stats()['sent']==1 and b.generate.await_count==1
        rows=s.db.execute('SELECT app_id FROM chat_conversations').fetchall();assert {r[0] for r in rows}=={'napcat:10001'}
        assert len(s.history('user:20002:20002',6))==2
        await b.stop();await b.client.aclose();s.close()


@pytest.mark.asyncio
async def test_account_change_event_closes_connection_before_another_send(tmp_path):
    async with napcat_server() as (url,calls,connections):
        s=Store(tmp_path);configure(s,url);b=Bot(s);await b.napcat.start()
        await connections[0].send(json.dumps({'post_type':'meta_event','meta_event_type':'heartbeat','self_id':99999,'status':{'online':True}}))
        for _ in range(30):
            if not b.napcat.ready:break
            await asyncio.sleep(.01)
        with pytest.raises(ValueError):await b.napcat.send_text(False,'20002','不应发到另一账号')
        assert not any(r['action']=='send_private_msg' for r in calls)
        await b.napcat.close();await b.client.aclose();s.close()


def test_official_and_napcat_same_numeric_id_do_not_share_scope_or_chat(tmp_path):
    s=Store(tmp_path);c=s.load();c.qq.app_id='10001';s.save(c)
    old=s.scopes.ensure('10001','user','20002','20002')
    s.chat.record('10001','user','20002','user','官方记录','in:10001:20002:1',sender_id='20002',source='incoming')
    c=configure(s);new=s.scopes.ensure(c.account_id,'user','20002','20002')
    assert new['id']!=old['id']
    with pytest.raises(ValueError):s.scopes.get(old['id'])
    assert not s.chat.conversations(c.account_id)['items']
    s.close()


def test_napcat_token_is_redacted_in_logs(tmp_path):
    s=Store(tmp_path);configure(s);s.log('error','连接失败 token fixture-napcat-secret')
    assert 'fixture-napcat-secret' not in json.dumps(s.logs())
    s.close()


@pytest.mark.asyncio
async def test_napcat_reset_confirmation_and_proactive_send_reuse_runtime(tmp_path):
    from app.proactive import ProactiveService
    async with napcat_server() as (url,calls,connections):
        s=Store(tmp_path);configure(s,url);b=Bot(s)
        b.models=AsyncMock(return_value=['test']);b.provider=lambda selection:__import__('app.providers',fromlist=['ProviderConfig']).ProviderConfig(type='deepseek')
        b.generate=AsyncMock(return_value={'message':{'content':'保留这句话'}})
        await b.start()
        for mid,text in [(1,'/reset'),(2,'/reset 确认')]:
            raw=message(mid=mid);raw['message']=[{'type':'text','data':{'text':text}}]
            await connections[0].send(json.dumps(raw))
            for _ in range(50):
                if s.stats()['sent']>=mid and not b.jobs:break
                await asyncio.sleep(.02)
        assert any('已清空' in r['params']['message'][0]['data']['text'] for r in calls if r['action']=='send_private_msg')
        service=ProactiveService(s,b);await service.execute('napcat-test-push',s.load(),'20002','test','测试主动消息',generated=False,manual=True)
        assert s.proactive_records('napcat:10001')[0]['status']=='sent'
        assert b.generate.await_count==0
        await b.stop();await b.client.aclose();s.close()


@pytest.mark.asyncio
async def test_native_meme_preserves_gif_bytes_and_archive_preview(tmp_path):
    import base64,io
    from PIL import Image
    from app.memes import MemeCatalog,MemeDescription
    async with napcat_server() as (url,calls,connections):
        library=MemeCatalog(tmp_path/'library');raw=io.BytesIO()
        Image.new('RGB',(16,16),'red').save(raw,'GIF',save_all=True,append_images=[Image.new('RGB',(16,16),'blue')])
        item=library.add(raw.getvalue(),'庆祝',MemeDescription(visual='测试用红蓝交替的动图',scenarios=['庆祝好消息']))
        s=Store(tmp_path/'bot');c=configure(s,url);c.memes.enabled=True;s.save(c);b=Bot(s,memes=library)
        b.models=AsyncMock(return_value=['test']);b.provider=lambda selection:__import__('app.providers',fromlist=['ProviderConfig']).ProviderConfig(type='deepseek')
        picked={**item,'selection_stamp':b.memes.config_stamp()};b.memes.candidates=AsyncMock(return_value=[picked])
        b.generate=AsyncMock(return_value={'message':{'content':json.dumps({'reply':'好开心！','meme_id':item['id']})}})
        await b.start();await connections[0].send(json.dumps(message()))
        for _ in range(100):
            if s.stats()['sent']==2:break
            await asyncio.sleep(.02)
        sent=[r for r in calls if r['action']=='send_private_msg'];assert len(sent)==2
        assert base64.b64decode(sent[-1]['params']['message'][0]['data']['file'].removeprefix('base64://'))==raw.getvalue()
        conversation=s.chat.conversations('napcat:10001')['items'][0]
        messages=s.chat.messages('napcat:10001',conversation['id'])['items']
        assert messages[-1]['meme_original'] and messages[-1]['meme_id']==item['id']
        assert b.generate.await_count==1 and s.stats()['sent']==2
        await b.stop();await b.client.aclose();s.close();library.close()


@pytest.mark.asyncio
async def test_probe_verifies_login_without_starting_or_consuming_events(client):
    async with napcat_server() as (url,calls,connections):
        c=body(client);c['transport']='napcat';c['napcat'].update(self_id='10001',ws_url=url,token='fixture-napcat-secret')
        assert (await asyncio.to_thread(client.put,'/api/bots/default/settings',json=c)).status_code==200
        result=await asyncio.to_thread(client.post,'/api/bots/default/qq/test')
        assert result.status_code==200 and result.json()['self_id']=='10001'
        status=await asyncio.to_thread(client.get,'/api/bots/default/status')
        assert status.json()['state']=='stopped'
        assert [r['action'] for r in calls]==['get_login_info','get_status']
