import asyncio
import copy
import json

import pytest
from app.store import Store
from app.schedule_dialogue import DialogueUpdate
from test_schedule import NOW, DAY, configured, schedule_bot


@pytest.mark.asyncio
async def test_private_group_and_each_user_have_independent_days(tmp_path):
    store = Store(tmp_path); config = configured(store)
    bot, calls = schedule_bot(store, [NOW], scoped=False)
    alice = store.scopes.ensure(config.qq.app_id, 'user', 'alice', 'alice')['id']
    bob = store.scopes.ensure(config.qq.app_id, 'user', 'bob', 'bob')['id']
    group = store.scopes.ensure(config.qq.app_id, 'group', 'g', 'alice')['id']
    a, b, g = [bot.schedule.for_scope(sid) for sid in (alice, bob, group)]
    plans = await asyncio.gather(a.ensure(), b.ensure(), g.ensure())
    assert len({plan['revision'] for plan in plans}) == 3
    before = b.snapshot()['schedule']
    update = DialogueUpdate(reason='只修改 Alice 的安排', activities=[{'start': '19:00', 'end': '20:00', 'activity': '和 Alice 散步', 'location': '公园', 'outfit': '运动服'}])
    async with a.lock:
        a.dialogue.apply(a.dialogue.prepare(update), {'kind': 'user', 'target': 'alice', 'sender_id': 'alice', 'message_id': 'm1'})
    assert b.snapshot()['schedule'] == before
    assert g.snapshot()['change_count'] == b.snapshot()['change_count'] == 0
    assert 'Alice' in json.dumps(a.snapshot()['schedule']) and 'Alice' not in json.dumps(before)
    await bot.client.aclose(); store.close()


@pytest.mark.asyncio
async def test_midnight_updates_each_known_user_and_preserves_confirmed_appointments(tmp_path):
    store = Store(tmp_path); config = configured(store); clock = [NOW]
    bot, calls = schedule_bot(store, clock, scoped=False)
    alice = store.scopes.ensure(config.qq.app_id, 'user', 'alice', 'alice')['id']
    bob = store.scopes.ensure(config.qq.app_id, 'user', 'bob', 'bob')['id']
    bot.memory.data.put(alice, 'commitment', 'walk', '陪 Alice 散步', [], due_at='2026-10-25T19:30:00+08:00', end_at='2026-10-25T20:00:00+08:00')
    await bot.schedule.tick()
    clock[0] += 86400
    await bot.schedule.tick()
    a, b = bot.schedule.for_scope(alice), bot.schedule.for_scope(bob)
    assert a.snapshot()['schedule']['date'] == b.snapshot()['schedule']['date'] == '2026-10-25'
    assert '陪 Alice 散步' in json.dumps(a.snapshot()['schedule'], ensure_ascii=False)
    assert '陪 Alice 散步' not in json.dumps(b.snapshot()['schedule'], ensure_ascii=False)
    assert len(calls) == 4
    await bot.client.aclose(); store.close()


@pytest.mark.asyncio
async def test_canceling_commitment_restores_only_its_own_future_interval(tmp_path):
    store = Store(tmp_path); config = configured(store)
    bot, calls = schedule_bot(store, [NOW], scoped=False)
    sid = store.scopes.ensure(config.qq.app_id, 'user', 'alice', 'alice')['id']
    day = bot.schedule.for_scope(sid)
    await day.ensure()
    item = bot.memory.data.put(sid, 'commitment', 'walk', '陪 Alice 散步', [], due_at='2026-10-24T19:30:00+08:00', end_at='2026-10-24T20:00:00+08:00')
    await day.sync_commitments()
    assert '陪 Alice 散步' in json.dumps(day.snapshot()['schedule'], ensure_ascii=False)
    bot.memory.data.put(sid, 'commitment', 'walk', '散步已取消', [], due_at='2026-10-24T19:30:00+08:00', end_at='2026-10-24T20:00:00+08:00', commitment_state='canceled')
    await day.sync_commitments()
    assert '陪 Alice 散步' not in json.dumps(day.snapshot()['schedule']['activities'], ensure_ascii=False)
    assert day.snapshot()['schedule']['activities'][0] == DAY['activities'][0]
    await bot.client.aclose(); store.close()


@pytest.mark.asyncio
async def test_forget_during_day_generation_rejects_old_result(tmp_path):
    from app.schedule import ScheduleError
    store = Store(tmp_path); config = configured(store)
    bot, calls = schedule_bot(store, [NOW], scoped=False)
    sid = store.scopes.ensure(config.qq.app_id, 'user', 'alice', 'alice')['id']
    item = bot.memory.data.put(sid, 'commitment', 'walk', '陪 Alice 散步', [], due_at='2026-10-24T19:30:00+08:00', end_at='2026-10-24T20:00:00+08:00')
    day = bot.schedule.for_scope(sid)
    async def generate(*args, **kwargs):
        bot.memory.data.forget(sid, item['id'])
        old = copy.deepcopy(DAY); old['summary'] = '今晚陪 Alice 散步'
        return {'message': {'content': json.dumps(old)}}
    bot.generate = generate
    with pytest.raises(ScheduleError):
        await day.ensure()
    assert day.saved(config) is None
    await bot.client.aclose(); store.close()


@pytest.mark.asyncio
async def test_day_baseline_prompt_does_not_contain_private_commitments(tmp_path):
    store = Store(tmp_path); config = configured(store)
    bot, calls = schedule_bot(store, [NOW], scoped=False)
    sid = store.scopes.ensure(config.qq.app_id, 'user', 'alice', 'alice')['id']
    bot.memory.data.put(sid, 'commitment', 'walk', '专属暗号松鼠散步', [], due_at='2026-10-24T19:30:00+08:00', end_at='2026-10-24T20:00:00+08:00')
    plan = await bot.schedule.for_scope(sid).ensure()
    assert '专属暗号松鼠散步' not in json.dumps(calls, ensure_ascii=False)
    assert '专属暗号松鼠散步' in json.dumps(plan, ensure_ascii=False)
    await bot.client.aclose(); store.close()


@pytest.mark.asyncio
async def test_cancellation_during_qq_send_does_not_commit_stale_day_patch(tmp_path):
    from unittest.mock import AsyncMock
    store = Store(tmp_path); config = configured(store); config.rules.cooldown = 0; store.save(config)
    bot, calls = schedule_bot(store, [NOW], scoped=False)
    sid = store.scopes.ensure(config.qq.app_id, 'user', 'alice', 'alice')['id']; day = bot.schedule.for_scope(sid)
    await day.ensure()
    item = bot.memory.data.put(sid, 'commitment', 'walk', '陪 Alice 散步', [], due_at='2026-10-24T19:30:00+08:00', end_at='2026-10-24T20:00:00+08:00')
    await day.sync_commitments()
    bot.generate = AsyncMock(return_value={'message': {'content': json.dumps({'reply': '好，一起散步喝咖啡', 'schedule_update': {'reason': '约定增加喝咖啡', 'activities': [{'start': '19:30', 'end': '20:00', 'activity': '陪 Alice 散步喝咖啡', 'location': '公园', 'outfit': '运动服'}]}})}})
    async def send(*args, **kwargs):
        bot.memory.data.put(sid, 'commitment', 'walk', '散步已取消', [], explicit=True, due_at='2026-10-24T19:30:00+08:00', end_at='2026-10-24T20:00:00+08:00', commitment_state='canceled')
        return {'id': 'accepted'}
    bot.api = send
    await bot.handle({'t': 'C2C_MESSAGE_CREATE', 'd': {'id': '1', 'content': '散步时顺便喝咖啡吧', 'author': {'user_openid': 'alice'}}})
    await day.sync_commitments()
    assert '喝咖啡' not in json.dumps(day.snapshot()['schedule']['activities'], ensure_ascii=False)
    await bot.client.aclose(); store.close()
