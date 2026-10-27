import asyncio
import base64
import io
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from app.main import create_app
from app.android import AndroidTasks, AndroidConfig


def png():
    b = io.BytesIO(); Image.new('RGB', (720, 1280), 'white').save(b, format='PNG')
    return base64.b64encode(b.getvalue()).decode()


def test_android_routes_require_auth_and_keep_bot_scopes(tmp_path, monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-password-long-enough')
    with TestClient(create_app(tmp_path)) as c:
        assert c.get('/api/bots/default/android').status_code == 401
        c.post('/api/login', json={'password': 'test-password-long-enough'})
        assert c.get('/api/bots/default/android').status_code == 200
        assert c.get('/api/bots/missing/android').status_code == 404
        assert c.get('/api/bots/default/android').json()['configured'] is False
        assert c.post('/api/bots/default/android/devices', json={'name': 'test'}).status_code == 503
        result = c.put('/api/bots/default/android/config', json={'model': 'test', 'max_steps': 0})
        assert result.status_code == 422
        assert c.post('/api/bots/default/android/tasks', json={'goal': 'open browser'}).status_code == 409


@pytest.mark.asyncio
async def test_task_uses_independent_model_verifies_completion_and_releases_lease(tmp_path):
    from app.registry import BotManager
    manager = BotManager(tmp_path)
    tasks = AndroidTasks(manager, tmp_path)
    tasks.save_config('default', AndroidConfig(model='vision-test', enabled=True))
    calls = []
    async def gateway(method, path, body=None, **kw):
        calls.append((method, path, body))
        if path.endswith('/claim'): return {'lease': 'lease-one'}
        if path.endswith('/observe'): return {'image': png(), 'hierarchy': '<node text="Settings"/>'}
        return {'ok': True}
    tasks.gateway.request = gateway
    choices = iter([{'action': {'kind': 'key', 'key': 'home'}, 'reason': 'Go home'}, {'done': True, 'result': 'Home screen visible'}])
    tasks.decide = AsyncMock(side_effect=lambda *a: next(choices))
    task = tasks.submit('default', '0' * 32, 'Go home')
    await tasks.jobs[task['id']]
    final = tasks.get('default', task['id'])
    assert final['state'] == 'completed'
    assert len(final['steps']) == 2
    assert sum(path.endswith('/observe') for _, path, _ in calls) == 2
    assert any(path.endswith('/release') for _, path, _ in calls)
    with pytest.raises(ValueError): tasks.get('other', task['id'])
    await tasks.close(); await manager.close()


@pytest.mark.asyncio
async def test_cancellation_during_model_wait_prevents_action(tmp_path):
    from app.registry import BotManager
    manager = BotManager(tmp_path); tasks = AndroidTasks(manager, tmp_path)
    tasks.save_config('default', AndroidConfig(model='vision', enabled=True))
    calls=[]; entered=asyncio.Event()
    async def gateway(method,path,body=None,**kw):
        calls.append(path)
        if path.endswith('/claim'):return {'lease':'lease'}
        if path.endswith('/observe'):return {'image':png(),'hierarchy':''}
        return {'ok':True}
    async def decide(*args):
        entered.set(); await asyncio.sleep(30)
        return {'action': {'kind':'key','key':'home'}}
    tasks.gateway.request=gateway; tasks.decide=decide
    job=tasks.submit('default','0'*32,'test'); await entered.wait()
    await tasks.cancel('default',job['id'])
    assert not any(p.endswith('/action') for p in calls)
    assert tasks.get('default',job['id'])['state']=='cancelled'
    await tasks.close(); await manager.close()

@pytest.mark.asyncio
async def test_gateway_preserves_destroy_confirmation_query(monkeypatch):
    import httpx
    from app.android import Gateway
    seen=[]
    real=httpx.AsyncClient
    async def handle(request):
        seen.append(str(request.url));return httpx.Response(200,json={'ok':True})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs: real(transport=httpx.MockTransport(handle),**kwargs))
    gateway=Gateway();gateway.url='http://runtime.test';gateway.token='x'*40;gateway.configured=True
    await gateway.request('DELETE','/bots/a/devices/device?destroy_data=true&confirm=device')
    assert 'destroy_data=true' in seen[0] and 'confirm=device' in seen[0]

@pytest.mark.asyncio
async def test_archive_cancels_model_task_and_revokes_before_closing_bot(tmp_path):
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path);manager.android_service=tasks
    tasks.save_config('default',AndroidConfig(model='vision',enabled=True))
    entered=asyncio.Event();calls=[]
    async def gateway(method,path,body=None,**kw):
        calls.append((path,body))
        if path.endswith('/claim'):return {'lease':body['lease']}
        if path.endswith('/observe'):return {'image':png(),'hierarchy':''}
        return {'ok':True}
    async def decide(*args):entered.set();await asyncio.sleep(30)
    tasks.gateway.request=gateway;tasks.decide=decide
    task=tasks.submit('default','0'*32,'test');await entered.wait()
    await manager.archive('default')
    assert any(path.endswith('/revoke') and body['lease']==task['id'] for path,body in calls)
    assert tasks.get('default',task['id'])['state']=='cancelled'
    assert not any(path.endswith('/action') for path,_ in calls)
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_manual_takeover_resolves_revocation_uncertainty(tmp_path):
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    tasks.save_config('default',AndroidConfig(enabled=True,model='vision'))
    tasks.gateway.request=AsyncMock(side_effect=ValueError('offline'))
    task=tasks.submit('default','0'*32,'test')
    await tasks.cancel('default',task['id'])
    assert tasks.get('default',task['id'])['state']=='unknown'
    tasks.acknowledge_takeover('default')
    assert tasks.get('default',task['id'])['state']=='cancelled'
    assert await tasks.cancel_bot('default') is True
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_cancel_before_worker_starts_does_not_claim_phone(tmp_path):
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    tasks.save_config('default',AndroidConfig(enabled=True,model='vision'))
    calls=[]
    async def gateway(method,path,body=None,**kwargs):
        calls.append(path)
        await asyncio.sleep(0)
        if path.endswith('/claim'):return {'lease':body['lease']}
        return {'ok':True}
    tasks.gateway.request=gateway
    task=tasks.submit('default','0'*32,'test')
    await tasks.cancel('default',task['id'])
    assert not any(path.endswith('/claim') for path in calls)
    assert tasks.get('default',task['id'])['state']=='cancelled'
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_invalid_model_decision_retries_before_action_and_keeps_diagnostics(tmp_path,monkeypatch):
    import app.android as module
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    runtime=manager.get('default');cfg=tasks.config('default')
    cfg.enabled=True;cfg.model='vision';tasks.save_config('default',cfg)
    responses=iter(['', '{"action":{"kind":"key","key":"home"}}'])
    async def generate(*args,**kwargs):return {'message':{'content':next(responses)},'eval_count':2}
    monkeypatch.setattr(module,'generate',generate)
    job=tasks.submit('default','0'*32,'test');tasks.jobs[job['id']].cancel();await asyncio.gather(tasks.jobs[job['id']],return_exceptions=True)
    tasks.update(job['id'],state='running')
    result=await tasks.decide('default',cfg,'test',{'image':png(),'hierarchy':''},[],job['id'])
    assert result['action']['key']=='home'
    attempts=tasks.diagnostics('default',job['id'])
    assert len(attempts)==2 and attempts[0]['error'] and attempts[1]['content'].startswith('{')
    assert runtime.store.stats()['output_tokens']==4
    assert 'image' not in attempts[0] and 'api_key' not in attempts[0]
    await tasks.close();await manager.close()
