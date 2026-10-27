import asyncio
import pytest
from app.android_decisions import parse_decision
from app.android_companion import CompanionConfig, SocialJournal, VideoBuffer, login_screen


def test_watch_decision_and_login_screen_detection():
    assert parse_decision('{"watch":{"frames":6,"interval_seconds":3}}')['watch']['frames']==6
    with pytest.raises(ValueError):parse_decision('{"watch":{"frames":100,"interval_seconds":0}}')
    assert login_screen('<node class="android.widget.EditText" password="true" />')
    assert login_screen('<node class="android.widget.EditText" text="请输入验证码" />')
    assert not login_screen('<node text="登录" class="android.widget.Button"/>')


def test_social_policy_scoping_rates_dedup_and_unknown_are_durable(tmp_path):
    cfg=CompanionConfig(platforms={'bilibili':{'comments':True,'mentions':True,'owner_id':'123','owner_name':'主人','cooldown_minutes':0}})
    journal=SocialJournal(tmp_path/'social.sqlite3')
    token=journal.reserve('bot-a','account-a','bilibili','video-1','hello',False,cfg)
    journal.finish(token,'unknown','发送结果不明确')
    with pytest.raises(ValueError):journal.reserve('bot-a','account-a','bilibili','video-1','hello',False,cfg)
    assert journal.reserve('bot-b','account-a','bilibili','video-1','hello',False,cfg)
    with pytest.raises(ValueError):journal.reserve('bot-a','account-a','douyin','v2','hi',False,cfg)
    with pytest.raises(ValueError):journal.reserve('bot-a','account-a','bilibili','v3','hi',True,CompanionConfig())
    journal.close()
    journal=SocialJournal(tmp_path/'social.sqlite3')
    assert journal.list('bot-a')[0]['state']=='unknown'
    journal.close()

@pytest.mark.asyncio
async def test_video_capture_is_bounded_and_runs_during_model_wait():
    count=0
    async def observe():
        nonlocal count
        count+=1
        return {'image':str(count),'at':float(count),'hierarchy':'caption '+str(count)}
    buffer=VideoBuffer(observe,interval=.01,limit=3)
    await buffer.start();await buffer.wait_batch(3)
    first=buffer.snapshot();await asyncio.sleep(.04);second=buffer.snapshot();await buffer.close()
    assert len(first['frames'])==3 and len(second['frames'])==3
    assert second['frames'][-1]['at']>first['frames'][-1]['at']
    assert second['audio_available'] is False
    assert second['observed_seconds']>0

@pytest.mark.asyncio
async def test_unknown_ui_cannot_bypass_public_send_guard(tmp_path):
    from app.android import AndroidTasks
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    with pytest.raises(ValueError):tasks.guard_public_action('default',{'steps':[]},{'hierarchy':''},{'kind':'text','text':'private'})
    with pytest.raises(ValueError):tasks.guard_public_action('default',{'steps':[]},{'hierarchy':'<hierarchy><node package="tv.danmaku.bili" text="发送" bounds="[0,0][200,200]"/></hierarchy>'},{'kind':'tap','x':10,'y':10})
    await tasks.close();await manager.close()


def test_content_and_mention_require_exact_observed_evidence():
    from app.android_companion import same_content, exact_identity, mention_in_editor
    assert not exact_identity('用户ID:1234','123')
    assert exact_identity('用户ID:123','123')
    assert not mention_in_editor('正文','主人','正文')
    assert mention_in_editor('@主人 正文','主人','正文')
    assert not same_content({'content_id':'v1','anchors':['标题A','作者A']},'<hierarchy><node text="标题B"/><node text="作者A"/></hierarchy>')
    assert same_content({'content_id':'v1','anchors':['标题A','作者A']},'<hierarchy><node text="标题A"/><node text="作者A"/></hierarchy>')

@pytest.mark.asyncio
async def test_login_fence_invalidates_old_screenshot_even_after_resume(tmp_path):
    from app.android import AndroidTasks
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    epoch=tasks.login_epoch('default','0'*32)
    tasks.set_login('default','0'*32,True)
    assert not tasks.login_valid('default','0'*32,epoch)
    tasks.set_login('default','0'*32,False)
    assert not tasks.login_valid('default','0'*32,epoch)
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_login_during_video_model_wait_fences_stale_action(tmp_path):
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from test_android import png
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    tasks.save_config('default',AndroidConfig(enabled=True,model='vision'))
    observations=0;decisions=0;entered=asyncio.Event();gated=asyncio.Event();actions=[]
    async def gateway(method,path,body=None,**kw):
        nonlocal observations
        if path.endswith('/claim'):return {'lease':'0'*32}
        if path.endswith('/login/begin'):gated.set();return {'owner_login':True}
        if path.endswith('/action'):actions.append(body);return {'ok':True}
        if path.endswith('/observe'):
            observations+=1
            tree='<node class="android.widget.EditText" password="true"/>' if entered.is_set() else '<node package="com.android.settings" text="Settings"/>'
            return {'image':png(),'hierarchy':tree,'at':float(observations)}
        return {'ok':True}
    async def decide(*args):
        nonlocal decisions
        decisions+=1
        if decisions==1:return {'watch':{'frames':3,'interval_seconds':.01}}
        entered.set();await gated.wait()
        return {'action':{'kind':'key','key':'home'}}
    tasks.gateway.request=gateway;tasks.decide=decide
    task=tasks.submit('default','0'*32,'看看视频')
    await asyncio.wait_for(tasks.jobs[task['id']],3)
    assert not actions and tasks.login_paused('default','0'*32)
    await tasks.close();await manager.close()
