import copy
import json
from unittest.mock import AsyncMock

import pytest
from app.store import Store
from test_schedule import NOW, DAY, configured, schedule_bot


def activity(start,end,action='留在用户家陪伴、休息',location='用户家'):
    return {'start':start,'end':end,'activity':action,'location':location,'outfit':'居家服'}


def decision():
    return {'changed':True,'reason':'双方确认今晚留宿，不再去图书馆',
        'evidence':'用户邀请留下，角色答应今晚住这里，明早再回去', 'time_inferred':True,
        'today':{'reason':'双方确认留宿','activities':[activity('12:08','24:00')]},
        'replace_tomorrow':True,'tomorrow':[activity('00:00','07:00','在用户家睡觉')]}


async def fixture(tmp_path, reply='好，那今晚就住你这里，明早再回去。'):
    store=Store(tmp_path);config=configured(store);clock=[NOW];bot,_=schedule_bot(store,clock)
    day=bot.schedule;await day.ensure();sid=day.scope_id
    bot.capture_incoming({'t':'C2C_MESSAGE_CREATE','d':{'id':'stay','content':'今晚别回去了，留下陪我吧', 'author':{'user_openid':'owner'}}})
    incoming='in:'+config.account_id+':owner:stay'
    store.chat.record(config.account_id,'user','owner','assistant',reply,'reply:'+config.account_id+':owner:stay',reply_to=incoming,status='sent')
    source={'kind':'user','target':'owner','sender_id':'owner','message_id':'stay'}
    return store,bot,day,clock,source


async def observe(bot,day,source):
    return await day.dialogue.semantic.observe([], '今晚别回去了，留下陪我吧',
        '好，那今晚就住你这里，明早再回去。', source,day.stamp(),bot.memory.stamp(day.scope_id))


@pytest.mark.asyncio
async def test_natural_stay_changes_day_and_audits_inferred_time(tmp_path):
    store,bot,day,clock,source=await fixture(tmp_path);before=copy.deepcopy(day.saved(store.load()))
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps(decision(),ensure_ascii=False)}})
    assert await observe(bot,day,source)
    after=day.saved(store.load())
    assert after['activities'][0]==before['activities'][0]
    assert after['activities'][-1]['location']=='用户家'
    assert after['events']==[DAY['events'][0]]
    record=day.dialogue.records()['items'][0]
    assert record['diff']['time_inferred'] is True and record['diff']['evidence']
    assert record['trigger_message_id']=='stay' and record['source_content']=='今晚别回去了，留下陪我吧'
    assert day.snapshot()['continuity']['activities'][0]['location']=='用户家'
    assert not await observe(bot,day,source)  # replay cannot run another model/write
    assert bot.generate.await_count==1
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
async def test_midnight_and_restart_keep_only_this_users_continuity(tmp_path):
    store,bot,day,clock,source=await fixture(tmp_path)
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps(decision())}});await observe(bot,day,source)
    await bot.client.aclose();store.close()
    store=Store(tmp_path);clock[0]+=86400
    bot,_=schedule_bot(store,clock);day=bot.schedule
    plan=await day.ensure()
    assert plan['activities'][0]['location']=='用户家' and plan['activities'][0]['end']=='07:00'
    assert '用户家' in json.dumps(bot.schedule.prompt(store.load(),plan['date']),ensure_ascii=False)
    other=store.scopes.ensure(store.load().account_id,'user','other','other')['id']
    other_plan=await day.for_scope(other).ensure()
    assert other_plan['activities'][0]['location']=='家里'
    assert other_plan.get('inherited_continuity') is None
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['reset','regenerate','midnight','disable'])
async def test_inflight_result_cannot_apply_after_state_change(tmp_path,mode):
    store,bot,day,clock,source=await fixture(tmp_path)
    async def generate(*args,**kwargs):
        if mode=='reset':bot.memory.data.reset_scope(day.scope_id)
        elif mode=='regenerate':
            c=store.load();plan=day.saved(c);plan['revision']='new-revision'
            with store.db:store.db.execute('UPDATE daily_schedules SET value=?',(json.dumps(plan),))
        elif mode=='midnight':clock[0]+=86400
        else:
            c=store.load();c.schedule.enabled=False;store.save(c)
        return {'message':{'content':json.dumps(decision())}}
    bot.generate=generate
    assert not await observe(bot,day,source)
    assert store.db.execute('SELECT COUNT(*) FROM schedule_changes').fetchone()[0]==0
    assert day.dialogue.semantic.continuity() is None
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
async def test_reset_hides_existing_carry_and_cancel_clears_it(tmp_path):
    store,bot,day,clock,source=await fixture(tmp_path)
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps(decision())}});await observe(bot,day,source)
    assert day.dialogue.semantic.continuity()
    # A later confirmed change may explicitly clear tomorrow without altering today's activities.
    source['message_id']='leave'
    bot.capture_incoming({'t':'C2C_MESSAGE_CREATE','d':{'id':'leave','content':'还是明天不留了', 'author':{'user_openid':'owner'}}})
    store.chat.record(store.load().account_id,'user','owner','assistant','好，明天不留了','reply:'+store.load().account_id+':owner:leave',reply_to='in:'+store.load().account_id+':owner:leave',status='sent')
    result=decision();result.update(today=None,tomorrow=[])
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps(result)}})
    assert await observe(bot,day,source)
    assert day.dialogue.semantic.continuity() is None
    assert 'continuity_before' in day.dialogue.records()['items'][0]['diff']
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('payload',[{'changed':False}, {'changed':True,'reason':'瞎改'}, {'message':'plain malformed'}])
async def test_no_agreement_or_invalid_proposal_does_not_change_day(tmp_path,payload):
    store,bot,day,clock,source=await fixture(tmp_path);before=day.saved(store.load())
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps(payload)}})
    assert not await observe(bot,day,source)
    assert day.saved(store.load())==before and day.dialogue.semantic.continuity() is None
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
async def test_unconfirmed_reply_cannot_trigger_inference_or_writes(tmp_path):
    store,bot,day,clock,source=await fixture(tmp_path)
    with store.db:store.db.execute("UPDATE chat_messages SET status='failed' WHERE role='assistant'")
    bot.generate=AsyncMock()
    assert not await observe(bot,day,source);bot.generate.assert_not_called()
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
async def test_semantic_write_and_continuity_are_atomic(tmp_path):
    store,bot,day,clock,source=await fixture(tmp_path);before=day.saved(store.load())
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps(decision())}})
    store.db.execute("CREATE TRIGGER fail_continuity BEFORE INSERT ON schedule_continuity BEGIN SELECT RAISE(ABORT,'test failure'); END")
    assert not await observe(bot,day,source)
    assert day.saved(store.load())==before
    assert store.db.execute('SELECT COUNT(*) FROM schedule_changes').fetchone()[0]==0
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
async def test_reset_invalidates_persisted_continuity_and_next_generation(tmp_path):
    store,bot,day,clock,source=await fixture(tmp_path)
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps(decision())}});await observe(bot,day,source)
    bot.memory.data.reset_scope(day.scope_id)
    assert day.dialogue.semantic.continuity() is None
    clock[0]+=86400
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps(DAY)}})
    plan=await day.ensure()
    assert plan['activities'][0]['location']=='家里'
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
async def test_plain_reply_runs_independent_check_after_delivery_and_keeps_history(tmp_path):
    store=Store(tmp_path);config=configured(store);config.rules.cooldown=0;store.save(config)
    bot,_=schedule_bot(store,[NOW]);day=bot.schedule;await day.ensure();calls=[]
    async def generate(selection,messages,*args,**kwargs):
        if '生活连续性检查器' in messages[0]['content']:
            assert calls==['sent']
            assert '好，那今晚就住你这里' in messages[-1]['content']
            return {'message':{'content':json.dumps(decision())}}
        return {'message':{'content':'好，那今晚就住你这里，明早再回去。'}}
    async def send(*args,**kwargs):calls.append('sent');return {'id':'accepted'}
    bot.generate=generate;bot.api=send
    event={'t':'C2C_MESSAGE_CREATE','d':{'id':'stay','content':'今晚别回去了，留下陪我吧','author':{'user_openid':'owner'}}}
    bot.capture_incoming(event)
    await bot.handle(event)
    assert day.saved(store.load())['activities'][-1]['location']=='用户家'
    assert store.history('user:owner:owner',6)[-1]['content']=='好，那今晚就住你这里，明早再回去。'
    assert day.snapshot()['change_count']==1
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
async def test_ordinary_memory_refresh_does_not_cancel_overnight_stay(tmp_path):
    store,bot,day,clock,source=await fixture(tmp_path)
    memory=bot.memory.data.put(day.scope_id,'fact','food','喜欢面条',[])
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps(decision())}});await observe(bot,day,source)
    epoch=bot.memory.data.epoch(day.scope_id)
    bot.memory.data.put(day.scope_id,'fact','food','更喜欢清汤面',[])
    assert bot.memory.data.epoch(day.scope_id)>epoch
    assert day.dialogue.semantic.continuity() is not None
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
async def test_memory_projection_cannot_overwrite_confirmed_semantic_location(tmp_path):
    store,bot,day,clock,source=await fixture(tmp_path)
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps(decision())}});await observe(bot,day,source)
    bot.memory.data.put(day.scope_id,'commitment','stay','今晚留宿用户家',[],due_at='2026-10-24T20:00:00+08:00',end_at='2026-10-24T23:59:00+08:00')
    await day.sync_commitments()
    assert all(item['location']=='用户家' for item in day.saved(store.load())['activities'] if item['start']>='12:08')
    await bot.client.aclose();store.close()
