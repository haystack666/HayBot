import asyncio
import base64
import io
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from app.main import create_app
from app.android import AndroidTasks, AndroidConfig


def png():
    b = io.BytesIO(); Image.new('RGB', (720, 1280), 'white').save(b, format='PNG')
    return base64.b64encode(b.getvalue()).decode()


def test_android_routes_require_auth_and_keep_bot_scopes(tmp_path, monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-password-long-enough')
    monkeypatch.delenv('ANDROID_RUNTIME_URL', raising=False); monkeypatch.delenv('ANDROID_RUNTIME_TOKEN', raising=False)
    with TestClient(create_app(tmp_path)) as c:
        assert c.get('/api/bots/default/android').status_code == 401
        c.post('/api/login', json={'password': 'test-password-long-enough'})
        assert c.get('/api/bots/default/android').status_code == 200
        assert c.get('/api/bots/missing/android').status_code == 404
        assert c.get('/api/bots/default/android').json()['configured'] is False
        assert c.post('/api/bots/default/android/devices', json={'name': 'test'}).status_code == 503
        result = c.put('/api/bots/default/android/config', json={'model': 'test', 'max_steps': 0})
        assert result.status_code == 422
        assert c.post('/api/bots/default/android/tasks', json={'goal': 'open browser'}).status_code == 409


def test_rename_device_validates_and_uses_authenticated_bot_scope(tmp_path, monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-password-long-enough')
    app = create_app(tmp_path)
    device_id = 'a' * 32
    url = '/api/bots/default/android/devices/' + device_id
    with TestClient(app) as c:
        gateway = AsyncMock(return_value={'id': device_id, 'name': '诗语的手机'})
        app.state.android.gateway.request = gateway
        assert c.patch(url, json={'name': 'new'}).status_code == 401
        c.post('/api/login', json={'password': 'test-password-long-enough'})
        for name in ('', '  ', 'x' * 61, 'bad\nname', 'bad\x00name'):
            assert c.patch(url, json={'name': name}).status_code == 422
        assert c.patch(url, json={'name': 'new', 'state': 'running'}).status_code == 422
        assert c.patch('/api/bots/missing/android/devices/' + device_id, json={'name': 'new'}).status_code == 404
        assert c.patch('/api/bots/default/android/devices/invalid', json={'name': 'new'}).status_code == 404
        gateway.assert_not_awaited()
        app.state.android.set_login('default', device_id, True)
        result = c.patch(url, json={'name': '  诗语的手机  '})
        assert result.status_code == 200 and result.json()['owner_login'] is True
        gateway.assert_awaited_once_with('PATCH', '/bots/default/devices/' + device_id, {'name': '诗语的手机'})


@pytest.mark.asyncio
async def test_task_uses_independent_model_verifies_completion_and_releases_lease(tmp_path):
    from app.registry import BotManager
    manager = BotManager(tmp_path)
    tasks = AndroidTasks(manager, tmp_path)
    tasks.save_config('default', AndroidConfig(model='vision-test', enabled=True))
    calls = []
    async def gateway(method, path, body=None, **kw):
        calls.append((method, path, body))
        if path.endswith('/claim'): return {'lease': 'lease-one'}
        if path.endswith('/cleanup'):return {'home':True,'background_cleared':True}
        if path.endswith('/observe'): return {'image': png(), 'hierarchy': '<node text="Settings"/>'}
        return {'ok': True}
    tasks.gateway.request = gateway
    choices = iter([{'action': {'kind': 'key', 'key': 'home'}, 'reason': 'Go home'}, {'done': True, 'result': 'Home screen visible'}])
    tasks.decide = AsyncMock(side_effect=lambda *a: next(choices))
    task = tasks.submit('default', '0' * 32, 'Go home')
    await tasks.jobs[task['id']]
    final = tasks.get('default', task['id'])
    assert final['state'] == 'completed'
    assert len(final['steps']) == 2
    assert sum(path.endswith('/observe') for _, path, _ in calls) == 2
    assert any(path.endswith('/release') for _, path, _ in calls)
    with pytest.raises(ValueError): tasks.get('other', task['id'])
    await tasks.close(); await manager.close()


@pytest.mark.asyncio
async def test_cancellation_during_model_wait_prevents_action(tmp_path):
    from app.registry import BotManager
    manager = BotManager(tmp_path); tasks = AndroidTasks(manager, tmp_path)
    tasks.save_config('default', AndroidConfig(model='vision', enabled=True))
    calls=[]; entered=asyncio.Event()
    async def gateway(method,path,body=None,**kw):
        calls.append(path)
        if path.endswith('/claim'):return {'lease':'lease'}
        if path.endswith('/cleanup'):return {'home':True,'background_cleared':True}
        if path.endswith('/observe'):return {'image':png(),'hierarchy':''}
        return {'ok':True}
    async def decide(*args):
        entered.set(); await asyncio.sleep(30)
        return {'action': {'kind':'key','key':'home'}}
    tasks.gateway.request=gateway; tasks.decide=decide
    job=tasks.submit('default','0'*32,'test'); await entered.wait()
    await tasks.cancel('default',job['id'])
    assert not any(p.endswith('/action') for p in calls)
    assert tasks.get('default',job['id'])['state']=='cancelled'
    await tasks.close(); await manager.close()

@pytest.mark.asyncio
async def test_gateway_preserves_destroy_confirmation_query(monkeypatch):
    import httpx
    from app.android import Gateway
    seen=[]
    real=httpx.AsyncClient
    async def handle(request):
        seen.append(str(request.url));return httpx.Response(200,json={'ok':True})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs: real(transport=httpx.MockTransport(handle),**kwargs))
    gateway=Gateway();gateway.url='http://runtime.test';gateway.token='x'*40;gateway.configured=True
    await gateway.request('DELETE','/bots/a/devices/device?destroy_data=true&confirm=device')
    assert 'destroy_data=true' in seen[0] and 'confirm=device' in seen[0]

@pytest.mark.asyncio
async def test_archive_cancels_model_task_and_revokes_before_closing_bot(tmp_path):
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path);manager.android_service=tasks
    tasks.save_config('default',AndroidConfig(model='vision',enabled=True))
    entered=asyncio.Event();calls=[]
    async def gateway(method,path,body=None,**kw):
        calls.append((path,body))
        if path.endswith('/claim'):return {'lease':body['lease']}
        if path.endswith('/cleanup'):return {'home':True,'background_cleared':True}
        if path.endswith('/observe'):return {'image':png(),'hierarchy':''}
        return {'ok':True}
    async def decide(*args):entered.set();await asyncio.sleep(30)
    tasks.gateway.request=gateway;tasks.decide=decide
    task=tasks.submit('default','0'*32,'test');await entered.wait()
    await manager.archive('default')
    claimed=next(body['lease'] for path,body in calls if path.endswith('/claim'))
    assert claimed!=task['id']
    assert any(path.endswith('/revoke') and body['lease']==claimed for path,body in calls)
    assert tasks.get('default',task['id'])['state']=='cancelled'
    assert not any(path.endswith('/action') for path,_ in calls)
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_manual_takeover_resolves_revocation_uncertainty(tmp_path):
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    tasks.save_config('default',AndroidConfig(enabled=True,model='vision'))
    tasks.gateway.request=AsyncMock(side_effect=ValueError('offline'))
    task=tasks.submit('default','0'*32,'test')
    await tasks.cancel('default',task['id'])
    assert tasks.get('default',task['id'])['state']=='unknown'
    tasks.acknowledge_takeover('default')
    assert tasks.get('default',task['id'])['state']=='cancelled'
    assert await tasks.cancel_bot('default') is True
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_cancel_before_worker_starts_does_not_claim_phone(tmp_path):
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    tasks.save_config('default',AndroidConfig(enabled=True,model='vision'))
    calls=[]
    async def gateway(method,path,body=None,**kwargs):
        calls.append(path)
        await asyncio.sleep(0)
        if path.endswith('/claim'):return {'lease':body['lease']}
        return {'ok':True}
    tasks.gateway.request=gateway
    task=tasks.submit('default','0'*32,'test')
    await tasks.cancel('default',task['id'])
    assert not any(path.endswith('/claim') for path in calls)
    assert tasks.get('default',task['id'])['state']=='cancelled'
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_invalid_model_decision_retries_before_action_and_keeps_diagnostics(tmp_path,monkeypatch):
    import app.android as module
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    runtime=manager.get('default');cfg=tasks.config('default')
    cfg.enabled=True;cfg.model='vision';tasks.save_config('default',cfg)
    responses=iter(['', '{"action":{"kind":"key","key":"home"}}'])
    async def generate(*args,**kwargs):return {'message':{'content':next(responses)},'eval_count':2}
    monkeypatch.setattr(module,'generate',generate)
    job=tasks.submit('default','0'*32,'test');tasks.jobs[job['id']].cancel();await asyncio.gather(tasks.jobs[job['id']],return_exceptions=True)
    tasks.update(job['id'],state='running')
    result=await tasks.decide('default',cfg,'test',{'image':png(),'hierarchy':''},[],job['id'])
    assert result['action']['key']=='home'
    attempts=tasks.diagnostics('default',job['id'])
    assert len(attempts)==2 and attempts[0]['error'] and attempts[1]['content'].startswith('{')
    assert runtime.store.stats()['output_tokens']==4
    assert 'image' not in attempts[0] and 'api_key' not in attempts[0]
    await tasks.close();await manager.close()

@pytest.mark.asyncio
async def test_duplicate_y_repair_uses_canonical_points_without_replaying_bad_assistant(tmp_path,monkeypatch):
    import app.android as module
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=tasks.config('default');cfg.enabled=True;cfg.model='vision';tasks.save_config('default',cfg)
    bad='{"action":{"kind":"swipe","x":360,"y":10,"x2":360,"y":700,"duration_ms":500}}'
    responses=iter([bad,'{"action":{"kind":"swipe","start":[360,10],"end":[360,700],"duration_ms":500}}'])
    messages=[]
    async def generate(*args,**kwargs):
        import copy
        messages.append(copy.deepcopy(args[3]))
        return {'message':{'content':next(responses)},'eval_count':3}
    monkeypatch.setattr(module,'generate',generate)
    job=tasks.submit('default','0'*32,'test');tasks.jobs[job['id']].cancel();await asyncio.gather(tasks.jobs[job['id']],return_exceptions=True);tasks.update(job['id'],state='running')
    result=await tasks.decide('default',cfg,'test',{'image':png(),'hierarchy':'<node package="com.android.launcher3" text="首页"/>'},[],job['id'])
    assert result['action']['y']==10 and result['action']['y2']==700
    assert not any(m.get('role')=='assistant' and m.get('content')==bad for m in messages[1])
    assert 'start' in messages[1][-1]['content'] and 'end' in messages[1][-1]['content']
    assert len(tasks.diagnostics('default',job['id']))==2
    await tasks.close();await manager.close()


@pytest.mark.asyncio
async def test_missing_selection_is_repaired_before_draft_side_effect(tmp_path,monkeypatch):
    import app.android as module
    from app.registry import BotManager
    from test_android_companion import video_page
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(enabled=True,model='vision',companion={'character_interests':'喜欢插画'})
    tasks.save_config('default',cfg);tasks.run=AsyncMock()
    replies=iter(['{"social":{"kind":"draft","platform":"bilibili"}}','{"social":{"kind":"select","platform":"bilibili","interest_basis":"兴趣1","selection_reason":"视频演示插画"}}'])
    async def generate(*args,**kwargs):return {'message':{'content':next(replies)}}
    monkeypatch.setattr(module,'generate',generate)
    try:
        task=tasks.submit('default','0'*32,'按自己兴趣看视频');await tasks.jobs[task['id']]
        decision=await tasks.decide('default',cfg,task['goal'],{'image':png(),'hierarchy':video_page()},[],task['id'])
        assert decision['social']['kind']=='select'
        assert '选择理由' in tasks.diagnostics('default',task['id'])[0]['error']
        assert tasks.social.list('default')==[]
    finally:await tasks.close();await manager.close()


@pytest.mark.asyncio
async def test_unknown_publication_outside_app_repairs_cleanup_into_return_for_verification(tmp_path,monkeypatch):
    import app.android as module
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(enabled=True,model='vision',companion={'platforms':{'bilibili':{'comments':True}}})
    tasks.save_config('default',cfg);tasks.run=AsyncMock()
    replies=iter(['{"action":{"kind":"swipe","start":[360,640],"end":[360,120]}}','{"action":{"kind":"launch","app":"bilibili"}}'])
    async def generate(*args,**kwargs):return {'message':{'content':next(replies)}}
    monkeypatch.setattr(module,'generate',generate)
    try:
        task=tasks.submit('default','0'*32,'继续任务');await tasks.jobs[task['id']]
        ident=tasks.social.reserve('default','account','bilibili','BV-test','已有正文',False,cfg.companion)
        tasks.social.finish(ident,'unknown','已经尝试发送')
        tasks.update(task['id'],step={'social':{'draft_id':ident}})
        steps=tasks.get('default',task['id'])['steps']
        result=await tasks.decide('default',cfg,task['goal'],{'image':png(),'hierarchy':'<node package="com.android.launcher3" content-desc="主屏幕"/>'},steps,task['id'])
        assert result['action']=={'kind':'launch','app':'bilibili'}
        assert 'unknown' in tasks.diagnostics('default',task['id'])[0]['error']
        assert tasks.social.get('default',ident)['state']=='unknown'
    finally:await tasks.close();await manager.close()


@pytest.mark.asyncio
async def test_settled_video_allows_continued_viewing_without_a_fixed_wait_quota(tmp_path,monkeypatch):
    import app.android as module
    from app.registry import BotManager
    from app.android_companion import page_context
    from test_android_companion import video_page
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(enabled=True,model='vision');tasks.save_config('default',cfg);tasks.run=AsyncMock()
    replies=iter(['{"action":{"kind":"wait","duration_ms":2000}}'])
    async def generate(*args,**kwargs):return {'message':{'content':next(replies)}}
    monkeypatch.setattr(module,'generate',generate)
    try:
        task=tasks.submit('default','0'*32,'看当前视频');await tasks.jobs[task['id']]
        tree=video_page();obs={'image':png(),'hierarchy':tree,'content_context':page_context(tree,'bilibili')}
        result=await tasks.decide('default',cfg,task['goal'],obs,[{'kind':'wait'}]*3,task['id'])
        assert result['action']['kind']=='wait'
        assert len(tasks.diagnostics('default',task['id']))==1
    finally:await tasks.close();await manager.close()


@pytest.mark.asyncio
async def test_repeated_action_is_reconsidered_before_a_phone_side_effect(tmp_path,monkeypatch):
    import app.android as module
    import json
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(enabled=True,model='vision',adaptive_budget=False)
    tasks.save_config('default',cfg);tasks.run=AsyncMock()
    action={'kind':'tap','x':360,'y':200};seen=[]
    replies=iter([json.dumps({'action':action}),'{"done":true,"result":"已完成观看"}'])
    async def generate(*args,**kwargs):
        seen.append(json.loads(args[3][1]['content']))
        return {'message':{'content':next(replies)}}
    monkeypatch.setattr(module,'generate',generate)
    try:
        task=tasks.submit('default','0'*32,'看两三分钟视频');await tasks.jobs[task['id']]
        tasks.update(task['id'],progress={'execution_seconds':190})
        result=await tasks.decide('default',cfg,task['goal'],{'image':png(),'hierarchy':'<node text="视频"/>','repeated_actions':[action]},[],task['id'])
        assert result['done']
        assert seen[0]['execution_status']['execution_seconds']==190
        assert seen[0]['repeated_actions_on_current_page']==[action]
        assert '同一界面反复执行' in tasks.diagnostics('default',task['id'])[0]['error']
    finally:await tasks.close();await manager.close()


@pytest.mark.asyncio
async def test_transient_empty_hierarchy_repairs_blind_tap_into_reobserve(tmp_path,monkeypatch):
    import app.android as module
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(enabled=True,model='vision',adaptive_budget=False)
    tasks.save_config('default',cfg);tasks.run=AsyncMock()
    replies=iter(['{"action":{"kind":"tap","x":150,"y":466}}','{"action":{"kind":"wait","duration_ms":1000}}'])
    async def generate(*args,**kwargs):return {'message':{'content':next(replies)}}
    monkeypatch.setattr(module,'generate',generate)
    try:
        task=tasks.submit('default','0'*32,'查看页面');await tasks.jobs[task['id']]
        result=await tasks.decide('default',cfg,task['goal'],{'image':png(),'hierarchy':'<hierarchy/>'},[],task['id'])
        assert result['action']=={'kind':'wait','duration_ms':1000}
        assert '无法核对界面结构' in tasks.diagnostics('default',task['id'])[0]['error']
    finally:await tasks.close();await manager.close()


@pytest.mark.asyncio
async def test_requested_browsing_time_repairs_extra_viewing_into_completion(tmp_path,monkeypatch):
    import app.android as module
    import json
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(enabled=True,model='vision',adaptive_budget=False)
    tasks.save_config('default',cfg);tasks.run=AsyncMock();seen=[]
    replies=iter(['{"reason":"继续观看视频细节","action":{"kind":"wait","duration_ms":2000}}','{"done":true,"result":"本轮观看已结束"}'])
    async def generate(*args,**kwargs):
        seen.append(json.loads(args[3][1]['content']))
        return {'message':{'content':next(replies)}}
    monkeypatch.setattr(module,'generate',generate)
    try:
        task=tasks.submit('default','0'*32,'逛两三分钟');await tasks.jobs[task['id']]
        tasks.update(task['id'],progress={'execution_seconds':185})
        result=await tasks.decide('default',cfg,task['goal'],{'image':png(),'hierarchy':'<node text="视频"/>'},[],task['id'])
        assert result['done']
        assert seen[0]['execution_status']['remaining_seconds']==0
        assert seen[0]['execution_status']['requested_browsing_time']['max_seconds']==180
        assert '浏览时长已到' in tasks.diagnostics('default',task['id'])[0]['error']
    finally:await tasks.close();await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('phase',['owner-candidate','wrong-candidate','publish','wrong-body','unknown'])
async def test_grounded_social_taps_use_checked_operations_only(tmp_path,monkeypatch,phase):
    import app.android as module
    import json
    from app.registry import BotManager
    from app.android_companion import page_context
    from test_android_companion import video_page
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(enabled=True,model='vision',adaptive_budget=False,companion={'platforms':{'bilibili':{'comments':True,'mentions':True,'owner_id':'owner','owner_name':'owner'}}})
    tasks.save_config('default',cfg);tasks.run=AsyncMock()
    try:
        task=tasks.submit('default','0'*32,'评论并@主人');await tasks.jobs[task['id']]
        context=page_context(video_page(),'bilibili')
        ident=tasks.social.reserve('default',manager.get('default').store.load().account_id,'bilibili',context['content_id'],'独立正文',True,cfg.companion,anchors=context['anchors'])
        tasks.update(task['id'],step={'social':{'draft_id':ident}})
        if phase in ('publish','wrong-body'):tasks.social.finish(ident,'mention_selected','blue token confirmed')
        if phase=='unknown':tasks.social.finish(ident,'unknown','already attempted')
        candidate='other' if phase=='wrong-candidate' else 'owner'
        target=f'@提及用户候选：{candidate}'
        body='@owner'
        if phase in ('publish','wrong-body'):
            target='发布';body='@owner 独立正文' if phase=='publish' else '@owner 其他正文'
        tree=f'<hierarchy><node package="tv.danmaku.bili" content-desc="{target}" bounds="[20,200][180,300]"/><node package="tv.danmaku.bili" class="android.widget.EditText" resource-id="tv.danmaku.bili:id/edit" text="{body}" bounds="[0,400][600,600]"/></hierarchy>'
        tap={'action':{'kind':'tap','x':50,'y':250}}
        task=tasks.get('default',task['id']);obs={'image':png(),'hierarchy':tree,'content_context':context}
        result=tasks.canonical_social_decision('default',task,cfg,obs,tap)
        if phase in ('owner-candidate','publish'):
            assert result['social']['kind']==('mention' if phase=='owner-candidate' else 'publish')
            assert result['social']['draft_id']==ident
            async def generate(*args,**kwargs):return {'message':{'content':json.dumps(tap)}}
            monkeypatch.setattr(module,'generate',generate)
            decision=await tasks.decide('default',cfg,task['goal'],obs,task['steps'],task['id'])
            assert decision['social']==result['social']
            # Conversion itself never clicks or marks the publication sent.
            assert tasks.social.get('default',ident)['state']==('draft' if phase=='owner-candidate' else 'mention_selected')
        else:assert result==tap
    finally:await tasks.close();await manager.close()


@pytest.mark.asyncio
async def test_video_evidence_retains_plan_browsing_memory_and_current_content(tmp_path,monkeypatch):
    import app.android as module
    import json
    from app.registry import BotManager
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(enabled=True,model='vision');tasks.save_config('default',cfg);tasks.run=AsyncMock()
    seen=[]
    async def generate(*args,**kwargs):
        seen.append(json.loads(args[3][1]['content']))
        return {'message':{'content':'{"done":true,"result":"已观看片段"}'}}
    monkeypatch.setattr(module,'generate',generate)
    try:
        task=tasks.submit('default','0'*32,'观看视频');await tasks.jobs[task['id']]
        tasks.update(task['id'],progress={'plan':{'milestones':['浏览','总结']},'browsing_history':[{'anchors':['视频','作者'],'visible_seconds':80}]})
        observation={'image':png(),'hierarchy':'<node text="当前页面"/>','content_context':{'content_id':'current'},'video':{'frames':[{'image':png(),'at':1,'hierarchy':'<node text="视频一帧"/>'}],'observed_seconds':15}}
        await tasks.decide('default',cfg,task['goal'],observation,[],task['id'])
        assert seen[0]['task_progress']['browsing_history'][0]['visible_seconds']==80
        assert seen[0]['current_public_content']['content_id']=='current'
        assert seen[0]['video_evidence']['observed_seconds']==15
    finally:await tasks.close();await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('phase',['missing-context','needs-selection','ready-to-draft'])
async def test_current_interaction_readiness_is_in_the_observation_message(tmp_path,monkeypatch,phase):
    import app.android as module
    import json
    from app.registry import BotManager
    from app.android_companion import page_context
    from test_android_companion import video_page
    manager=BotManager(tmp_path);tasks=AndroidTasks(manager,tmp_path)
    cfg=AndroidConfig(enabled=True,model='vision',adaptive_budget=False);tasks.save_config('default',cfg);tasks.run=AsyncMock()
    seen=[]
    async def generate(*args,**kwargs):
        seen.append(json.loads(args[3][1]['content']))
        return {'message':{'content':'{"action":{"kind":"key","key":"back"}}'}}
    monkeypatch.setattr(module,'generate',generate)
    try:
        task=tasks.submit('default','0'*32,'看你喜欢的视频，分享给我');await tasks.jobs[task['id']]
        context=page_context(video_page(),'bilibili')
        if phase=='ready-to-draft':tasks.update(task['id'],progress={'selection':context})
        obs={'image':png(),'hierarchy':video_page()}
        if phase!='missing-context':obs['content_context']=context
        await tasks.decide('default',cfg,task['goal'],obs,[],task['id'])
        readiness=seen[0]['interaction_readiness']
        if phase=='missing-context':assert '先按back' in readiness
        elif phase=='needs-selection':assert 'select' in readiness['required_decision']
        else:assert readiness['draft_decision']['social']=={'kind':'draft','platform':'bilibili','mention':True}
    finally:await tasks.close();await manager.close()
