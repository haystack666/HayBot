import pytest
from app.android_progress import TaskBudget, collect_links,estimate_plan

@pytest.mark.parametrize('goal,expected',[
    ('去B站逛两三分钟',{'min_seconds':120,'max_seconds':180}),
    ('看视频2-3分钟',{'min_seconds':120,'max_seconds':180}),
    ('浏览十分钟',{'min_seconds':600,'max_seconds':600}),
    ('看二十五分钟',{'min_seconds':1500,'max_seconds':1500}),
    ('看1小时',{'min_seconds':3600,'max_seconds':3600}),
    ('去B站自己逛一逛',None),
    ('不限制时长，看看视频',None),
    ('搜索“三分钟做蛋糕”的视频',None),
])
def test_only_explicit_browsing_duration_provides_a_time_range(goal,expected):
    from app.android_progress import requested_browsing_time
    assert requested_browsing_time(goal)==expected

def test_link_collection_rejects_invented_browser_plan_and_actions():
    from app.android_progress import browser_detour
    goal='打开酷安，浏览几条内容，整理分享链接发给主人'
    assert browser_detour(goal,{'plan':{'milestones':['复制链接并在 Chrome 地址栏读取核对']}})
    assert browser_detour(goal,{'action':{'kind':'launch','app':'chrome'}})
    assert browser_detour(goal,{'action':{'kind':'open','url':'https://coolapk.com/feed/123'}})
    assert browser_detour(goal,{'reason':'点地址栏粘贴链接','action':{'kind':'tap','x':20,'y':30}})
    assert not browser_detour(goal,{'action':{'kind':'launch','app':'coolapk'}})
    assert not browser_detour('用Chrome打开这个链接',{'action':{'kind':'launch','app':'chrome'}})

def test_complex_collection_gets_more_budget_than_returning_home():
    assert estimate_plan('打开酷安浏览几条内容，获取整理分享链接发给主人')['estimated_steps']>estimate_plan('返回桌面')['estimated_steps']
    assert '收集' not in ' '.join(estimate_plan('浏览视频，不用发链接')['milestones'])

def test_adaptive_budget_uses_plan_and_pauses_instead_of_destroying_progress():
    short=TaskBudget({'estimated_steps':5,'estimated_minutes':2},adaptive=True,max_steps=60,timeout_minutes=20,now=0)
    long=TaskBudget({'estimated_steps':200,'estimated_minutes':40},adaptive=True,max_steps=60,timeout_minutes=20,now=0)
    assert long.steps>short.steps and long.seconds>short.seconds
    assert short.boundary(short.steps,0)
    assert short.boundary(0,short.seconds)
    manual=TaskBudget({},adaptive=False,max_steps=600,timeout_minutes=90,now=0)
    assert manual.steps==600 and manual.seconds==5400

def test_only_observed_public_links_are_collected_and_deduplicated():
    tree='<hierarchy><node text="分享 https://www.coolapk.com/feed/74618723?share=1"/><node text="https://www.coolapk.com/feed/74618723"/><node text="https://example.com/login?token=secret"/></hierarchy>'
    progress=collect_links({},tree,1)
    assert [x['url'] for x in progress['links']]==['https://www.coolapk.com/feed/74618723']
    assert collect_links(progress,tree,2)['links']==progress['links']
    assert collect_links({},'<node text="https://[bad"/>',1).get('links',[])==[]


def test_browsing_history_survives_switches_without_counting_pause_as_watching():
    from app.android_progress import record_browsing
    progress={};first={'content_id':'first','anchors':['视频一','作者一']};second={'content_id':'second','anchors':['视频二','作者二']}
    record_browsing(progress,first,0);record_browsing(progress,first,12)
    record_browsing(progress,None,14);record_browsing(progress,second,20)
    record_browsing(progress,first,30);record_browsing(progress,first,40)
    progress['browsing_active']=None
    record_browsing(progress,first,1000)
    saved=progress['browsing_history'][0]
    assert saved['visible_seconds']==22 and saved['visits']==3 and saved['observations']==5
    assert progress['browsing_history'][1]['visible_seconds']==0


def test_browsing_identity_upgrades_when_official_bv_becomes_visible():
    from app.android_progress import record_browsing
    progress={};first={'content_id':'ui:first','anchors':['视频','作者'],'identity_source':'title_author_fallback'}
    official={**first,'content_id':'bilibili:BV1234567890','identity_source':'platform_id','identity_aliases':['ui:first','bilibili:BV1234567890']}
    record_browsing(progress,first,0);record_browsing(progress,official,10);record_browsing(progress,first,20)
    record=progress['browsing_history'][0]
    assert record['content_id']=='bilibili:BV1234567890'
    assert record['visits']==1 and record['visible_seconds']==20
    assert set(record['identity_aliases'])=={'ui:first','bilibili:BV1234567890'}

@pytest.mark.asyncio
async def test_manual_stage_limit_pauses_and_resume_preserves_completed_steps(tmp_path):
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from unittest.mock import AsyncMock
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    tasks.save_config('default',AndroidConfig(enabled=True,model='vision',adaptive_budget=False,max_steps=1))
    actions=[];claims=[]
    async def gateway(method,path,body=None,**kwargs):
        if path.endswith('/claim'):
            if body['lease'] in claims:raise ValueError('old lease revoked')
            claims.append(body['lease']);return {'lease':body['lease']}
        if path.endswith('/cleanup'):return {'home':True,'background_cleared':True}
        if path.endswith('/observe'):return {'hierarchy':'<node text="https://www.coolapk.com/feed/12345"/>'}
        if path.endswith('/action'):actions.append(body)
        return {'ok':True}
    tasks.gateway.request=gateway;tasks.decide=AsyncMock(return_value={'action':{'kind':'wait','duration_ms':100}})
    try:
        task=tasks.submit('default','0'*32,'收集链接');await tasks.jobs[task['id']]
        saved=tasks.get('default',task['id'])
        assert saved['state']=='paused' and len(saved['steps'])==1
        assert saved['progress']['links'][0]['url'].endswith('/12345')
        tasks.decide=AsyncMock(return_value={'done':True,'result':'已有链接，完成整理'})
        resumed=tasks.resume('default',task['id']);await tasks.jobs[task['id']]
        final=tasks.get('default',task['id'])
        assert final['state']=='completed' and len(actions)==1
        assert len(claims)==2 and claims[0]!=claims[1]
        assert final['steps'][0]==saved['steps'][0] and final['progress']['links']==saved['progress']['links']
        with pytest.raises(ValueError):tasks.resume('other',task['id'])
    finally:await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_dynamic_player_clock_is_not_progress_for_automatic_extension(tmp_path,monkeypatch):
    import asyncio
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from unittest.mock import AsyncMock
    from app.android_progress import TaskBudget
    def small_budget(*args,**kwargs):
        budget=TaskBudget(*args,**kwargs);budget.steps=2;return budget
    monkeypatch.setattr('app.android.TaskBudget',small_budget)
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path);tasks.save_config('default',AndroidConfig(enabled=True,model='vision'))
    frames=0
    async def gateway(method,path,body=None,**kwargs):
        nonlocal frames
        if path.endswith('/claim'):return {'lease':'lease'}
        if path.endswith('/cleanup'):return {'home':True,'background_cleared':True}
        if path.endswith('/observe'):
            frames+=1;return {'hierarchy':f'<node text="00:{frames:02}"/>'}
        return {'ok':True}
    tasks.gateway.request=gateway;tasks.decide=AsyncMock(return_value={'action':{'kind':'wait','duration_ms':100}})
    try:
        task=tasks.submit('default','0'*32,'观察视频');await asyncio.wait_for(tasks.jobs[task['id']],2.5)
        assert tasks.get('default',task['id'])['state']=='paused'
        assert tasks.decide.await_count==2
    finally:await tasks.close();await manager.close()


@pytest.mark.asyncio
async def test_network_waits_use_stage_budget_instead_of_repeated_tap_limit(tmp_path):
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from unittest.mock import AsyncMock
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    tasks.save_config('default',AndroidConfig(enabled=True,model='vision',adaptive_budget=False,max_steps=4))
    actions=[]
    async def gateway(method,path,body=None,**kwargs):
        if path.endswith('/claim'):return {'lease':'lease'}
        if path.endswith('/observe'):return {'hierarchy':'<node text="正在加载数据…"/>'}
        if path.endswith('/action'):actions.append(body)
        return {'ok':True}
    tasks.gateway.request=gateway;tasks.decide=AsyncMock(return_value={'action':{'kind':'wait','duration_ms':100}})
    try:
        task=tasks.submit('default','0'*32,'等待搜索结果');await tasks.jobs[task['id']]
        result=tasks.get('default',task['id'])
        assert result['state']=='paused' and '预算已到' in result['result']
        assert len(actions)==4
    finally:await tasks.close();await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('changing',[True,False],ids=['image-article-scrolls','stuck-image'])
async def test_image_only_scrolling_uses_visible_progress_when_tree_stays_the_same(tmp_path,changing):
    import io,base64
    from PIL import Image
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from unittest.mock import AsyncMock
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    tasks.save_config('default',AndroidConfig(enabled=True,model='vision',adaptive_budget=False,max_steps=4))
    actions=[];frame=0
    async def gateway(method,path,body=None,**kwargs):
        nonlocal frame
        if path.endswith('/claim'):return {'lease':'lease'}
        if path.endswith('/observe'):
            frame+=1;image=Image.new('RGB',(720,1280),(frame*20 if changing else 20,0,0));out=io.BytesIO();image.save(out,format='PNG')
            return {'hierarchy':'<node text="图片专栏" scrollable="true"/>','image':base64.b64encode(out.getvalue()).decode()}
        if path.endswith('/action'):actions.append(body)
        return {'ok':True}
    tasks.gateway.request=gateway;tasks.decide=AsyncMock(return_value={'action':{'kind':'swipe','x':360,'y':900,'x2':360,'y2':400}})
    try:
        task=tasks.submit('default','0'*32,'浏览图片');await tasks.jobs[task['id']]
        result=tasks.get('default',task['id'])
        assert result['state']=='paused'
        assert len(actions)==(4 if changing else 2)
    finally:await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_copy_link_is_read_and_saved_before_next_decision(tmp_path):
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from unittest.mock import AsyncMock
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    tasks.save_config('default',AndroidConfig(enabled=True,model='vision',adaptive_budget=False,max_steps=1))
    calls=[]
    async def gateway(method,path,body=None,**kwargs):
        calls.append(path)
        if path.endswith('/claim'):return {'lease':'lease'}
        if path.endswith('/cleanup'):return {'home':True,'background_cleared':True}
        if path.endswith('/observe'):return {'hierarchy':'<hierarchy><node text="复制链接" bounds="[0,0][100,100]"/></hierarchy>'}
        if path.endswith('/clipboard'):return {'links':['https://www.coolapk.com/feed/74612141']}
        return {'ok':True}
    tasks.gateway.request=gateway;tasks.decide=AsyncMock(return_value={'action':{'kind':'tap','x':50,'y':50}})
    try:
        task=tasks.submit('default','0'*32,'收集酷安分享链接');await tasks.jobs[task['id']]
        result=tasks.get('default',task['id'])
        link=result['progress']['links'][0]
        assert link['url']=='https://www.coolapk.com/feed/74612141' and link['source']=='copied_share_link' and link['step']==1
        assert '复制链接' in link['observed_text']
        assert any(p.endswith('/clipboard') for p in calls)
    finally:await tasks.close();await manager.close()


@pytest.mark.asyncio
async def test_navigation_cannot_restore_old_video_from_selection_history(tmp_path):
    from app.android import AndroidTasks,AndroidConfig
    from app.registry import BotManager
    from unittest.mock import AsyncMock
    from test_android_companion import video_page
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    tasks.save_config('default',AndroidConfig(enabled=True,model='vision',adaptive_budget=False,max_steps=3,companion={'platforms':{'bilibili':{'comments':True}}}))
    unsupported='<hierarchy><node package="tv.danmaku.bili" text="简介"/><node package="tv.danmaku.bili" text="评论"/><node package="tv.danmaku.bili" text="纪录片新页面"/></hierarchy>'
    observed=iter([video_page(),video_page(),unsupported]);seen=[]
    async def gateway(method,path,body=None,**kwargs):
        if path.endswith('/claim'):return {'lease':'lease'}
        if path.endswith('/observe'):return {'hierarchy':next(observed)}
        if path.endswith('/cleanup'):return {'home':True,'background_cleared':True}
        return {'ok':True}
    async def decide(bot_id,cfg,goal,obs,steps,task_id):
        seen.append(obs.get('content_context'))
        if len(seen)==1:return {'social':{'kind':'select','platform':'bilibili','interest_basis':'本次探索','selection_reason':'当前真实视频'}}
        if len(seen)==2:return {'action':{'kind':'tap','x':100,'y':100}}
        return {'done':True,'result':'停止当前探索'}
    tasks.gateway.request=gateway;tasks.decide=decide
    try:
        task=tasks.submit('default','0'*32,'浏览视频');await tasks.jobs[task['id']]
        final=tasks.get('default',task['id'])
        assert seen[0] and seen[1] and seen[2] is None
        assert final['progress']['selection']['anchors']==['视频标题','作者甲']
        assert final['progress']['content_context'] is None
    finally:await tasks.close();await manager.close()
