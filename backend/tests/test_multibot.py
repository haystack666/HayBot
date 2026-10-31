import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from websockets.asyncio.server import serve

from app.bot import Bot
from app.config import Settings
from app.main import create_app
from app.registry import BotManager
from app.store import Store

PASSWORD = 'test-password-long-enough'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', PASSWORD)
    with TestClient(create_app(tmp_path)) as client:
        client.post('/api/login', json={'password': PASSWORD})
        yield client


def settings(client, bot_id):
    body = client.get(f'/api/bots/{bot_id}/settings').json()
    body['qq'].pop('secret_set')
    body['qq']['secret'] = ''
    return body


def test_catalog_config_isolation_archive_and_restore(client):
    assert client.get('/api/bots').json()['bots'][0]['id'] == 'default'
    created = client.post('/api/bots', json={'name': ' 工作助手 '})
    assert created.status_code == 201 and created.json()['name'] == '工作助手'
    second = created.json()['id']
    for bot_id, app_id, model, prompt in [('default', '111', 'model-a', 'persona-a-private'),
                                            (second, '222', 'model-b', 'persona-b-private')]:
        body = settings(client, bot_id)
        body['qq'].update(app_id=app_id, secret=f'{app_id}-private-secret')
        body['ollama']['model'] = model
        body['rules']['prompt'] = prompt
        body['proactive'].update(cooldown_minutes=0 if bot_id == 'default' else 1440, unanswered_limit=20)
        result = client.put(f'/api/bots/{bot_id}/settings', json=body)
        assert result.status_code == 200
        assert 'secret' not in result.json()['qq'] and result.json()['qq']['secret_set']
    assert client.get('/api/settings').json()['rules']['prompt'] == 'persona-a-private'
    assert client.get(f'/api/bots/{second}/settings').json()['rules']['prompt'] == 'persona-b-private'
    assert client.patch(f'/api/bots/{second}', json={'name': '第二个 Bot'}).status_code == 200
    catalog = client.get('/api/bots').json()['bots']
    assert len(catalog) == 2 and catalog[1]['name'] == '第二个 Bot'
    assert 'private-secret' not in str(catalog) and 'persona-a-private' not in str(catalog)
    assert client.post(f'/api/bots/{second}/archive').status_code == 200
    assert len(client.get('/api/bots').json()['bots']) == 1
    assert client.get(f'/api/bots/{second}/settings').status_code == 404
    assert client.get('/api/bots?include_archived=true').json()['bots'][1]['archived']
    assert client.post(f'/api/bots/{second}/restore').status_code == 200
    restored = client.get(f'/api/bots/{second}/settings').json()
    assert restored['rules']['prompt'] == 'persona-b-private' and restored['ollama']['model'] == 'model-b'
    assert restored['proactive']['cooldown_minutes'] == 1440 and restored['qq']['secret_set']
    assert client.get(f'/api/bots/{second}/status').json()['state'] == 'stopped'
    assert client.get('/api/bots/unknown/settings').status_code == 404
    assert client.post('/api/bots', json={'name': '  '}).status_code == 422
    assert client.post('/api/bots', json={'name': 'x', 'secret': 'not-accepted'}).status_code == 422


def test_duplicate_official_app_id_and_restore_conflict(client):
    second = client.post('/api/bots', json={'name': 'Bot 2'}).json()['id']
    first = settings(client, 'default')
    first['qq'].update(app_id='123', secret='private')
    assert client.put('/api/bots/default/settings', json=first).status_code == 200
    body = settings(client, second)
    body['qq']['app_id'] = '123'
    assert client.put(f'/api/bots/{second}/settings', json=body).status_code == 400
    assert client.post('/api/bots/default/archive').status_code == 200
    assert client.put(f'/api/bots/{second}/settings', json=body).status_code == 200
    assert client.post('/api/bots/default/restore').status_code == 400
    assert client.get('/api/settings').status_code == 404
    assert client.get(f'/api/bots/{second}/settings').status_code == 200


def test_contacts_reminders_and_history_apis_stay_in_bot_scope(client, tmp_path):
    second = client.post('/api/bots', json={'name': 'Bot 2'}).json()['id']
    for bot_id, directory, app_id in [('default', tmp_path, '111'), (second, tmp_path / 'bots' / second, '222')]:
        store = Store(directory)
        config = store.load()
        config.qq.app_id = app_id
        config.proactive.recipient_id = 'same-user'
        config.proactive.enabled = True
        store.save(config)
        store.remember_contact(app_id, 'same-user', time.time(), 'same-message')
        store.set_capability(app_id, 'same-user', 'supported', 'verified', time.time())
        store.save_history('same-key', [{'role': 'user', 'content': app_id}], 2)
        store.close()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    result = client.post('/api/bots/default/proactive/reminders', json={'at': future, 'content': 'only-first'})
    assert result.status_code == 200
    reminder_id = result.json()['reminders'][0]['id']
    assert client.get(f'/api/bots/{second}/proactive').json()['reminders'] == []
    assert client.delete(f'/api/bots/{second}/proactive/reminders/{reminder_id}').status_code == 400
    assert client.delete(f'/api/bots/{second}/history').status_code == 200
    first = Store(tmp_path)
    other = Store(tmp_path / 'bots' / second)
    assert first.history('same-key', 2) and not other.history('same-key', 2)
    first.close(); other.close()
    client.post('/api/logout')
    assert client.get(f'/api/bots/{second}/settings').status_code == 401
    assert client.post('/api/bots', json={'name': 'blocked'}).status_code == 401


@pytest.mark.asyncio
async def test_legacy_data_migrates_in_place_and_restarts_without_reimport(tmp_path):
    store = Store(tmp_path)
    config = store.load()
    config.qq.app_id, config.qq.secret = '123', 'legacy-private-secret'
    config.rules.prompt = 'legacy-persona'
    store.save(config)
    store.claim('legacy-message')
    store.record_result('sent', 'legacy-sent')
    store.record_usage({'prompt_eval_count': 31, 'eval_count': 7})
    store.save_history('legacy-key', [{'role': 'user', 'content': 'saved'}], 2)
    store.remember_contact('123', 'owner', time.time())
    store.add_reminder('legacy-reminder', '123', 'owner', time.time() + 3600, 'saved', time.time())
    key = (tmp_path / 'secret.key').read_bytes()
    store.close()
    manager = BotManager(tmp_path)
    first = manager.get('default').store
    assert first.load().qq.secret == 'legacy-private-secret' and first.load().rules.prompt == 'legacy-persona'
    assert first.stats()['received'] == 1 and first.stats()['sent'] == 1 and first.stats()['total_tokens'] == 38
    assert first.history('legacy-key', 2) and first.reminders('123')[0]['id'] == 'legacy-reminder'
    assert first.contact('123', 'owner')
    second = (await manager.create('second'))['id']
    assert manager.get(second).store.stats()['total_tokens'] == 0
    await manager.close()
    backups = list((tmp_path / 'backups').glob('before-multibot-*.sqlite3'))
    assert len(backups) == 1 and (tmp_path / 'secret.key').read_bytes() == key
    manager = BotManager(tmp_path)
    assert len(manager.registry.list()) == 2 and manager.get('default').store.stats()['total_tokens'] == 38
    await manager.close()
    assert len(list((tmp_path / 'backups').glob('before-multibot-*.sqlite3'))) == 1


@pytest.mark.asyncio
async def test_two_bots_handle_same_message_independently_and_share_model_capacity(tmp_path):
    manager = BotManager(tmp_path)
    second = (await manager.create('second'))['id']
    runtimes = [manager.get('default'), manager.get(second)]
    sends, generations, in_flight, peak = [], [], 0, 0

    async def transport(request):
        nonlocal in_flight, peak
        data = json.loads(request.content) if request.content else {}
        if request.url.path.endswith('/getAppAccessToken'):
            return httpx.Response(200, json={'access_token': 'token-' + data['appId'], 'expires_in': 7200})
        if request.url.path == '/api/chat':
            in_flight += 1; peak = max(peak, in_flight)
            await asyncio.sleep(0.02)
            generations.append(data)
            in_flight -= 1
            return httpx.Response(200, json={'message': {'content': data['model'] + '-reply'}, 'prompt_eval_count': 10, 'eval_count': 3})
        sends.append((request.headers['Authorization'], data))
        return httpx.Response(200, json={'id': 'sent'})

    for index, runtime in enumerate(runtimes):
        config = runtime.store.load()
        config.qq.app_id, config.qq.secret = str(index + 1), 'private'
        config.ollama.model, config.rules.prompt = f'model-{index}', f'persona-{index}'
        runtime.store.save(config)
        await runtime.bot.client.aclose()
        runtime.bot.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    event = {'t': 'C2C_MESSAGE_CREATE', 'd': {'id': 'same-message-id', 'content': 'hello', 'author': {'user_openid': 'same-user'}}}
    await asyncio.gather(*(runtime.bot.handle(event) for runtime in runtimes))
    assert peak == 1 and len(sends) == 2
    assert {token for token, _ in sends} == {'QQBot token-1', 'QQBot token-2'}
    assert {message['messages'][0]['content'].split('\n[参考资料规则]',1)[0] for message in generations} == {'persona-0', 'persona-1'}
    for index, runtime in enumerate(runtimes):
        assert runtime.store.stats()['received'] == 1 and runtime.store.stats()['sent'] == 1
        assert runtime.store.stats()['total_tokens'] == 13
        assert runtime.store.history('user:same-user:same-user', 6)[-1]['content'] == f'model-{index}-reply'
        assert runtime.store.contacts(str(index + 1))[0]['id'] == 'same-user'
    await manager.close()


@pytest.mark.asyncio
async def test_two_official_websocket_loops_stay_connected_when_one_stops(tmp_path):
    manager = BotManager(tmp_path)
    second = (await manager.create('second'))['id']
    runtimes = [manager.get('default'), manager.get(second)]
    ready = [asyncio.Event(), asyncio.Event()]

    def gateway(index):
        async def handler(ws):
            await ws.send(json.dumps({'op': 10, 'd': {'heartbeat_interval': 1000}}))
            identify = json.loads(await ws.recv())
            assert identify['op'] == 2 and identify['d']['token'] == f'QQBot token-{index}'
            await ws.send(json.dumps({'op': 0, 't': 'READY', 's': 1, 'd': {'session_id': f'session-{index}'}}))
            ready[index].set()
            async for _ in ws:
                await ws.send(json.dumps({'op': 11}))
        return handler
    async with serve(gateway(0), '127.0.0.1', 0) as first, serve(gateway(1), '127.0.0.1', 0) as other:
        for index, (runtime, server) in enumerate(zip(runtimes, [first, other])):
            runtime.bot.api = AsyncMock(return_value={'url': f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'})
            runtime.bot.access_token = AsyncMock(return_value=f'token-{index}')
            runtime.bot.task = asyncio.create_task(runtime.bot.run())
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in ready)), 5)
        # READY must be consumed by both independent clients.
        for _ in range(50):
            if all(runtime.bot.state == 'connected' for runtime in runtimes): break
            await asyncio.sleep(0.01)
        assert all(runtime.bot.state == 'connected' for runtime in runtimes)
        await runtimes[0].bot.stop()
        assert runtimes[0].bot.state == 'stopped' and runtimes[1].bot.state == 'connected'
        await runtimes[1].bot.stop()
    await manager.close()


@pytest.mark.asyncio
async def test_enabled_bots_restore_independently_and_archive_is_persistent(tmp_path, monkeypatch):
    async def start(bot):
        bot.state = 'connected'
    monkeypatch.setattr(Bot, 'start', start)
    manager = BotManager(tmp_path)
    second = (await manager.create('second'))['id']
    for runtime in manager.runtimes.values(): runtime.store.set_enabled(True)
    await manager.close()
    manager = BotManager(tmp_path)
    await asyncio.sleep(0)
    assert all(runtime.bot.state == 'connected' for runtime in manager.runtimes.values())
    await manager.archive(second)
    assert manager.get('default').bot.state == 'connected'
    await manager.close()
    manager = BotManager(tmp_path)
    await asyncio.sleep(0)
    assert set(manager.runtimes) == {'default'} and manager.get('default').bot.state == 'connected'
    await manager.restore(second)
    assert manager.get(second).bot.state == 'stopped' and not manager.get(second).store.enabled()
    await manager.close()


@pytest.mark.asyncio
async def test_api_starts_bots_concurrently_without_global_control_lock(tmp_path, monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', PASSWORD)
    app = create_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            await client.post('/api/login', json={'password': PASSWORD})
            second = (await client.post('/api/bots', json={'name': 'second'})).json()['id']
            entered = [asyncio.Event(), asyncio.Event()]
            release = asyncio.Event()
            def start(index, runtime):
                async def run():
                    entered[index].set()
                    await release.wait()
                    runtime.bot.state = 'connected'
                return run
            for index, bot_id in enumerate(['default', second]):
                runtime = app.state.manager.get(bot_id)
                runtime.bot.start = start(index, runtime)
            starts = [asyncio.create_task(client.post(f'/api/bots/{bot_id}/start')) for bot_id in ['default', second]]
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered)), 3)
            release.set()
            assert all(result.status_code == 200 for result in await asyncio.gather(*starts))
            assert all(runtime.bot.state == 'connected' for runtime in app.state.manager.runtimes.values())
            assert (await client.post('/api/bots/default/stop')).status_code == 200
            assert (await client.get(f'/api/bots/{second}/status')).json()['state'] == 'connected'
            assert app.state.manager.get(second).store.enabled()


@pytest.mark.asyncio
async def test_proactive_schedules_send_independently_with_same_recipient(tmp_path):
    manager = BotManager(tmp_path)
    second = (await manager.create('second'))['id']
    now = time.time()
    sends = []
    for index, runtime in enumerate(manager.runtimes.values()):
        config = runtime.store.load()
        config.qq.app_id = str(index + 1)
        config.proactive.enabled, config.proactive.recipient_id = True, 'same-user'
        config.proactive.active_start = config.proactive.active_end = '00:00'
        config.proactive.cooldown_minutes = 0
        config.proactive.greetings = []
        runtime.store.save(config)
        runtime.store.remember_contact(config.qq.app_id, 'same-user', now - 3600, 'same-message')
        runtime.store.set_capability(config.qq.app_id, 'same-user', 'supported', 'verified', now)
        runtime.store.set_idle_time(config.qq.app_id, 'same-user', now - 1)
        await runtime.bot.client.aclose()
        def transport(index):
            def respond(request):
                sends.append((index, json.loads(request.content)))
                return httpx.Response(200, json={'id': 'sent'})
            return respond
        runtime.bot.client = httpx.AsyncClient(transport=httpx.MockTransport(transport(index)))
        runtime.bot.access_token = AsyncMock(return_value=f'token-{index}')
        runtime.bot.request = AsyncMock(return_value={'message': {'content': f'hello-{index}'}, 'prompt_eval_count': index + 1, 'eval_count': 2})
        runtime.bot.state = 'connected'
        runtime.proactive.clock = lambda: now
    await asyncio.gather(*(runtime.proactive.tick() for runtime in manager.runtimes.values()))
    assert {body['content'] for _, body in sends} == {'hello-0', 'hello-1'}
    for runtime in manager.runtimes.values():
        assert runtime.store.stats()['sent'] == 1
        assert len(runtime.proactive.snapshot()['records']) == 1
    await manager.close()


def test_create_napcat_bot_preserves_transport_without_official_credentials(client):
    response = client.post('/api/bots', json={'name': 'NapCat 助手', 'transport': 'napcat'})
    assert response.status_code == 201
    bot_id = response.json()['id']
    config = client.get(f'/api/bots/{bot_id}/settings').json()
    assert config['transport'] == 'napcat'
    assert config['qq']['app_id'] == ''
    assert not config['qq']['secret_set']
    assert config['napcat']['self_id'] == ''
    assert client.get(f'/api/bots/{bot_id}/status').json()['state'] == 'stopped'
    bot = next(bot for bot in client.get('/api/bots').json()['bots'] if bot['id'] == bot_id)
    assert bot['transport'] == 'napcat'
    assert not bot['configured']
    assert client.patch(f'/api/bots/{bot_id}', json={'name': '改名后'}).status_code == 200
    assert client.get(f'/api/bots/{bot_id}/settings').json()['transport'] == 'napcat'


def test_create_bot_transport_defaults_and_validation(client):
    response = client.post('/api/bots', json={'name': '官方机器人'})
    assert response.status_code == 201
    assert client.get(f"/api/bots/{response.json()['id']}/settings").json()['transport'] == 'qq_official'
    count = len(client.get('/api/bots').json()['bots'])
    assert client.post('/api/bots', json={'name': '无效类型', 'transport': 'other'}).status_code == 422
    assert len(client.get('/api/bots').json()['bots']) == count
