import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest
from app.bot import Bot
from app.store import Store
from app.config import RulesConfig
from pydantic import ValidationError
from test_providers import client


def event(mid,text,user='alice',group=None):
    return {'t':'GROUP_AT_MESSAGE_CREATE' if group else 'C2C_MESSAGE_CREATE','d':{'id':mid,'content':text,'author':{'member_openid' if group else 'user_openid':user},**({'group_openid':group} if group else {})}}


def make(tmp_path):
    s=Store(tmp_path);c=s.load();c.qq.app_id='111';c.qq.group_reply=True;c.rules.cooldown=0;c.rules.split_delay=0;c.rules.debounce_seconds=.2;c.rules.debounce_max_wait=1; s.save(c)
    b=Bot(s);b.group_identity.fetch=AsyncMock(return_value={});b.state='connected';b.generate=AsyncMock(return_value={'message':{'content':'我想听，快说说！'},'prompt_eval_count':10,'eval_count':5});b.api=AsyncMock(return_value={'id':'ok'})
    return s,b


async def idle(bot):
    async with asyncio.timeout(5):
        while bot.inbox.snapshot()['queued'] or bot.inbox.active:
            await asyncio.sleep(.01)


async def close(store,bot):
    await bot.stop();await bot.client.aclose();store.close()


def test_debounce_validation():
    c=RulesConfig();assert c.debounce_enabled and c.debounce_seconds==3 and c.debounce_max_wait==10 and c.debounce_max_messages==10
    for values in ({'debounce_seconds':0},{'debounce_max_wait':61},{'debounce_seconds':5,'debounce_max_wait':2},{'debounce_max_messages':11}):
        with pytest.raises(ValidationError):RulesConfig(**values)


@pytest.mark.asyncio
async def test_burst_is_one_call_and_each_original_is_archived(tmp_path):
    s,b=make(tmp_path)
    texts=['你知道吗','我今天遇到个巨好玩的事情','你想不想听']
    for i,text in enumerate(texts):
        await b.receive(event(str(i),text));await asyncio.sleep(.06)
    assert b.generate.await_count==0
    await idle(b)
    assert b.generate.await_count==1
    assert b.generate.await_args.args[1][-1]['content']=='\n'.join(texts)
    rows=s.db.execute("SELECT content FROM chat_messages WHERE role='user' ORDER BY id").fetchall()
    assert [r['content'] for r in rows]==texts
    assert s.stats()['received']==3 and s.stats()['total_tokens']==15
    assert len(s.history('user:alice:alice',6))==2
    assert b.api.await_args.kwargs['json']['msg_id']=='2'
    batch=next(e for e in s.events.query()['items'] if e['event']=='message.batch_started')
    assert batch['details']['batch_count']==3
    detail=s.events.detail(next(e['id'] for e in s.events.query()['items'] if e['event']=='message.sent'))
    assert [m['content'] for m in detail['messages'] if m['role']=='user']==texts
    assert all(r['payload']=='' for r in s.db.execute('SELECT payload FROM message_inbox'))
    await close(s,b)


@pytest.mark.asyncio
async def test_new_messages_during_inference_wait_and_form_next_batch(tmp_path):
    s,b=make(tmp_path);entered=asyncio.Event();release=asyncio.Event();calls=[]
    async def generate(*args,**kwargs):
        calls.append(args[1][-1]['content'])
        if len(calls)==1:entered.set();await release.wait()
        return {'message':{'content':'回答'+str(len(calls))}}
    b.generate=generate
    await b.receive(event('a','第一轮'))
    await asyncio.wait_for(entered.wait(),2)
    await b.receive(event('b','再补充一下'));await b.receive(event('c','还有这个'))
    await asyncio.sleep(.3);assert len(calls)==1
    release.set();await idle(b)
    assert calls==['第一轮','再补充一下\n还有这个']
    assert len(s.history('user:alice:alice',6))==4
    await close(s,b)


@pytest.mark.asyncio
async def test_cooldown_and_per_batch_cap_queue_every_message(tmp_path):
    s,b=make(tmp_path);c=s.load();c.rules.debounce_max_messages=2;c.rules.cooldown=1;s.save(c)
    for i in range(5):await b.receive(event(str(i),'消息'+str(i)))
    await idle(b)
    questions=[call.args[1][-1]['content'] for call in b.generate.await_args_list]
    assert questions==['消息0\n消息1','消息2\n消息3','消息4']
    assert s.stats()['received']==5
    await close(s,b)


@pytest.mark.asyncio
async def test_users_and_group_members_are_isolated_and_duplicates_ignored(tmp_path):
    s,b=make(tmp_path)
    for user,group in [('alice',None),('bob',None),('alice','g'),('bob','g')]:
        p=event(user+str(group),'私有消息'+user+str(group),user,group)
        await b.receive(p);await b.receive(p)
    await idle(b)
    assert b.generate.await_count==4 and s.stats()['received']==4
    assert all(call.args[1][-1]['content'].count('私有消息')==1 for call in b.generate.await_args_list)
    await close(s,b)


@pytest.mark.asyncio
async def test_confirmed_reset_clears_buffer_but_request_and_cancel_do_not(tmp_path):
    s,b=make(tmp_path);await b.receive(event('1','缓冲中的旧问题'))
    prompt=await b.receive(event('r1','/reset'));await prompt
    assert b.inbox.snapshot()['queued']==1
    confirm=await b.receive(event('r2','/reset 确认'));await confirm
    await idle(b);assert b.generate.await_count==0
    await b.receive(event('2','全新的问题'));await idle(b)
    assert b.generate.await_count==1 and '旧问题' not in b.generate.await_args.args[1][-1]['content']
    await close(s,b)


@pytest.mark.asyncio
async def test_waiting_queue_survives_stop_restart_without_plaintext_payload(tmp_path):
    s,b=make(tmp_path);await b.receive(event('1','独有的等待内容'))
    raw=s.db.execute('SELECT payload FROM message_inbox').fetchone()[0]
    assert '独有的等待内容' not in raw
    await close(s,b)
    s=Store(tmp_path);b=Bot(s);b.state='connected';b.generate=AsyncMock(return_value={'message':{'content':'恢复成功'}});b.api=AsyncMock(return_value={'id':'ok'})
    b.inbox.start();await idle(b)
    assert b.generate.await_count==1 and b.generate.await_args.args[1][-1]['content']=='独有的等待内容'
    await close(s,b)


@pytest.mark.asyncio
async def test_max_wait_submits_despite_continuing_messages(tmp_path):
    s,b=make(tmp_path);c=s.load();c.rules.debounce_seconds=.8;c.rules.debounce_max_wait=1;s.save(c)
    for i in range(5):await b.receive(event(str(i),str(i)));await asyncio.sleep(.25)
    assert b.generate.await_count>=1
    await idle(b);await close(s,b)


def test_debounce_presentation_save_preserves_context(client):
    manager=client.app.state.manager;r=client.portal.call(manager.get,'default')
    client.portal.call(r.store.save_history,'user:a:a',[{'role':'user','content':'keep'}],6)
    c=client.get('/api/bots/default/settings').json();c['qq'].pop('secret_set');c['rules'].update(debounce_enabled=True,debounce_seconds=2,debounce_max_wait=8,debounce_max_messages=8)
    assert client.put('/api/bots/default/settings',json=c).status_code==200
    assert client.portal.call(r.store.history,'user:a:a',6)


@pytest.mark.asyncio
async def test_actual_websocket_burst_calls_model_once(tmp_path):
    from websockets.asyncio.server import serve
    s,b=make(tmp_path)
    async def gateway(ws):
        await ws.send(json.dumps({'op':10,'d':{'heartbeat_interval':1000}}));await ws.recv()
        await ws.send(json.dumps({'op':0,'t':'READY','s':1,'d':{'session_id':'fixture'}}))
        for i,text in enumerate(['你知道吗','今天特别有趣','你想听吗']):
            await ws.send(json.dumps({'op':0,'t':'C2C_MESSAGE_CREATE','s':i+2,'d':event(str(i),text)['d']}))
        await ws.wait_closed()
    async with serve(gateway,'127.0.0.1',0) as server:
        async def api(method,path,**kwargs):
            return {'url':f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'} if path=='/gateway' else {'id':'sent'}
        b.api=AsyncMock(side_effect=api);b.access_token=AsyncMock(return_value='fixture-token')
        b.task=asyncio.create_task(b.run())
        async with asyncio.timeout(3):
            while s.stats()['received']<3:await asyncio.sleep(.01)
        await idle(b)
        assert b.generate.await_count==1
        assert b.generate.await_args.args[1][-1]['content']=='你知道吗\n今天特别有趣\n你想听吗'
        await b.stop()
    await b.client.aclose();s.close()


@pytest.mark.asyncio
async def test_more_users_than_slots_are_queued_instead_of_dropped(tmp_path):
    s,b=make(tmp_path);release=asyncio.Event();calls=[]
    async def generate(*args,**kwargs):
        calls.append(args[1][-1]['content']);await release.wait();return {'message':{'content':'好'}}
    b.generate=generate
    for i in range(5):await b.receive(event(str(i),'消息'+str(i),'user'+str(i)))
    await asyncio.sleep(.35)
    assert len(calls)==4 and b.inbox.snapshot()['queued']==1
    release.set();await idle(b)
    assert len(calls)==5 and s.stats()['received']==5
    await close(s,b)


@pytest.mark.asyncio
async def test_unconfirmed_sending_is_not_replayed_after_restart(tmp_path):
    s,b=make(tmp_path);await b.receive(event('1','可能已经发送'))
    with s.db:s.db.execute("UPDATE message_inbox SET status='sending',batch_id='interrupted'")
    await close(s,b)
    s=Store(tmp_path);b=Bot(s);b.state='connected';b.generate=AsyncMock();b.api=AsyncMock();b.inbox.start()
    await asyncio.sleep(.3)
    assert b.generate.await_count==0
    row=s.db.execute('SELECT status,payload FROM message_inbox').fetchone();assert row['status']=='uncertain' and row['payload']==''
    await close(s,b)


@pytest.mark.asyncio
async def test_reset_interrupts_inference_and_cancels_next_batch(tmp_path):
    s,b=make(tmp_path);entered=asyncio.Event()
    async def generate(*args,**kwargs):entered.set();await asyncio.Event().wait()
    b.generate=generate
    await b.receive(event('first','旧问题'));await asyncio.wait_for(entered.wait(),2)
    await b.receive(event('next','另一个旧问题'))
    request=await b.receive(event('reset1','/reset'));await request
    confirm=await b.receive(event('reset2','/reset confirm'));await confirm
    await idle(b)
    assert s.db.execute("SELECT COUNT(*) FROM message_inbox WHERE status='canceled'").fetchone()[0]==2
    assert not s.history('user:alice:alice',6)
    b.generate=AsyncMock(return_value={'message':{'content':'重新开始'}})
    await b.receive(event('new','新问题'));await idle(b)
    assert b.generate.await_count==1
    await close(s,b)


@pytest.mark.asyncio
async def test_picture_messages_split_at_three_images_without_loss(tmp_path,monkeypatch):
    s,b=make(tmp_path)
    b.request=AsyncMock(return_value={'capabilities':['vision']})
    async def load(client,items):return ['image']*len(items),[]
    monkeypatch.setattr('app.bot.load_images',load)
    for i in range(4):
        p=event(str(i),'图片'+str(i));p['d']['attachments']=[{'content_type':'image/png','url':'https://qpic.cn/test.png'}]
        await b.receive(p)
    await idle(b)
    assert b.generate.await_count==2
    assert [len(call.args[1][-1]['images']) for call in b.generate.await_args_list]==[3,1]
    assert s.db.execute("SELECT COUNT(*) FROM chat_messages WHERE role='user' AND attachment_count=1").fetchone()[0]==4
    await close(s,b)


@pytest.mark.asyncio
async def test_pending_message_not_discarded_after_explicit_memory_edit(tmp_path):
    s,b=make(tmp_path);c=s.load();c.memory.enabled=True;c.memory.embedding.provider_id='a'*32;c.memory.embedding.model='embed';s.save(c)
    b.memory.context=AsyncMock(return_value='')
    b.memory.stamp=lambda sid:(s.load().qq.app_id,b.memory.data.epoch(sid))
    b.memory.matches=lambda sid,stamp:b.memory.stamp(sid)==stamp
    await b.receive(event('1','之前排队的问题'))
    command=await b.receive(event('remember','/记住 我喜欢喝茶'));await command
    await idle(b)
    assert b.generate.await_count==1 and '之前排队的问题' in b.generate.await_args.args[1][-1]['content']
    await close(s,b)


@pytest.mark.asyncio
async def test_out_of_order_duplicate_does_not_reset_contact_state(tmp_path):
    s,b=make(tmp_path)
    await b.receive(event('a','第一条'));await b.receive(event('b','第二条'))
    with s.db:s.db.execute("UPDATE proactive_contacts SET unanswered=2,next_idle=12345 WHERE app_id='111' AND id='alice'")
    before=s.contact('111','alice')
    await b.receive(event('a','第一条'))
    after=s.contact('111','alice')
    assert after['last_inbound_id']=='b'
    assert after['last_received']==before['last_received'] and after['unanswered']==2 and after['next_idle']==12345
    await close(s,b)


@pytest.mark.asyncio
async def test_generating_restart_requeues_without_double_received_count(tmp_path):
    s,b=make(tmp_path);entered=asyncio.Event()
    async def generate(*args,**kwargs):entered.set();await asyncio.Event().wait()
    b.generate=generate
    await b.receive(event('1','生成中重启的问题'));await asyncio.wait_for(entered.wait(),2)
    await b.stop()
    assert s.db.execute('SELECT status FROM message_inbox').fetchone()[0]=='queued'
    await b.client.aclose();s.close()
    s=Store(tmp_path);b=Bot(s);b.state='connected';b.generate=AsyncMock(return_value={'message':{'content':'恢复后回答'}});b.api=AsyncMock(return_value={'id':'ok'});b.inbox.start()
    await idle(b)
    assert b.generate.await_count==1 and s.stats()['received']==1
    assert s.db.execute("SELECT COUNT(*) FROM chat_messages WHERE role='user'").fetchone()[0]==1
    await close(s,b)


@pytest.mark.asyncio
async def test_reset_during_send_does_not_restore_prefix_or_emit_tail(tmp_path):
    s,b=make(tmp_path);c=s.load();c.rules.split_length=20;c.rules.split_delay=.1;s.save(c)
    b.generate=AsyncMock(return_value={'message':{'content':'第一段回答有很多内容，需要完整地说清楚。第二段回答也是旧的消息，现在不应该继续发出来。'}})
    entered=asyncio.Event();outgoing=[]
    async def api(*args,**kwargs):
        message=kwargs['json'];outgoing.append(message)
        if message['msg_id']=='old':
            entered.set()
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:return {'id':'already-delivered'}
        return {'id':'control-accepted'}
    b.api=AsyncMock(side_effect=api)
    await b.receive(event('old','旧问题'));await asyncio.wait_for(entered.wait(),2)
    task=await b.receive(event('r1','/reset'));await task
    task=await b.receive(event('r2','/reset confirm'));await task
    await idle(b)
    assert len([m for m in outgoing if m['msg_id']=='old'])==1
    assert not s.history('user:alice:alice',6)
    assert s.db.execute('SELECT COUNT(*) FROM memory_jobs').fetchone()[0]==0
    assert s.db.execute('SELECT status FROM message_inbox').fetchone()[0]=='canceled'
    await close(s,b)
