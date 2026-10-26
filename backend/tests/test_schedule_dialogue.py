import asyncio
import copy
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.bot import Bot
from app.main import create_app
from app.store import Store
from test_schedule import DAY, NOW, configured, schedule_bot


UPDATE = {
    'reason': '用户邀请现在到家里复习，并确认晚上一起散步',
    'summary': '按约定调整：在家复习，晚上一起散步',
    'activities': [
        {'start': '12:08', 'end': '14:00', 'activity': '陪用户复习', 'location': '用户家', 'outfit': '白色卫衣、牛仔裤'},
        {'start': '18:20', 'end': '20:00', 'activity': '陪用户吃饭和散步', 'location': '附近公园', 'outfit': '黑色裙子、白色运动鞋'},
    ],
}


@pytest.mark.asyncio
async def test_dialogue_changes_preserve_past_unrelated_plans_and_create_audit(tmp_path):
    store = Store(tmp_path)
    configured(store)
    bot, _ = schedule_bot(store, [NOW])
    before = await bot.schedule.ensure()
    bot.capture_incoming({'t': 'C2C_MESSAGE_CREATE', 'd': {'id': 'agree-1', 'content': '现在来我家复习吧，晚上一起散步', 'author': {'user_openid': 'owner', 'nickname': '测试用户'}}})
    _, update = bot.schedule.dialogue.decode(json.dumps({'reply': '好，我现在过去，晚上一起散步。', 'schedule_update': UPDATE}))
    async with bot.schedule.lock:
        prepared = bot.schedule.dialogue.prepare(update)
        assert bot.schedule.dialogue.apply(prepared, {'kind': 'user', 'target': 'owner', 'sender_id': 'owner', 'message_id': 'agree-1'})
    after = bot.schedule.snapshot()['schedule']
    assert after['revision'] != before['revision']
    assert after['activities'][:2] == before['activities'][:2]
    assert {'start': '12:00', 'end': '12:08', 'activity': '午饭后去图书馆', 'location': '图书馆', 'outfit': '白色卫衣、牛仔裤'} in after['activities']
    assert {'start': '14:00', 'end': '18:20', 'activity': '午饭后去图书馆', 'location': '图书馆', 'outfit': '白色卫衣、牛仔裤'} in after['activities']
    assert after['activities'][-1]['start'] == '20:00' and after['activities'][-1]['end'] == '24:00'
    assert after['events'] == [{'time': '11:35', 'event': '遇到高中同学小林'}]
    changes = bot.schedule.dialogue.records()['items']
    assert len(changes) == 1
    assert changes[0]['reason'] == UPDATE['reason']
    assert changes[0]['source_content'] == '现在来我家复习吧，晚上一起散步'
    assert changes[0]['sender_name'] == '测试用户'
    assert changes[0]['conversation_id']
    assert changes[0]['diff']['activities_after'][0]['location'] == '用户家'
    assert changes[0]['diff']['events_removed'][0]['time'] == '18:27'
    assert bot.schedule.snapshot()['change_count'] == 1
    assert bot.schedule.snapshot()['changes'][0]['id'] == changes[0]['id']
    await bot.client.aclose()
    store.close()
    reopened = Store(tmp_path)
    bot, _ = schedule_bot(reopened, [NOW])
    assert bot.schedule.snapshot()['schedule']['revision'] == after['revision']
    assert bot.schedule.dialogue.records()['items'][0]['reason'] == UPDATE['reason']
    await bot.client.aclose()
    reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', ['past', 'overlap', 'past_event', 'stale'])
async def test_invalid_or_stale_dialogue_update_cannot_overwrite_schedule(tmp_path, bad):
    store = Store(tmp_path)
    configured(store)
    bot, _ = schedule_bot(store, [NOW])
    saved = await bot.schedule.ensure()
    value = copy.deepcopy(UPDATE)
    if bad == 'past': value['activities'][0].update(start='07:30', end='08:00')
    if bad == 'overlap': value['activities'][1].update(start='13:00', end='15:00')
    if bad == 'past_event': value['cancel_events'] = ['11:35']
    _, update = bot.schedule.dialogue.decode(json.dumps({'reply': '好。', 'schedule_update': value}))
    with pytest.raises(ValueError):
        prepared = bot.schedule.dialogue.prepare(update)
        if bad == 'stale':
            await bot.schedule.ensure(force=True)
            bot.schedule.dialogue.apply(prepared, {'kind': 'user', 'target': 'owner', 'sender_id': 'owner', 'message_id': 'invalid'})
    if bad != 'stale':
        assert bot.schedule.snapshot()['schedule'] == saved
    assert bot.schedule.dialogue.records()['items'] == []
    await bot.client.aclose()
    store.close()


@pytest.mark.asyncio
async def test_current_activity_change_splits_at_now_and_repeat_message_is_idempotent(tmp_path):
    store = Store(tmp_path)
    configured(store)
    bot, _ = schedule_bot(store, [NOW])
    await bot.schedule.ensure()
    value = copy.deepcopy(UPDATE)
    value['activities'][0]['start'] = '12:00'
    _, update = bot.schedule.dialogue.decode(json.dumps({'reply': '现在就来。', 'schedule_update': value}))
    source = {'kind': 'user', 'target': 'owner', 'sender_id': 'owner', 'message_id': 'same-event'}
    async with bot.schedule.lock:
        assert bot.schedule.dialogue.apply(bot.schedule.dialogue.prepare(update), source)
        assert not bot.schedule.dialogue.apply(bot.schedule.dialogue.prepare(update), source)
    assert bot.schedule.snapshot()['schedule']['activities'][2]['end'] == '12:08'
    assert bot.schedule.snapshot()['change_count'] == 1
    await bot.client.aclose()
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('qq_failure', [False, True])
async def test_single_chat_inference_applies_only_after_confirmed_reply(tmp_path, qq_failure):
    store = Store(tmp_path)
    config = configured(store)
    config.rules.cooldown = 0
    store.save(config)
    model_calls, sent, systems = [], [], []
    reply = '好，我现在去你家复习，晚上一起散步。'
    async def transport(request):
        if request.url.path.endswith('getAppAccessToken'):
            return httpx.Response(200, json={'access_token': 'fake-token', 'expires_in': 7200})
        if request.url.path.endswith('/chat'):
            body = json.loads(request.content)
            model_calls.append(body)
            if '规划器' in body['messages'][0]['content']:
                content = json.dumps(DAY)
            else:
                systems.append(body['messages'][0]['content'])
                content = json.dumps({'reply': reply, 'schedule_update': UPDATE}, ensure_ascii=False)
            return httpx.Response(200, json={'message': {'content': content}, 'prompt_eval_count': 10, 'eval_count': 20})
        sent.append(json.loads(request.content))
        assert store.db.execute('SELECT COUNT(*) FROM schedule_changes').fetchone()[0] == 0
        return httpx.Response(500 if qq_failure else 200, json={'error': 'QQ failure'} if qq_failure else {'id': 'accepted'})
    bot = Bot(store, httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    bot.schedule.clock = lambda: NOW
    sid = store.scopes.ensure(config.qq.app_id, 'user', 'owner', 'owner')['id']
    bot.schedule = bot.schedule.for_scope(sid)
    try:
        await bot.schedule.ensure()
        event = {'t': 'C2C_MESSAGE_CREATE', 'd': {'id': 'invite-1', 'content': '现在来我家复习吧，晚上一起散步', 'author': {'user_openid': 'owner'}}}
        await bot.handle(event)
        await bot.handle(event)
        assert len(model_calls) == (2 if qq_failure else 3)  # daily plan + chat; semantic check only after delivery
        assert sent[0]['content'] == reply
        assert len(sent) == 1
        assert 'schedule_update' not in sent[0]['content']
        assert '18:20' in systems[0]  # future planned activities can be negotiated
        assert '18:27' not in systems[0] and '便利店' not in systems[0]  # unexperienced surprises stay hidden
        assert bot.schedule.snapshot()['change_count'] == (0 if qq_failure else 1)
        if not qq_failure:
            assert '用户家' in json.dumps(bot.schedule.snapshot()['schedule'], ensure_ascii=False)
            assert store.history('user:owner:owner', 6)[-1]['content'] == reply
    finally:
        await bot.client.aclose()
        store.close()


@pytest.mark.asyncio
async def test_tentative_chat_and_plain_text_fallback_do_not_change_schedule(tmp_path):
    store = Store(tmp_path)
    configured(store)
    bot, _ = schedule_bot(store, [NOW])
    saved = await bot.schedule.ensure()
    for raw in ['只是随口聊聊。', json.dumps({'reply': '你是想约今晚吗？', 'schedule_update': None})]:
        reply, update = bot.schedule.dialogue.decode(raw)
        assert reply and update is None
    assert bot.schedule.snapshot()['schedule'] == saved
    assert bot.schedule.dialogue.records()['items'] == []
    await bot.client.aclose()
    store.close()


def test_dialogue_audit_api_auth_and_bot_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-password-long-enough')
    async def seed():
        store = Store(tmp_path)
        config = configured(store)
        bot, _ = schedule_bot(store, [NOW])
        await bot.schedule.ensure()
        _, update = bot.schedule.dialogue.decode(json.dumps({'reply': '好。', 'schedule_update': UPDATE}))
        async with bot.schedule.lock:
            bot.schedule.dialogue.apply(bot.schedule.dialogue.prepare(update), {'kind': 'user', 'target': 'owner', 'sender_id': 'owner', 'message_id': 'api-case'})
        config.schedule.enabled = False
        store.save(config)
        await bot.client.aclose()
        store.close()
    asyncio.run(seed())
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/api/bots/default/schedule/changes').status_code == 401
        client.post('/api/login', json={'password': 'test-password-long-enough'})
        second = client.post('/api/bots', json={'name': '另一个角色'}).json()['id']
        sid = client.get('/api/bots/default/users').json()['items'][0]['id']
        result = client.get(f'/api/bots/default/schedule/changes?scope_id={sid}&day=2026-10-24').json()
        assert len(result['items']) == 1
        assert client.get(f'/api/bots/{second}/schedule/changes?scope_id={sid}&day=2026-10-24').status_code == 400
        assert client.get('/api/bots/default/schedule/changes?limit=101').status_code == 422
        assert client.get('/api/bots/default/schedule/changes?day=not-a-date').status_code == 422


@pytest.mark.asyncio
async def test_many_dialogue_changes_keep_qq_schedule_display_bounded(tmp_path):
    store = Store(tmp_path)
    configured(store)
    bot, _ = schedule_bot(store, [NOW])
    plan = await bot.schedule.ensure()
    plan['activities'] = []
    for index in range(96):
        start, end = index*15, (index+1)*15
        plan['activities'].append({'start':f'{start//60:02}:{start%60:02}', 'end':f'{end//60:02}:{end%60:02}',
            'activity':'整理资料和复习课程'*3, 'location':'学校安静的阅览室', 'outfit':'白色上衣和深色裤子、舒适的运动鞋'*3})
    text = bot.schedule.format(plan)
    assert len(text) <= 6400
    assert '12:00–12:15' in text and '网页' in text
    await bot.client.aclose()
    store.close()


@pytest.mark.asyncio
async def test_timeline_keeps_provenance_beyond_latest_audit_page(tmp_path):
    store = Store(tmp_path)
    configured(store)
    bot, _ = schedule_bot(store, [NOW])
    await bot.schedule.ensure()
    for index in range(25):
        start, end = 13*60+index*10, 13*60+(index+1)*10
        raw = {'reply':'好。', 'schedule_update': {'reason':'按本次约定安排', 'activities': [{
            'start':f'{start//60:02}:{start%60:02}', 'end':f'{end//60:02}:{end%60:02}',
            'activity':f'共同复习第{index+1}部分', 'location':'家中', 'outfit':'白色卫衣'}]}}
        _, update = bot.schedule.dialogue.decode(json.dumps(raw))
        async with bot.schedule.lock:
            bot.schedule.dialogue.apply(bot.schedule.dialogue.prepare(update),
                {'kind':'user','target':'owner','sender_id':'owner','message_id':f'change-{index}'})
    snapshot = bot.schedule.snapshot()
    assert len(snapshot['changes']) == 20 and snapshot['change_count'] == 25
    assert snapshot['schedule']['dialogue_ranges'] == [{'start':'13:00','end':'17:10'}]
    await bot.client.aclose()
    store.close()
