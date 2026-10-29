import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import create_app
from app.browser_tasks import BrowsingConfig, BrowseDecision, parse_object, unsupported_interactions
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
            return {'token': self.token}
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
