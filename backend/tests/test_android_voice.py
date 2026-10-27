import asyncio
import json
from unittest.mock import AsyncMock
import pytest
from app.android_voice import AndroidVoice
from test_android_qq import setup_bridge

@pytest.mark.asyncio
async def test_voice_uses_persona_dialogue_and_confirmed_facts(tmp_path):
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    config=bot.store.load();config.rules.prompt='测试人格：直率自然，不强行撒娇';bot.store.save(config)
    bot.generate=AsyncMock(return_value={'message':{'content':'{"reply":"看到了，是 Android 12。这手机我收下啦。"}'},'eval_count':8})
    voice=AndroidVoice(bridge)
    answer=await voice.compose(bot,'completed',{'goal':'查看安卓版本','result':'Android version 为12','state':'completed','steps':[]},lambda:True)
    assert 'Android 12' in answer
    messages=bot.generate.call_args.args[1]
    assert config.rules.prompt in messages[0]['content']
    facts=json.loads(messages[-1]['content']);assert facts['phone_facts']['result']=='Android version 为12'
    assert bot.store.stats()['output_tokens']==8
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_can_omit_unnecessary_completion_but_not_explicit_status(tmp_path):
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    bot.generate=AsyncMock(return_value={'message':{'content':'{"reply":null}'}})
    voice=AndroidVoice(bridge);task={'goal':'去刷刷视频','result':'已打开视频应用','state':'completed','steps':[]}
    assert await voice.compose(bot,'completed',task,lambda:True) is None
    assert await voice.compose(bot,'status',task,lambda:True)
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_wrong_version_does_not_replace_actual_result(tmp_path):
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    bot.generate=AsyncMock(return_value={'message':{'content':'{"reply":"是 Android 14哦。"}'}})
    answer=await AndroidVoice(bridge).compose(bot,'completed',{'goal':'查看安卓版本','result':'Android version 为12','state':'completed','steps':[]},lambda:True)
    assert '12' in answer and '14' not in answer
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_late_model_reply_cannot_send_after_authorization_changes(tmp_path):
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    valid=True
    async def generate(*args,**kwargs):
        nonlocal valid
        valid=False
        return {'message':{'content':'{"reply":"看到了，是12。"}'}}
    bot.generate=generate
    assert await AndroidVoice(bridge).compose(bot,'completed',{'goal':'查看版本','result':'Android12','state':'completed','steps':[]},lambda:valid) is None
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_model_failure_uses_short_truthful_nontechnical_fallback(tmp_path):
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    bot.generate=AsyncMock(side_effect=ValueError('provider-error-sentinel'))
    answer=await AndroidVoice(bridge).compose(bot,'failed',{'goal':'查看安卓版本','result':'操作模型连续两次返回无效格式，未执行本轮动作','state':'failed','steps':[]},lambda:True)
    assert answer and 'provider-error' not in answer and '任务' not in answer and 'y2' not in answer
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_service_close_cancels_completed_task_still_composing_reply(tmp_path):
    from test_android_qq import payload
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    entered=asyncio.Event()
    async def voice(bot,phase,task,guard):
        if phase=='started':return '我看看。'
        entered.set();await asyncio.sleep(30)
    bridge.voice=voice
    await bot.handle(payload('/手机 看看版本'))
    job=tasks.list('default')[0];await entered.wait()
    await tasks.close()
    assert tasks.jobs[job['id']].done()
    await manager.close()

@pytest.mark.asyncio
async def test_unnecessary_completion_can_be_silent_without_duplicate_notice(tmp_path):
    from test_android_qq import payload
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    async def voice(bot,phase,task,guard):return '我去逛一会儿。' if phase=='started' else None
    bridge.voice=voice
    await bot.handle(payload('/手机 去刷刷视频'))
    job=tasks.list('default')[0];await tasks.jobs[job['id']]
    assert bot.api.await_count==1
    assert tasks.get('default',job['id'])['notification']=='skipped'
    await bridge.notify('default',job['id'])
    assert bot.api.await_count==1
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_stopped_task_cannot_send_delayed_start_reply(tmp_path):
    from test_android_qq import payload
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    start_entered=asyncio.Event();resume=asyncio.Event()
    async def decide(*args):await asyncio.sleep(30)
    tasks.decide=decide
    async def voice(bot,phase,task,guard):
        if phase=='started':start_entered.set();await resume.wait();return '我去看看。'
        return '好，先停下。'
    bridge.voice=voice
    handling=asyncio.create_task(bot.handle(payload('/手机 看看版本')))
    await start_entered.wait()
    await bot.handle(payload('/停止手机',mid='stop-now'))
    resume.set();await handling
    sent=[call.kwargs['json']['content'] for call in bot.api.call_args_list]
    assert sent==['好，先停下。']
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_fast_completion_replaces_late_start_and_still_answers(tmp_path):
    from test_android_qq import payload
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    entered=asyncio.Event();resume=asyncio.Event()
    async def voice(bot,phase,task,guard):
        if phase=='started':entered.set();await resume.wait();return '我去看看。'
        if phase=='completed_unannounced':return '看到了，是 Android12。'
        return None
    bridge.voice=voice
    handling=asyncio.create_task(bot.handle(payload('/手机 看看版本')))
    await entered.wait()
    job=tasks.list('default')[0];await tasks.jobs[job['id']]
    resume.set();await handling
    sent=[call.kwargs['json']['content'] for call in bot.api.call_args_list]
    assert sent==['看到了，是 Android12。']
    assert tasks.get('default',job['id'])['notification']=='sent'
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_natural_plain_text_is_used_instead_of_fixed_fallback(tmp_path):
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    text='看到了，这台显示 Android 12。'
    bot.generate=AsyncMock(return_value={'message':{'content':text}})
    answer=await AndroidVoice(bridge).compose(bot,'completed',{'goal':'看看安卓版本','state':'completed','result':'Android version为12','steps':[]},lambda:True)
    assert answer==text
    await tasks.close();await manager.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('phase,state,text,forbidden',[
    ('failed','failed','刚才没成功，等下我再试试。','再试'),
    ('status','running','马上就好。','马上'),
    ('stopped','unknown','已经全部完成了。','完成'),
])
async def test_voice_cannot_promise_retry_deadline_or_unknown_success(tmp_path,phase,state,text,forbidden):
    manager,tasks,bridge,bot=await setup_bridge(tmp_path)
    bot.generate=AsyncMock(return_value={'message':{'content':text}})
    result=await AndroidVoice(bridge).compose(bot,phase,{'goal':'查看安卓版本','state':state,'result':'未能确认操作结果','steps':[]},lambda:True)
    assert result and forbidden not in result
    if state=='unknown':assert '确认' in result
    await tasks.close();await manager.close()
