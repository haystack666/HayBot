import asyncio
import json
import os
import sqlite3
from unittest.mock import AsyncMock
import httpx
import pytest
from websockets.asyncio.server import serve
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.store import Store
from app.bot import Bot


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-password-long-enough')
    with TestClient(create_app(tmp_path)) as c:
        yield c


def login(c):
    assert c.post('/api/login', json={'password': 'test-password-long-enough'}).status_code == 200


def test_frontend_routes_and_theme_script(tmp_path, monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-password-long-enough')
    static = tmp_path / 'static'
    static.mkdir()
    (static / 'index.html').write_text('<html><title>HayBot</title></html>')
    (static / 'theme.js').write_text('document.documentElement.classList.add("dark")')
    with TestClient(create_app(tmp_path / 'data', static)) as client:
        for path in ['/', '/overview', '/qq', '/ollama', '/rules', '/proactive', '/logs']:
            result = client.get(path)
            assert result.status_code == 200
            assert '<title>HayBot</title>' in result.text
            assert result.headers['Cache-Control'] == 'no-cache'
        script = client.get('/theme.js')
        assert script.status_code == 200 and 'text/javascript' in script.headers['Content-Type']
        assert 'classList.add' in script.text
        assert client.get('/api/settings').status_code == 401
        assert client.get('/missing-page').status_code == 404
        assert client.get('/api/missing').status_code == 401
        login(client)
        assert client.get('/api/missing').status_code == 404


def test_auth_origin_and_validation(client):
    assert client.get('/api/status').status_code == 401
    assert client.get('/api/health').status_code == 200
    assert client.post('/api/login', json={'password': 'bad'}).status_code == 401
    login(client)
    assert client.get('/api/status').status_code == 200
    assert client.post('/api/bot/stop', headers={'Origin': 'https://evil.example'}).status_code == 403
    c = Settings().model_dump()
    c['qq']['secret'] = 'must-not-appear'
    c['ollama']['url'] = 'file:///etc/passwd'
    result = client.put('/api/settings', json=c)
    assert result.status_code == 422
    assert 'must-not-appear' not in result.text
    assert client.post('/api/bot/start').status_code == 400
    client.post('/api/logout')
    assert client.get('/api/settings').status_code == 401


def test_settings_secret_persistence(client, tmp_path):
    login(client)
    config = Settings().model_dump()
    config['qq'].update(app_id='123456', secret='example-test-secret')
    response = client.put('/api/settings', json=config)
    assert response.status_code == 200
    assert response.json()['qq']['secret_set']
    assert 'example-test-secret' not in response.text
    config['qq']['secret'] = ''
    assert client.put('/api/settings', json=config).status_code == 200
    store = Store(tmp_path)
    assert store.load().qq.secret == 'example-test-secret'
    raw = store.db.execute('SELECT value FROM settings').fetchone()['value']
    assert 'example-test-secret' not in raw
    store.close()


def test_save_proactive_frequency_limits_and_safe_errors(client):
    login(client)
    config = Settings().model_dump()
    config['qq']['secret'] = 'private-secret-sentinel'
    config['rules']['prompt'] = 'private-prompt-sentinel'
    for values in [dict(daily_limit=0, cooldown_minutes=0, unanswered_limit=20,
                        idle_min_minutes=5, idle_max_minutes=1440),
                   dict(daily_limit=999, cooldown_minutes=1440, unanswered_limit=1,
                        idle_min_minutes=1440, idle_max_minutes=1440)]:
        config['proactive'].update(values)
        result = client.put('/api/settings', json=config)
        assert result.status_code == 200
        for key, value in values.items():
            assert result.json()['proactive'][key] == value
    for values, message in [(dict(cooldown_minutes=1441), '冷却时间'),
                            (dict(unanswered_limit=21), '1–20'),
                            (dict(daily_limit=-1), '0 表示不限次数'),
                            (dict(idle_min_minutes=1440, idle_max_minutes=5), '最长间隔不能小于最短间隔')]:
        body = {**config, 'proactive': {**config['proactive'], **values}}
        result = client.put('/api/settings', json=body)
        assert result.status_code == 422
        assert message in result.json()['detail']
        assert 'private-secret-sentinel' not in result.text
        assert 'private-prompt-sentinel' not in result.text


@pytest.mark.asyncio
async def test_reply_routes_dedup_and_member_isolation(tmp_path):
    store = Store(tmp_path)
    c = Settings()
    c.qq.group_reply = True
    c.rules.cooldown = 0
    c.ollama.model = 'test'
    store.save(c)
    requests = []
    def transport(req):
        if req.url.path.endswith('getAppAccessToken'):
            return httpx.Response(200, json={'access_token': 'fake-token', 'expires_in': 7200})
        requests.append(req)
        if req.url.path.endswith('/chat'):
            return httpx.Response(200, json={'message': {'content': '你好！'}, 'prompt_eval_count': 12, 'eval_count': 8})
        return httpx.Response(200, json={'id': 'sent'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        bot = Bot(store, client)
        event = {'t': 'C2C_MESSAGE_CREATE', 'd': {'id': 'msg1', 'content': '你好', 'author': {'user_openid': 'user1'}}}
        await bot.handle(event)
        await bot.handle(event)
        assert bot.stats['sent'] == 1
        assert requests[-1].url.path == '/v2/users/user1/messages'
        assert json.loads(requests[-1].content)['msg_id'] == 'msg1'
        group = {'t': 'GROUP_AT_MESSAGE_CREATE', 'd': {'id': 'msg2', 'content': '<@123> 你好', 'group_openid': 'group1', 'author': {'member_openid': 'member1'}}}
        await bot.handle(group)
        assert requests[-1].url.path == '/v2/groups/group1/messages'
        group['d']['id'], group['d']['author']['member_openid'] = 'msg3', 'member2'
        await bot.handle(group)
        # 新群成员不会看到其他成员的历史。
        assembled = json.loads(requests[-2].content)['messages']
        assert not any(m['role'] == 'assistant' for m in assembled)
        assert assembled[-1]['role'] == 'user'
        assert bot.stats['sent'] == 3
        assert bot.stats['received'] == 3
        assert bot.stats['input_tokens'] == 36
        assert bot.stats['output_tokens'] == 24
        assert bot.stats['total_tokens'] == 60
    store.close()
    reopened = Store(tmp_path)
    assert not reopened.claim('user1:msg1')
    assert len(reopened.history('user:user1:user1', 6)) == 2
    assert reopened.stats()['total_tokens'] == 60
    assert reopened.stats()['received'] == 3
    reopened.clear_history()
    assert reopened.history('user:user1:user1', 6) == []
    reopened.close()


def test_statistics_migration_and_restart(tmp_path):
    with sqlite3.connect(tmp_path / 'hayqqbot.sqlite3') as db:
        db.executescript('''
            CREATE TABLE seen(id TEXT PRIMARY KEY, at REAL);
            CREATE TABLE logs(id INTEGER PRIMARY KEY, at REAL, level TEXT, message TEXT);
            INSERT INTO seen VALUES ('legacy1', 1), ('legacy2', 2);
            INSERT INTO logs VALUES (1, 1, 'info', '单聊回复已发送'),
                (2, 2, 'info', '群聊回复已发送'), (3, 3, 'error', '回复失败：接口错误'),
                (4, 4, 'info', 'QQ 官方 WebSocket 已连接');
        ''')
    store = Store(tmp_path)
    assert store.stats() == dict(received=2, sent=2, errors=1, input_tokens=0, output_tokens=0, total_tokens=0)
    assert store.claim('new-message')
    assert not store.claim('new-message')
    store.record_result('sent', '单聊回复已发送')
    store.record_usage({'prompt_eval_count': 20, 'eval_count': 10})
    expected = dict(received=3, sent=3, errors=1, input_tokens=20, output_tokens=10, total_tokens=30)
    assert store.stats() == expected
    with store.db:
        store.db.execute('DELETE FROM seen')
        store.db.execute('DELETE FROM logs')
    store.clear_history()
    store.close()
    reopened = Store(tmp_path)
    assert reopened.stats() == expected
    reopened.record_usage({'prompt_eval_count': -1, 'eval_count': '50'})
    reopened.record_usage({'prompt_eval_count': None, 'eval_count': True})
    assert reopened.stats() == expected
    reopened.close()


def test_status_reads_cumulative_statistics(client, tmp_path):
    login(client)
    store = Store(tmp_path)
    store.claim('incoming')
    store.record_result('sent', '单聊回复已发送')
    store.record_usage({'prompt_eval_count': 7, 'eval_count': 3})
    expected = dict(received=1, sent=1, errors=0, input_tokens=7, output_tokens=3, total_tokens=10)
    assert client.get('/api/status').json()['stats'] == expected
    store.close()


@pytest.mark.asyncio
async def test_pending_message_failure_and_cancellation(tmp_path):
    store = Store(tmp_path)
    store.save(Settings())
    bot = Bot(store)
    event = {'t': 'C2C_MESSAGE_CREATE', 'd': {'id': 'msg1', 'content': 'hi', 'author': {'user_openid': 'u'}}}
    bot.request = AsyncMock(side_effect=ValueError('模型测试错误'))
    await bot.handle(event)
    assert bot.stats['sent'] == 0
    assert bot.stats['errors'] == 1
    assert not bot.pending
    assert store.history('user:u:u', 6) == []
    await bot.client.aclose()
    store.close()


@pytest.mark.asyncio
async def test_usage_is_recorded_when_qq_send_fails(tmp_path):
    store = Store(tmp_path)
    bot = Bot(store)
    bot.request = AsyncMock(return_value={'message': {'content': '测试回复'}, 'prompt_eval_count': 30, 'eval_count': 15})
    bot.api = AsyncMock(side_effect=ValueError('QQ 发送失败'))
    event = {'t': 'C2C_MESSAGE_CREATE', 'd': {'id': 'send-failed', 'content': '测试', 'author': {'user_openid': 'u'}}}
    await bot.handle(event)
    assert bot.stats == dict(received=1, sent=0, errors=1, input_tokens=30, output_tokens=15, total_tokens=45)
    await bot.handle(event)
    assert bot.stats['total_tokens'] == 45
    await bot.client.aclose()
    store.close()


@pytest.mark.asyncio
async def test_qq_business_error_on_http_200(tmp_path):
    store = Store(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'code': 100016, 'message': 'sensitive'}))) as client:
        bot = Bot(store, client)
        with pytest.raises(ValueError, match='100016') as exc:
            await bot.access_token()
        assert 'sensitive' not in str(exc.value)
    store.close()


@pytest.mark.asyncio
async def test_websocket_identify_heartbeat_and_stop(tmp_path, monkeypatch):
    store = Store(tmp_path)
    bot = Bot(store)
    packets = []
    heartbeat_received = asyncio.Event()

    async def gateway(ws):
        await ws.send(json.dumps({'op': 10, 'd': {'heartbeat_interval': 1000}}))
        auth = json.loads(await ws.recv())
        packets.append(auth)
        await ws.send(json.dumps({'op': 0, 't': 'READY', 's': 7, 'd': {'session_id': 'test-session'}}))
        p = json.loads(await ws.recv())
        packets.append(p)
        await ws.send(json.dumps({'op': 11}))
        heartbeat_received.set()
        await ws.wait_closed()

    async with serve(gateway, '127.0.0.1', 0) as server:
        port = server.sockets[0].getsockname()[1]
        bot.api = AsyncMock(return_value={'url': f'ws://127.0.0.1:{port}'})
        bot.access_token = AsyncMock(return_value='test-token')
        bot.task = asyncio.create_task(bot.run())
        await asyncio.wait_for(heartbeat_received.wait(), timeout=5)
        assert bot.state == 'connected'
        assert packets[0]['op'] == 2
        assert packets[0]['d']['token'] == 'QQBot test-token'
        assert packets[0]['d']['intents'] == 1 << 25
        assert packets[1] == {'op': 1, 'd': 7}
        await bot.stop()
        assert bot.state == 'stopped'
        assert bot.session is None
    await bot.client.aclose()
    store.close()
