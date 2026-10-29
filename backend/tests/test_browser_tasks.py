import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import create_app
from app.browser_tasks import BrowsingConfig, ViewingConfig, BrowseDecision, parse_object, unsupported_interactions
from app.browser_qq import BrowserQQ


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', 'douyin-test-password-long')
    monkeypatch.setenv('BROWSER_RUNTIME_URL', 'http://127.0.0.1:17322')
    monkeypatch.setenv('BROWSER_RUNTIME_TOKEN', 'test-token-' * 5)
    with TestClient(create_app(tmp_path)) as c:
        c.post('/api/login', json={'password': 'douyin-test-password-long'})
        yield c


def test_config_scoped_strict_and_explicit_interest_migration(client):
    app = client.app
    android = app.state.android.config('default')
    android.companion.character_interests = '猫咪，手工积木'
    android.companion.owner_interests = '科技资讯'
    app.state.android.save_config('default', android)
    cfg = client.get('/api/bots/default/browser/douyin/config').json()
    assert cfg['config']['character_interests'] == '猫咪，手工积木'
    assert not cfg['config']['enabled'] and not cfg['qq_account_bound']
    config = {**cfg['config'], 'enabled': True, 'qq_enabled': True, 'qq_owner_id': 'owner123'}
    assert client.put('/api/bots/default/browser/douyin/config', json=config).status_code == 200
    assert client.get('/api/bots/default/browser/douyin/config').json()['qq_account_bound']
    other = client.post('/api/bots', json={'name': 'other'}).json()['id']
    assert not client.get(f'/api/bots/{other}/browser/douyin/config').json()['config']['enabled']
    assert client.put('/api/bots/default/browser/douyin/config', json={**config, 'max_steps': 5000}).status_code == 422
    assert client.get('/api/bots/missing/browser/douyin/tasks').status_code == 404
    assert client.post('/api/bots/default/browser/douyin/tasks', json={'goal': ' '}).status_code == 422


def test_legacy_dm_polling_config_migrates_to_task_mode(tmp_path,monkeypatch):
    import sqlite3
    monkeypatch.setenv('ADMIN_PASSWORD','douyin-test-password-long')
    monkeypatch.setenv('BROWSER_RUNTIME_URL','http://127.0.0.1:17322')
    monkeypatch.setenv('BROWSER_RUNTIME_TOKEN','test-token-'*5)
    value=BrowsingConfig().model_dump();interactions=value['interactions']
    interactions.pop('dm_monitor_mode');interactions['messages_enabled']=True;interactions['dm_check_interval_seconds']=5
    db=sqlite3.connect(tmp_path/'browser_tasks.sqlite3')
    db.execute('CREATE TABLE browser_config(bot_id TEXT PRIMARY KEY,account_id TEXT NOT NULL,config TEXT NOT NULL)')
    db.execute('INSERT INTO browser_config VALUES (?,?,?)',('default','legacy-account',json.dumps(value,ensure_ascii=False)))
    db.commit();db.close()
    with TestClient(create_app(tmp_path)) as legacy:
        legacy.post('/api/login',json={'password':'douyin-test-password-long'})
        saved=legacy.get('/api/bots/default/browser/douyin/config').json()['config']['interactions']
        assert saved['messages_enabled'] is True and saved['dm_monitor_mode']=='task'
        assert 'dm_check_interval_seconds' not in saved
        raw=json.loads(legacy.app.state.browser_tasks.db.execute('SELECT config FROM browser_config WHERE bot_id=?',('default',)).fetchone()[0])
        assert raw['interactions']['dm_monitor_mode']=='task' and 'dm_check_interval_seconds' not in raw['interactions']


def test_always_dm_monitor_uses_existing_browser_and_stops_when_mode_changes(client,monkeypatch):
    tasks=client.app.state.browser_tasks;calls=[];started=asyncio.Event();release=asyncio.Event()
    async def gateway(method,path,body=None):
        calls.append((method,path,body))
        if method=='GET':return {'state':'ready','generation':7,'automation':False,'owner_login':False,'controller':None}
        if path.endswith('/douyin/begin'):return {'token':body['runId']}
        if path.endswith('/douyin/end'):return {'stopped':True}
        assert path.endswith('/douyin/act') and body['op']=='account'
        return {'generation':8,'account':{'id':'self-sec','verified':True}}
    async def dm_run(task,cfg,token,**kwargs):
        assert task['id']=='dm-always:default' and kwargs['standalone'] is True and kwargs['valid']()
        started.set();await release.wait()
    monkeypatch.setattr(tasks.browser.gateway,'request',gateway)
    monkeypatch.setattr(tasks.dm,'run',dm_run)
    async def scenario():
        cfg=tasks.config('default');cfg.interactions.messages_enabled=True;cfg.interactions.dm_monitor_mode='always';tasks.save_config('default',cfg)
        await asyncio.wait_for(started.wait(),1)
        assert tasks.dm_status('default')['state']=='monitoring'
        assert any(path.endswith('/douyin/begin') for _,path,_ in calls)
        assert not any(path.endswith('/start') for _,path,_ in calls)
        cfg.interactions.dm_monitor_mode='task';tasks.save_config('default',cfg)
        for _ in range(20):
            if not tasks.dm_jobs.get('default'):break
            await asyncio.sleep(.01)
        assert tasks.dm_status('default')['state']=='task_only'
        assert any(path.endswith('/douyin/end') for _,path,_ in calls)
    client.portal.call(scenario)


def test_viewing_settings_persist_per_bot_and_validate_relationships(client):
    endpoint='/api/bots/default/browser/douyin/config'
    old=client.get(endpoint).json()['config']
    assert old['viewing']==ViewingConfig().model_dump()
    custom={'preview_enabled':True,'preview_after_minutes':2,'max_video_minutes':45,'segment_seconds':8,'skip_seconds':90}
    assert client.put(endpoint,json={**old,'viewing':custom}).status_code==200
    assert client.get(endpoint).json()['config']['viewing']==custom
    other=client.post('/api/bots',json={'name':'separate viewing'}).json()['id']
    assert client.get(f'/api/bots/{other}/browser/douyin/config').json()['config']['viewing']==ViewingConfig().model_dump()
    for invalid in ({'segment_seconds':0},{'skip_seconds':-1},{'max_video_minutes':121},{'preview_after_minutes':46},{'segment_seconds':True},{'skip_seconds':'60'}):
        assert client.put(endpoint,json={**old,'viewing':{**custom,**invalid}}).status_code==422
    assert client.put(endpoint,json={**old,'viewing':{**custom,'preview_enabled':False,'max_video_minutes':1}}).status_code==200


def test_legacy_config_without_viewing_gets_defaults(client):
    tasks=client.app.state.browser_tasks
    async def legacy():
        config=BrowsingConfig(character_interests='保留我的兴趣').model_dump()
        del config['viewing']
        with tasks.db:
            tasks.db.execute('INSERT OR REPLACE INTO browser_config VALUES (?,?,?)',('default','legacy',json.dumps(config)))
    client.portal.call(legacy)
    saved=client.get('/api/bots/default/browser/douyin/config').json()['config']
    assert saved['character_interests']=='保留我的兴趣' and saved['viewing']==ViewingConfig().model_dump()


def test_verify_endpoint_uses_original_grant_without_writes_and_releases_on_failure(client,monkeypatch):
    from app.douyin_interactions import InteractionConfig
    tasks=client.app.state.browser_tasks
    grant=tasks.interactions.reserve({'id':'old-task','bot_id':'default'},BrowseDecision(op='like',id='123456789',reason='喜欢'),
        {'account':{'id':'self-account','verified':True},'current':{'id':'123456789'},'watched':True},InteractionConfig(likes_enabled=True))
    tasks.interactions.settle(grant['operation_id'],{'status':'unknown'})
    calls=[];bad=False;blocked=False
    async def gateway(method,path,body=None):
        calls.append((method,path,body))
        if method=='GET':return {'state':'owner_control' if blocked else 'ready','generation':3}
        if path.endswith('/begin'):return {'token':body['runId']}
        if path.endswith('/end'):return {'stopped':True}
        if body['op']=='account':return {'generation':4,'account':{'id':'wrong' if bad else 'self-account'}}
        assert body['op']=='reconcile'
        return {'interaction':{**grant,'op':'like','reconciled':True,'status':'confirmed','liked':True,'evidence':'fresh_video_detail'}}
    monkeypatch.setattr(tasks.browser.gateway,'request',gateway)
    endpoint=f'/api/bots/default/browser/douyin/operations/{grant["operation_id"]}/verify'
    blocked=True
    assert client.post(endpoint,json={}).status_code==409 and not tasks.reconciling
    blocked=False;bad=True
    assert client.post(endpoint,json={}).status_code==409 and not tasks.reconciling
    assert calls[-1][1].endswith('/end')
    bad=False
    assert client.post(endpoint,json={}).json()['status']=='confirmed'
    assert not tasks.reconciling
    assert all(body.get('op') not in ('like','comment','share') for _,_,body in calls if body)
    assert client.post(endpoint,json={}).status_code==409


def test_reconciled_results_overlay_original_task_evidence_without_rewriting_history(client):
    import time
    from app.douyin_interactions import InteractionConfig
    tasks=client.app.state.browser_tasks
    async def verify():
        tasks.save_config('default',BrowsingConfig(enabled=True))
        task=tasks.submit('default','查看',deferred=True)
        grant=tasks.interactions.reserve(task,BrowseDecision(op='like',id='123456789',reason='喜欢'),
            {'account':{'id':'self-account','verified':True},'current':{'id':'123456789'},'watched':True},InteractionConfig(likes_enabled=True))
        tasks.interactions.settle(grant['operation_id'],{'status':'unknown'})
        tasks.update(task['id'],state='blocked',steps=[{'op':'like','at':time.time(),'current':{'id':'123456789'},'interaction':{'status':'unknown'}}])
        tasks.interactions.reconcile('default',grant['operation_id'],{**grant,'op':'like','reconciled':True,'status':'confirmed','liked':True,'evidence':'fresh_video_detail'})
        step=tasks.get('default',task['id'])['steps'][0]
        assert step['interaction']['status']=='confirmed' and step['original_interaction']['status']=='unknown'
        original=json.loads(tasks.db.execute('SELECT steps FROM browser_tasks WHERE id=?',(task['id'],)).fetchone()[0])
        assert original[0]['interaction']['status']=='unknown'
    client.portal.call(verify)


def test_strict_decisions_and_share_intention():
    for raw in ('{"op":"next","op":"finish","reason":"x"}', '{"op":"next","reason":"x"} {"op":"finish"}', 'xx {"op":"next","reason":"x"}'):
        with pytest.raises(ValueError):
            parse_object(raw)
    with pytest.raises(ValueError):
        BrowseDecision.model_validate({'op': 'comment', 'reason': '发布'})
    assert unsupported_interactions('看你喜欢的抖音，记得分享给我')
    assert unsupported_interactions('看看猫猫，@我')
    assert not unsupported_interactions('看看猫猫，把链接发我')
    assert not unsupported_interactions('看看猫猫，不要点赞，不要评论')
    assert parse_object('```\n{"op":"next","reason":"继续"}\n```')['op'] == 'next'
    for seconds in (True, 10.5, '15', None):
        with pytest.raises(ValueError):
            BrowseDecision.model_validate({'op': 'watch', 'reason': '看', 'seconds': seconds})
    assert BrowseDecision.model_validate({'op':'watch','reason':'跳看','start_at':0}).start_at == 0
    for position in (True,-1,7200,'120'):
        with pytest.raises(ValueError):
            BrowseDecision.model_validate({'op':'watch','reason':'跳看','start_at':position})
    with pytest.raises(ValueError):
        BrowseDecision.model_validate({'op':'next','reason':'继续','start_at':15})


class Host:
    def __init__(self, *, captcha=False, takeover=False):
        self.calls, self.token, self.watches = [], None, 0
        self.captcha, self.takeover = captcha, takeover
    async def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path.endswith('/start'):
            return {'state': 'ready'}
        if path.endswith('/douyin/begin'):
            self.token = body['runId']
            return {'token': self.token, 'viewing': body.get('viewing')}
        if path.endswith('/douyin/end'):
            self.token = None
            return {'stopped': True}
        if path.endswith('/douyin/act'):
            assert body['token'] == self.token
            value = {'generation': 1, 'url': 'https://www.douyin.com/video/1234567890123456789', 'blocked': 'captcha' if self.captcha else '',
                'items': [{'id': '1234567890123456789', 'title': '猫咪玩积木'}], 'body': '猫咪玩积木',
                'current': {'id': '1234567890123456789', 'title': '猫咪玩积木', 'url': 'https://www.douyin.com/video/1234567890123456789'}}
            if body['op'] == 'watch':
                self.watches += 1
                value.update(watch={'advancedSeconds': 0 if self.watches == 1 else 12, 'requestedSeconds': body['seconds'], 'samples': [], 'audioAvailable': False}, images=['fixture-frame'])
            return value
        return {'state': 'owner_control' if self.takeover else 'ready', 'generation': 1, 'automation': bool(self.token)}


def setup(c, monkeypatch, decisions, **host_options):
    tasks = c.app.state.browser_tasks
    c.portal.call(tasks.save_config, 'default', BrowsingConfig(enabled=True, qq_enabled=True, qq_owner_id='owner123', character_interests='猫咪积木', owner_interests='科技资讯'))
    host, contexts = Host(**host_options), []
    monkeypatch.setattr(tasks.browser.gateway, 'request', host.request)
    async def model(runtime, messages, tokens=1600):
        contexts.append(messages)
        return json.dumps(next(decisions), ensure_ascii=False)
    monkeypatch.setattr(tasks, 'model', model)
    return tasks, host, contexts


def run_task(c, tasks, goal):
    async def run():
        task = tasks.submit('default', goal, deferred=True)
        await tasks.run('default', task['id'])
        return tasks.get('default', task['id'])
    return c.portal.call(run)


def test_autonomous_loop_interest_scope_buffering_and_visual_evidence(client, monkeypatch):
    decisions = iter([{'op': 'home', 'reason': '先看看推荐'}, {'op': 'search', 'query': '猫咪积木', 'reason': '按我填写的兴趣找'},
        {'op': 'open', 'id': '1234567890123456789', 'reason': '想看看猫咪怎么玩'}, {'op': 'watch', 'seconds': 15, 'reason': '观察实际内容'},
        {'op': 'next', 'reason': '继续探索推荐'}, {'op': 'watch', 'seconds': 15, 'reason': '再看一会'},
        {'op': 'finish', 'reason': '本轮浏览满足目标', 'note': '猫咪碰倒积木那段挺有意思，我又往下逛了一会。'}])
    tasks, host, contexts = setup(client, monkeypatch, decisions)
    task = run_task(client, tasks, '去抖音看你自己喜欢的内容')
    assert task['state'] == 'completed', task
    assert host.watches == 3  # First failed playback is waited out before model can skip.
    assert len(task['steps']) == 7
    prompts = [json.loads(msg[1]['content']) for msg in contexts]
    assert all(p['interest_scope'] == 'character' and not p['owner_interests'] for p in prompts)
    assert any(msg[1].get('images') == ['fixture-frame'] for msg in contexts)
    assert host.token is None
    assert 'fixture-frame' not in json.dumps(task)


def test_verification_on_last_step_is_blocked_not_step_limit_pause(client,monkeypatch):
    decisions=iter([{'op':'home','reason':'浏览'}]*5)
    tasks,host,_=setup(client,monkeypatch,decisions)
    cfg=tasks.config('default');cfg.max_steps=5
    client.portal.call(tasks.save_config,'default',cfg)
    original=host.request;count=0
    async def gateway(method,path,body=None):
        nonlocal count
        result=await original(method,path,body)
        if path.endswith('/act') and body['op']=='home':
            count+=1
            if count==5:result['blocked']='account_verification'
        return result
    monkeypatch.setattr(tasks.browser.gateway,'request',gateway)
    result=run_task(client,tasks,'去抖音看看')
    assert result['state']=='blocked' and '短信本人验证' in result['result']
    assert len(result['steps'])==5


def test_captcha_blocks_without_retry_and_takeover_discards_model_action(client, monkeypatch):
    tasks, host, _ = setup(client, monkeypatch, iter([{'op': 'home', 'reason': '打开抖音'}]), captcha=True)
    task = run_task(client, tasks, '刷抖音')
    assert task['state'] == 'blocked' and '验证' in task['result']
    assert len([c for c in host.calls if c[1].endswith('/act')]) == 1
    tasks, host, _ = setup(client, monkeypatch, iter([{'op': 'home', 'reason': '打开抖音'}]), takeover=True)
    task = run_task(client, tasks, '刷抖音')
    assert task['state'] == 'blocked' and '接管' in task['result']
    assert not any(c[1].endswith('/act') for c in host.calls)


def test_no_false_completion_when_mention_is_unimplemented(client, monkeypatch):
    decisions = iter([{'op': 'home', 'reason': '打开抖音'}, {'op': 'watch', 'reason': '看内容', 'seconds': 15},
        {'op': 'finish', 'reason': '看好了', 'note': '已经@主人了'}])
    tasks, host, _ = setup(client, monkeypatch, decisions)
    task = run_task(client, tasks, '看你喜欢的抖音，记得分享给我')
    assert task['state'] == 'blocked'
    assert '未执行' in task['result'] and '已经@' not in task['result']
    assert not any(c[2] and c[2].get('op') in ('comment', 'share', 'mention') for c in host.calls)


def test_owner_only_both_transports_and_account_binding(client, monkeypatch):
    tasks, _, _ = setup(client, monkeypatch, iter([]))
    runtime = client.portal.call(client.app.state.manager.get, 'default')
    qq = runtime.bot.browser
    assert client.portal.call(qq.allowed, runtime.bot, 'owner123', False)
    assert not client.portal.call(qq.allowed, runtime.bot, 'owner123', True)
    assert not client.portal.call(qq.allowed, runtime.bot, 'someone', False)
    assert qq.command('/抖音 看看猫咪')['request'] == 'start'
    assert qq.command('/抖音进度')['request'] == 'status'
    assert qq.command('/停止抖音')['request'] == 'stop'
    config = client.portal.call(runtime.store.load)
    config.qq.app_id = '987654321'
    client.portal.call(runtime.store.save, config)
    assert not client.portal.call(qq.allowed, runtime.bot, 'owner123', False)


@pytest.mark.parametrize('transport', ['qq_official', 'napcat'])
def test_qq_send_requires_receipt_and_rechecks_guard(client, monkeypatch, transport):
    runtime = client.portal.call(client.app.state.manager.get, 'default')
    bot, qq = runtime.bot, runtime.bot.browser
    cfg = client.portal.call(bot.store.load)
    cfg.transport = transport
    monkeypatch.setattr(bot, 'schedule_reply_expired', lambda *a, **k: False)
    seen = []
    async def api(method, path, **kwargs):
        seen.append(kwargs)
        return {'id': 'receipt-1'}
    monkeypatch.setattr(bot, 'api', api)
    ok = client.portal.call(qq.send, bot, cfg, {'id': 'incoming'}, 'owner123', '我看到猫咪玩积木了。', lambda: True)
    assert ok and seen[0]['before_send']()
    assert not client.portal.call(qq.send, bot, cfg, {'id': 'incoming2'}, 'owner123', '不应发送', lambda: False)
    assert len(seen) == 1
    async def no_receipt(*args, **kwargs):
        return {}
    monkeypatch.setattr(bot, 'api', no_receipt)
    assert not client.portal.call(qq.send, bot, cfg, {'id': 'incoming3'}, 'owner123', '未确认', lambda: True)


def test_cancel_revokes_pending_begin_with_known_run_id(client, monkeypatch):
    tasks, host, _ = setup(client, monkeypatch, iter([]))
    original = host.request
    async def scenario():
        entered = asyncio.Event()
        async def request(method, path, body=None):
            if path.endswith('/douyin/begin'):
                entered.set()
                await asyncio.Future()
            return await original(method, path, body)
        monkeypatch.setattr(tasks.browser.gateway, 'request', request)
        task = tasks.submit('default', '刷抖音')
        await asyncio.wait_for(entered.wait(), 2)
        run_id = tasks.tokens[task['id']]
        result = await tasks.cancel('default', task['id'])
        assert result['state'] == 'cancelled'
        assert any(c[1].endswith('/douyin/end') and c[2]['token'] == run_id for c in host.calls)
        assert task['id'] not in tasks.jobs
    client.portal.call(scenario)


def test_explicit_links_come_from_watched_evidence_and_no_title_only_completion(client, monkeypatch):
    decisions = iter([{'op': 'home', 'reason': '打开抖音'},
        {'op': 'finish', 'reason': '只读了标题', 'note': '看完了'},
        {'op': 'watch', 'reason': '实际看视频', 'seconds': 15},
        {'op': 'finish', 'reason': '完成观看', 'note': '这段积木视频挺有意思。 https://example.invalid/invented'}])
    tasks, host, _ = setup(client, monkeypatch, decisions)
    task = run_task(client, tasks, '去抖音看点你喜欢的视频，把链接发我')
    assert task['state'] == 'completed'
    assert any(s['op'] == 'invalid' and '播放推进' in s['reason'] for s in task['steps'])
    assert 'https://www.douyin.com/video/1234567890123456789' in task['result']
    assert 'example.invalid' not in task['result']


def test_rejected_decision_is_repaired_with_feedback_and_does_not_consume_action_budget(client, monkeypatch):
    decisions = iter([{'op': 'home', 'reason': '先打开抖音'}, {'op': 'watch', 'seconds': 0, 'reason': '观察'},
        {'op': 'watch', 'seconds': 15, 'reason': '纠正观看时长'},
        {'op': 'finish', 'reason': '这一段看到了有趣的画面', 'note': '刚才看了猫咪搭积木的一小段。'}])
    tasks, host, contexts = setup(client, monkeypatch, decisions)
    task = run_task(client, tasks, '看猫咪')
    assert task['state'] == 'completed'
    assert len(task['decision_errors']) == 1
    error = task['decision_errors'][0]
    assert 'seconds' in error['error'] and 'greater' in error['error']
    assert contexts[2][-2]['role'] == 'assistant'
    assert 'seconds' in contexts[2][-1]['content'] and '未执行' in contexts[2][-1]['content']
    assert host.watches == 2 and len(task['steps']) == 3
    assert all(s['op'] != 'invalid' for s in task['steps'])


def test_repair_exhaustion_keeps_watch_evidence_and_redacts_diagnostics(client, monkeypatch):
    tasks, host, contexts = setup(client, monkeypatch, iter([]))
    calls = 0
    async def model(runtime, messages, tokens=1600):
        nonlocal calls
        calls += 1
        contexts.append(messages)
        if calls == 1:
            return '{"op":"home","reason":"先打开抖音"}'
        if calls == 2:
            return '{"op":"watch","reason":"实际看一段","seconds":15}'
        return json.dumps({'op': 'publish', 'reason': tasks.tokens[next(iter(tasks.tokens))] + ' ' + tasks.browser.gateway.token})
    monkeypatch.setattr(tasks, 'model', model)
    task = run_task(client, tasks, '二次元cos')
    assert task['state'] == 'blocked' and '3 次' in task['result']
    assert len(task['decision_errors']) == 3 and len(task['steps']) == 3
    assert task['steps'][-1]['watch']['advancedSeconds'] == 12
    assert tasks.browser.gateway.token not in json.dumps(task)
    assert '[已隐藏]' in task['decision_errors'][0]['response']
    assert [e['attempt'] for e in task['decision_errors']] == [1, 2, 3]
    assert host.token is None
    assert len(contexts[-1]) == 6


def test_ended_video_is_not_retried_as_buffering(client, monkeypatch):
    tasks, host, _ = setup(client, monkeypatch, iter([
        {'op': 'home', 'reason': '打开抖音'}, {'op': 'watch', 'seconds': 15, 'reason': '看这一段'},
        {'op': 'blocked', 'reason': '此前已经结束', 'note': '当前视频已经结束，本轮未取得播放证据。'}]))
    request = host.request
    async def ended(method, path, body=None):
        value = await request(method, path, body)
        if body and body.get('op') == 'watch':
            value['watch']['ended'] = True
        return value
    monkeypatch.setattr(tasks.browser.gateway, 'request', ended)
    task = run_task(client, tasks, '看猫咪')
    assert host.watches == 1 and task['state'] == 'blocked'


def test_browser_model_events_have_task_trace_and_stage(client, monkeypatch):
    tasks, host, _ = setup(client, monkeypatch, iter([]))
    runtime = client.portal.call(client.app.state.manager.get, 'default')
    seen = []
    async def generate(selection, messages, max_tokens, **kwargs):
        seen.append(dict(runtime.store.events.current.get()))
        return {'message': {'content': '{"op":"blocked","reason":"测试观察已完成","note":"本次只检查决策日志，没有播放视频。"}'}}
    monkeypatch.setattr(runtime.bot, 'generate', generate)
    # Use the real BrowserTasks.model, replaced by setup for other tests.
    monkeypatch.setattr(tasks, 'model', tasks.__class__.model.__get__(tasks))
    task = run_task(client, tasks, '看看抖音')
    assert task['state'] == 'blocked'
    assert seen == [{'stage': 'browser_decision', 'trace_id': task['id'], 'attempt': 1}]


@pytest.mark.parametrize('outcome', [
    {'skipped':{'id':'1234567890123456789','duration':3601,'reason':'超过 60 分钟，已跳过观看'}},
    {'seekFailed':{'requested':120,'actual':0}},
    {'previewComplete':True},
])
def test_skips_and_seek_outcomes_return_to_model_without_buffer_retry_or_false_completion(client, monkeypatch, outcome):
    tasks, host, contexts = setup(client, monkeypatch, iter([
        {'op':'home','reason':'打开抖音'}, {'op':'watch','reason':'尝试观看','seconds':15},
        {'op':'finish','reason':'不能以跳过作为观看','note':'看完了'},
        {'op':'blocked','reason':'本轮尚未看到画面','note':'进度已保存，尚未取得观看证据。'},
    ]))
    request=host.request
    async def skipped(method,path,body=None):
        value=await request(method,path,body)
        if body and body.get('op')=='watch':
            value.pop('watch',None);value.pop('images',None);value.update(outcome)
        return value
    monkeypatch.setattr(tasks.browser.gateway,'request',skipped)
    task=run_task(client,tasks,'看看抖音')
    assert task['state']=='blocked' and host.watches==1
    assert task['steps'][1].items() >= outcome.items()
    assert any(s['op']=='invalid' for s in task['steps'])
    assert json.loads(contexts[2][1]['content'])['progress'][-1].items() >= outcome.items()


def test_model_selected_preview_position_reaches_runtime_including_zero(client, monkeypatch):
    tasks,host,_=setup(client,monkeypatch,iter([
        {'op':'home','reason':'打开抖音'},
        {'op':'watch','reason':'先看开头','seconds':15,'start_at':0},
        {'op':'watch','reason':'跳到中段','seconds':15,'start_at':240.5},
        {'op':'finish','reason':'看过两个片段','note':'这条我跳着看了两段。'},
    ]))
    task=run_task(client,tasks,'看看抖音')
    assert task['state']=='completed'
    watches=[body for _,path,body in host.calls if path.endswith('/act') and body['op']=='watch']
    assert watches[0]['start_at']==0 and watches[-1]['start_at']==240.5
    assert 'start_at' not in watches[1] and watches[1]['continue_segment']  # Do not rewind or choose a new segment while buffering.


def test_viewing_configuration_reaches_runtime_model_and_task_evidence(client,monkeypatch):
    tasks,host,contexts=setup(client,monkeypatch,iter([
        {'op':'home','reason':'找视频'}, {'op':'watch','reason':'看一段','seconds':15},
        {'op':'finish','reason':'看到了片段','note':'这次跳着看了一小段。'}]))
    custom=ViewingConfig(preview_after_minutes=2,max_video_minutes=90,segment_seconds=6,skip_seconds=75)
    client.portal.call(tasks.save_config,'default',BrowsingConfig(enabled=True,viewing=custom))
    task=run_task(client,tasks,'看你喜欢的视频')
    assert task['state']=='completed'
    begin=next(body for _,path,body in host.calls if path.endswith('/begin'))
    assert begin['viewing']==custom.model_dump()
    assert all(json.loads(messages[1]['content'])['viewing']==custom.model_dump() for messages in contexts)
    assert all(s['viewing']==custom.model_dump() for s in task['steps'])


def test_old_runtime_cannot_silently_ignore_user_viewing_settings(client,monkeypatch):
    tasks,host,_=setup(client,monkeypatch,iter([]))
    request=host.request
    async def legacy(method,path,body=None):
        value=await request(method,path,body)
        if path.endswith('/begin'):value.pop('viewing',None)
        return value
    monkeypatch.setattr(tasks.browser.gateway,'request',legacy)
    task=run_task(client,tasks,'看看你喜欢的')
    assert task['state']=='blocked' and '观看策略' in task['result']
    assert not any(path.endswith('/act') for _,path,_ in host.calls)
    assert host.token is None


def test_confirmed_like_integrates_durable_policy_and_completion(client,monkeypatch):
    decisions=iter([{'op':'watch','reason':'先看内容','seconds':3},{'op':'like','id':'1234567890123456789','reason':'动作有趣'},
        {'op':'finish','reason':'本轮已完成','note':'看了这一段，也点了赞。'}])
    tasks,host,_=setup(client,monkeypatch,decisions)
    config=tasks.config('default');config.interactions.likes_enabled=True
    client.portal.call(tasks.save_config,'default',config)
    original=host.request
    async def request(method,path,body=None):
        result=await original(method,path,body)
        if path.endswith('/douyin/begin'):result['interactions']=body['interactions']
        if path.endswith('/douyin/act'):
            result.update(account={'id':'self-sec','verified':True},watched=True)
            if body['op']=='like':
                assert body['authorization']['account_id']=='self-sec'
                result['interaction']={'op':'like','status':'confirmed','submitted':True}
        return result
    monkeypatch.setattr(tasks.browser.gateway,'request',request)
    result=run_task(client,tasks,'刷抖音并点赞')
    assert result['state']=='completed'
    assert any(s.get('interaction',{}).get('status')=='confirmed' for s in result['steps'])
    assert tasks.interactions.count('self-sec','like')==1
    assert 'operation_id' not in json.dumps(result)


@pytest.mark.parametrize('messages_enabled',[False,True])
def test_invalid_watch_position_returns_feedback_without_stopping_or_replaying(client,monkeypatch,messages_enabled):
    tasks,host,contexts=setup(client,monkeypatch,iter([
        {'op':'home','reason':'打开抖音'},
        {'op':'watch','seconds':5,'start_at':16,'reason':'误把短视频当跳看'},
        {'op':'watch','seconds':5,'reason':'按当前正常播放位置继续'},
        {'op':'finish','reason':'已看到内容','note':'看了一会儿。'},
    ]))
    cfg=tasks.config('default');cfg.interactions.messages_enabled=messages_enabled
    client.portal.call(tasks.save_config,'default',cfg)
    request=host.request
    async def observed(method,path,body=None):
        value=await request(method,path,body)
        if path.endswith('/begin'):value['interactions']=body['interactions']
        if body and body.get('op')=='watch' and 'start_at' in body:
            value.pop('watch',None);value.pop('images',None)
            value['actionError']={'code':'invalid_position','recoverable':True,'submitted':False,'reason':'正常观看省略 start_at'}
        return value
    monkeypatch.setattr(tasks.browser.gateway,'request',observed)
    task=run_task(client,tasks,'刷会抖音')
    assert task['state']=='completed',task
    failed=task['steps'][1]
    assert failed['actionError']['submitted'] is False
    assert failed['request']=={'seconds':5,'start_at':16}
    feedback=json.loads(contexts[2][1]['content'])
    assert feedback['observation']['actionError']['code']=='invalid_position'
    assert feedback['progress'][-1]['actionError']['code']=='invalid_position'
    assert host.watches==2
    assert len([b for _,p,b in host.calls if b and b.get('start_at')==16])==1


def test_repeated_invalid_position_is_bounded_and_retains_reason(client,monkeypatch):
    tasks,host,_=setup(client,monkeypatch,iter([{'op':'watch','reason':'错误位置','start_at':17}]*3))
    request=host.request
    async def invalid(method,path,body=None):
        value=await request(method,path,body)
        if body and body.get('op')=='watch':
            value.pop('watch',None);value['actionError']={'code':'invalid_position','reason':'正常观看不能指定跳转位置','submitted':False}
        return value
    monkeypatch.setattr(tasks.browser.gateway,'request',invalid)
    task=run_task(client,tasks,'看抖音')
    assert task['state']=='blocked' and '3 次' in task['result']
    assert len(task['steps'])==3 and host.token is None
