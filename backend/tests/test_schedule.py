import asyncio
import copy
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from app.bot import Bot
from app.config import Settings
from app.main import create_app
from app.store import Store


NOW = datetime(2026, 10, 24, 12, 8, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
DAY = {
    'summary': '周末回家休息', 'outfit': '白色卫衣、牛仔裤', 'appearance': '低马尾、淡妆',
    'activities': [
        {'start': '00:00', 'end': '07:15', 'activity': '睡觉', 'location': '家里', 'outfit': '棉质睡衣'},
        {'start': '07:15', 'end': '12:00', 'activity': '起床吃饭、整理笔记', 'location': '家里', 'outfit': '白色卫衣、牛仔裤'},
        {'start': '12:00', 'end': '18:20', 'activity': '午饭后去图书馆', 'location': '图书馆', 'outfit': '白色卫衣、牛仔裤'},
        {'start': '18:20', 'end': '24:00', 'activity': '晚饭、休息', 'location': '家里', 'outfit': '棉质睡衣'},
    ],
    'events': [{'time': '11:35', 'event': '遇到高中同学小林'}, {'time': '18:27', 'event': '突然下雨，去便利店躲雨'}],
}


def configured(store):
    config = Settings()
    config.qq.app_id = '123456'
    config.rules.prompt = '你是中文角色助手。'
    config.ollama.model = 'test'
    config.schedule.enabled = True
    config.schedule.premise = '经管系大一学生，周一到周五上课，周末回家。'
    store.save(config)
    return config


def schedule_bot(store, clock, answers=None, scoped=True):
    from app.schedule import ScheduleService
    calls = []
    replies = answers or [DAY]
    def transport(request):
        body = json.loads(request.content)
        calls.append(body)
        payload = replies[min(len(calls) - 1, len(replies) - 1)]
        return httpx.Response(200, json={'message': {'content': json.dumps(payload, ensure_ascii=False)},
                                       'prompt_eval_count': 10, 'eval_count': 30})
    bot = Bot(store, httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    bot.schedule = ScheduleService(store, bot, clock=lambda: clock[0])
    if scoped:
        sid = store.scopes.ensure(store.load().qq.app_id, 'user', 'owner', 'owner')['id']
        bot.schedule = bot.schedule.for_scope(sid)
    return bot, calls


@pytest.mark.asyncio
async def test_daily_schedule_persists_single_flight_and_resets(tmp_path):
    store = Store(tmp_path)
    configured(store)
    changed = copy.deepcopy(DAY)
    changed['summary'] = '重新安排周末'
    bot, calls = schedule_bot(store, [NOW], [DAY, changed])
    first, second = await asyncio.gather(bot.schedule.ensure(), bot.schedule.ensure())
    assert first['date'] == '2026-10-24' and first == second
    assert len(calls) == 1
    assert calls[0]['options']['num_predict'] >= 4096
    assert '2026-10-24' in calls[0]['messages'][-1]['content']
    assert '星期六' in calls[0]['messages'][-1]['content']
    assert store.stats()['total_tokens'] == 40
    assert (await bot.schedule.ensure(force=True))['summary'] == '重新安排周末'
    await bot.client.aclose()
    store.close()
    store = Store(tmp_path)
    bot, calls = schedule_bot(store, [NOW])
    assert (await bot.schedule.ensure())['summary'] == '重新安排周末'
    assert calls == []
    await bot.client.aclose()
    store.close()


@pytest.mark.asyncio
async def test_context_contains_current_and_past_but_no_future_events(tmp_path):
    store = Store(tmp_path)
    configured(store)
    bot, calls = schedule_bot(store, [NOW])
    await bot.schedule.ensure()
    context = await bot.schedule.context()
    assert '12:08' in context and '图书馆' in context
    assert '小林' in context
    assert '下雨' not in context and '便利店' not in context and '18:27' not in context
    assert len(calls) == 1
    await bot.client.aclose()
    store.close()


@pytest.mark.asyncio
async def test_midnight_catchup_and_restart_use_timezone(tmp_path):
    store = Store(tmp_path)
    configured(store)
    clock = [NOW]
    bot, calls = schedule_bot(store, clock)
    store.set_enabled(True)
    await bot.schedule.tick()
    clock[0] = datetime(2026, 10, 24, 23, 59, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
    await bot.schedule.tick()
    assert len(calls) == 1
    clock[0] += 60
    await bot.schedule.tick()
    assert bot.schedule.snapshot()['schedule']['date'] == '2026-10-25'
    assert len(calls) == 2
    await bot.client.aclose()
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['overlap', 'gap', 'bad_time', 'no_clothes', 'empty', 'bad_event'])
async def test_invalid_reset_preserves_previous_day_and_counts_usage(tmp_path, mutation):
    bad = copy.deepcopy(DAY)
    if mutation == 'overlap': bad['activities'][1]['start'] = '07:00'
    if mutation == 'gap': bad['activities'][1]['start'] = '07:20'
    if mutation == 'bad_time': bad['activities'][0]['end'] = '25:00'
    if mutation == 'no_clothes': bad['outfit'] = ''
    if mutation == 'empty': bad['activities'] = []
    if mutation == 'bad_event': bad['events'][0]['time'] = '24:01'
    store = Store(tmp_path)
    configured(store)
    bot, calls = schedule_bot(store, [NOW], [DAY, bad])
    saved = await bot.schedule.ensure()
    with pytest.raises(ValueError, match='日程'):
        await bot.schedule.ensure(force=True)
    assert bot.schedule.snapshot()['schedule'] == saved
    assert store.stats()['total_tokens'] >= 80
    assert bot.schedule.snapshot()['error']
    await bot.client.aclose()
    store.close()


@pytest.mark.asyncio
async def test_config_change_during_generation_discards_result(tmp_path):
    from app.schedule import ScheduleService
    store = Store(tmp_path)
    config = configured(store)
    entered, release = asyncio.Event(), asyncio.Event()
    async def transport(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json={'message': {'content': json.dumps(DAY)}})
    bot = Bot(store, httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    bot.schedule = ScheduleService(store, bot, clock=lambda: NOW)
    task = asyncio.create_task(bot.schedule.ensure())
    await entered.wait()
    config.schedule.premise = '已换成新角色'
    store.save(config)
    release.set()
    with pytest.raises(ValueError, match='配置|日期'):
        await task
    assert bot.schedule.snapshot()['schedule'] is None
    await bot.client.aclose()
    store.close()


@pytest.mark.asyncio
async def test_disabled_and_empty_settings_do_not_call_model(tmp_path):
    store = Store(tmp_path)
    bot, calls = schedule_bot(store, [NOW])
    assert await bot.schedule.context() == ''
    await bot.schedule.tick()
    assert calls == []
    await bot.client.aclose()
    store.close()


def test_schedule_config_validation():
    with pytest.raises(ValueError):
        Settings.model_validate({'schedule': {'enabled': True, 'premise': '  '}})
    with pytest.raises(ValueError):
        Settings.model_validate({'schedule': {'timezone': 'invalid/zone'}})


@pytest.mark.asyncio
async def test_schedule_updates_with_bot_stopped_and_disabled_preserves_saved_day(tmp_path):
    store = Store(tmp_path)
    config = configured(store)
    bot, calls = schedule_bot(store, [NOW])
    assert not store.enabled()
    await bot.schedule.tick()
    assert len(calls) == 1
    config.schedule.enabled = False
    store.save(config)
    assert bot.schedule.snapshot()['schedule']['date'] == '2026-10-24'
    assert await bot.schedule.context() == ''
    await bot.client.aclose()
    store.close()


@pytest.mark.asyncio
async def test_failed_generation_throttled_and_errors_redacted(tmp_path):
    store = Store(tmp_path)
    configured(store)
    clock = [NOW]
    bot, calls = schedule_bot(store, clock, [{'error': 'private-key-sentinel'}])
    for _ in range(2):
        with pytest.raises(ValueError):
            await bot.schedule.ensure()
    assert len(calls) == 1
    assert 'private-key-sentinel' not in json.dumps(bot.schedule.snapshot())
    clock[0] += 301
    with pytest.raises(ValueError):
        await bot.schedule.ensure()
    assert len(calls) == 2
    await bot.client.aclose()
    store.close()


@pytest.mark.asyncio
async def test_qq_commands_bypass_cooldown_dedup_and_keep_schedule_out_of_history(tmp_path):
    store = Store(tmp_path)
    config = configured(store)
    config.rules.cooldown = 300
    store.save(config)
    requests, generation = [], []
    def transport(request):
        body = json.loads(request.content) if request.content else {}
        if request.url.path.endswith('getAppAccessToken'):
            return httpx.Response(200, json={'access_token': 'fake-token', 'expires_in': 7200})
        if request.url.path.endswith('/chat'):
            generation.append(body)
            return httpx.Response(200, json={'message': {'content': json.dumps(DAY)}, 'prompt_eval_count': 10, 'eval_count': 20})
        requests.append(body)
        return httpx.Response(200, json={'id': 'accepted'})
    bot = Bot(store, httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    bot.schedule.clock = lambda: NOW
    bot.last['user:owner:owner'] = __import__('time').time()
    event = {'t': 'C2C_MESSAGE_CREATE', 'd': {'id': 'view-1', 'content': '/查看日程', 'author': {'user_openid': 'owner'}}}
    await bot.handle(event)
    await bot.handle(event)
    assert generation and len(generation) == 1
    assert '周末回家' in ''.join(body['content'] for body in requests)
    assert '▶ 12:00' in ''.join(body['content'] for body in requests)
    assert store.stats()['received'] == 1
    assert store.history('user:owner:owner', 6) == []
    assert store.db.execute("SELECT COUNT(*) FROM chat_messages WHERE role='assistant'").fetchone()[0] == len(requests)
    event['d']['id'], event['d']['content'] = 'reset-1', '/重置日程'
    await bot.handle(event)
    assert len(generation) == 2
    assert '重置' in requests[-1]['content']
    assert store.stats()['received'] == 2
    await bot.client.aclose()
    store.close()


@pytest.mark.asyncio
async def test_long_qq_schedule_uses_distinct_chunk_sequences(tmp_path):
    store = Store(tmp_path)
    configured(store)
    long_day = copy.deepcopy(DAY)
    long_day['activities'] = []
    for index in range(24):
        long_day['activities'].append({'start': f'{index:02}:00', 'end': f'{index + 1:02}:00',
            'activity': '整理资料和复习课程' * 3, 'location': '学校安静的阅览室', 'outfit': '白色上衣和深色裤子、舒适的运动鞋' * 3})
    sent = []
    def transport(request):
        if request.url.path.endswith('getAppAccessToken'):
            return httpx.Response(200, json={'access_token': 'fake-token', 'expires_in': 7200})
        if request.url.path.endswith('/chat'):
            return httpx.Response(200, json={'message': {'content': json.dumps(long_day)}})
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={'id': 'accepted'})
    bot = Bot(store, httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    bot.schedule.clock = lambda: NOW
    await bot.handle({'t': 'C2C_MESSAGE_CREATE', 'd': {'id': 'long-view', 'content': '/查看日程', 'author': {'user_openid': 'owner'}}})
    assert 2 <= len(sent) <= 4
    assert [body['msg_seq'] for body in sent] == list(range(1, len(sent) + 1))
    assert all(len(body['content']) <= 1600 for body in sent)
    assert '23:00–24:00' in ''.join(body['content'] for body in sent)
    assert '便利店' in ''.join(body['content'] for body in sent)
    await bot.client.aclose()
    store.close()


@pytest.mark.asyncio
async def test_normal_and_proactive_replies_receive_only_elapsed_schedule(tmp_path):
    from app.proactive import ProactiveService
    store = Store(tmp_path)
    configured(store)
    messages = []
    def transport(request):
        if request.url.path.endswith('getAppAccessToken'):
            return httpx.Response(200, json={'access_token': 'fake-token', 'expires_in': 7200})
        if request.url.path.endswith('/chat'):
            body = json.loads(request.content)
            if '规划器' in body['messages'][0]['content']:
                content = json.dumps(DAY)
            elif '生活连续性检查器' in body['messages'][0]['content']:
                content = json.dumps({'changed': False})
            else:
                messages.append(body['messages'])
                content = '我在图书馆，上午还碰到小林啦。'
            return httpx.Response(200, json={'message': {'content': content}})
        return httpx.Response(200, json={'id': 'accepted'})
    bot = Bot(store, httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    bot.schedule.clock = lambda: NOW
    await bot.handle({'t': 'C2C_MESSAGE_CREATE', 'd': {'id': 'normal', 'content': '在干什么', 'author': {'user_openid': 'owner'}}})
    proactive = ProactiveService(store, bot, clock=lambda: NOW)
    await proactive.generate(store.load(), 'owner', '聊聊今天的生活')
    assert len(messages) == 2
    for request_messages in messages:
        system = request_messages[0]['content']
        assert '12:08' in system and '小林' in system and '图书馆' in system
        assert '便利店' not in system and '18:27' not in system
    await bot.client.aclose()
    store.close()


def test_scoped_schedule_api_auth_isolation_and_save(tmp_path, monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-password-long-enough')
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/api/bots/default/schedule').status_code == 401
        client.post('/api/login', json={'password': 'test-password-long-enough'})
        assert client.get('/api/bots/default/schedule').status_code == 200
        second = client.post('/api/bots', json={'name': '独立日程'}).json()['id']
        body = Settings().model_dump()
        body['schedule'] = {'enabled': True, 'premise': '大学生，周末回家', 'timezone': 'Asia/Shanghai'}
        assert client.put('/api/bots/default/settings', json=body).status_code == 200
        assert client.get('/api/bots/default/schedule').json()['enabled']
        assert not client.get(f'/api/bots/{second}/schedule').json()['enabled']
        assert client.post(f'/api/bots/{second}/schedule/generate').status_code == 400
        assert client.get('/api/bots/missing/schedule').status_code == 404
        assert client.post('/api/bots/default/schedule/generate', headers={'Origin': 'https://evil.example'}).status_code == 403


@pytest.mark.asyncio
async def test_reset_acknowledges_before_slow_model_and_chat_does_not_wait(tmp_path):
    store = Store(tmp_path)
    configured(store)
    entered, release = asyncio.Event(), asyncio.Event()
    sent = []
    async def transport(request):
        if request.url.path.endswith('getAppAccessToken'):
            return httpx.Response(200, json={'access_token': 'fake-token', 'expires_in': 7200})
        if request.url.path.endswith('/chat'):
            assert request.extensions['timeout']['read'] >= 600
            entered.set()
            await release.wait()
            return httpx.Response(200, json={'message': {'content': json.dumps(DAY)}})
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={'id': 'accepted'})
    bot = Bot(store, httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    bot.schedule.clock = lambda: NOW
    task = asyncio.create_task(bot.handle({'t': 'C2C_MESSAGE_CREATE', 'd': {'id': 'slow-reset', 'content': '/重置日程', 'author': {'user_openid': 'owner'}}}))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert sent and '正在' in sent[0]['content']
        context = await asyncio.wait_for(bot.schedule.context(), .1)
        assert '日程' in context
        release.set()
        await task
        assert [body['msg_seq'] for body in sent] == [1, 2]
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await bot.client.aclose()
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('proactive', [False, True])
async def test_reset_during_model_reply_prevents_delivery_and_old_history(tmp_path, proactive):
    from app.providers import ProviderConfig, ProviderStore
    from app.proactive import ProactiveService
    store = Store(tmp_path / 'bot')
    config = configured(store)
    (tmp_path / 'providers').mkdir()
    providers = ProviderStore(tmp_path / 'providers')
    config.ollama.provider_id = providers.save(ProviderConfig(type='openai_chat', base_url='https://model.test/v1'))
    config.proactive.enabled = True
    config.proactive.recipient_id = 'owner'
    config.proactive.active_start = config.proactive.active_end = '00:00'
    config.proactive.cooldown_minutes = 0
    store.save(config)
    store.remember_contact(config.qq.app_id, 'owner', NOW - 7200)
    store.set_capability(config.qq.app_id, 'owner', 'supported', 'test', NOW - 7200)
    entered, release = asyncio.Event(), asyncio.Event()
    sent, schedule_calls = [], []
    changed = copy.deepcopy(DAY)
    changed['activities'][2]['location'] = '新日程里的家中'
    async def transport(request):
        if request.url.path.endswith('/chat/completions'):
            messages = json.loads(request.content)['messages']
            if '规划器' in messages[0]['content']:
                schedule_calls.append(1)
                content = json.dumps(DAY if len(schedule_calls) == 1 else changed)
            else:
                entered.set()
                await release.wait()
                content = '我还在旧日程的图书馆。'
            return httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', 'content': content}}]})
        if request.url.path.endswith('getAppAccessToken'):
            return httpx.Response(200, json={'access_token': 'fake-token', 'expires_in': 7200})
        sent.append(request)
        return httpx.Response(200, json={'id': 'accepted'})
    bot = Bot(store, httpx.AsyncClient(transport=httpx.MockTransport(transport)), providers=providers)
    bot.state = 'connected'
    bot.schedule.clock = lambda: NOW
    sid = store.scopes.ensure(config.qq.app_id, 'user', 'owner', 'owner')['id']
    bot.schedule = bot.schedule.for_scope(sid)
    await bot.schedule.ensure()
    if proactive:
        service = ProactiveService(store, bot, clock=lambda: NOW)
        action = service.execute('reset-race', config, 'owner', 'idle', '聊聊近况')
    else:
        action = bot.handle({'t': 'C2C_MESSAGE_CREATE', 'd': {'id': 'old-reply', 'content': '在干什么', 'author': {'user_openid': 'owner'}}})
    task = asyncio.create_task(action)
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await bot.schedule.ensure(force=True)
        release.set()
        await task
        assert sent == []
        assert store.history('user:owner:owner', 6) == []
        if proactive:
            assert store.proactive_records(config.qq.app_id)[0]['status'] == 'skipped'
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await bot.client.aclose()
        store.close()
        providers.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('native', [True, False])
async def test_ollama_schedule_streaming_avoids_long_response_timeout(tmp_path, native):
    from app.providers import ProviderConfig, ProviderStore
    store = Store(tmp_path / 'bot')
    config = configured(store)
    config.ollama.model = 'Gemma4E4BUncensoredQ8KP:latest'
    (tmp_path / 'providers').mkdir()
    providers = ProviderStore(tmp_path / 'providers')
    config.ollama.provider_id = providers.save(ProviderConfig(type='ollama',
        base_url='http://model.test' if native else 'http://model.test/v1', api_key='test-only-key'))
    store.save(config)
    text = json.dumps(DAY, ensure_ascii=False)
    parts = [text[index:index+57] for index in range(0, len(text), 57)]
    if native:
        frames = [{'message': {'content': part}} for part in parts]
        frames.append({'done': True, 'prompt_eval_count': 12, 'eval_count': 34})
        payload = ''.join(json.dumps(frame, ensure_ascii=False)+'\n' for frame in frames)
    else:
        frames = [{'choices': [{'delta': {'reasoning_content': 'private-reasoning-sentinel'}}]}]
        frames += [{'choices': [{'delta': {'content': part}}]} for part in parts]
        frames += [{'choices': [{'delta': {}, 'finish_reason': 'stop'}]}, {'choices': [], 'usage': {'prompt_tokens': 12, 'completion_tokens': 34}}]
        payload = ''.join('data: '+json.dumps(frame, ensure_ascii=False)+'\n\n' for frame in frames)+'data: [DONE]\n\n'
    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            encoded = payload.encode()
            for index in range(0, len(encoded), 19):
                yield encoded[index:index+19]
    def transport(request):
        assert request.headers['authorization'] == 'Bearer test-only-key'
        body = json.loads(request.content)
        assert body.get('think') is False if native else body.get('reasoning_effort') == 'none'
        if not body['stream']:
            return httpx.Response(504, json={'error': 'long response timed out'})
        return httpx.Response(200, headers={'Content-Type': 'application/x-ndjson' if native else 'text/event-stream'}, stream=Bytes())
    bot = Bot(store, httpx.AsyncClient(transport=httpx.MockTransport(transport)), providers=providers)
    bot.schedule.clock = lambda: NOW
    try:
        assert (await bot.schedule.ensure())['summary'] == '周末回家休息'
        assert store.stats()['total_tokens'] == 46
        assert 'private-reasoning-sentinel' not in json.dumps(bot.schedule.snapshot())
    finally:
        await bot.client.aclose()
        store.close()
        providers.close()

