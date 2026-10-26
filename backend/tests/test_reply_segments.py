import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from app.bot import Bot
from app.config import RulesConfig
from app.store import Store
from test_providers import client


def event(mid='m1',user='alice',group=False):
    return {'t':'GROUP_AT_MESSAGE_CREATE' if group else 'C2C_MESSAGE_CREATE','d':{'id':mid,'content':'说说今天的安排','author':{'member_openid' if group else 'user_openid':user},**({'group_openid':'g1'} if group else {})}}


def test_semantic_segments_preserve_protected_content_and_tail():
    from app.reply_segments import split_reply
    text='早上去上课。下午一起喝茶！晚上再聊聊今天的事。明天也有新的安排。'
    parts=split_reply(text,12,4)
    assert 1<len(parts)<=4 and ''.join(parts)==text
    protected='资料在 https://example.test/a.b?q=1 。\n\n```python\nprint("hello。world")\nprint("another！")\n```\n\n看完告诉我。'
    parts=split_reply(protected,20,4)
    assert sum('print(' in part for part in parts)==1
    assert any('https://example.test/a.b?q=1' in part for part in parts)
    assert ''.join(parts).replace('\n','').replace(' ','')==protected.replace('\n','').replace(' ','')
    assert split_reply('好呀！',100,4)==['好呀！']
    assert len(split_reply(text*20,10,4))<=4 and ''.join(split_reply(text*20,10,4))==text*20
    assert split_reply('x'*1000,20,4)==['x'*1000]


def test_segment_configuration_validation():
    c=RulesConfig();assert c.split_enabled and c.split_length==100 and c.split_max_parts==4 and c.split_delay==.8
    for values in ({'split_length':0},{'split_max_parts':5},{'split_delay':6},{'split_delay':float('nan')}):
        with pytest.raises(ValidationError):RulesConfig(**values)


def make_bot(tmp_path,group=False):
    store=Store(tmp_path);c=store.load();c.qq.app_id='111';c.qq.group_reply=group;c.rules.cooldown=0
    c.rules.split_enabled=True;c.rules.split_length=20;c.rules.split_max_parts=4;c.rules.split_delay=0;store.save(c)
    bot=Bot(store);bot.api=AsyncMock(return_value={'id':'accepted'})
    text='早上先去上课，然后认真做完作业。下午我们可以一起去喝茶，聊聊今天的趣事。晚上再散散步，然后早点休息。'
    bot.generate=AsyncMock(return_value={'message':{'content':text},'prompt_eval_count':10,'eval_count':20})
    return store,bot,text


@pytest.mark.asyncio
@pytest.mark.parametrize('group',[False,True])
async def test_handle_sends_bubbles_in_order_and_keeps_one_logical_turn(tmp_path,group):
    store,bot,text=make_bot(tmp_path,group)
    await bot.handle(event(group=group))
    calls=bot.api.await_args_list
    assert 1<len(calls)<=4
    assert [call.kwargs['json']['msg_seq'] for call in calls]==list(range(1,len(calls)+1))
    assert all(call.kwargs['json']['msg_id']=='m1' for call in calls)
    assert ''.join(call.kwargs['json']['content'] for call in calls)==text
    key='group:g1:alice' if group else 'user:alice:alice'
    assert len(store.history(key,6))==2 and store.history(key,6)[-1]['content']==text
    assert bot.generate.await_count==1 and store.stats()['total_tokens']==30
    rows=store.db.execute("SELECT * FROM chat_messages WHERE role='assistant' ORDER BY id").fetchall()
    assert len(rows)==len(calls) and all(row['reply_to']==('in:111:g1:m1' if group else 'in:111:alice:m1') for row in rows)
    owner=store.scopes.ensure('111','group' if group else 'user','g1' if group else 'alice','alice')['id']
    assert all(store.scopes.source(owner,row['id']) for row in rows)
    if group:
        other=store.scopes.ensure('111','group','g1','bob')['id']
        assert all(store.scopes.source(other,row['id']) is None for row in rows)
    detail=store.events.detail(next(item['id'] for item in store.events.query()['items'] if item['event']=='message.sent'))
    assert len(detail['messages'])==len(calls)+1
    assert store.stats()['sent']==len(calls)
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
async def test_partial_failure_archives_only_sent_prefix_without_unsent_memory(tmp_path):
    store,bot,text=make_bot(tmp_path)
    bot.api.side_effect=[{'id':'first'},httpx.ReadTimeout('timeout')]
    await bot.handle(event())
    rows=store.db.execute("SELECT content FROM chat_messages WHERE role='assistant'").fetchall()
    assert len(rows)==1 and rows[0]['content']!=text
    history=store.history('user:alice:alice',6)
    assert history[-1]['content']==rows[0]['content']
    assert store.db.execute('SELECT COUNT(*) FROM memory_jobs').fetchone()[0]==0
    assert store.stats()['sent']==1
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
async def test_reset_between_segments_stops_tail_and_does_not_restore_history(tmp_path):
    store,bot,text=make_bot(tmp_path)
    sent=[]
    async def send(*args,**kwargs):
        sent.append(kwargs['json']['content'])
        if len(sent)==1:
            sid=store.scopes.ensure('111','user','alice','alice')['id']
            bot.memory.data.reset_scope(sid)
        return {'id':'first'}
    bot.api.side_effect=send
    await bot.handle(event())
    assert len(sent)==1 and not store.history('user:alice:alice',6)
    assert store.db.execute('SELECT COUNT(*) FROM memory_jobs').fetchone()[0]==0
    await bot.client.aclose();store.close()


@pytest.mark.asyncio
async def test_disabled_segmentation_preserves_single_reply(tmp_path):
    store,bot,text=make_bot(tmp_path);c=store.load();c.rules.split_enabled=False;store.save(c)
    await bot.handle(event())
    assert bot.api.await_count==1 and bot.api.await_args.kwargs['json']['content']==text
    await bot.client.aclose();store.close()


def test_saving_only_presentation_does_not_clear_history(client):
    manager=client.app.state.manager;runtime=client.portal.call(manager.get,'default')
    client.portal.call(runtime.store.save_history,'user:alice:alice',[{'role':'user','content':'keep'}],6)
    c=client.get('/api/bots/default/settings').json();c['qq'].pop('secret_set')
    c['rules'].update(split_enabled=True,split_length=120,split_max_parts=3,split_delay=1.2)
    assert client.put('/api/bots/default/settings',json=c).status_code==200
    assert client.portal.call(runtime.store.history,'user:alice:alice',6)


@pytest.mark.asyncio
@pytest.mark.parametrize('fail_last',[False,True])
async def test_prepared_day_change_commits_only_after_all_segments(tmp_path,fail_last):
    from test_schedule import configured,DAY,NOW
    from test_schedule_dialogue import UPDATE
    store=Store(tmp_path);c=configured(store);c.rules.split_length=20;c.rules.split_delay=0;store.save(c)
    bot=Bot(store);bot.schedule.clock=lambda:NOW
    sid=store.scopes.ensure(c.qq.app_id,'user','alice','alice')['id'];day=bot.schedule.for_scope(sid)
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps(DAY,ensure_ascii=False)}})
    plan=await day.ensure()
    text='好，我现在出发去你家复习，我们可以把课上的内容再过一遍。等到晚上，我们再一起去附近公园吃饭和散步。'
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps({'reply':text,'schedule_update':UPDATE},ensure_ascii=False)}})
    from app.reply_segments import split_reply
    count=len(split_reply(text,c.rules.split_length,c.rules.split_max_parts));calls=[]
    async def api(*args,**kwargs):
        sequence=kwargs['json']['msg_seq'];calls.append(sequence)
        assert day.saved(c)['revision']==plan['revision']
        if fail_last and sequence==count:raise httpx.ReadTimeout('last bubble failed')
        return {'id':str(sequence)}
    bot.api=AsyncMock(side_effect=api)
    await bot.handle(event())
    after=day.saved(c)
    assert (after['revision']!=plan['revision']) is (not fail_last)
    if fail_last:
        assert not day.dialogue.records()['items']
        assert store.history('user:alice:alice',6)[-1]['content']!=text
    else:
        assert len(day.dialogue.records()['items'])==1
        assert store.history('user:alice:alice',6)[-1]['content']==text
    assert len(calls)==count and count>1
    await bot.client.aclose();store.close()


def test_existing_chat_table_migrates_reply_parent_without_losing_rows(tmp_path):
    import sqlite3
    store=Store(tmp_path);store.chat.record('','user','alice','user','旧档案','in::alice:old',sender_id='alice');store.close()
    db=sqlite3.connect(tmp_path/'hayqqbot.sqlite3');db.execute('DROP INDEX chat_reply_parent');db.execute('ALTER TABLE chat_messages DROP COLUMN reply_to');db.commit();db.close()
    store=Store(tmp_path)
    row=store.db.execute('SELECT * FROM chat_messages').fetchone()
    assert row['content']=='旧档案' and row['reply_to']==''
    store.close()
