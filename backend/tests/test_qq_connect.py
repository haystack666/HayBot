import asyncio
import base64
import json
import os
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import create_app
from app.bot import Bot
from app.qq_connect import QQConnect
from app.registry import BotManager
from app.store import Store

PASSWORD='test-password-long-enough'


@pytest.fixture(autouse=True)
def mock_qq_start(monkeypatch):
    async def start(bot):
        bot.state = 'connected'
    monkeypatch.setattr(Bot, 'start', start)


async def settled(session):
    await asyncio.wait_for(session.task, 5)


def transport_for(status=2, app_id='123456', corrupt=False):
    keys=[]
    def respond(request):
        assert str(request.url).startswith('https://q.qq.com/lite/')
        body=json.loads(request.content)
        assert 'Authorization' not in request.headers
        if request.url.path.endswith('create_bind_task'):
            key=base64.b64decode(body['key']);assert len(key)==32;keys.append(key)
            return httpx.Response(200,json={'retcode':0,'data':{'task_id':'official-task-'+str(len(keys))}})
        assert set(body)=={'task_id'}
        payload={'status':status}
        if status==2:
            nonce=os.urandom(12);encrypted=nonce+AESGCM(keys[-1]).encrypt(nonce,b'private-qr-secret',None)
            if corrupt:encrypted=encrypted[:-1]+bytes([encrypted[-1]^1])
            payload.update(bot_appid=app_id,bot_encrypt_secret=base64.b64encode(encrypted).decode(),user_openid='not-a-received-message')
        return httpx.Response(200,json={'retcode':0,'data':payload})
    return httpx.MockTransport(respond),keys


@pytest.mark.asyncio
async def test_official_qr_crypto_and_confirmed_creation_are_private_and_idempotent(tmp_path):
    manager=BotManager(tmp_path);transport,keys=transport_for()
    async with httpx.AsyncClient(transport=transport) as client:
        service=QQConnect(manager,client)
        started=await service.start('owner')
        assert started['state']=='waiting' and started['qr_url'].startswith('https://q.qq.com/qqbot/openclaw/connect.html?')
        session=service.get(started['session_id'],'owner')
        assert base64.b64encode(keys[0]).decode() not in json.dumps(started)
        await settled(session)
        public=service.snapshot(session)
        assert public['state']=='authorized' and public['app_id']=='123456' and not public['qr_url']
        assert 'private-qr-secret' not in json.dumps(public) and not session.key
        assert len(manager.registry.list())==1
        completed=await service.complete(session.id,'owner','扫码 Bot')
        assert completed['state']=='completed' and not session.secret
        bot=manager.get(completed['bot_id']);config=bot.store.load()
        assert config.qq.app_id=='123456' and config.qq.secret=='private-qr-secret'
        assert config.ollama.provider_id and bot.store.enabled()
        for _ in range(20):
            if bot.bot.state == 'connected': break
            await asyncio.sleep(0)
        assert bot.bot.state == 'connected'
        assert not bot.store.contacts('123456')  # A QR authorization is not a chat message.
        raw=bot.store.db.execute('SELECT value FROM settings').fetchone()[0]
        assert 'private-qr-secret' not in raw and 'private-qr-secret' not in json.dumps(completed)
        assert (await service.complete(session.id,'owner','ignored'))['bot_id']==completed['bot_id']
        assert len(manager.registry.list())==2
        await service.close()
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('status,corrupt,expected',[(3,False,'expired'),(2,True,'error')])
async def test_expiry_and_tampered_ciphertext_never_create_a_bot(tmp_path,status,corrupt,expected):
    manager=BotManager(tmp_path);transport,_=transport_for(status=status,corrupt=corrupt)
    async with httpx.AsyncClient(transport=transport) as client:
        service=QQConnect(manager,client);started=await service.start('owner');session=service.get(started['session_id'],'owner')
        await settled(session)
        assert session.state==expected and not session.secret and not session.key
        assert len(manager.registry.list())==1
        with pytest.raises(HTTPException):await service.complete(session.id,'owner','bad')
        await service.close()
    await manager.close()


@pytest.mark.asyncio
async def test_duplicate_app_id_requires_explicit_update_of_stopped_existing_bot(tmp_path):
    manager=BotManager(tmp_path);runtime=manager.get('default');config=runtime.store.load()
    config.qq.app_id='123456';config.qq.secret='old-secret';config.rules.prompt='keep-persona';runtime.store.save(config)
    runtime.store.save_history('user:u:u',[{'role':'user','content':'keep-history'}],3)
    runtime.store.chat.record('123456','user','u','user','keep-archive','keep')
    transport,_=transport_for()
    async with httpx.AsyncClient(transport=transport) as client:
        service=QQConnect(manager,client);start=await service.start('owner');session=service.get(start['session_id'],'owner');await settled(session)
        assert service.snapshot(session)['existing_bot']['id']=='default'
        with pytest.raises(HTTPException) as error:await service.complete(session.id,'owner','duplicate')
        assert error.value.status_code==409 and runtime.store.load().qq.secret=='old-secret'
        runtime.bot.state='connected'
        with pytest.raises(HTTPException):await service.complete(session.id,'owner','duplicate',True)
        assert runtime.store.load().qq.secret=='old-secret'
        runtime.bot.state='stopped';runtime.bot.token='old-token'
        result=await service.complete(session.id,'owner','do-not-rename',True)
        assert result['bot_id']=='default' and len(manager.registry.list())==1
        assert runtime.store.load().qq.secret=='private-qr-secret' and not runtime.bot.token
        assert runtime.store.load().rules.prompt=='keep-persona' and runtime.store.history('user:u:u',3)
        assert runtime.store.db.execute('SELECT count(*) FROM chat_messages').fetchone()[0]==1
        assert manager.registry.get('default')['name']=='默认机器人'
        await service.close()
    await manager.close()


@pytest.mark.asyncio
async def test_archived_duplicates_owner_expiry_and_cancel_are_guarded(tmp_path):
    manager=BotManager(tmp_path);runtime=manager.get('default');config=runtime.store.load();config.qq.app_id='123456';runtime.store.save(config)
    await manager.archive('default')
    transport,_=transport_for();clock=[1000.]
    async with httpx.AsyncClient(transport=transport) as client:
        service=QQConnect(manager,client,clock=lambda:clock[0]);started=await service.start('owner');session=service.get(started['session_id'],'owner');await settled(session)
        assert service.snapshot(session)['existing_bot']['archived']
        with pytest.raises(HTTPException):service.get(session.id,'wrong-owner')
        with pytest.raises(HTTPException):await service.complete(session.id,'owner','new',True)
        clock[0]=1601
        with pytest.raises(HTTPException):service.get(session.id,'owner')
        assert not session.secret and not service.sessions
        start=await service.start('owner');new=service.get(start['session_id'],'owner')
        await service.cancel(new.id,'owner')
        assert new.task.done() and not new.key and not service.sessions
        await service.close()
    await manager.close()


@pytest.mark.asyncio
async def test_qq_service_failure_and_rate_limit_are_safe(tmp_path):
    manager=BotManager(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'retcode':9,'msg':'private-upstream-sentinel'}))) as client:
        service=QQConnect(manager,client)
        with pytest.raises(ValueError) as error:await service.start('owner')
        assert 'private-upstream-sentinel' not in str(error.value) and not service.sessions
        service.attempts=[service.clock()]*10
        with pytest.raises(HTTPException) as error:await service.start('owner')
        assert error.value.status_code==429
        await service.close()
    await manager.close()


@pytest.mark.asyncio
async def test_logout_revokes_binding_waiting_for_catalog_lock(tmp_path):
    manager=BotManager(tmp_path);transport,_=transport_for()
    async with httpx.AsyncClient(transport=transport) as client:
        service=QQConnect(manager,client);start=await service.start('owner');session=service.get(start['session_id'],'owner');await settled(session)
        async with manager.catalog_lock:
            task=asyncio.create_task(service.complete(session.id,'owner','revoked'))
            await asyncio.sleep(0)
            await service.cancel_all()
        with pytest.raises(HTTPException):await task
        assert len(manager.registry.list())==1
        await service.close()
    await manager.close()


def test_qr_api_auth_origin_confirm_and_logout(tmp_path,monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD',PASSWORD)
    with TestClient(create_app(tmp_path)) as client:
        assert client.post('/api/qq/qr').status_code==401
        client.post('/api/login',json={'password':PASSWORD})
        service=client.app.state.qq_connect
        transport,_=transport_for(status=1)
        async def replace_client():
            await service.client.aclose();service.client=httpx.AsyncClient(transport=transport)
        client.portal.call(replace_client)
        assert client.post('/api/qq/qr',headers={'Origin':'https://evil.test'}).status_code==403
        start=client.post('/api/qq/qr');assert start.status_code==201
        sid=start.json()['session_id']
        assert client.get('/api/qq/qr/'+sid).json()['state']=='waiting'
        assert client.post('/api/qq/qr/'+sid+'/complete',json={}).status_code==409
        assert client.delete('/api/qq/qr/'+sid).status_code==200
        assert client.get('/api/qq/qr/'+sid).status_code==404
        sid=client.post('/api/qq/qr').json()['session_id']
        client.post('/api/logout');client.post('/api/login',json={'password':PASSWORD})
        assert client.get('/api/qq/qr/'+sid).status_code==404


@pytest.mark.asyncio
async def test_logout_during_qr_creation_does_not_leave_pending_session(tmp_path):
    manager=BotManager(tmp_path);entered=asyncio.Event();release=asyncio.Event();valid=[True]
    service=QQConnect(manager)
    async def request(*args):
        entered.set();await release.wait();return {'task_id':'pending-create'}
    service.request=request
    pending=asyncio.create_task(service.start('old-owner',still_valid=lambda:valid[0]))
    await entered.wait();valid[0]=False;await service.cancel_all();release.set()
    with pytest.raises(HTTPException) as error:await pending
    assert error.value.status_code==401 and not service.sessions
    await service.close();await manager.close()


@pytest.mark.asyncio
async def test_completed_binding_wakes_sleeping_runtime_and_does_not_need_another_scan(tmp_path):
    manager=BotManager(tmp_path);runtime=manager.get('default');config=runtime.store.load()
    config.qq.app_id='123456';config.qq.secret='old';runtime.store.save(config)
    await asyncio.sleep(0)  # Let the initially stopped recovery worker go to sleep.
    started=asyncio.Event()
    async def start():
        runtime.bot.state='connected';started.set()
    runtime.bot.start=start
    transport,_=transport_for()
    async with httpx.AsyncClient(transport=transport) as client:
        service=QQConnect(manager,client);data=await service.start('owner');session=service.get(data['session_id'],'owner');await settled(session)
        await service.complete(session.id,'owner','ignored',True)
        await asyncio.wait_for(started.wait(),1)
        assert runtime.store.enabled() and runtime.bot.state=='connected'
        await service.cancel(session.id,'owner')
        assert runtime.store.enabled() and runtime.bot.state=='connected'
        await service.close()
    await manager.close()


@pytest.mark.asyncio
async def test_auto_start_failure_keeps_saved_bot_and_can_retry_without_rebinding(tmp_path):
    manager=BotManager(tmp_path);transport,_=transport_for()
    async with httpx.AsyncClient(transport=transport) as client:
        service=QQConnect(manager,client);data=await service.start('owner');session=service.get(data['session_id'],'owner');await settled(session)
        original_attach=manager.attach;failed=asyncio.Event()
        def attach(bot_id):
            runtime=original_attach(bot_id)
            async def start():
                failed.set();raise ValueError('模型不存在，请检查配置')
            runtime.bot.start=start
            return runtime
        manager.attach=attach
        result=await service.complete(session.id,'owner','saved-even-if-start-fails')
        await asyncio.wait_for(failed.wait(),1);await asyncio.sleep(0)
        runtime=manager.get(result['bot_id'])
        assert runtime.store.load().qq.secret=='private-qr-secret' and runtime.store.enabled()
        assert service.snapshot(session)['start_error']=='模型不存在，请检查配置'
        started=asyncio.Event()
        async def successful():runtime.bot.state='connected';started.set()
        runtime.bot.start=successful;runtime.request_start()
        await asyncio.wait_for(started.wait(),1)
        assert not runtime.start_error and len(manager.registry.list())==2
        await service.close()
    await manager.close()
