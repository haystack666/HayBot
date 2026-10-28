import asyncio
import json
from datetime import datetime, date
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.bot import Bot
from app.diary_store import DiaryConfig, DiaryStore
from app.diary import DiaryService
from app.config import GroupOwner
from app.store import Store
from test_debounce import make, close, event, idle
from test_providers import client, body

ZONE=ZoneInfo('Asia/Shanghai')
NOW=datetime(2026,10,28,23,40,tzinfo=ZONE).timestamp()


def setup(tmp_path, now=NOW):
    store,bot=make(tmp_path);clock=[now]
    diary=DiaryService(store,bot,lambda:clock[0]);bot.diary=diary
    c=store.load();c.rules.prompt='你是林诗语，与Owner是恋人。';c.group_chat.character_name='林诗语'
    c.group_chat.owners=[GroupOwner(account_id=c.account_id,sender_id='owner-member')];store.save(c)
    diary.data.save_config(c.account_id,DiaryConfig(owner_id='owner'))
    bot.generate=AsyncMock(return_value={'message':{'content':'今天没聊太多，还是有点想他。也许他正忙着，我先把这点心情记下来。'},'prompt_eval_count':20,'eval_count':15})
    return store,bot,diary,clock


def record(store,mid,text,*,user='owner',kind='user',role='user',account=None,at=NOW-100,status=None,reply_to=''):
    c=store.load();account=account or c.account_id
    store.scopes.ensure(account,kind,'g' if kind=='group' else user,user)
    return store.chat.record(account,kind,'g' if kind=='group' else user,role,text,mid,
        sender_id=user if role=='user' else '',sender_name=user,at=at,source='incoming' if role=='user' else 'reply',
        status=status or ('received' if role=='user' else 'sent'),reply_to=reply_to)


def test_config_validation():
    assert DiaryConfig().time=='23:30' and DiaryConfig().enabled
    for value in ({'time':'24:00'},{'timezone':'unknown'},{'owner_id':'bad owner'},{'instruction':'x'*2001}):
        with pytest.raises(ValidationError):DiaryConfig(**value)


@pytest.mark.asyncio
async def test_writing_uses_own_persona_today_owner_private_and_attributed_public_only(tmp_path):
    s,b,d,_=setup(tmp_path);c=s.load()
    record(s,'owner-one','午饭吃好了')
    record(s,'stranger','stranger-private-secret',user='stranger')
    record(s,'yesterday','yesterday-secret',at=NOW-86400)
    record(s,'future','future-secret',at=NOW+100)
    record(s,'other-account','other-account-secret',account='222')
    record(s,'peer','我是大肥鱼，刚才看完视频了',user='peer-bot',kind='group')
    record(s,'self','我也想画一幅小画',kind='group',role='assistant',reply_to='peer')
    record(s,'failed','failed-send-secret',role='assistant',status='failed')
    b.memory.context=AsyncMock(side_effect=AssertionError('memory should not be read'))
    b.api.reset_mock()
    try:
        entry=await d.write()
        args=b.generate.await_args_list[0];prompt=args.args[1][0]['content'];payload=json.loads(args.args[1][1]['content'])
        assert '你是林诗语' in prompt and '公开人格' not in prompt
        text=str(payload)
        for secret in ('stranger-private-secret','yesterday-secret','future-secret','other-account-secret','failed-send-secret'):
            assert secret not in text
        assert any(m['speaker']=='participant' and m['sender_id']=='peer-bot' for m in payload['materials']['messages'])
        assert any(m['speaker']=='self' for m in payload['materials']['messages'])
        assert entry['status']=='ready' and entry['revision']==1 and entry['sources']['message_count']==3
        b.api.assert_not_awaited();b.memory.context.assert_not_awaited()
        assert s.stats()['total_tokens']==70
        raw=s.db.execute('SELECT content,evidence FROM diary_entries').fetchone()
        assert '今天没聊' not in raw['content'] and 'owner-one' not in raw['evidence']
    finally:await close(s,b)


@pytest.mark.asyncio
async def test_rewrite_preserves_versions_and_failure_keeps_old_entry(tmp_path):
    s,b,d,_=setup(tmp_path)
    try:
        first=await d.write();b.generate.return_value={'message':{'content':'补记一笔：今天这点小开心，我想留得久一点。'}}
        second=await d.write()
        assert first['id']==second['id'] and second['revision']==2 and d.data.list(s.load().account_id)['total']==1
        versions=d.data.versions(s.load().account_id,first['id'])
        assert [v['revision'] for v in versions]==[2,1] and versions[1]['content']==first['content']
        b.generate.side_effect=ValueError('model unavailable')
        with pytest.raises(ValueError):await d.write()
        saved=d.data.get(s.load().account_id,first['id'])
        assert saved['content']==second['content'] and saved['revision']==2 and saved['error']
    finally:await close(s,b)


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['owner','persona','account','reset','delete','policy'])
async def test_changes_during_generation_cannot_commit_stale_diary(tmp_path,change):
    s,b,d,_=setup(tmp_path)
    record(s,'owner-one','有效素材')
    started=asyncio.Event();release=asyncio.Event()
    async def generate(*args,**kwargs):
        started.set();await release.wait();return {'message':{'content':'不能保存的旧正文'}}
    b.generate.side_effect=generate
    task=asyncio.create_task(d.write())
    try:
        await started.wait();c=s.load();p,_,_=d.data.config(c.account_id)
        if change=='owner':p.owner_id='new-owner';d.data.save_config(c.account_id,p)
        if change=='persona':c.rules.prompt='new persona';s.save(c)
        if change=='account':c.qq.app_id='222';s.save(c)
        if change=='reset':
            with s.db:s.db.execute('UPDATE user_scopes SET source_floor=1,epoch=epoch+1')
        if change=='policy':p.include_groups=False;d.data.save_config(c.account_id,p)
        if change=='delete':
            row=s.db.execute('SELECT id FROM diary_entries').fetchone();d.data.delete(c.account_id,row['id'])
        release.set()
        with pytest.raises(ValueError):await task
        assert s.db.execute("SELECT COUNT(*) FROM diary_versions").fetchone()[0]==0
        assert not d.chat_context('owner')
        if change=='delete':assert s.db.execute('SELECT status FROM diary_entries').fetchone()[0]=='deleted'
    finally:release.set();await close(s,b)


@pytest.mark.asyncio
async def test_new_chat_scope_during_writing_does_not_cancel_diary(tmp_path):
    s,b,d,_=setup(tmp_path)
    async def generate(*args,**kwargs):
        record(s,'new-chat','新群友的消息',kind='group',user='new-member')
        return {'message':{'content':'今天有一点开心。'}}
    b.generate.side_effect=generate
    try:assert (await d.write())['revision']==1
    finally:await close(s,b)


@pytest.mark.asyncio
async def test_automatic_schedule_once_catchup_disabled_and_deleted_days(tmp_path):
    before=datetime(2026,10,28,20,0,tzinfo=ZONE).timestamp()
    s,b,d,clock=setup(tmp_path,before)
    try:
        await d.tick();b.generate.assert_not_awaited()
        clock[0]=NOW;await d.tick();await d.tick()
        assert b.generate.await_count==2
        row=d.data.row(s.load().account_id,'2026-10-28');assert row['automatic_at']==NOW
        clock[0]=datetime(2026,10,29,2,0,tzinfo=ZONE).timestamp();await d.tick();assert b.generate.await_count==2
        p,_,_=d.data.config(s.load().account_id);p.enabled=False;d.data.save_config(s.load().account_id,p)
        clock[0]=datetime(2026,10,30,23,40,tzinfo=ZONE).timestamp();await d.tick();assert b.generate.await_count==2
        p.enabled=True;d.data.save_config(s.load().account_id,p);await d.tick();assert b.generate.await_count==4
        row=d.data.row(s.load().account_id,'2026-10-30');d.data.delete(s.load().account_id,row['id'])
        await d.tick();assert b.generate.await_count==4
    finally:await close(s,b)


@pytest.mark.asyncio
async def test_auto_retries_are_bounded_and_manual_future_day_is_rejected(tmp_path):
    s,b,d,clock=setup(tmp_path);b.generate.side_effect=ValueError('offline')
    try:
        with pytest.raises(ValueError):await d.write(date(2026,10,29))
        b.generate.assert_not_awaited()
        for _ in range(3):
            with pytest.raises(ValueError):await d.tick()
            count=b.generate.await_count;await d.tick();assert b.generate.await_count==count
            clock[0]+=601
        await d.tick();assert b.generate.await_count==3
    finally:await close(s,b)


@pytest.mark.asyncio
async def test_cancelled_generation_can_retry_and_restart_preserves_ready_versions(tmp_path):
    s,b,d,_=setup(tmp_path);started=asyncio.Event()
    async def generate(*args,**kwargs):started.set();await asyncio.Event().wait()
    b.generate.side_effect=generate;task=asyncio.create_task(d.write())
    try:
        await started.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        row=d.data.row(s.load().account_id,'2026-10-28');assert row['status']=='failed'
        b.generate.side_effect=None;b.generate.return_value={'message':{'content':'重新记下今天。'}}
        item=await d.write()
        data=DiaryStore(s);assert data.get(s.load().account_id,item['id'])['content']=='重新记下今天。'
        assert len(data.versions(s.load().account_id,item['id']))==1
    finally:await close(s,b)


@pytest.mark.asyncio
async def test_private_sharing_only_to_bound_owner_and_resets_revoke_context(tmp_path):
    s,b,d,_=setup(tmp_path);record(s,'owner-one','今天有点累')
    try:
        entry=await d.write();assert entry['content'] in d.chat_context('owner')
        assert not d.chat_context('member') and not d.chat_context('owner',True)
        p,_,_=d.data.config(s.load().account_id);p.allow_sharing=False;d.data.save_config(s.load().account_id,p)
        assert not d.chat_context('owner')
        p.allow_sharing=True;p.owner_id='other';d.data.save_config(s.load().account_id,p)
        assert not d.chat_context('other')
        p.owner_id='owner';d.data.save_config(s.load().account_id,p)
        with s.db:s.db.execute('UPDATE user_scopes SET source_floor=100,epoch=epoch+1')
        assert not d.chat_context('owner')
    finally:await close(s,b)


@pytest.mark.asyncio
async def test_diary_context_is_supplied_to_owner_chat_but_not_group_or_other_user(tmp_path):
    s,b,d,_=setup(tmp_path);record(s,'owner-one','聊过的话')
    try:
        item=await d.write();b.generate.reset_mock()
        for user,group in [('owner',None),('stranger',None),('owner','g')]:
            p=event('new-'+user+str(group),'今天有什么想说的？',user,group)
            await b.handle(p)
            prompt=b.generate.await_args.args[1][0]['content']
            assert (item['content'] in prompt)==(user=='owner' and group is None)
    finally:await close(s,b)


@pytest.mark.asyncio
async def test_only_confirmed_phone_tasks_and_reset_floor_are_materials(tmp_path):
    s,b,d,_=setup(tmp_path);record(s,'old','reset-secret')
    scope=s.db.execute('SELECT id FROM user_scopes').fetchone()[0]
    with s.db:s.db.execute('UPDATE user_scopes SET source_floor=1,epoch=1 WHERE id=?',(scope,))
    record(s,'new','保留的消息')
    class Tasks:
        def valid_origin(self,t):return t['id']!='revoked'
        def list(self,bid):
            base={'origin':{'source':'qq','account_id':s.load().account_id,'requester_id':'owner'},'state':'completed','updated':NOW-100,'goal':'浏览视频','result':'核验完成'}
            return [dict(base,id='ok'),dict(base,id='failed',state='failed'),dict(base,id='revoked'),
                    dict(base,id='other',origin={**base['origin'],'requester_id':'other'}),dict(base,id='tomorrow',updated=NOW+100)]
    class Android:
        tasks=Tasks()
        def runtime(self,bot):return type('Runtime',(),{'id':'this-bot'})()
    b.android=Android()
    try:
        materials,evidence=d.collect(s.load(),d.data.config(s.load().account_id)[0],date(2026,10,28))
        assert 'reset-secret' not in str(materials)
        assert [t['id'] for t in materials['phone_tasks']]==['ok']
        assert evidence['phone_task_ids']==['ok']
    finally:b.android=None;await close(s,b)


def test_diary_api_authenticated_and_isolated(client):
    c=body(client);c['qq']['app_id']='111';assert client.put('/api/bots/default/settings',json=c).status_code==200
    second=client.post('/api/bots',json={'name':'Second'}).json()['id']
    settings=client.get('/api/bots/default/diary').json()
    assert settings['config']['time']=='23:30'
    settings['config']['owner_id']='only-owner'
    assert client.put('/api/bots/default/diary/config',json=settings['config']).status_code==200
    assert client.get(f'/api/bots/{second}/diary').json()['config']['owner_id']==''
    assert client.get('/api/bots/default/diary/entries').json()['total']==0
    assert client.post('/api/bots/default/diary/write',json={'day':'2099-01-01'}).status_code==400
    assert client.get('/api/bots/default/diary/entries/missing').status_code==400
    client.post('/api/logout')
    assert client.get('/api/bots/default/diary').status_code==401
    assert client.post('/api/bots/default/diary/write',json={}).status_code==401


@pytest.mark.asyncio
async def test_diary_deletion_during_chat_cancels_unsent_private_excerpt(tmp_path):
    s,b,d,_=setup(tmp_path);record(s,'owner-one','旧话')
    item=await d.write()
    async def generate(*args,**kwargs):
        d.data.delete(s.load().account_id,item['id'])
        return {'message':{'content':'日记里写了这件事'}}
    b.generate.side_effect=generate;b.api.reset_mock()
    try:
        await b.handle(event('new','你今天写了什么？','owner'))
        b.api.assert_not_awaited()
    finally:await close(s,b)


def test_diary_api_full_lifecycle_and_bot_isolation(client):
    c=body(client);c['qq']['app_id']='111';client.put('/api/bots/default/settings',json=c)
    second=client.post('/api/bots',json={'name':'另一个Bot'}).json()['id']
    b=client.app.state.manager.runtimes['default'].bot
    b.generate=AsyncMock(return_value={'message':{'content':'今天的心情，只写给自己看。'}})
    b.api=AsyncMock(side_effect=AssertionError('diary must not send QQ'))
    entry=client.post('/api/bots/default/diary/write',json={})
    assert entry.status_code==200
    eid=entry.json()['id']
    assert client.get('/api/bots/default/diary/entries').json()['total']==1
    assert client.get(f'/api/bots/{second}/diary/entries').json()['total']==0
    assert client.get(f'/api/bots/{second}/diary/entries/{eid}').status_code==400
    assert client.delete(f'/api/bots/{second}/diary/entries/{eid}').status_code==400
    assert client.post('/api/bots/default/diary/write',json={}).json()['revision']==2
    versions=client.get(f'/api/bots/default/diary/entries/{eid}/versions').json()['items']
    assert len(versions)==2
    assert client.delete(f'/api/bots/default/diary/entries/{eid}').status_code==200
    assert client.get('/api/bots/default/diary/entries').json()['total']==0
    b.api.assert_not_awaited()


@pytest.mark.asyncio
async def test_previous_diary_is_feeling_context_only_and_account_switch_hides_entries(tmp_path):
    s,b,d,_=setup(tmp_path)
    try:
        old=await d.write(date(2026,10,27))
        await d.write()
        payload=json.loads(b.generate.await_args_list[-2].args[1][1]['content'])
        assert old['content'] in payload['previous_diaries']
        assert '不是新事实来源' in b.generate.await_args_list[-2].args[1][0]['content']
        assert d.data.list('222')['total']==0
        with pytest.raises(ValueError):d.data.get('222',old['id'])
        with pytest.raises(ValueError):d.data.delete('222',old['id'])
        assert s.db.execute('SELECT COUNT(*) FROM diary_versions').fetchone()[0]==2
    finally:await close(s,b)


@pytest.mark.asyncio
async def test_scheduled_activities_are_not_completed_facts_and_future_plans_excluded(tmp_path):
    s,b,d,clock=setup(tmp_path,datetime(2026,10,28,12,0,tzinfo=ZONE).timestamp())
    c=s.load();c.schedule.enabled=True;c.schedule.premise='在家学习';s.save(c)
    record(s,'owner-chat','中午了',at=clock[0]-100)
    scope=s.db.execute("SELECT id FROM user_scopes WHERE target='owner'").fetchone()[0]
    plan={'source_epoch':0,'activities':[{'start':'09:00','activity':'计划练习水彩'},{'start':'19:00','activity':'未来活动不能用'}]}
    with s.db:s.db.execute('INSERT INTO daily_schedules VALUES (?,?,?,?,?,?)', (c.account_id,scope,'2026-10-28','Asia/Shanghai','test',json.dumps(plan)))
    try:
        await d.write()
        payload=json.loads(b.generate.await_args_list[-2].args[1][1]['content'])
        assert payload['materials']['planned_activities']==[{'start':'09:00','activity':'计划练习水彩'}]
        assert '不是实际执行证据' in b.generate.await_args_list[-2].args[1][0]['content']
        assert '未来活动不能用' not in str(payload)
    finally:await close(s,b)


@pytest.mark.asyncio
async def test_review_replaces_unsupported_draft_and_failed_review_preserves_last_version(tmp_path):
    s,b,d,_=setup(tmp_path)
    try:
        b.generate.side_effect=[{'message':{'content':'我和主人见了面。'}}, {'message':{'content':'今天有点想他，没有见面。'}}]
        item=await d.write()
        assert item['content']=='今天有点想他，没有见面。'
        review=b.generate.await_args
        assert 'draft' in review.args[1][1]['content'] and review.args[2]==8192
        b.generate.side_effect=[{'message':{'content':'第二份草稿'}},{'message':{'content':''}}]
        with pytest.raises(ValueError):await d.write()
        assert d.data.get(s.load().account_id,item['id'])['content']==item['content']
        assert len(d.data.versions(s.load().account_id,item['id']))==1
    finally:await close(s,b)


@pytest.mark.asyncio
async def test_stopping_bot_cancels_active_diary_and_prevents_late_save(tmp_path):
    s,b,d,_=setup(tmp_path);started=asyncio.Event()
    async def generate(*args,**kwargs):started.set();await asyncio.Event().wait()
    b.generate.side_effect=generate;task=asyncio.create_task(d.write())
    try:
        await started.wait();assert task in b.jobs
        await b.stop()
        assert task.cancelled() and not b.jobs
        assert s.db.execute('SELECT status FROM diary_entries').fetchone()[0]=='failed'
        assert s.db.execute('SELECT COUNT(*) FROM diary_versions').fetchone()[0]==0
    finally:await close(s,b)
