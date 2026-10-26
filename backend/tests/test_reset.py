import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from app.bot import Bot
from app.memory_store import MemoryStore, StaleMemory
from app.store import Store


def event(mid, text, user='alice', group=None):
    return {'t': 'GROUP_AT_MESSAGE_CREATE' if group else 'C2C_MESSAGE_CREATE', 'd': {'id': mid, 'content': ('<@123> ' if group else '') + text, 'author': {'member_openid' if group else 'user_openid': user}, **({'group_openid': group} if group else {})}}


def owner(store, user='alice', group=None):
    return store.scopes.ensure(store.load().qq.app_id, 'group' if group else 'user', group or user, user)['id']


def seed(store, memory, sid, content='旧记忆'):
    item = memory.put(sid, 'preference', 'drink', content, [])
    memory.set_summary(sid, content + '的摘要', [], memory.epoch(sid))
    memory.save_vector(sid, item['id'], 'index', [1., 0.], item['revision'], memory.epoch(sid))
    store.save_history(store.scopes.history_key(sid), [{'role': 'user', 'content': content}], 6)
    return item


def test_reset_clears_complete_scope_but_preserves_other_users_and_archive(tmp_path):
    store = Store(tmp_path); memory = MemoryStore(store); sid = owner(store)
    item = seed(store, memory, sid); bob = owner(store, 'bob'); seed(store, memory, bob, 'Bob的记忆')
    group = owner(store, group='g1'); seed(store, memory, group, '群聊的记忆')
    store.chat.record('', 'user', 'alice', 'user', '旧聊天档案', 'in::alice:old', sender_id='alice', source='incoming', status='received')
    mid = store.db.execute('SELECT MAX(id) FROM chat_messages').fetchone()[0]
    with store.db:
        store.db.execute("INSERT INTO memory_jobs(scope_id,source_key,source_ids,epoch,status,created) VALUES (?,?,?,?,?,?)", (sid,'old-job',json.dumps([mid]),memory.epoch(sid),'running',time.time()))
        store.db.execute("INSERT INTO memory_index VALUES (?,?,?,?,?)", (sid,'index','ready','',time.time()))
    before = memory.epoch(sid)
    assert memory.reset_scope(sid) == 1
    assert memory.epoch(sid) > before
    assert memory.list(sid, include_inactive=True)['items'] == [] and memory.summary(sid) == ''
    assert not store.history(store.scopes.history_key(sid), 6) and not memory.vectors(sid, 'index')
    assert not store.db.execute('SELECT * FROM memory_fts WHERE rowid=?', (item['id'],)).fetchone()
    assert not store.db.execute('SELECT * FROM memory_jobs WHERE scope_id=?', (sid,)).fetchall()
    assert not store.db.execute('SELECT * FROM memory_index WHERE scope_id=?', (sid,)).fetchone()
    assert '旧记忆' not in json.dumps(memory.audit(sid), ensure_ascii=False)
    assert memory.audit(sid)[0]['action'] == 'reset'
    assert memory.list(bob)['total'] == memory.list(group)['total'] == 1
    assert store.db.execute('SELECT COUNT(*) FROM chat_messages').fetchone()[0] == 1
    with pytest.raises(StaleMemory): memory.put(sid, 'fact', 'old', '旧任务', [], expected_epoch=before)
    with pytest.raises(StaleMemory): memory.put(sid, 'fact', 'old', '旧来源', [mid])
    store.chat.record('', 'user', 'alice', 'user', '新的表达', 'in::alice:new', sender_id='alice', source='incoming', status='received')
    new_id = store.db.execute('SELECT MAX(id) FROM chat_messages').fetchone()[0]
    assert memory.put(sid, 'preference', 'drink', '新的偏好', [new_id])
    store.close(); store = Store(tmp_path); assert MemoryStore(store).list(owner(store))['total'] == 1; store.close()


@pytest_asyncio.fixture
async def setup(tmp_path):
    store = Store(tmp_path); config = store.load(); config.qq.app_id='111'; config.qq.group_reply=True; config.rules.cooldown=300; store.save(config)
    bot = Bot(store); bot.api=AsyncMock(return_value={'id':'accepted'}); bot.generate=AsyncMock(return_value={'message':{'content':'普通回答'}})
    yield store, bot
    await bot.client.aclose(); store.close()


@pytest.mark.asyncio
async def test_warning_confirmation_and_duplicate_do_not_call_model(setup):
    store, bot = setup; sid = owner(store); seed(store,bot.memory.data,sid)
    bot.last['user:alice:alice']=time.time()
    await bot.handle(event('r1','/reset'))
    warning=bot.api.await_args.kwargs['json']['content']
    for text in ('长期记忆','上下文','聊天档案','2 分钟','/reset 确认','/reset 取消','不可'):
        assert text in warning
    assert bot.memory.data.list(sid)['total'] == 1
    await bot.handle(event('r2','/reset 确认'))
    assert not bot.memory.data.list(sid)['items'] and not store.history('user:alice:alice',6)
    assert '已清空' in bot.api.await_args.kwargs['json']['content']
    epoch=bot.memory.data.epoch(sid)
    await bot.handle(event('r2','/reset 确认'))
    await bot.handle(event('r3','/reset 确认'))
    assert bot.memory.data.epoch(sid)==epoch
    bot.generate.assert_not_awaited()
    assert store.db.execute('SELECT COUNT(*) FROM chat_messages').fetchone()[0] >= 4


@pytest.mark.asyncio
async def test_cancel_expiry_and_missing_confirmation_keep_data(setup):
    store,bot=setup; sid=owner(store); seed(store,bot.memory.data,sid)
    await bot.handle(event('c0','/reset confirm'))
    assert bot.memory.data.list(sid)['total']==1
    await bot.handle(event('c1','/reset'))
    await bot.handle(event('c2','/reset 取消'))
    await bot.handle(event('c3','/reset 确认'))
    assert bot.memory.data.list(sid)['total']==1
    await bot.handle(event('c4','/reset'))
    bot.reset.confirmations[sid]['expires']=0
    await bot.handle(event('c5','/reset confirm'))
    assert bot.memory.data.list(sid)['total']==1
    bot.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_group_confirmation_is_bound_to_original_sender_and_context(setup):
    store,bot=setup; alice=owner(store,group='g1'); bob=owner(store,'bob',group='g1'); private=owner(store)
    for sid in (alice,bob,private):seed(store,bot.memory.data,sid)
    await bot.handle(event('g1','/reset',group='g1'))
    await bot.handle(event('g2','/reset confirm',user='bob',group='g1'))
    await bot.handle(event('g3','/reset confirm'))
    assert all(bot.memory.data.list(sid)['total']==1 for sid in (alice,bob,private))
    await bot.handle(event('g4','/reset confirm',group='g1'))
    assert not bot.memory.data.list(alice)['items']
    assert bot.memory.data.list(bob)['total']==bot.memory.data.list(private)['total']==1
    assert '/v2/groups/g1/messages' in bot.api.await_args.args


@pytest.mark.asyncio
async def test_failed_warning_and_restart_never_authorize_deletion(setup):
    store,bot=setup; sid=owner(store);seed(store,bot.memory.data,sid)
    bot.api.return_value={}
    await bot.handle(event('f1','/reset'))
    bot.api.return_value={'id':'accepted'}
    await bot.handle(event('f2','/reset confirm'))
    assert bot.memory.data.list(sid)['total']==1
    await bot.handle(event('f3','/reset'))
    other=Bot(store); other.api=AsyncMock(return_value={'id':'accepted'})
    await other.handle(event('f4','/reset confirm'))
    assert other.memory.data.list(sid)['total']==1
    await other.client.aclose()


@pytest.mark.asyncio
async def test_confirmation_cancels_busy_reply_and_next_message_starts_fresh(setup):
    store,bot=setup; sid=owner(store);seed(store,bot.memory.data,sid)
    entered=asyncio.Event(); canceled=asyncio.Event()
    async def blocked(*args,**kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        except asyncio.CancelledError:
            canceled.set()
            # Even an adapter that returns after cancellation must not revive old context.
            return {'message':{'content':'旧回答'}}
    bot.generate=blocked
    running=asyncio.create_task(bot.handle(event('busy','旧问题')))
    await asyncio.wait_for(entered.wait(),2)
    await bot.handle(event('b1','/reset'))
    assert not canceled.is_set() and bot.memory.data.list(sid)['total']==1
    await bot.handle(event('b2','/reset 确认'))
    await asyncio.wait_for(running,2)
    assert canceled.is_set() and not bot.pending
    assert all(call.kwargs['json']['content']!='旧回答' for call in bot.api.await_args_list)
    bot.generate=AsyncMock(return_value={'message':{'content':'新回答'}})
    await bot.handle(event('b3','新问题'))
    assert bot.generate.await_count==1
    sent=bot.generate.await_args.args[1]
    assert not any('旧问题' in message['content'] or '旧记忆' in message['content'] for message in sent)
    assert store.history('user:alice:alice',6)[-1]['content']=='新回答'


@pytest.mark.asyncio
async def test_reset_during_extraction_cannot_restore_old_fact_or_summary(setup):
    store,bot=setup;sid=owner(store);seed(store,bot.memory.data,sid)
    c=store.load();c.memory.enabled=True;c.memory.embedding.provider_id='a'*32;c.memory.embedding.model='embed';store.save(c)
    store.chat.record('111','user','alice','user','我喜欢喝茶','in:111:alice:old',sender_id='alice',source='incoming',status='received')
    mid=store.db.execute('SELECT MAX(id) FROM chat_messages').fetchone()[0]
    bot.memory.enqueue(sid,'old-extract',[mid],immediate=True)
    jobs=[dict(row) for row in store.db.execute('SELECT * FROM memory_jobs WHERE scope_id=?',(sid,))]
    started=asyncio.Event(); release=asyncio.Event()
    async def generate(*args,**kwargs):
        started.set();await release.wait()
        return {'message':{'content':json.dumps({'summary':'旧摘要','memories':[{'category':'preference','key':'drink','content':'喜欢喝茶','evidence':[mid]}]})}}
    bot.generate=generate
    extracting=asyncio.create_task(bot.memory.extract(sid,jobs))
    await asyncio.wait_for(started.wait(),2)
    await bot.handle(event('e1','/reset'));await bot.handle(event('e2','/reset confirm'));release.set()
    with pytest.raises(StaleMemory):await extracting
    assert not bot.memory.data.list(sid)['items'] and not bot.memory.data.summary(sid)


def test_reset_transaction_rolls_back_all_changes_on_failure(tmp_path):
    import sqlite3
    store=Store(tmp_path);memory=MemoryStore(store);sid=owner(store);seed(store,memory,sid)
    epoch=memory.epoch(sid)
    store.db.executescript("CREATE TRIGGER reject_reset BEFORE INSERT ON memory_audit WHEN NEW.action='reset' BEGIN SELECT RAISE(ABORT,'simulated failure'); END;")
    with pytest.raises(sqlite3.IntegrityError):memory.reset_scope(sid)
    assert memory.epoch(sid)==epoch and memory.list(sid)['total']==1
    assert memory.summary(sid) and store.history(store.scopes.history_key(sid),6)
    assert memory.vectors(sid,'index')
    store.close()


@pytest.mark.asyncio
async def test_confirm_cannot_run_before_warning_delivery_or_after_cancel(setup):
    store,bot=setup;sid=owner(store);seed(store,bot.memory.data,sid)
    sending=asyncio.Event();release=asyncio.Event()
    async def api(*args,**kwargs):
        if '重置前请确认影响' in kwargs['json']['content']:
            sending.set();await release.wait()
        return {'id':'accepted'}
    bot.api=AsyncMock(side_effect=api)
    prompt=asyncio.create_task(bot.handle(event('w1','/reset')))
    await asyncio.wait_for(sending.wait(),2)
    await bot.handle(event('w2','/reset confirm'))
    assert bot.memory.data.list(sid)['total']==1
    await bot.handle(event('w3','/reset cancel'))
    release.set();await prompt
    await bot.handle(event('w4','/reset confirm'))
    assert bot.memory.data.list(sid)['total']==1 and sid not in bot.reset.confirmations


@pytest.mark.asyncio
async def test_stale_archived_message_and_old_user_cannot_replay_after_reset(setup):
    store,bot=setup;sid=owner(store);seed(store,bot.memory.data,sid)
    old=event('replayed','尚未处理的旧聊天');bot.capture_incoming(old)
    await bot.handle(event('p1','/reset'));await bot.handle(event('p2','/reset confirm'))
    await bot.handle(old)
    bot.generate.assert_not_awaited()
    old_app=store.load();old_app.qq.app_id='222';store.save(old_app)
    with pytest.raises(ValueError):bot.memory.data.reset_scope(sid)


@pytest.mark.asyncio
async def test_confirmation_archived_before_latest_warning_cannot_clear(setup):
    store,bot=setup;sid=owner(store);seed(store,bot.memory.data,sid)
    delayed=event('delayed','/reset confirm');bot.capture_incoming(delayed)
    await bot.handle(event('latest','/reset'))
    await bot.handle(delayed)
    assert bot.memory.data.list(sid)['total']==1
    await bot.handle(event('fresh-confirm','/reset confirm'))
    assert bot.memory.data.list(sid)['total']==0


@pytest.mark.asyncio
async def test_confirmation_received_while_warning_is_in_flight_is_not_reused(setup):
    store,bot=setup;sid=owner(store);seed(store,bot.memory.data,sid)
    delayed=event('early-confirm','/reset confirm')
    async def api(*args,**kwargs):
        if '重置前请确认影响' in kwargs['json']['content']:
            bot.capture_incoming(delayed)
        return {'id':'accepted'}
    bot.api=AsyncMock(side_effect=api)
    await bot.handle(event('new-warning','/reset'))
    await bot.handle(delayed)
    assert bot.memory.data.list(sid)['total']==1
    await bot.handle(event('real-confirm','/reset confirm'))
    assert bot.memory.data.list(sid)['total']==0


@pytest.mark.asyncio
async def test_reset_removes_future_memory_appointment_but_keeps_ordinary_day(tmp_path):
    from test_schedule import configured, DAY, NOW
    from datetime import datetime
    from zoneinfo import ZoneInfo
    store=Store(tmp_path);config=configured(store);store.save(config)
    bot=Bot(store);bot.schedule.clock=lambda:NOW;sid=owner(store)
    date=datetime.fromtimestamp(NOW,ZoneInfo(config.schedule.timezone)).date().isoformat()
    bot.memory.data.put(sid,'commitment','walk','重置前的约定',[],due_at=date+'T19:30:00+08:00',end_at=date+'T20:00:00+08:00')
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps(DAY,ensure_ascii=False)}})
    day=bot.schedule.for_scope(sid);plan=await day.ensure()
    assert any(piece['activity']=='重置前的约定' for piece in plan['activities'])
    bot.api=AsyncMock(return_value={'id':'accepted'})
    await bot.handle(event('s1','/reset'));await bot.handle(event('s2','/reset confirm'))
    after=day.saved(store.load())
    assert after and after['summary']==plan['summary']
    assert not any(piece['activity']=='重置前的约定' for piece in after['activities'])
    assert not bot.memory.data.list(sid)['items']
    assert bot.generate.await_count==1
    await bot.client.aclose();store.close()
