import asyncio
import pytest
from app.android_decisions import parse_decision
from app.android_companion import CompanionConfig, SocialJournal, VideoBuffer, login_screen

def video_page(title='视频标题',author='作者甲'):
    return '<hierarchy><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/title" text="'+title+'"/><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/name" text="'+author+'"/><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/comment_layout" content-desc="评论" bounds="[600,600][720,700]"/></hierarchy>'

def test_backend_identifies_video_without_link_and_retains_only_controlled_comment_transition():
    from app.android_companion import page_context, bind_page_context, keeps_page_context
    first=page_context(video_page('同一个视频&#10;183万播放'), 'bilibili')
    assert first['content_id'].startswith('ui:v1:')
    assert first==page_context(video_page('同一个视频&#10;184万播放'),'bilibili')
    assert first!=page_context(video_page('另一视频'),'bilibili')
    assert page_context('<node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/title" text="热门评论"/>','bilibili') is None
    overlay={'hierarchy':'<hierarchy><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/input" class="android.widget.EditText" text="评论千万条，等你发一条"/></hierarchy>'}
    assert bind_page_context(overlay,first)==first
    partial={'hierarchy':overlay['hierarchy'].replace('</hierarchy>','<node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/title" text="另一个视频"/></hierarchy>')}
    assert bind_page_context(partial,first) is None
    commenter={'hierarchy':'<hierarchy><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/video_title" text="同一个视频"/><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/name" text="评论用户乙"/><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/comment_layout" content-desc="热门评论"/></hierarchy>'}
    assert bind_page_context(commenter,first)==first
    assert bind_page_context({'hierarchy':'<node package="com.android.chrome"/>'},first) is None
    assert keeps_page_context(video_page(),{'kind':'tap','x':650,'y':650})
    assert not keeps_page_context(video_page(),{'kind':'swipe'})
    assert not keeps_page_context(video_page(),{'kind':'launch','app':'chrome'})
    assert not keeps_page_context(video_page(),{'kind':'tap','x':300,'y':100})

def test_comment_placeholder_is_not_active_composer():
    from app.android_companion import public_editor
    assert not public_editor('<node class="android.widget.EditText" focused="false" text="评论千万条，等你发一条"/>')
    assert public_editor('<node class="android.widget.EditText" focused="true" hint="评论"/>')
    assert public_editor('<node class="android.widget.EditText" text="正文" resource-id="tv.danmaku.bili:id/comment_editor"/>')


def test_model_tree_distinguishes_search_hint_from_actual_input():
    import xml.etree.ElementTree as ET
    from app.android_companion import model_ui_tree
    tree='<hierarchy><node package="com.android.inputmethod.latin" text="'+('keyboard'*3000)+'"/><node package="com.android.systemui" content-desc="电池"/><node class="android.widget.EditText" text="deepseekharness" hint="deepseekharness"/><node class="android.widget.EditText" text="插画" hint="搜索"/><node class="android.widget.TextView" text="保留正文"/></hierarchy>'
    first,second,third=list(ET.fromstring(model_ui_tree(tree)))
    assert first.get('text')=='' and first.get('hint')=='deepseekharness'
    assert second.get('text')=='插画' and third.get('text')=='保留正文'
    assert 'text="deepseekharness"' in tree
    assert len(model_ui_tree(tree))<18000


def test_sharing_word_in_content_title_is_not_a_share_control():
    from app.android_companion import share_control
    tree='<hierarchy><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/title" text="色块起稿思路分享" bounds="[0,0][300,100]"/><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/frame_share" content-desc="分享，21个分享" bounds="[400,0][500,100]"/><node text="复制链接" bounds="[0,200][100,300]"/></hierarchy>'
    assert not share_control(tree,50,50)
    assert share_control(tree,450,50)
    assert share_control(tree,50,250)


@pytest.mark.asyncio
async def test_requested_owner_mention_cannot_finish_without_a_verified_comment(tmp_path):
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from unittest.mock import AsyncMock
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    tasks.save_config('default',AndroidConfig(enabled=True,model='vision'))
    calls=[]
    async def gateway(method,path,body=None,**kwargs):
        calls.append(path)
        if path.endswith('/claim'):return {'lease':'lease'}
        if path.endswith('/observe'):return {'hierarchy':video_page()}
        return {'ok':True}
    tasks.gateway.request=gateway
    tasks.decide=AsyncMock(return_value={'done':True,'result':'已经浏览完毕'})
    try:
        task=tasks.submit('default','0'*32,'看你喜欢的视频，记得艾特主人')
        await tasks.jobs[task['id']]
        result=tasks.get('default',task['id'])
        assert result['state']=='blocked' and '尚无核验成功' in result['result']
        assert not any(p.endswith('/action') for p in calls)
    finally:await tasks.close();await manager.close()

def test_ui_identity_also_deduplicates_preexisting_link_based_records(tmp_path):
    from app.android_companion import page_context
    cfg=CompanionConfig(platforms={'bilibili':{'comments':True,'cooldown_minutes':0}})
    journal=SocialJournal(tmp_path/'legacy.sqlite3')
    try:
        journal.reserve('bot','account','bilibili','BV-old-record','旧评论',False,cfg,anchors=['视频标题','作者甲'])
        context=page_context(video_page(),'bilibili')
        with pytest.raises(ValueError,match='重复'):
            journal.reserve('bot','account','bilibili',context['content_id'],'新评论',False,cfg,anchors=context['anchors'])
    finally:journal.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('rendered,expected',[('@主人 讲得很清楚。','verified'),('讲得很清楚。','unknown')])
async def test_published_mention_requires_owner_visible_in_actual_comment(tmp_path,rendered,expected):
    from app.android import AndroidTasks,AndroidConfig
    from app.android_companion import page_context
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(model='vision',companion={'platforms':{'bilibili':{'comments':True,'mentions':True,'owner_id':'123','owner_name':'主人','cooldown_minutes':0}}})
    tasks.save_config('default',cfg);context=page_context(video_page(),'bilibili')
    ident=tasks.social.reserve('default',manager.get('default').store.load().account_id,'bilibili',context['content_id'],'讲得很清楚。',True,cfg.companion,anchors=context['anchors'])
    tasks.social.finish(ident,'unknown','发送过一次')
    try:
        obs={'hierarchy':'<hierarchy><node package="tv.danmaku.bili" text="热门评论"/><node package="tv.danmaku.bili" class="android.widget.TextView" text="'+rendered+'"/></hierarchy>','content_context':context}
        result=await tasks.social_step('default',{},cfg,{'kind':'verify','platform':'bilibili','draft_id':ident},obs,'/device','lease')
        assert result['state']==expected
    finally:await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_at_toolbar_is_allowed_but_send_still_requires_social_flow(tmp_path):
    from app.android import AndroidTasks
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    tree='<hierarchy><node package="tv.danmaku.bili" class="android.widget.EditText" focused="true" hint="评论"/><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/at" text="@" bounds="[0,0][100,100]"/><node package="tv.danmaku.bili" text="发送" bounds="[200,0][300,100]"/></hierarchy>'
    try:
        tasks.guard_public_action('default',{'steps':[]},{'hierarchy':tree},{'kind':'tap','x':50,'y':50})
        with pytest.raises(ValueError):tasks.guard_public_action('default',{'steps':[]},{'hierarchy':tree},{'kind':'tap','x':250,'y':50})
    finally:await tasks.close();await manager.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('raw,finish,valid',[('这个讲解挺清楚。','stop',True),('','length',False),('<think>unfinished','length',False),('<｜DSML｜ invoke name="tap">','stop',False)])
async def test_deepseek_comment_draft_explicitly_disables_reasoning_only_for_draft(tmp_path,monkeypatch,raw,finish,valid):
    import httpx
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from app.providers import ProviderConfig
    from test_android import png
    from unittest.mock import AsyncMock
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    pid=manager.providers.save(ProviderConfig(type='deepseek',base_url='https://model.test/v1'))
    bodies=[]
    async def request(client,method,url,**kwargs):
        bodies.append(kwargs['json'])
        return httpx.Response(200,json={'choices':[{'message':{'content':raw},'finish_reason':finish}],'usage':{'completion_tokens':12}},request=httpx.Request(method,url))
    monkeypatch.setattr(httpx.AsyncClient,'request',request)
    try:
        cfg=AndroidConfig(enabled=True,provider_id=pid,model='deepseek-flash');tasks.save_config('default',cfg);tasks.run=AsyncMock()
        task=tasks.submit('default','0'*32,'公开草稿测试');await tasks.jobs[task['id']]
        if valid:
            result=await tasks.public_draft('default',cfg,{'image':png(),'hierarchy':video_page()},'bilibili',False,task['id'])
            assert result=='这个讲解挺清楚。'
        else:
            with pytest.raises(ValueError):await tasks.public_draft('default',cfg,{'image':png(),'hierarchy':video_page()},'bilibili',False,task['id'])
        diagnostic=tasks.diagnostics('default',task['id'])[0]
        assert diagnostic['metadata']['purpose']=='public_comment' and diagnostic['metadata']['finish_reason']==finish
        assert bodies[0].get('thinking')=={'type':'disabled'}
        assert manager.providers.get(pid).chat_thinking is False
    finally:await tasks.close();await manager.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('changed',[False,True],ids=['same-video','video-changed-during-generation'])
async def test_draft_uses_observed_identity_without_link_and_rechecks_after_generation(tmp_path,changed):
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from unittest.mock import AsyncMock
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(enabled=True,model='vision',companion={'platforms':{'bilibili':{'comments':True,'cooldown_minutes':0}}})
    tasks.save_config('default',cfg);tasks.run=AsyncMock()
    task=tasks.submit('default','0'*32,'private task must not become public text');await tasks.jobs[task['id']]
    tasks.public_draft=AsyncMock(return_value='这个讲解挺清楚。')
    async def gateway(*args,**kw):return {'hierarchy':video_page('另一视频' if changed else '视频标题')}
    tasks.gateway.request=gateway
    operation={'kind':'draft','platform':'bilibili','mention':False,'content_id':'model-made-up-id'}
    try:
        if changed:
            with pytest.raises(ValueError,match='变化'):
                await tasks.social_step('default',tasks.get('default',task['id']),cfg,operation,{'hierarchy':video_page()},'/device','lease')
            assert not tasks.social.list('default')
        else:
            result=await tasks.social_step('default',tasks.get('default',task['id']),cfg,operation,{'hierarchy':video_page()},'/device','lease')
            saved=tasks.social.get('default',result['draft_id'])
            assert saved['content_id'].startswith('ui:v1:') and saved['text']=='这个讲解挺清楚。'
            assert saved['content_id']!='model-made-up-id'
    finally:await tasks.close();await manager.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('verify',[True,False],ids=['verified','unverified-model-done'])
@pytest.mark.parametrize('rendered',[True,False],ids=['comment-visible','comment-missing'])
async def test_full_comment_flow_keeps_video_binding_through_editor_without_copying_link(tmp_path,verify,rendered):
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from unittest.mock import AsyncMock
    from test_android import png
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(enabled=True,model='vision',companion={'platforms':{'bilibili':{'comments':True,'cooldown_minutes':0}}})
    tasks.save_config('default',cfg);tasks.public_draft=AsyncMock(return_value='讲得很清楚。')
    phase='video';actions=[];turn=0
    def overlay():
        text='讲得很清楚。' if phase=='filled' else '评论千万条，等你发一条'
        shown='<node package="tv.danmaku.bili" class="android.widget.TextView" text="讲得很清楚。"/>' if phase=='published' and rendered else ''
        return '<hierarchy><node package="tv.danmaku.bili" text="热门评论"/>'+shown+'<node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/input" class="android.widget.EditText" text="'+text+'" bounds="[0,1100][600,1200]"/><node package="tv.danmaku.bili" text="发送" bounds="[600,1100][720,1200]"/></hierarchy>'
    async def gateway(method,path,body=None,**kw):
        nonlocal phase
        if path.endswith('/claim'):return {'lease':'lease'}
        if path.endswith('/cleanup'):return {'home':True,'background_cleared':True}
        if path.endswith('/observe'):return {'image':png(),'hierarchy':video_page() if phase=='video' else overlay()}
        if path.endswith('/action'):
            actions.append(body)
            if body['kind']=='text':phase='filled'
            elif body.get('x')==650 and body.get('y')==1150:phase='published'
            else:phase='editor'
        return {'ok':True}
    async def decide(bot,config,goal,obs,steps,tid):
        nonlocal turn
        turn+=1
        if turn==5 and not verify:return {'done':True,'result':'模型宣称发送成功'}
        draft=next((s['social']['draft_id'] for s in steps if s.get('social',{}).get('draft_id')),'')
        return [
            {'social':{'kind':'draft','platform':'bilibili','mention':False}},
            {'action':{'kind':'tap','x':650,'y':650}},
            {'action':{'kind':'text','text':'讲得很清楚。'}},
            {'social':{'kind':'publish','platform':'bilibili','draft_id':draft,'x':650,'y':1150}},
            {'social':{'kind':'verify','platform':'bilibili','draft_id':draft}},
            {'done':True,'result':'评论已在列表中出现'},
        ][turn-1]
    tasks.gateway.request=gateway;tasks.decide=decide
    try:
        task=tasks.submit('default','0'*32,'在当前视频评论')
        await tasks.jobs[task['id']]
        result=tasks.get('default',task['id'])
        assert result['state']==('completed' if rendered else 'unknown'),result['result']
        assert tasks.social.list('default')[0]['state']==('verified' if rendered else 'unknown')
        assert any('自动在真实评论列表' in s.get('reason','') for s in result['steps'])==rendered
        assert [a['kind'] for a in actions]==['tap','text','tap']
        assert sum(a.get('y')==1150 for a in actions)==1
    finally:await tasks.close();await manager.close()


@pytest.mark.asyncio
async def test_device_decision_disables_deepseek_reasoning_and_does_not_echo_simulated_steps(tmp_path,monkeypatch):
    import httpx,json
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from app.providers import ProviderConfig
    from test_android import png
    from unittest.mock import AsyncMock
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    pid=manager.providers.save(ProviderConfig(type='deepseek',base_url='https://model.test/v1',vision=True))
    bad='{"action":{"kind":"key","key":"delete"}}\n<system>Step 26 completed</system>\n{"action":{"kind":"key","key":"back"}}'
    replies=iter([bad,'{"action":{"kind":"text","text":"插画"}}']);bodies=[]
    async def request(client,method,url,**kwargs):
        bodies.append(kwargs['json'])
        return httpx.Response(200,json={'choices':[{'message':{'content':next(replies)},'finish_reason':'stop'}]},request=httpx.Request(method,url))
    monkeypatch.setattr(httpx.AsyncClient,'request',request)
    try:
        cfg=AndroidConfig(enabled=True,provider_id=pid,model='deepseek-flash');tasks.save_config('default',cfg);tasks.run=AsyncMock()
        task=tasks.submit('default','0'*32,'按兴趣搜索视频');await tasks.jobs[task['id']]
        tree='<node class="android.widget.EditText" text="推荐词" hint="推荐词"/>'
        result=await tasks.decide('default',cfg,task['goal'],{'image':png(),'hierarchy':tree},[],task['id'])
        assert result['action']['text']=='插画'
        assert all(b['thinking']=={'type':'disabled'} for b in bodies)
        user_content=bodies[0]['messages'][1]['content'][0]['text']
        assert 'text=""' in json.loads(user_content)['untrusted_ui_tree']
        assert 'Step 26' not in str(bodies[1]['messages'])
        assert len(tasks.diagnostics('default',task['id']))==2
    finally:await tasks.close();await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('label,operation',[('@提及用户候选：主人','mention'),('发布','publish')])
async def test_plain_social_tap_is_repaired_into_dedicated_operation_before_execution(tmp_path,monkeypatch,label,operation):
    import app.android as module
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from test_android import png
    from unittest.mock import AsyncMock
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(enabled=True,model='vision');tasks.save_config('default',cfg);tasks.run=AsyncMock()
    replies=iter(['{"action":{"kind":"tap","x":40,"y":50}}','{"social":{"kind":"'+operation+'","platform":"bilibili","draft_id":"'+('a'*32)+'","x":40,"y":50}}'])
    async def generate(*args,**kwargs):return {'message':{'content':next(replies)}}
    monkeypatch.setattr(module,'generate',generate)
    try:
        task=tasks.submit('default','0'*32,'继续当前操作');await tasks.jobs[task['id']]
        tree='<node package="tv.danmaku.bili" content-desc="'+label+'" bounds="[0,0][100,100]"/>'
        result=await tasks.decide('default',cfg,task['goal'],{'image':png(),'hierarchy':tree},[],task['id'])
        assert result['social']['kind']==operation
        assert ('social mention' if operation=='mention' else '"publish"') in tasks.diagnostics('default',task['id'])[0]['error']
        assert not tasks.get('default',task['id'])['steps']
    finally:await tasks.close();await manager.close()


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
    with pytest.raises(ValueError):journal.reserve('bot-b','account-a','bilibili','video-1','hello',False,cfg)
    assert journal.reserve('bot-b','account-b','bilibili','video-1','hello',False,cfg)
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
        if path.endswith('/cleanup'):return {'home':True,'background_cleared':True}
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

@pytest.mark.parametrize('blue',[True,False])
def test_mention_needs_blue_token_in_editor_not_plain_text(blue):
    import base64,io
    from PIL import Image,ImageDraw
    from app.android_companion import blue_mention_editor
    im=Image.new('RGB',(120,60),'white');draw=ImageDraw.Draw(im)
    draw.rectangle((10,15,50,30),fill=(40,160,240) if blue else (40,40,40))
    out=io.BytesIO();im.save(out,format='PNG')
    obs={'image':base64.b64encode(out.getvalue()).decode(),'hierarchy':'<hierarchy><node class="android.widget.EditText" text="@主人 " bounds="[0,0][120,60]"/></hierarchy>'}
    assert blue_mention_editor(obs,'主人') is blue

@pytest.mark.asyncio
async def test_interest_selection_accepts_single_observed_video_and_user_interest(tmp_path):
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from unittest.mock import AsyncMock
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(enabled=True,model='vision',companion={'character_interest_mode':'custom','character_interests':'喜欢数码','platforms':{'bilibili':{'comments':True}}})
    tasks.save_config('default',cfg);tasks.run=AsyncMock()
    try:
        task=tasks.submit('default','0'*32,'按喜好挑选感兴趣的视频');await tasks.jobs[task['id']]
        op={'kind':'select','platform':'bilibili','interest_basis':'喜欢数码','selection_reason':'当前视频介绍设备'}
        result=await tasks.social_step('default',tasks.get('default',task['id']),cfg,op,{'hierarchy':video_page()},'/device','lease')
        assert result['selection']['interest_basis']=='喜欢数码'
        op['interest_basis']='虚构的喜好'
        with pytest.raises(ValueError,match='兴趣依据'):await tasks.social_step('default',tasks.get('default',task['id']),cfg,op,{'hierarchy':video_page()},'/device','lease')
    finally:await tasks.close();await manager.close()

@pytest.mark.parametrize('placeholder',['不发没关系，请继续友善哦~','轻轻敲醒沉睡的心灵，让我看看你的点评'])
def test_bilibili_rotating_placeholder_is_not_entered_comment(placeholder):
    from app.android_companion import public_editor,keeps_page_context
    tree=f'<hierarchy><node package="tv.danmaku.bili" text="热门评论"/><node package="tv.danmaku.bili" class="android.widget.EditText" resource-id="tv.danmaku.bili:id/edit" text="{placeholder}" bounds="[0,0][600,100]"/></hierarchy>'
    assert not public_editor(tree)
    assert keeps_page_context(tree,{'kind':'tap','x':30,'y':50})


def test_unsent_draft_does_not_consume_publication_cooldown(tmp_path):
    cfg=CompanionConfig(platforms={'bilibili':{'comments':True,'cooldown_minutes':30,'daily_limit':1}})
    journal=SocialJournal(tmp_path/'social.sqlite3')
    try:
        first=journal.reserve('bot','account','bilibili','first','hello',False,cfg)
        second=journal.reserve('bot','account','bilibili','second','hello',False,cfg)
        journal.finish(second,'unknown','attempted')
        with pytest.raises(ValueError):journal.reserve('bot','account','bilibili','third','hello',False,cfg)
    finally:journal.close()


def test_comment_availability_explains_cooldown_and_expiry(tmp_path):
    cfg=CompanionConfig(platforms={'bilibili':{'comments':True,'cooldown_minutes':30,'daily_limit':2}})
    journal=SocialJournal(tmp_path/'social.sqlite3')
    try:
        token=journal.reserve('bot','account','bilibili','first','hello',False,cfg)
        created=journal.get('bot',token)['created']
        assert journal.availability('bot','account','bilibili',cfg,created+10)['allowed']
        journal.finish(token,'unknown','attempted')
        blocked=journal.availability('bot','account','bilibili',cfg,created+10)
        assert not blocked['allowed'] and blocked['retry_after_seconds']==1791
        assert journal.availability('bot','account','bilibili',cfg,created+1800)['allowed']
        assert journal.availability('bot','another-account','bilibili',cfg,created+10)['allowed']
    finally:journal.close()


@pytest.mark.asyncio
async def test_first_platform_account_binding_preserves_history_and_cooldown(tmp_path):
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(companion={'platforms':{'bilibili':{'comments':True,'cooldown_minutes':30}}})
    tasks.save_config('default',cfg)
    legacy=manager.get('default').store.load().account_id
    try:
        ident=tasks.social.reserve('default',legacy,'bilibili','ui:first','hello',False,cfg.companion,anchors=['视频','作者'],aliases=['bilibili:BV1234567890'])
        tasks.social.finish(ident,'verified','observed')
        cfg.companion.platforms['bilibili'].posting_account_id='platform-uid'
        tasks.save_config('default',cfg)
        assert tasks.social.get('default',ident)['account_id']=='platform-uid'
        assert tasks.social.seen('platform-uid','bilibili','bilibili:BV1234567890')
        assert not tasks.social.availability('default','platform-uid','bilibili',cfg.companion)['allowed']
        with pytest.raises(ValueError,match='不重复评论'):
            tasks.social.reserve('another-bot','platform-uid','bilibili','bilibili:BV1234567890','different',False,cfg.companion)
        # Changing an explicit account means switching accounts, not merging them.
        cfg.companion.platforms['bilibili'].posting_account_id='other-uid'
        tasks.save_config('default',cfg)
        assert not tasks.social.seen('other-uid','bilibili','bilibili:BV1234567890')
        assert tasks.social.get('default',ident)['account_id']=='platform-uid'
    finally:await tasks.close();await manager.close()


@pytest.mark.asyncio
async def test_cooldown_is_checked_before_generating_a_public_draft(tmp_path):
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from unittest.mock import AsyncMock
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(enabled=True,model='vision',companion={'platforms':{'bilibili':{'comments':True,'cooldown_minutes':30}}})
    tasks.save_config('default',cfg);tasks.run=AsyncMock();tasks.public_draft=AsyncMock()
    try:
        task=tasks.submit('default','0'*32,'看视频并评论');await tasks.jobs[task['id']]
        ident=tasks.social.reserve('default',manager.get('default').store.load().account_id,'bilibili','previous','hello',False,cfg.companion)
        tasks.social.finish(ident,'verified','observed')
        result=await tasks.social_step('default',tasks.get('default',task['id']),cfg,{'kind':'draft','platform':'bilibili'}, {'hierarchy':video_page()},'/device','lease')
        assert result['unavailable'] and result['retry_after_seconds']>0
        tasks.public_draft.assert_not_awaited()
        assert len(tasks.social.list('default'))==1
    finally:await tasks.close();await manager.close()


def test_bilibili_main_identity_ignores_ad_titles():
    from app.android_companion import page_context
    tree='<hierarchy><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/author_name" text="作者"/><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/title" text="主视频"/><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/views" text="1万"/><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/title" text="广告标题"/></hierarchy>'
    assert page_context(tree,'bilibili')['anchors']==['主视频','作者']


def test_compose_editor_preserves_comment_context_and_blocks_plain_candidate_tap():
    from app.android_companion import comment_surface,public_editor
    tree='<hierarchy><node package="tv.danmaku.bili" class="android.widget.EditText" resource-id="tv.danmaku.bili:id/edit" focused="true" text="@IMHAYSTACK"/></hierarchy>'
    assert comment_surface(tree) and public_editor(tree)

@pytest.mark.asyncio
async def test_published_mention_in_accessibility_description_is_verified(tmp_path):
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from app.android_companion import page_context
    from unittest.mock import AsyncMock
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(enabled=True,model='vision',companion={'platforms':{'bilibili':{'comments':True,'mentions':True,'owner_id':'123','owner_name':'主人','cooldown_minutes':0}}})
    tasks.save_config('default',cfg);tasks.run=AsyncMock()
    try:
        task=tasks.submit('default','0'*32,'评论验收');await tasks.jobs[task['id']]
        ctx=page_context(video_page(),'bilibili')
        ident=tasks.social.reserve('default',manager.get('default').store.load().account_id,'bilibili',ctx['content_id'],'讲得清楚。',True,cfg.companion,anchors=ctx['anchors'])
        tasks.social.finish(ident,'unknown','attempted once')
        obs={'content_context':ctx,'hierarchy':'<hierarchy><node package="tv.danmaku.bili" content-desc="@主人 讲得清楚。"/><node package="tv.danmaku.bili" class="android.widget.EditText" resource-id="tv.danmaku.bili:id/edit" text="不发没关系，请继续友善哦~"/></hierarchy>'}
        result=await tasks.social_step('default',task,cfg,{'kind':'verify','platform':'bilibili','draft_id':ident},obs,'/device','lease')
        assert result['state']=='verified'
    finally:await tasks.close();await manager.close()


def test_bilibili_intro_bv_identity_and_conflicting_ids():
    from app.android_companion import page_context,same_content
    def page(bv,title='视频标题'):
        return video_page(title).replace('</hierarchy>','<node package="tv.danmaku.bili" text="简介"/><node package="tv.danmaku.bili" text="'+bv+'"/></hierarchy>')
    first=page_context(page('BV1xx411c7mD'),'bilibili')
    assert first['content_id']=='bilibili:BV1xx411c7mD'
    assert same_content(first,page('BV1xx411c7mD','修改后的标题'))
    assert not same_content(first,page('BV1yy411c7mD'))
    assert page_context(video_page().replace('</hierarchy>','<node text="用户评论里提到BV1xx411c7mD"/></hierarchy>'),'bilibili')['content_id'].startswith('ui:v1:')


def test_bv_dedup_across_bots_and_changed_title(tmp_path):
    cfg=CompanionConfig(platforms={'bilibili':{'comments':True,'cooldown_minutes':0}})
    journal=SocialJournal(tmp_path/'bv.sqlite3')
    try:
        ident=journal.reserve('one','account','bilibili','bilibili:BV1xx411c7mD','评论',False,cfg,anchors=['原标题','作者'])
        journal.finish(ident,'unknown','结果未知')
        with pytest.raises(ValueError):journal.reserve('two','account','bilibili','bilibili:BV1xx411c7mD','评论',False,cfg,anchors=['新标题','作者'])
        assert journal.reserve('two','another-account','bilibili','bilibili:BV1xx411c7mD','评论',False,cfg)
    finally:journal.close()

@pytest.mark.asyncio
async def test_buffer_wait_observes_recovery_without_model_calls(tmp_path,monkeypatch):
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from unittest.mock import AsyncMock
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(enabled=True,model='vision');tasks.save_config('default',cfg);tasks.run=AsyncMock()
    task=tasks.submit('default','0'*32,'看视频');await tasks.jobs[task['id']];tasks.update(task['id'],state='running')
    buffered={'hierarchy':video_page().replace('</hierarchy>','<node text="正在缓冲"/></hierarchy>')}
    recovered={'hierarchy':video_page()};tasks.gateway.request=AsyncMock(return_value=recovered);tasks.decide=AsyncMock()
    monkeypatch.setattr('app.android.asyncio.sleep',AsyncMock())
    progress={}
    try:
        assert await tasks.wait_for_video('default',task['id'],cfg,buffered,'/device','lease',progress)==recovered
        assert progress['buffering']['recovered']
        tasks.decide.assert_not_called()
        tasks.gateway.request.assert_awaited_once()
    finally:await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_buffer_timeout_uses_configured_elapsed_time(tmp_path,monkeypatch):
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from unittest.mock import AsyncMock
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(enabled=True,model='vision',companion={'buffering_wait_seconds':30})
    tasks.save_config('default',cfg);tasks.run=AsyncMock()
    task=tasks.submit('default','0'*32,'看视频');await tasks.jobs[task['id']];tasks.update(task['id'],state='running')
    obs={'hierarchy':video_page().replace('</hierarchy>','<node text="缓冲中"/></hierarchy>')}
    clock=[0.0];waits=[]
    async def sleep(seconds):waits.append(seconds);clock[0]+=seconds
    monkeypatch.setattr('app.android.time.monotonic',lambda:clock[0])
    monkeypatch.setattr('app.android.asyncio.sleep',sleep)
    tasks.gateway.request=AsyncMock(return_value=obs);progress={}
    try:
        await tasks.wait_for_video('default',task['id'],cfg,obs,'/device','lease',progress)
        assert sum(waits)==30 and len(waits)==6
        assert progress['buffering']['timed_out']
        await tasks.wait_for_video('default',task['id'],cfg,obs,'/device','lease',progress)
        assert len(waits)==6
    finally:await tasks.close();await manager.close()


def test_real_bilibili_expanded_intro_reads_official_bv_not_body_references():
    from pathlib import Path
    from app.android_companion import page_context
    tree=(Path(__file__).parent/'fixtures'/'bilibili-expanded-intro.xml').read_text()
    context=page_context(tree,'bilibili')
    assert context['content_id']=='bilibili:BV1U7nQ65EnK'
    assert context['identity_source']=='platform_id'
    assert context['anchors'][1]=='FC投资人S'
    # The description may mention other videos; only the official leading ID counts.
    extra=tree.replace('BV1U7nQ65EnK','BV1U7nQ65EnK &#10;参考视频 BV1xx411c7mD')
    assert page_context(extra,'bilibili')['content_id']==context['content_id']
    assert 'bilibili:BV1xx411c7mD' not in page_context(extra,'bilibili')['identity_aliases']


def test_real_inline_bv_without_resource_ids_and_selected_video_transition():
    from pathlib import Path
    from app.android_companion import page_context,bind_page_context,same_content
    tree=(Path(__file__).parent/'fixtures'/'bilibili-inline-bv.xml').read_text()
    current=page_context(tree,'bilibili')
    assert current['content_id']=='bilibili:BV1btH36uEru'
    title='为什么你的DeepSeek，和别人不一样？【实测揭秘】'
    selected=page_context(video_page(title,'三颗门牙X'),'bilibili')
    merged=bind_page_context({'hierarchy':tree},selected)
    assert merged['content_id']==current['content_id']
    assert merged['anchors']==[title,'三颗门牙X']
    assert same_content(selected,tree,merged)
    assert bind_page_context({'hierarchy':tree},page_context(video_page('别的视频','作者乙'),'bilibili'))['anchors']==[title]
    conflicting={**merged,'content_id':'bilibili:BV1xx411c7mD'}
    assert not same_content(conflicting,tree,merged)
    # Neither a comment mentioning BV nor another app's identical text is metadata.
    assert page_context(tree.replace('playCount66.2万','用户评论66.2万'),'bilibili') is None
    assert page_context(tree.replace('tv.danmaku.bili','com.coolapk.market'),'bilibili') is None

@pytest.mark.asyncio
async def test_typing_at_triggers_candidates_only_for_authorized_unsent_mention(tmp_path):
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from app.android_companion import page_context
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(model='vision',companion={'platforms':{'bilibili':{'comments':True,'mentions':True,'owner_id':'123','owner_name':'主人','cooldown_minutes':0}}})
    tasks.save_config('default',cfg);context=page_context(video_page(),'bilibili')
    ident=tasks.social.reserve('default',manager.get('default').store.load().account_id,'bilibili',context['content_id'],'这处演示有意思。',True,cfg.companion,anchors=context['anchors'])
    task={'steps':[{'social':{'draft_id':ident}}]}
    tree='<hierarchy><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/edit" class="android.widget.EditText" focused="true" text=""/></hierarchy>'
    obs={'hierarchy':tree,'content_context':context}
    try:
        tasks.guard_public_action('default',task,obs,{'kind':'text','text':'@'})
        for text in ['@主人','@123','这处演示有意思。','@@']:
            with pytest.raises(ValueError):tasks.guard_public_action('default',task,obs,{'kind':'text','text':text})
        with pytest.raises(ValueError):tasks.guard_public_action('default',{'steps':[]},obs,{'kind':'text','text':'@'})
        with pytest.raises(ValueError):tasks.guard_public_action('default',task,{**obs,'content_context':page_context(video_page('另一个视频'),'bilibili')},{'kind':'text','text':'@'})
        with pytest.raises(ValueError):tasks.guard_public_action('default',task,{**obs,'hierarchy':tree.replace('text=""','text="@"')},{'kind':'text','text':'@'})
        tasks.social.finish(ident,'mention_selected','测试候选已核对')
        with pytest.raises(ValueError):tasks.guard_public_action('default',task,obs,{'kind':'text','text':'@'})
        tasks.guard_public_action('default',task,obs,{'kind':'text','text':'这处演示有意思。'})
    finally:await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_inline_at_query_can_select_candidate_but_still_requires_blue_token(tmp_path,monkeypatch):
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from app.android_companion import page_context
    from unittest.mock import AsyncMock
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(model='vision',companion={'platforms':{'bilibili':{'comments':True,'mentions':True,'owner_id':'123','owner_name':'主人','cooldown_minutes':0}}})
    tasks.save_config('default',cfg);context=page_context(video_page(),'bilibili')
    ident=tasks.social.reserve('default',manager.get('default').store.load().account_id,'bilibili',context['content_id'],'这处演示有意思。',True,cfg.companion,anchors=context['anchors'])
    task={'steps':[{'social':{'draft_id':ident}}]}
    query='<hierarchy><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/edit" class="android.widget.EditText" focused="true" text="@123"/><node package="tv.danmaku.bili" text="主人" bounds="[10,100][200,150]"/></hierarchy>'
    obs={'hierarchy':query,'content_context':context}
    tasks.gateway.request=AsyncMock(side_effect=[{'ok':True},obs,{'ok':True},obs])
    blue=[False]
    monkeypatch.setattr('app.android.blue_mention_editor',lambda *args:blue[0])
    operation={'kind':'mention','platform':'bilibili','draft_id':ident,'x':80,'y':125}
    try:
        with pytest.raises(ValueError,match='蓝色'):await tasks.social_step('default',task,cfg,operation,obs,'/device','lease')
        assert tasks.social.get('default',ident)['state']=='draft'
        blue[0]=True
        result=await tasks.social_step('default',task,cfg,operation,obs,'/device','lease')
        assert result['state']=='mention_selected'
        assert all(call.args[1].endswith(('/action','/observe')) for call in tasks.gateway.request.call_args_list)
    finally:await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_real_hint_text_allows_at_but_entered_text_does_not(tmp_path):
    from pathlib import Path
    from app.android import AndroidTasks,AndroidConfig
    from app.android_companion import page_context,empty_editor,ui_nodes
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(model='vision',companion={'platforms':{'bilibili':{'comments':True,'mentions':True,'owner_id':'123','owner_name':'主人','cooldown_minutes':0}}})
    tasks.save_config('default',cfg);context=page_context(video_page(),'bilibili')
    ident=tasks.social.reserve('default',manager.get('default').store.load().account_id,'bilibili',context['content_id'],'这处演示有意思。',True,cfg.companion,anchors=context['anchors'])
    task={'steps':[{'social':{'draft_id':ident}}]}
    tree=(Path(__file__).parent/'fixtures'/'bilibili-empty-comment-hint.xml').read_text()
    try:
        tasks.guard_public_action('default',task,{'hierarchy':tree,'content_context':context},{'kind':'text','text':'@'})
        entered=tree.replace('text="与其赞同别人的话语，不如自己畅所欲言。"','text="已有正文"')
        with pytest.raises(ValueError):tasks.guard_public_action('default',task,{'hierarchy':entered,'content_context':context},{'kind':'text','text':'@'})
        assert not empty_editor({'class':'android.widget.EditText','text':'已有正文','hint':'提示文字'})
    finally:await tasks.close();await manager.close()


def test_search_results_mentioning_replies_are_not_comment_composer():
    from app.android_companion import public_editor
    tree='<hierarchy><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/search_src_text" class="android.widget.EditText" focused="true" content-desc="搜索查询" text="deepseek harness"/><node package="tv.danmaku.bili" text="私信我，系统自动回复领取方式"/></hierarchy>'
    assert not public_editor(tree)
