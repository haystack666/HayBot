import asyncio
import json
import random
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from app.qzone_store import QzoneConfig
from test_qzone import qbot


def owner(s,uid='20002',text='今天一起聊了一本很有趣的书'):
    c=s.load();sid=s.scopes.ensure(c.account_id,'user',uid,uid)['id']
    s.chat.record(c.account_id,'user',uid,'user',text,'in:'+c.account_id+':'+uid+':'+str(s.db.execute('SELECT COALESCE(MAX(id),0)+1 FROM chat_messages').fetchone()[0]),sender_id=uid,source='incoming')
    return sid


def test_owner_default_blank_and_random_ranges():
    assert QzoneConfig().owner_id==''
    for changes in ({'owner_id':'bad'},{'interval_min_minutes':20,'interval_max_minutes':10},{'event_min_minutes':30,'event_max_minutes':5},{'share_probability':1.1}):
        with pytest.raises(ValidationError):QzoneConfig(**changes)


@pytest.mark.asyncio
async def test_generation_uses_configured_owner_only_after_source_floor(tmp_path):
    s,b,q=qbot(tmp_path);sid=owner(s,text='old-owner-sentinel');owner(s,'30003','other-user-private-sentinel')
    q.bot.memory.data.reset_scope(sid);owner(s,text='new-owner-safe-sentinel')
    q.data.save_config(s.load().account_id,QzoneConfig(owner_id='20002'))
    b.generate=AsyncMock(return_value={'message':{'content':'聊到喜欢的书，心情也亮了一点。'}})
    await q.generate()
    prompt=str(b.generate.await_args)
    assert 'new-owner-safe-sentinel' in prompt and 'old-owner-sentinel' not in prompt and 'other-user-private-sentinel' not in prompt
    await q.close();await b.client.aclose();s.close()


@pytest.mark.asyncio
async def test_owner_change_or_reset_during_generation_invalidates_result(tmp_path):
    s,b,q=qbot(tmp_path);sid=owner(s);q.data.save_config(s.load().account_id,QzoneConfig(owner_id='20002'))
    async def generate(*args,**kwargs):
        b.memory.data.reset_scope(sid)
        return {'message':{'content':'不应沿用的旧回忆'}}
    b.generate=generate
    with pytest.raises(ValueError):await q.generate()
    await q.close();await b.client.aclose();s.close()


@pytest.mark.asyncio
async def test_random_opportunity_is_persisted_and_never_uses_fixed_times(tmp_path):
    s,b,q=qbot(tmp_path);q.clock=lambda:1792976400 # 09:00 Asia/Shanghai
    owner(s);q.data.save_config(s.load().account_id,QzoneConfig(owner_id='20002',auto_enabled=True,interval_min_minutes=30,interval_max_minutes=120))
    await q.tick();state=q.random.snapshot();due=state['next_check']
    assert q.clock()+30*60<=due<=q.clock()+120*60 and b.napcat.call.await_count==0
    for _ in range(3):await q.tick()
    assert q.random.snapshot()['next_check']==due
    from app.qzone_random import RandomSharing
    restored=RandomSharing(q);assert restored.snapshot()['next_check']==due
    await q.close();await b.client.aclose();s.close()


@pytest.mark.asyncio
async def test_random_model_can_choose_not_to_share_and_unconfigured_owner_blocks(tmp_path):
    s,b,q=qbot(tmp_path);q.clock=lambda:1792976400
    q.data.save_config(s.load().account_id,QzoneConfig(auto_enabled=True,share_probability=1))
    b.generate=AsyncMock()
    await q.tick();assert b.napcat.call.await_count==0 and b.generate.await_count==0
    owner(s);q.data.save_config(s.load().account_id,QzoneConfig(owner_id='20002',auto_enabled=True,share_probability=1))
    await q.tick();q.clock=lambda:1792976400+1800
    with s.db:s.db.execute('UPDATE qzone_random_state SET next_check=?',(q.clock()-1,))
    b.generate=AsyncMock(return_value={'message':{'content':json.dumps({'share':False,'content':'','reason':'只是普通日常，暂时没有分享欲。'},ensure_ascii=False)}})
    await q.tick();await q.drain()
    assert b.napcat.call.await_count==0 and b.generate.await_count==1
    assert q.random.snapshot()['next_check']>q.clock()
    await q.close();await b.client.aclose();s.close()


@pytest.mark.asyncio
async def test_random_share_persists_owner_provenance_and_respects_cooldown(tmp_path):
    s,b,q=qbot(tmp_path);q.clock=lambda:1792976400;owner(s)
    q.data.save_config(s.load().account_id,QzoneConfig(owner_id='20002',auto_enabled=True,share_probability=1))
    await q.tick()
    b.generate=AsyncMock(return_value={'message':{'content':json.dumps({'share':True,'content':'聊起喜欢的书，心情很好。','reason':'有想分享的心情'})}})
    with s.db:s.db.execute('UPDATE qzone_random_state SET next_check=?',(q.clock()-1,))
    await q.tick();await q.drain()
    posts=q.data.list(s.load().account_id)['items'];assert len(posts)==1 and posts[0]['status']=='sent' and posts[0]['source_owner']=='20002'
    assert posts[0]['source_stamp'] and b.napcat.call.await_count==1
    with s.db:s.db.execute('UPDATE qzone_random_state SET next_check=?',(q.clock()-1,))
    await q.tick();await q.drain();assert b.napcat.call.await_count==1 and b.generate.await_count==1
    await q.close();await b.client.aclose();s.close()


@pytest.mark.asyncio
async def test_owner_day_material_excludes_future_events(tmp_path):
    from test_schedule import DAY,configured,NOW
    s,b,q=qbot(tmp_path);c=configured(s);c.transport='napcat';c.napcat.self_id='10001';s.save(c)
    sid=owner(s);q.data.save_config(c.account_id,QzoneConfig(owner_id='20002'));q.clock=lambda:NOW;b.schedule.clock=lambda:NOW
    day=b.schedule.for_scope(sid);plan={**DAY,'date':day.local(c).date().isoformat(),'revision':'fixture-revision'}
    day.saved=lambda config:plan
    result=q.owner.collect()['day'];minute=day.local(c).strftime('%H:%M')
    assert result['activities'] and all(i['start']<=minute for i in result['activities'])
    assert all(e['time']<=minute for e in result['events'])
    assert 'summary' not in result and 'location' not in str(result)
    await q.close();await b.client.aclose();s.close()


@pytest.mark.asyncio
async def test_restart_replaces_missed_opportunity_instead_of_publishing(tmp_path):
    from app.qzone_random import RandomSharing
    s,b,q=qbot(tmp_path);q.clock=lambda:1792976400;owner(s)
    q.data.save_config(s.load().account_id,QzoneConfig(owner_id='20002',auto_enabled=True,share_probability=1))
    await q.tick();due=q.random.snapshot()['next_check'];q.clock=lambda:due+1
    q.random=RandomSharing(q);b.generate=AsyncMock()
    await q.tick();await q.drain()
    assert q.random.snapshot()['next_check']>q.clock() and b.generate.await_count==0 and b.napcat.call.await_count==0
    await q.close();await b.client.aclose();s.close()


@pytest.mark.asyncio
async def test_old_derived_day_is_not_reintroduced_after_reset(tmp_path):
    from test_schedule import DAY,configured,NOW
    s,b,q=qbot(tmp_path);c=configured(s);c.transport='napcat';c.napcat.self_id='10001';s.save(c)
    sid=owner(s);q.data.save_config(c.account_id,QzoneConfig(owner_id='20002'));q.clock=lambda:NOW;b.schedule.clock=lambda:NOW
    day=b.schedule.for_scope(sid);plan={**DAY,'date':day.local(c).date().isoformat(),'revision':'old','source_epoch':0}
    day.saved=lambda config:plan
    assert q.owner.collect()['day']
    b.memory.data.reset_scope(sid)
    assert q.owner.collect()['day']=={}
    plan['source_epoch']=s.scopes.get(sid)['epoch']
    assert q.owner.collect()['day']
    await q.close();await b.client.aclose();s.close()


@pytest.mark.asyncio
async def test_chat_knows_only_current_bots_confirmed_owner_posts(tmp_path):
    from app.qzone_store import PostWrite
    s,b,q=qbot(tmp_path);sid=owner(s);other=owner(s,'30003')
    q.data.save_config(s.load().account_id,QzoneConfig(owner_id='20002'))
    account=s.load().account_id
    for status,text in [('sent','刚刚分享的晚风'),('draft','草稿秘密'),('failed','失败秘密'),('deleted','已删除秘密'),('unknown','未知秘密')]:
        post=q.data.create(account,PostWrite(content=text))
        q.data.state(account,post['id'],status,tid='tid' if status=='sent' else '')
    foreign=q.data.create('another-bot',PostWrite(content='其他机器人秘密'))
    q.data.state('another-bot',foreign['id'],'sent',tid='foreign')
    context=q.chat_context(sid)
    assert '刚刚分享的晚风' in context and '发布时间' in context
    for secret in ['草稿秘密','失败秘密','已删除秘密','未知秘密','其他机器人秘密']:
        assert secret not in context
    assert q.chat_context(other)==''
    q.data.save_config(account,QzoneConfig(owner_id='30003'))
    assert q.chat_context(sid)==''
    await q.close();await b.client.aclose();s.close()


@pytest.mark.asyncio
async def test_owner_asks_about_post_and_real_chat_prompt_contains_it(tmp_path):
    from test_napcat import napcat_server,message,configure
    from app.qzone import QzoneService
    from app.qzone_store import PostWrite
    from app.bot import Bot
    from app.store import Store
    from app.providers import ProviderConfig
    async with napcat_server() as (url,calls,connections):
        s=Store(tmp_path);configure(s,url);b=Bot(s);q=QzoneService(s,b)
        q.data.save_config(s.load().account_id,QzoneConfig(owner_id='20002'))
        post=q.data.create(s.load().account_id,PostWrite(content='晚风把今天的小烦恼吹散了'))
        q.data.state(s.load().account_id,post['id'],'sent',tid='confirmed')
        b.models=AsyncMock(return_value=['test']);b.provider=lambda selection:ProviderConfig(type='deepseek')
        b.generate=AsyncMock(return_value={'message':{'content':'就是刚才吹了会儿风，心情轻松了点。'}})
        await b.start()
        event=message();event['message'][0]['data']['text']='你刚刚发的动态什么意思？'
        await connections[0].send(json.dumps(event))
        for _ in range(150):
            if any(r['action']=='send_private_msg' for r in calls):break
            await asyncio.sleep(.01)
        assert b.generate.await_count==1
        assert any('晚风把今天的小烦恼吹散了' in m['content'] for m in b.generate.await_args.args[1])
        assert '晚风把今天的小烦恼吹散了' not in b.generate.await_args.args[1][0]['content']
        assert any(r['action']=='send_private_msg' for r in calls)
        await b.stop();await q.close();await b.client.aclose();s.close()
