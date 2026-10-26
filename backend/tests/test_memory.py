import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from app.bot import Bot
from app.config import Settings
from app.store import Store
from app.providers import ProviderConfig, ProviderStore
from test_providers import client


def scope(store, user='alice', kind='user', target=None):
    return store.scopes.ensure(store.load().qq.app_id, kind, target or user, user)['id']


def test_memory_is_scoped_by_bot_app_user_and_group(tmp_path):
    from app.memory_store import MemoryStore
    store = Store(tmp_path)
    alice, bob, group = scope(store), scope(store, 'bob'), scope(store, 'alice', 'group', 'g1')
    memories = MemoryStore(store)
    item = memories.put(alice, 'preference', 'drink', '我不喝咖啡', [])
    assert memories.list(alice)['items'][0]['content'] == '我不喝咖啡'
    assert not memories.list(bob)['items'] and not memories.list(group)['items']
    with pytest.raises(ValueError):
        memories.get(bob, item['id'])
    config = store.load(); config.qq.app_id = '222'; store.save(config)
    with pytest.raises(ValueError):
        store.scopes.get(alice)
    other = Store(tmp_path / 'other')
    assert not MemoryStore(other).list(scope(other))['items']
    other.close(); store.close()


def test_corrections_audit_and_forgetting_prevent_replay(tmp_path):
    from app.memory_store import MemoryStore, StaleMemory
    store = Store(tmp_path); sid = scope(store); memories = MemoryStore(store)
    first = memories.put(sid, 'preference', 'drink', '喜欢咖啡', [])
    epoch = memories.epoch(sid)
    second = memories.put(sid, 'preference', 'drink', '现在不喝咖啡', [])
    assert second['id'] == first['id'] and second['revision'] == 2
    assert len(memories.audit(sid)) == 2
    memories.forget(sid, first['id'])
    assert not memories.list(sid)['items']
    assert memories.put(sid, 'preference', 'drink', '喜欢咖啡', []) is None
    with pytest.raises(StaleMemory):
        memories.put(sid, 'fact', 'other', '排队中的旧提取', [], expected_epoch=epoch)
    restored = memories.put(sid, 'preference', 'drink', '记住我只喝茶', [], explicit=True)
    assert restored['content'] == '记住我只喝茶'
    store.close()


def test_forget_clears_summary_context_and_vector_but_keeps_chat_archive(tmp_path):
    from app.memory_store import MemoryStore
    store = Store(tmp_path); sid = scope(store); memories = MemoryStore(store)
    store.save_history('user:alice:alice', [{'role': 'user', 'content': '旧偏好'}], 6)
    store.chat.record('', 'user', 'alice', 'user', '原始消息', 'source', sender_id='alice')
    item = memories.put(sid, 'fact', 'profile', '用户资料', [])
    memories.set_summary(sid, '包含旧偏好的摘要', [], memories.epoch(sid))
    memories.save_vector(sid, item['id'], 'fingerprint', [1., 0.], item['revision'], memories.epoch(sid))
    memories.forget(sid, item['id'])
    assert not memories.summary(sid)
    assert not store.history('user:alice:alice', 6)
    assert memories.vectors(sid, 'fingerprint') == []
    assert store.db.execute('SELECT COUNT(*) FROM chat_messages').fetchone()[0] == 1
    store.close()


def test_stale_vectors_and_other_index_versions_are_ignored(tmp_path):
    from app.memory_store import MemoryStore
    store = Store(tmp_path); sid = scope(store); memories = MemoryStore(store)
    item = memories.put(sid, 'fact', 'profile', '原文', [])
    memories.save_vector(sid, item['id'], 'old-model', [1., 0.], 1, memories.epoch(sid))
    assert not memories.vectors(sid, 'new-model')
    memories.put(sid, 'fact', 'profile', '更正文', [])
    assert not memories.vectors(sid, 'old-model')
    assert not memories.save_vector(sid, item['id'], 'new-model', [1., 0.], 1, memories.epoch(sid))
    store.close()


def test_commitments_require_absolute_time_and_survive_reopening(tmp_path):
    from app.memory_store import MemoryStore
    store = Store(tmp_path); sid = scope(store); memories = MemoryStore(store)
    with pytest.raises(ValueError):
        memories.put(sid, 'commitment', 'walk', '明晚散步', [], due_at='明晚')
    memories.put(sid, 'commitment', 'walk', '一起散步', [], due_at='2026-10-25T19:30:00+08:00', end_at='2026-10-25T20:00:00+08:00')
    store.close(); store = Store(tmp_path); memories = MemoryStore(store)
    assert memories.appointments(sid, '2026-10-25', 'Asia/Shanghai')[0]['content'] == '一起散步'
    assert not memories.appointments(scope(store, 'bob'), '2026-10-25', 'Asia/Shanghai')
    store.close()


@pytest.mark.asyncio
async def test_recall_reranks_then_forgetting_invalidates_context(tmp_path):
    from app.memory import MemoryService
    catalog = ProviderStore(tmp_path)
    eid = catalog.save(ProviderConfig(type='openai_embedding', base_url='https://embed.test/v1'))
    rid = catalog.save(ProviderConfig(type='xinference_rerank', base_url='https://rank.test/v1'))
    store = Store(tmp_path / 'bot'); c = Settings(); c.memory.enabled = True
    c.memory.embedding.provider_id = eid; c.memory.embedding.model = 'embed'
    c.memory.rerank.provider_id = rid; c.memory.rerank.model = 'rank'; c.memory.top_k = 1; store.save(c)
    bot = Bot(store, providers=catalog); memory = bot.memory; sid = scope(store)
    tea = memory.data.put(sid, 'preference', 'tea', '用户只喝茶', [])
    memory.data.put(sid, 'fact', 'bike', '用户有自行车', [])
    async def request(method, url, **kwargs):
        if 'embed.test' in url:
            return {'data': [{'index': i, 'embedding': [1., 0.]} for i, _ in enumerate(kwargs['json']['input'])]}
        assert kwargs['json']['query'] == '喝什么'
        index = kwargs['json']['documents'].index('用户只喝茶')
        return {'results': [{'index': index, 'relevance_score': .9}]}
    bot.request = request
    await memory.index(sid)
    text = await memory.context(sid, '喝什么')
    assert '用户只喝茶' in text and '用户有自行车' not in text
    memory.data.forget(sid, tea['id'])
    assert '用户只喝茶' not in await memory.context(sid, '喝什么')
    await bot.client.aclose(); store.close(); catalog.close()


@pytest.mark.asyncio
async def test_extraction_uses_delivered_sources_and_rejects_other_users(tmp_path):
    store = Store(tmp_path); sid = scope(store); other = scope(store, 'bob')
    c = store.load(); c.memory.embedding.provider_id = 'a' * 32; c.memory.embedding.model = 'embed'; c.memory.enabled = True; store.save(c)
    bot = Bot(store)
    store.chat.record('', 'user', 'alice', 'user', '我不喝咖啡', 'in::alice:m1', sender_id='alice', source='incoming', status='received')
    store.chat.record('', 'user', 'alice', 'assistant', '好，我记住啦', 'reply::alice:m1', source='reply', status='sent')
    mids = [row['id'] for row in store.db.execute('SELECT id FROM chat_messages')]
    assert bot.memory.enqueue(sid, 'pair1', mids, immediate=True)
    assert not bot.memory.enqueue(sid, 'pair1', mids, immediate=True)
    with pytest.raises(ValueError):
        bot.memory.enqueue(other, 'bad', mids)
    bot.generate = AsyncMock(return_value={'message': {'content': json.dumps({'summary': '用户不喝咖啡', 'memories': [{'category': 'preference', 'key': 'coffee', 'content': '用户不喝咖啡', 'evidence': mids}]})}})
    jobs = [dict(row) for row in store.db.execute('SELECT * FROM memory_jobs')]
    await bot.memory.extract(sid, jobs)
    assert bot.memory.data.list(sid)['items'][0]['content'] == '用户不喝咖啡'
    assert bot.memory.data.summary(sid) == '用户不喝咖啡'
    await bot.client.aclose(); store.close()


@pytest.mark.asyncio
async def test_forget_during_extraction_cannot_restore_summary_or_fact(tmp_path):
    from app.memory_store import StaleMemory
    store = Store(tmp_path); sid = scope(store)
    c = store.load(); c.memory.embedding.provider_id = 'a' * 32; c.memory.embedding.model = 'embed'; c.memory.enabled = True; store.save(c)
    bot = Bot(store); item = bot.memory.data.put(sid, 'preference', 'coffee', '用户喝咖啡', [])
    store.chat.record('', 'user', 'alice', 'user', '我喝咖啡', 'in::alice:m1', sender_id='alice', source='incoming', status='received')
    mid = store.db.execute('SELECT MAX(id) FROM chat_messages').fetchone()[0]
    bot.memory.enqueue(sid, 'pair1', [mid], immediate=True)
    async def generate(*args, **kwargs):
        bot.memory.data.forget(sid, item['id'])
        return {'message': {'content': json.dumps({'summary': '用户喝咖啡', 'memories': [{'category': 'preference', 'key': 'coffee', 'content': '用户喝咖啡', 'evidence': [mid]}]})}}
    bot.generate = generate
    jobs = [dict(row) for row in store.db.execute('SELECT * FROM memory_jobs')]
    with pytest.raises(StaleMemory):
        await bot.memory.extract(sid, jobs)
    assert not bot.memory.data.summary(sid) and not bot.memory.data.list(sid)['items']
    await bot.client.aclose(); store.close()


def test_memory_settings_validate_provider_purposes_and_references(client):
    embedding = client.post('/api/providers', json={'type': 'openai_embedding', 'base_url': 'https://embedding.test/v1'}).json()['id']
    reranker = client.post('/api/providers', json={'type': 'xinference_rerank', 'base_url': 'http://xinference.test:9997'}).json()['id']
    config = client.get('/api/settings').json(); config['qq'].pop('secret_set', None)
    config['memory'].update(enabled=True, embedding={'provider_id': embedding, 'model': 'embed'}, rerank={'provider_id': reranker, 'model': 'rank'})
    assert client.put('/api/settings', json=config).status_code == 200
    assert client.delete('/api/providers/' + embedding).status_code == 409
    config['memory']['embedding']['provider_id'] = reranker
    assert client.put('/api/settings', json=config).status_code == 400


def test_scoped_memory_api_requires_owner_and_preserves_source(client):
    runtime = client.portal.call(client.app.state.manager.get, 'default')
    sid = client.portal.call(lambda: scope(runtime.store))
    other = client.portal.call(lambda: scope(runtime.store, 'bob'))
    base = '/api/bots/default/memory'
    assert client.get(base).status_code == 400
    response = client.post(base + '?scope_id=' + sid, json={'category': 'preference', 'content': '用户不喝咖啡'})
    assert response.status_code == 201
    mid = response.json()['id']
    assert client.get(base + '?scope_id=' + other).json()['total'] == 0
    assert client.put(base + '/' + str(mid) + '?scope_id=' + other, json={'category': 'preference', 'content': '越权修改'}).status_code == 400
    assert client.delete(base + '/' + str(mid) + '?scope_id=' + sid).status_code == 200
    assert client.get(base + '?scope_id=' + sid).json()['total'] == 0


@pytest.mark.asyncio
async def test_qq_memory_commands_are_user_scoped_and_bypass_cooldown(tmp_path):
    store = Store(tmp_path); c = store.load(); c.memory.enabled = True
    c.memory.embedding.provider_id = 'a' * 32; c.memory.embedding.model = 'embed'; c.rules.cooldown = 300; store.save(c)
    bot = Bot(store); bot.api = AsyncMock(return_value={'id': 'sent'})
    def event(mid, user, text):
        return {'t': 'C2C_MESSAGE_CREATE', 'd': {'id': mid, 'content': text, 'author': {'user_openid': user}}}
    await bot.handle(event('1', 'alice', '/记住 我不喝咖啡'))
    assert bot.stats['sent'] == 1
    sid = scope(store); items = bot.memory.data.list(sid)['items']; assert len(items) == 1
    await bot.handle(event('2', 'bob', '/查看记忆'))
    assert '咖啡' not in bot.api.await_args.kwargs['json']['content']
    await bot.handle(event('3', 'alice', '/忘记 ' + str(items[0]['id'])))
    assert not bot.memory.data.list(sid)['items'] and bot.stats['sent'] == 3
    await bot.client.aclose(); store.close()


@pytest.mark.asyncio
async def test_unconfirmed_qq_reply_does_not_enqueue_or_become_memory_evidence(tmp_path):
    catalog = ProviderStore(tmp_path); eid = catalog.save(ProviderConfig(type='openai_embedding'))
    store = Store(tmp_path / 'bot'); c = store.load(); c.memory.enabled = True
    c.memory.embedding.provider_id = eid; c.memory.embedding.model = 'embed'; store.save(c)
    bot = Bot(store, providers=catalog); bot.api = AsyncMock(return_value={})
    bot.memory.context = AsyncMock(return_value='')
    bot.generate = AsyncMock(return_value={'message': {'content': '好，我答应明晚一起散步'}})
    await bot.handle({'t': 'C2C_MESSAGE_CREATE', 'd': {'id': '1', 'content': '明晚一起散步', 'author': {'user_openid': 'alice'}}})
    assert store.db.execute('SELECT COUNT(*) FROM memory_jobs').fetchone()[0] == 0
    assert store.db.execute("SELECT COUNT(*) FROM chat_messages WHERE role='assistant'").fetchone()[0] == 0
    await bot.client.aclose(); store.close(); catalog.close()


@pytest.mark.asyncio
async def test_forget_during_embedding_cannot_commit_stale_vector(tmp_path):
    from app.memory_store import StaleMemory
    catalog = ProviderStore(tmp_path); eid = catalog.save(ProviderConfig(type='openai_embedding'))
    store = Store(tmp_path / 'bot'); c = store.load(); c.memory.enabled = True
    c.memory.embedding.provider_id = eid; c.memory.embedding.model = 'embed'; store.save(c)
    bot = Bot(store, providers=catalog); sid = scope(store)
    item = bot.memory.data.put(sid, 'preference', 'coffee', '用户喝咖啡', [])
    async def request(*args, **kwargs):
        bot.memory.data.forget(sid, item['id'])
        return {'data': [{'index': 0, 'embedding': [1., 0.]}]}
    bot.request = request
    with pytest.raises(StaleMemory):
        await bot.memory.index(sid)
    assert not bot.memory.data.vectors(sid, bot.memory.index_key())
    await bot.client.aclose(); store.close(); catalog.close()


def test_group_sources_exclude_other_members_and_private_chat(tmp_path):
    store = Store(tmp_path); a = scope(store, 'alice', 'group', 'g'); b = scope(store, 'bob', 'group', 'g')
    store.chat.record('', 'group', 'g', 'user', 'Alice 的秘密', 'in::g:alice-1', sender_id='alice', source='incoming', status='received')
    store.chat.record('', 'group', 'g', 'assistant', '回复 Alice', 'reply::g:alice-1', source='reply', status='sent')
    mids = [row['id'] for row in store.db.execute('SELECT id FROM chat_messages')]
    assert all(store.scopes.source(a, mid) for mid in mids)
    assert all(store.scopes.source(b, mid) is None for mid in mids)
    private = scope(store)
    assert all(store.scopes.source(private, mid) is None for mid in mids)
    store.close()


@pytest.mark.asyncio
async def test_proactive_delivery_after_forget_does_not_restore_history(tmp_path):
    import httpx
    from app.proactive import ProactiveService
    from test_proactive import NOW
    store = Store(tmp_path); c = store.load(); c.qq.app_id = '123456'
    c.proactive.enabled = True; c.proactive.recipient_id = 'alice'; c.proactive.active_start = c.proactive.active_end = '00:00'; c.proactive.cooldown_minutes = 0; store.save(c)
    store.remember_contact(c.qq.app_id, 'alice', NOW - 7200, 'old')
    store.set_capability(c.qq.app_id, 'alice', 'supported', 'test', NOW - 7200)
    sid = scope(store); bot = None; mid = None
    async def transport(request):
        bot.memory.data.forget(sid, mid)
        return httpx.Response(200, json={'id': 'confirmed'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        bot = Bot(store, client); bot.state = 'connected'; bot.access_token = AsyncMock(return_value='token')
        mid = bot.memory.data.put(sid, 'fact', 'secret', '应被遗忘的事实', [])['id']
        service = ProactiveService(store, bot, clock=lambda: NOW)
        service.generate = AsyncMock(return_value='根据应被遗忘的事实生成的回复')
        await service.execute('forget-race', c, 'alice', 'idle', '关心近况')
        assert store.history('user:alice:alice', 6) == []
        assert store.proactive_records(c.qq.app_id)[0]['status'] == 'sent'
    store.close()


@pytest.mark.asyncio
async def test_old_retry_cannot_overwrite_newer_fact_and_summary(tmp_path):
    store = Store(tmp_path); sid = scope(store); c = store.load(); c.memory.enabled = True
    c.memory.embedding.provider_id = 'a' * 32; c.memory.embedding.model = 'embed'; store.save(c)
    bot = Bot(store)
    jobs = []
    for event, content in [('old', '我喜欢咖啡'), ('new', '更正，现在只喝茶，不喝咖啡')]:
        store.chat.record('', 'user', 'alice', 'user', content, f'in::alice:{event}', sender_id='alice', source='incoming', status='received')
        mid = store.db.execute('SELECT MAX(id) FROM chat_messages').fetchone()[0]
        bot.memory.enqueue(sid, event, [mid], immediate=True)
        jobs.append(dict(store.db.execute('SELECT * FROM memory_jobs ORDER BY id DESC LIMIT 1').fetchone()))
    async def generate(selection, messages, budget):
        rows = json.loads(messages[-1]['content'])['本次消息']
        old = rows[0]['content'] == '我喜欢咖啡'
        return {'message': {'content': json.dumps({'summary': '喜欢咖啡' if old else '只喝茶', 'memories': [{'category': 'preference', 'key': 'drink', 'content': '喜欢咖啡' if old else '只喝茶', 'evidence': [rows[0]['id']]}]})}}
    bot.generate = generate
    await bot.memory.extract(sid, [jobs[1]])
    await bot.memory.extract(sid, [jobs[0]])
    assert bot.memory.data.list(sid)['items'][0]['content'] == '只喝茶'
    assert bot.memory.data.summary(sid) == '只喝茶'
    await bot.client.aclose(); store.close()


def test_extractor_accepts_null_commitment_state_for_ordinary_facts_only():
    from app.memory import Extraction
    result = Extraction.model_validate({'memories': [{'category': 'preference', 'key': 'drink', 'content': '不喝咖啡', 'evidence': [1], 'commitment_state': None}]})
    assert result.memories[0].commitment_state == 'pending'
    with pytest.raises(ValueError):
        Extraction.model_validate({'memories': [{'category': 'commitment', 'key': 'walk', 'content': '散步', 'evidence': [1], 'commitment_state': None}]})


@pytest.mark.asyncio
async def test_expired_fact_is_removed_from_summary_and_recall(tmp_path):
    import time
    catalog = ProviderStore(tmp_path); eid = catalog.save(ProviderConfig(type='openai_embedding'))
    store = Store(tmp_path / 'bot'); c = store.load(); c.memory.enabled = True
    c.memory.embedding.provider_id = eid; c.memory.embedding.model = 'embed'; store.save(c)
    bot = Bot(store, providers=catalog); sid = scope(store)
    bot.memory.data.put(sid, 'fact', 'temporary', '临时在广州出差', [], expires_at=time.time()-1)
    bot.memory.data.set_summary(sid, '用户临时在广州出差', [], bot.memory.data.epoch(sid))
    async def request(*args, **kwargs):
        return {'data': [{'index': 0, 'embedding': [1., 0.]}]}
    bot.request = request
    assert '广州' not in await bot.memory.context(sid, '你记得我在哪里吗')
    await bot.client.aclose(); store.close(); catalog.close()


@pytest.mark.asyncio
async def test_expiry_cleanup_does_not_drop_first_reply_or_reuse_old_context(tmp_path):
    import time
    catalog = ProviderStore(tmp_path); eid = catalog.save(ProviderConfig(type='openai_embedding'))
    store = Store(tmp_path / 'bot'); c = store.load(); c.memory.enabled = True
    c.memory.embedding.provider_id = eid; c.memory.embedding.model = 'embed'; store.save(c)
    bot = Bot(store, providers=catalog); sid = scope(store)
    bot.memory.data.put(sid, 'fact', 'temporary', '临时在广州出差', [], expires_at=time.time()-1)
    store.save_history('user:alice:alice', [{'role': 'user', 'content': '临时在广州出差'}, {'role': 'assistant', 'content': '好'}], 6)
    async def request(*args, **kwargs):
        return {'data': [{'index': 0, 'embedding': [1., 0.]}]}
    bot.request = request; bot.generate = AsyncMock(return_value={'message': {'content': '你好'}})
    bot.api = AsyncMock(return_value={'id': 'sent'})
    await bot.handle({'t': 'C2C_MESSAGE_CREATE', 'd': {'id': 'new', 'content': '你好', 'author': {'user_openid': 'alice'}}})
    assert bot.stats['sent'] == 1
    assert '广州' not in str(bot.generate.await_args.args[1])
    await bot.client.aclose(); store.close(); catalog.close()
