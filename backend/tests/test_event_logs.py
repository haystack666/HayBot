import json
import sqlite3
from unittest.mock import AsyncMock

import httpx
import pytest
from app.bot import Bot
from app.store import Store
from app.providers import ProviderConfig, ProviderStore
from test_providers import client


def test_structured_logs_filter_paginate_and_keep_legacy(tmp_path):
    store = Store(tmp_path)
    store.log('info', '旧格式事件')
    store.log('info', '模型调用成功', category='model', event='model.completed', details={'model': 'gemma-test', 'duration_ms': 1234, 'input_tokens': 21})
    store.log('error', '连接失败', category='qq', event='qq.failed', details={'error_type': 'ConnectError'})
    result = store.events.query(category='model', query='gemma-test')
    assert result['total'] == 1 and result['items'][0]['details']['duration_ms'] == 1234
    latest = store.events.query(limit=1)
    older = store.events.query(limit=10, before=latest['items'][0]['id'])
    assert len(older['items']) == 2 and older['items'][-1]['message'] == '旧格式事件'
    after = store.events.query(after=older['items'][0]['id'])
    assert len(after['items']) == 1 and after['items'][0]['category'] == 'qq'
    assert store.events.query(level='error')['summary']['error'] == 1
    store.close()


def test_legacy_log_table_is_migrated_without_losing_history(tmp_path):
    db = sqlite3.connect(tmp_path / 'hayqqbot.sqlite3')
    db.executescript("CREATE TABLE logs (id INTEGER PRIMARY KEY,at REAL,level TEXT,message TEXT); INSERT INTO logs VALUES (1,1,'info','旧事件');")
    db.close()
    store = Store(tmp_path)
    assert store.events.query()['items'][0]['message'] == '旧事件'
    store.log('info', '新事件', category='memory', details={'count': 2})
    store.close(); store = Store(tmp_path)
    assert store.events.query()['total'] == 2
    store.close()


def test_credentials_and_unapproved_payloads_are_never_written_or_returned(tmp_path):
    store = Store(tmp_path); c = store.load(); c.qq.secret = 'qq-secret-sensitive-value'; store.save(c)
    store.events.secret_resolver = lambda: ['custom-provider-key']
    store.log('error', '失败 qq-secret-sensitive-value custom-provider-key sk-1234567890123456', category='model',
              details={'error_type': 'ConnectError', 'reason': 'Bearer private-access-token', 'api_key': 'raw-forbidden', 'prompt': 'private-persona', 'headers': {'Authorization': 'do-not-store'}})
    raw = store.db.execute('SELECT message,details FROM logs').fetchone()
    output = json.dumps(store.events.query())
    for secret in ('qq-secret-sensitive-value', 'custom-provider-key', 'sk-1234567890123456', 'private-access-token', 'raw-forbidden', 'private-persona', 'do-not-store'):
        assert secret not in str(tuple(raw)) and secret not in output
    store.close()


def test_event_api_auth_scope_details_and_chat_link(client):
    manager = client.app.state.manager
    runtime = client.portal.call(manager.get, 'default')
    def seed():
        store = runtime.store
        owner = store.scopes.ensure('', 'user', 'alice', 'alice', 'Alice')
        store.chat.record('', 'user', 'alice', 'user', '你好，请推荐一本书', 'in::alice:m1', sender_id='alice', source='incoming', status='received')
        mid = store.db.execute('SELECT MAX(id) FROM chat_messages').fetchone()[0]
        store.log('info', '单聊回复已发送', category='message', event='message.sent', details={'scope_id': owner['id'], 'incoming_id': mid, 'trace_id': 'test-trace'})
    client.portal.call(seed)
    result = client.get('/api/bots/default/logs')
    assert result.status_code == 200
    event = next(item for item in result.json()['items'] if item['event'] == 'message.sent')
    detail = client.get(f'/api/bots/default/logs/{event["id"]}').json()
    assert detail['messages'][0]['content'] == '你好，请推荐一本书'
    assert detail['conversation_id']
    other = client.post('/api/bots', json={'name': '另一个Bot'}).json()['id']
    assert not any(item.get('trace_id') == 'test-trace' for item in client.get(f'/api/bots/{other}/logs').json()['items'])
    assert client.get('/api/bots/default/logs?before=1&after=2').status_code == 400
    client.post('/api/logout')
    assert client.get('/api/bots/default/logs').status_code == 401


def test_log_scope_cannot_resolve_another_users_message(tmp_path):
    store = Store(tmp_path)
    alice = store.scopes.ensure('', 'user', 'alice', 'alice')['id']
    store.chat.record('', 'user', 'bob', 'user', 'Bob 私聊内容', 'in::bob:m', sender_id='bob', source='incoming', status='received')
    mid = store.db.execute('SELECT MAX(id) FROM chat_messages').fetchone()[0]
    event = store.log('info', '来源测试', details={'scope_id': alice, 'incoming_id': mid})
    assert store.events.detail(event)['messages'] == []
    config = store.load(); config.qq.app_id = '222'; store.save(config)
    # Old app-id-specific events remain in SQLite, but never resolve into the new identity.
    assert store.events.detail(event)['messages'] == []
    store.close()


@pytest.mark.asyncio
async def test_concurrent_messages_have_separate_traces_and_model_details(tmp_path):
    import asyncio
    catalog = ProviderStore(tmp_path)
    pid = catalog.save(ProviderConfig(type='openai_chat', base_url='https://model.test/v1', api_key='custom-log-test-secret'))
    store = Store(tmp_path / 'bot'); c = store.load(); c.qq.app_id = '111'; c.ollama.provider_id = pid; c.ollama.model = 'test-model'; c.rules.cooldown = 0; store.save(c)
    entered, both = set(), asyncio.Event()
    async def transport(request):
        body = json.loads(request.content); question = body['messages'][-1]['content']; entered.add(question)
        if len(entered) == 2: both.set()
        await asyncio.wait_for(both.wait(), 2)
        return httpx.Response(200, json={'choices': [{'message': {'content': '收到 ' + question}}], 'usage': {'prompt_tokens': 12, 'completion_tokens': 5}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        bot = Bot(store, client, providers=catalog); bot.api = AsyncMock(return_value={'id': 'accepted'})
        await asyncio.gather(*(bot.handle({'t': 'C2C_MESSAGE_CREATE', 'd': {'id': 'm1', 'content': user + ' question', 'author': {'user_openid': user}}}) for user in ('alice', 'bob')))
        events = store.events.query(limit=100)['items']
        completed = [event for event in events if event['event'] == 'model.completed']
        assert len(completed) == 2
        assert len({event['trace_id'] for event in completed}) == 2
        for event in completed:
            assert event['details']['model'] == 'test-model'
            assert event['details']['input_tokens'] == 12 and event['details']['output_tokens'] == 5
            assert event['details']['duration_ms'] >= 0
            detail = store.events.detail(event['id'])
            assert detail['messages'] and len(detail['related']) >= 3
        assert 'custom-log-test-secret' not in json.dumps(events)
    store.close(); catalog.close()


def test_redaction_snapshot_is_reused_but_refreshes_after_key_changes(tmp_path):
    store = Store(tmp_path)
    calls = []
    keys = ['first-private-key']
    def resolve():
        calls.append(True)
        return keys
    store.events.secret_resolver = resolve
    for i in range(10):
        store.log('info', 'test', details={'model': 'model', 'provider': 'provider', 'reason': 'first-private-key'})
    calls.clear()
    result = store.events.query()
    assert len(calls) == 1 and 'first-private-key' not in json.dumps(result)
    keys[:] = ['second-private-key']
    event = store.log('info', 'second-private-key')
    assert store.events.detail(event)['message'] == '[已隐藏]'
    store.close()


def test_validation_error_details_exclude_raw_inputs():
    from app.event_logs import exception_details
    from pydantic import BaseModel, ValidationError
    class Payload(BaseModel):
        count: int
    try:
        Payload(count='private-persona-or-input')
    except ValidationError as error:
        details = exception_details(error)
    assert details['error_type'] == 'ValidationError'
    assert 'count' in details['reason']
    assert 'private-persona-or-input' not in json.dumps(details)


def test_app_id_change_hides_previous_identity_events(tmp_path):
    store = Store(tmp_path)
    config = store.load(); config.qq.app_id = '111'; store.save(config)
    event = store.log('info', 'first-app-only')
    config.qq.app_id = '222'; store.save(config)
    assert store.events.detail(event) is None
    assert store.events.query()['total'] == 0
    store.close()


@pytest.mark.asyncio
async def test_retrieval_logs_success_usage_and_failure_without_text(tmp_path):
    store = Store(tmp_path); bot = Bot(store)
    provider = ProviderConfig(type='openai_embedding', name='测试嵌入', base_url='https://embedding.test/v1')
    sid = store.scopes.ensure('', 'user', 'alice', 'alice')['id']
    bot.request = AsyncMock(return_value={'data': [{'index': 0, 'embedding': [1., 2.]}], 'usage': {'prompt_tokens': 13}})
    await bot.memory.retrieval_call('embedding', sid, provider, 'test-embed', ['never-save-this-input'], 'query', 5)
    done = store.events.query(category='model')['items'][0]
    assert done['event'] == 'embedding.completed'
    assert done['details']['input_tokens'] == 13 and done['details']['duration_ms'] >= 0
    request = httpx.Request('POST', 'https://embedding.test/v1/embeddings')
    bot.request = AsyncMock(side_effect=httpx.HTTPStatusError('limited', request=request, response=httpx.Response(429, request=request)))
    with pytest.raises(httpx.HTTPStatusError):
        await bot.memory.retrieval_call('embedding', sid, provider, 'test-embed', ['never-save-this-input'], 'query', 5)
    error = store.events.query(level='error')['items'][0]
    assert error['details']['http_status'] == 429 and error['details']['error_type'] == 'HTTPStatusError'
    provider = ProviderConfig(type='xinference_rerank', name='测试重排', base_url='https://rank.test/v1')
    bot.request = AsyncMock(return_value={'results': [{'index': 0, 'relevance_score': .9}], 'usage': {'prompt_tokens': 9}})
    await bot.memory.retrieval_call('rerank', sid, provider, 'test-rank', 'never-save-this-input', ['never-save-this-document'], 1, 5)
    assert store.events.query()['items'][0]['event'] == 'rerank.completed'
    assert 'never-save-this-input' not in json.dumps(store.events.query())
    assert 'never-save-this-document' not in json.dumps(store.events.query())
    await bot.client.aclose(); store.close()


def test_legacy_migration_binds_known_app_id(tmp_path):
    store = Store(tmp_path); config = store.load(); config.qq.app_id = '111'; store.save(config); store.close()
    db = sqlite3.connect(tmp_path / 'hayqqbot.sqlite3')
    db.executescript("DROP TABLE logs; CREATE TABLE logs (id INTEGER PRIMARY KEY,at REAL,level TEXT,message TEXT); INSERT INTO logs VALUES (1,1,'info','历史事件');")
    db.close(); store = Store(tmp_path)
    assert store.events.detail(1)['app_id'] == '111'
    config = store.load(); config.qq.app_id = '222'; store.save(config)
    assert store.events.detail(1) is None
    store.close()


@pytest.mark.asyncio
async def test_unknown_proactive_recipient_does_not_leave_log_context(tmp_path):
    from app.proactive import ProactiveService
    store = Store(tmp_path); bot = Bot(store)
    service = ProactiveService(store, bot)
    await service.execute('missing-contact', store.load(), 'missing', 'idle', 'test', generated=False)
    assert store.events.current.get() == {}
    event = store.log('info', 'later unrelated worker event')
    assert 'push_id' not in store.events.detail(event)['details']
    await bot.client.aclose(); store.close()
