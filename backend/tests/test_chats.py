import json
import time
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.bot import Bot
from app.main import create_app
from app.store import Store

PASSWORD = 'test-password-long-enough'


def seed(store, content, index=1, target='owner', role='user', app_id='111'):
    return store.chat.record(app_id, 'user', target, role, content, f'test-{target}-{index}',
                             sender_id=target if role == 'user' else '', at=time.time(), source='incoming' if role == 'user' else 'reply',
                             status='received' if role == 'user' else 'sent')


def test_legacy_context_import_is_labelled_deduped_and_separate(tmp_path):
    store = Store(tmp_path)
    config = store.load(); config.qq.app_id = '111'; store.save(config)
    context = [{'role': 'system', 'content': 'private-system-must-not-appear'},
               {'role': 'user', 'content': '以前的问题', 'images': ['private-base64-must-not-appear']},
               {'role': 'assistant', 'content': '以前的回答'},
               {'role': 'user', 'content': '[按设置发送的主动消息]'},
               {'role': 'assistant', 'content': '主动问候'}]
    store.save_history('user:owner:owner', context, 8)
    with store.db:
        store.db.execute("DELETE FROM chat_meta WHERE key='legacy_imported'")
        store.db.execute("INSERT INTO proactive_events(event_key,app_id,recipient,kind,created,status,content,sent_at) VALUES ('old','111','owner','idle',?,'sent','主动问候',?)", (time.time(), time.time()))
    store.close()
    store = Store(tmp_path)
    conversation = store.chat.conversations('111')['items'][0]
    items = store.chat.messages('111', conversation['id'])['items']
    assert [message['content'] for message in items] == ['以前的问题', '以前的回答', '主动问候']
    assert all(message['at'] is None and message['status'] == 'historical' for message in items[:2])
    assert items[2]['at'] is not None and items[2]['source'] == 'idle'
    assert 'private-system' not in json.dumps(items) and 'base64' not in json.dumps(items)
    store.clear_history(); store.close()
    store = Store(tmp_path)
    assert store.chat.messages('111', conversation['id'])['conversation']['message_count'] == 3
    assert not store.history('user:owner:owner', 8)
    store.close()


@pytest.mark.asyncio
async def test_incoming_messages_survive_disabled_replies_cooldown_and_dedupe(tmp_path):
    store = Store(tmp_path)
    config = store.load(); config.qq.app_id = '111'; config.qq.private_reply = False; store.save(config)
    bot = Bot(store)
    bot.request = AsyncMock()
    event = {'t': 'C2C_MESSAGE_CREATE', 'd': {'id': 'one', 'content': '没有开启回复也要记录', 'author': {'user_openid': 'owner', 'username': '测试用户'}}}
    await bot.handle(event); await bot.handle(event)
    config.qq.private_reply = True; store.save(config)
    bot.last['user:owner:owner'] = time.time()
    event['d'].update(id='two', content='冷却期间的消息')
    await bot.handle(event)
    conversation = store.chat.conversations('111')['items'][0]
    assert conversation['title'] == '测试用户' and conversation['message_count'] == 2
    assert [row['content'] for row in store.chat.messages('111', conversation['id'])['items']] == ['没有开启回复也要记录', '冷却期间的消息']
    assert store.stats()['received'] == 0
    bot.request.assert_not_called()
    await bot.client.aclose(); store.close()


@pytest.mark.asyncio
async def test_successful_replies_are_archived_without_context_and_failed_drafts_are_not(tmp_path):
    store = Store(tmp_path)
    config = store.load(); config.qq.app_id = '111'; config.rules.rounds = 0; config.rules.cooldown = 0; store.save(config)
    bot = Bot(store)
    bot.request = AsyncMock(return_value={'message': {'content': '<script>literal text only</script>'}})
    bot.api = AsyncMock(return_value={'id': 'sent'})
    def event(message_id, content):
        return {'t': 'C2C_MESSAGE_CREATE', 'd': {'id': message_id, 'content': content, 'author': {'user_openid': 'owner'}}}
    await bot.handle(event('first', '你好'))
    bot.api.side_effect = httpx.ReadTimeout('failed')
    await bot.handle(event('second', '发送失败的这一条'))
    conversation = store.chat.conversations('111')['items'][0]
    items = store.chat.messages('111', conversation['id'])['items']
    assert [row['role'] for row in items] == ['user', 'assistant', 'user']
    assert items[1]['content'] == '<script>literal text only</script>'
    assert not store.history('user:owner:owner', 10)
    store.clear_history()
    assert store.chat.messages('111', conversation['id'])['conversation']['message_count'] == 3
    await bot.client.aclose(); store.close()


def test_group_members_share_archive_conversation_but_not_other_groups(tmp_path):
    store = Store(tmp_path)
    for target, sender in [('group-a', 'user-1'), ('group-a', 'user-2'), ('group-b', 'user-1')]:
        store.chat.record('111', 'group', target, 'user', sender, f'{target}-{sender}', sender_id=sender, at=time.time(), source='incoming', status='received')
    rows = store.chat.conversations('111')['items']
    assert len(rows) == 2
    group_a = next(row for row in rows if row['target_id'] == 'group-a')
    assert {row['sender_id'] for row in store.chat.messages('111', group_a['id'])['items']} == {'user-1', 'user-2'}
    store.close()


def test_image_records_use_count_without_saving_urls_or_base64(tmp_path):
    store = Store(tmp_path)
    config = store.load(); config.qq.app_id = '111'; store.save(config)
    bot = Bot(store)
    bot.capture_incoming({'t': 'C2C_MESSAGE_CREATE', 'd': {'id': 'image', 'content': '', 'author': {'user_openid': 'owner'},
        'attachments': [{'content_type': 'image/png', 'url': 'https://multimedia.nt.qq.com/test.png'}]}})
    conversation = store.chat.conversations('111')['items'][0]
    item = store.chat.messages('111', conversation['id'])['items'][0]
    assert item['attachment_count'] == 1 and item['content'] == ''
    assert 'https://' not in json.dumps(item)
    # This test only calls synchronous capture; no client network is used.
    import asyncio
    asyncio.run(bot.client.aclose()); store.close()


def test_proactive_archive_only_records_confirmed_send_once(tmp_path):
    store = Store(tmp_path)
    event = store.reserve_proactive('push', '111', 'owner', 'reminder', time.time())
    store.update_proactive(event, 'sending', content='该喝水了')
    assert not store.chat.conversations('111')['items']
    store.proactive_sent(event, time.time(), time.time() + 1000)
    store.proactive_sent(event, time.time(), time.time() + 1000)
    conversation = store.chat.conversations('111')['items'][0]
    assert conversation['message_count'] == 1
    item = store.chat.messages('111', conversation['id'])['items'][0]
    assert item['content'] == '该喝水了' and item['source'] == 'reminder' and item['status'] == 'sent'
    store.close()


def test_chat_apis_page_both_directions_and_stay_in_bot_scope(tmp_path, monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', PASSWORD)
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/api/bots/default/conversations').status_code == 401
        client.post('/api/login', json={'password': PASSWORD})
        second = client.post('/api/bots', json={'name': 'second'}).json()['id']
        for directory in [tmp_path, tmp_path / 'bots' / second]:
            store = Store(directory)
            config = store.load(); config.qq.app_id = '111' if directory == tmp_path else '222'; store.save(config)
            for index in range(7): seed(store, f'message-{index}', index, app_id=config.qq.app_id)
            store.close()
        first = client.get('/api/bots/default/conversations').json()['items'][0]
        path = f'/api/bots/default/conversations/{first["id"]}/messages'
        latest = client.get(path + '?limit=2').json()
        assert [row['content'] for row in latest['items']] == ['message-5', 'message-6'] and latest['has_more']
        earlier = client.get(path + f'?limit=2&before={latest["items"][0]["id"]}').json()
        assert [row['content'] for row in earlier['items']] == ['message-3', 'message-4']
        forward = client.get(path + f'?limit=2&after={earlier["items"][0]["id"]}').json()
        assert [row['content'] for row in forward['items']] == ['message-4', 'message-5'] and forward['has_more']
        assert client.get(f'/api/bots/{second}/conversations/{first["id"]}/messages').status_code == 404
        assert client.get(path + '?before=1&after=2').status_code == 400
        assert client.get(path + '?limit=201').status_code == 422
        assert client.delete('/api/bots/default/history').status_code == 200
        assert client.get(path).json()['conversation']['message_count'] == 7
        assert client.get('/api/bots/missing/conversations').status_code == 404


def test_permanent_delete_requires_archive_and_name_and_never_deletes_other_bots(tmp_path, monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', PASSWORD)
    with TestClient(create_app(tmp_path)) as client:
        client.post('/api/login', json={'password': PASSWORD})
        second = client.post('/api/bots', json={'name': '保留的机器人'}).json()['id']
        directory = tmp_path / 'bots' / second
        store = Store(directory); seed(store, 'keep'); store.close()
        assert client.request('DELETE', '/api/bots/default', json={'name': '默认机器人'}).status_code == 409
        assert client.post('/api/bots/default/archive').status_code == 200
        assert client.request('DELETE', '/api/bots/default', json={'name': 'wrong'}).status_code == 400
        assert (tmp_path / 'secret.key').exists()
        assert client.request('DELETE', '/api/bots/default', json={'name': '默认机器人'}).status_code == 200
        assert not (tmp_path / 'hayqqbot.sqlite3').exists() and not (tmp_path / 'secret.key').exists()
        assert (directory / 'hayqqbot.sqlite3').exists() and (tmp_path / 'bots.sqlite3').exists()
        store = Store(directory); assert store.chat.conversations('111')['items'][0]['message_count'] == 1; store.close()
        assert client.get('/api/settings').status_code == 404
    with TestClient(create_app(tmp_path)) as client:
        client.post('/api/login', json={'password': PASSWORD})
        assert [bot['id'] for bot in client.get('/api/bots').json()['bots']] == [second]
        client.post(f'/api/bots/{second}/archive')
        assert client.request('DELETE', f'/api/bots/{second}', json={'name': '保留的机器人'}).status_code == 200
        assert not directory.exists()
    with TestClient(create_app(tmp_path)) as client:
        client.post('/api/login', json={'password': PASSWORD})
        assert client.get('/api/bots').json()['bots'] == []
        assert not (tmp_path / 'secret.key').exists()


@pytest.mark.asyncio
async def test_debounced_websocket_archives_every_message_without_using_workers(tmp_path):
    import asyncio
    from websockets.asyncio.server import serve
    store = Store(tmp_path)
    config = store.load(); config.qq.app_id = '111'; store.save(config)
    bot = Bot(store)
    hold = asyncio.Event()
    async def blocked_handler(payload, **kwargs):
        await hold.wait()
    bot.handle = blocked_handler
    async def gateway(ws):
        await ws.send(json.dumps({'op': 10, 'd': {'heartbeat_interval': 1000}}))
        await ws.recv()
        await ws.send(json.dumps({'op': 0, 't': 'READY', 's': 1, 'd': {'session_id': 'test'}}))
        for index in range(5):
            await ws.send(json.dumps({'op': 0, 't': 'C2C_MESSAGE_CREATE', 's': index + 2, 'd': {
                'id': f'burst-{index}', 'content': str(index), 'author': {'user_openid': 'owner'}}}))
        await ws.wait_closed()
    async with serve(gateway, '127.0.0.1', 0) as server:
        bot.api = AsyncMock(return_value={'url': f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'})
        bot.access_token = AsyncMock(return_value='test')
        bot.task = asyncio.create_task(bot.run())
        for _ in range(100):
            rows = store.chat.conversations('111')['items']
            if rows and rows[0]['message_count'] == 5: break
            await asyncio.sleep(0.01)
        assert len(bot.jobs) == 0
        assert bot.inbox.snapshot()['queued'] == 5
        items = store.chat.messages('111', rows[0]['id'])['items']
        assert [row['content'] for row in items] == ['0', '1', '2', '3', '4']
        await bot.stop()
    await bot.client.aclose(); store.close()
