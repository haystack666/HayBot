import asyncio
import time
from unittest.mock import AsyncMock
import pytest
from app.registry import BotManager
from app.android import AndroidTasks,AndroidConfig
from app.android_qq import AndroidQQ
from test_android import png

async def setup_bridge(tmp_path):
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path);manager.android_service=tasks
    bridge=AndroidQQ(tasks);manager.android_qq=bridge
    bot=manager.get('default').bot;bot.android=bridge
    cfg=bot.store.load();cfg.transport='napcat';cfg.napcat.self_id='20002';cfg.napcat.ws_url='ws://test';cfg.rules.cooldown=0;bot.store.save(cfg);bot.state='connected'
    tasks.save_config('default',AndroidConfig(enabled=True,model='vision',qq_enabled=True,qq_owner_id='10001'))
    async def voice(bot,phase,task,guard):
        if not guard():return None
        if phase=='started':return '我去看看。'
        if phase=='no_task':return '这会儿没在弄手机。'
        if phase=='stopped':return '好，先停下。'
        return task.get('result') or '还在看。'
    bridge.voice=AsyncMock(side_effect=voice)
    bot.api=AsyncMock(return_value={'id':'receipt'})
    async def gateway(method,path,body=None,**kwargs):
        if path.endswith('/devices'):return {'devices':[{'id':'0'*32,'state':'running'}]}
        if path.endswith('/claim'):return {'lease':body['lease']}
        if path.endswith('/observe'):return {'image':png(),'hierarchy':''}
        return {'ok':True}
    tasks.gateway.request=gateway
    tasks.decide=AsyncMock(return_value={'done':True,'result':'Android12，已返回桌面'})
    return manager,tasks,bridge,bot

def payload(text,user='10001',mid='one',group=False):
    return {'t':'GROUP_AT_MESSAGE_CREATE' if group else 'C2C_MESSAGE_CREATE','d':{'id':mid,'content':text,'timestamp':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'author':{'member_openid' if group else 'user_openid':user},**({'group_openid':'12345'} if group else {})}}

@pytest.mark.asyncio
async def test_qq_command_submits_background_task_and_receipt_confirmed_result(tmp_path):
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    await bot.handle(payload('/手机 打开设置查看版本'))
    job=tasks.list('default')[0];await tasks.jobs[job['id']]
    assert job['origin']['requester_id']=='10001'
    final=tasks.get('default',job['id']);assert final['state']=='completed' and final['notification']=='sent'
    sent=[c.kwargs['json']['content'] for c in bot.api.call_args_list]
    assert '我去看看。' in sent and any('Android12' in s for s in sent)
    assert all('手机任务已' not in s and '/手机进度' not in s for s in sent)
    await bridge.notify('default',job['id'])
    assert len(bot.api.call_args_list)==len(sent)
    await bot.handle(payload('/手机进度',mid='two'))
    assert 'Android12' in bot.api.call_args.kwargs['json']['content']
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_non_owner_and_group_cannot_operate_or_get_task_results(tmp_path):
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    await bot.handle(payload('/手机 打开设置',user='10003'))
    await bot.handle(payload('/手机进度',user='10003',mid='two'))
    await bot.handle(payload('/手机 打开设置',mid='three',group=True))
    assert tasks.list('default')==[]
    assert 'Android12' not in str(bot.api.call_args_list)
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_natural_request_is_routed_but_ordinary_chat_is_not(tmp_path):
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    bridge.classify=AsyncMock(return_value={'request':'start','goal':'打开设置查看版本'})
    await bot.handle(payload('用你的手机打开设置查看系统版本'))
    job=tasks.list('default')[0];await tasks.jobs[job['id']]
    assert job['goal']=='打开设置查看版本'
    assert bridge.classify.call_count==1
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_reset_floor_during_model_wait_prevents_phone_action_and_notification(tmp_path):
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    entered=asyncio.Event();resume=asyncio.Event()
    async def decide(*args):entered.set();await resume.wait();return {'action':{'kind':'key','key':'home'}}
    tasks.decide=decide;calls=[];original=tasks.gateway.request
    async def gateway(method,path,body=None,**kwargs):calls.append(path);return await original(method,path,body,**kwargs)
    tasks.gateway.request=gateway
    await bot.handle(payload('/手机 打开设置'))
    job=tasks.list('default')[0];await entered.wait()
    with bot.store.db:bot.store.db.execute('UPDATE user_scopes SET source_floor=999999')
    resume.set();await tasks.jobs[job['id']]
    assert not any(p.endswith('/action') for p in calls)
    assert tasks.get('default',job['id'])['notification']!='sent'
    assert len(bot.api.call_args_list)==1
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_status_after_reset_does_not_redisclose_old_goal_or_result(tmp_path):
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    await bot.handle(payload('/手机 打开设置查看版本'))
    job=tasks.list('default')[0];await tasks.jobs[job['id']]
    with bot.store.db:bot.store.db.execute('UPDATE user_scopes SET source_floor=999999')
    # New message is after the reset floor; the old task is not.
    with bot.store.db:bot.store.db.execute("UPDATE sqlite_sequence SET seq=1000000 WHERE name='chat_messages'")
    await bot.handle(payload('/手机进度',mid='after-reset'))
    response=bot.api.call_args.kwargs['json']['content']
    assert 'Android12' not in response and '打开设置查看版本' not in response
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_websocket_commands_reply_stop_and_dedupe_while_model_waits(tmp_path):
    import json
    from app.bot import Bot
    from test_napcat import napcat_server
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    async with napcat_server(account=20002) as (url,calls,connections):
        c=bot.store.load();c.napcat.ws_url=url;bot.store.save(c)
        bot.api=Bot.api.__get__(bot,Bot)
        entered=asyncio.Event()
        async def decide(*args):entered.set();await asyncio.sleep(30)
        tasks.decide=decide
        await bot.napcat.start();bot.state='connected'
        event={'post_type':'message','message_type':'private','self_id':20002,'user_id':10001,'message_id':301,'time':int(time.time()),'sender':{},'message':[{'type':'text','data':{'text':'/手机 打开设置'}}]}
        await connections[0].send(json.dumps(event));await asyncio.wait_for(entered.wait(),3)
        # An actual duplicate WebSocket event must not create a second job.
        await connections[0].send(json.dumps(event))
        event['message_id']=302;event['message'][0]['data']['text']='/停止手机'
        await connections[0].send(json.dumps(event))
        deadline=time.monotonic()+3
        while tasks.list('default')[0]['state']!='cancelled' and time.monotonic()<deadline:await asyncio.sleep(.02)
        await asyncio.sleep(.05)
        assert len(tasks.list('default'))==1
        assert tasks.list('default')[0]['state']=='cancelled'
        assert sum(c['action']=='send_private_msg' for c in calls)>=2
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_screenshot_command_sends_real_image_only_to_owner(tmp_path):
    import base64
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    bot.napcat.send_picture=AsyncMock(return_value={'id':'picture-receipt'})
    await bot.handle(payload('/手机截图'))
    assert bot.napcat.send_picture.await_count==1
    args=bot.napcat.send_picture.call_args
    assert args.args[0] is False and args.args[1]=='10001'
    assert args.args[2].startswith(b'\xff\xd8')
    assert tasks.list('default')==[]
    row=bot.store.db.execute("SELECT attachment_count,status FROM chat_messages WHERE source='android_screenshot'").fetchone()
    assert row['attachment_count']==1 and row['status']=='sent'
    await bot.handle(payload('/手机截图',user='10003',mid='other'))
    assert bot.napcat.send_picture.await_count==1
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_reset_during_screenshot_capture_prevents_image_send(tmp_path):
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    bot.napcat.send_picture=AsyncMock(return_value={'id':'picture-receipt'})
    original=tasks.gateway.request
    async def gateway(method,path,body=None,**kw):
        value=await original(method,path,body,**kw)
        if path.endswith('/observe'):
            with bot.store.db:bot.store.db.execute('UPDATE user_scopes SET source_floor=999999')
        return value
    tasks.gateway.request=gateway
    await bot.handle(payload('/手机截图'))
    bot.napcat.send_picture.assert_not_awaited()
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_official_screenshot_upload_does_not_send_until_guard_and_media_ready(tmp_path):
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    c=bot.store.load();c.transport='qq_official';c.qq.app_id='123456';bot.store.save(c)
    bot.api=AsyncMock(side_effect=[{'file_info':'media-token'},{'id':'picture-receipt'}])
    await bot.handle(payload('/手机截图'))
    assert bot.api.await_count==2
    upload,sent=bot.api.call_args_list
    assert upload.args[1].endswith('/files') and upload.kwargs['json']['srv_send_msg'] is False
    assert sent.kwargs['json']['msg_type']==7
    assert sent.kwargs['json']['media']['file_info']=='media-token'
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_contextual_show_request_receives_recent_real_phone_task_and_private_dialogue(tmp_path):
    import json
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    await bot.handle(payload('/手机 去哔哩哔哩看看视频'))
    job=tasks.list('default')[0];await tasks.jobs[job['id']]
    bot.generate=AsyncMock(return_value={'message':{'content':'{"request":"screenshot"}'}})
    bot.napcat.send_picture=AsyncMock(return_value={'id':'picture-receipt'})
    await bot.handle(payload('你刷的啥？给我看看',mid='context-show'))
    bot.napcat.send_picture.assert_awaited_once()
    model_input=json.loads(bot.generate.call_args.args[1][1]['content'])
    assert model_input['recent_phone_tasks'][0]['goal']=='去哔哩哔哩看看视频'
    assert any('去哔哩哔哩' in turn['content'] for turn in model_input['recent_dialogue'])
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_contextual_router_does_not_include_tasks_or_dialogue_before_reset(tmp_path):
    import json
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    await bot.handle(payload('/手机 旧的私人目标'))
    job=tasks.list('default')[0];await tasks.jobs[job['id']]
    with bot.store.db:bot.store.db.execute('UPDATE user_scopes SET source_floor=999999')
    bot.generate=AsyncMock(return_value={'message':{'content':'{"request":"none"}'}})
    await bridge.classify(bot,'给我看看',[])
    data=json.loads(bot.generate.call_args.args[1][1]['content'])
    assert data['recent_phone_tasks']==[] and data['recent_dialogue']==[]
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_late_notice_receipt_after_reset_is_excluded_from_router_context(tmp_path):
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    c=bot.store.load();data=payload('/手机 旧私人目标')['d'];bot.capture_incoming({'t':'C2C_MESSAGE_CREATE','d':data},c)
    scope=bot.store.scopes.ensure(c.account_id,'user','10001','10001')
    source=bot.store.db.execute('SELECT MAX(id) FROM chat_messages').fetchone()[0]
    def guard():return bot.store.scopes.get(scope['id'],c.account_id)['source_floor']<source
    async def send(*args,**kwargs):
        with bot.store.db:bot.store.db.execute('UPDATE user_scopes SET source_floor=?',(source,))
        return {'id':'late-receipt'}
    bot.api=send
    await bridge.send(bot,c,data,'10001','旧私人目标的结果',guard=guard)
    assert bridge.intent_context(bot)['recent_dialogue']==[]
    await tasks.close();await manager.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('operation',['reset','stop'])
async def test_reset_or_bot_stop_revokes_inflight_qq_phone_task(tmp_path,operation):
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    entered=asyncio.Event()
    async def decide(*args):entered.set();await asyncio.sleep(30)
    tasks.decide=decide;original=tasks.gateway.request;calls=[]
    async def gateway(method,path,body=None,**kw):calls.append(path);return await original(method,path,body,**kw)
    tasks.gateway.request=gateway
    await bot.handle(payload('/手机 打开设置'))
    job=tasks.list('default')[0];await entered.wait()
    if operation=='reset':
        await bot.handle(payload('/reset',mid='reset-request'))
        await bot.handle(payload('/reset confirm',mid='reset-confirm'))
    else:await bot.stop()
    assert tasks.get('default',job['id'])['state']=='cancelled'
    assert any(path.endswith('/revoke') for path in calls)
    assert not any(path.endswith('/action') for path in calls)
    await tasks.close();await manager.close()
