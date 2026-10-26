import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, ProactiveConfig, GreetingConfig
from app.main import create_app
from app.proactive import ProactiveService, active_at, day_start
from app.store import Store
from app.bot import Bot


NOW = datetime(2026, 10, 24, 12, 0, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path)
    config = Settings()
    config.qq.app_id = '123456'
    config.proactive.enabled = True
    config.proactive.recipient_id = 'owner'
    config.proactive.active_start = config.proactive.active_end = '00:00'
    config.proactive.cooldown_minutes = 10
    config.proactive.daily_limit = 10
    config.proactive.idle_min_minutes = config.proactive.idle_max_minutes = 10
    config.proactive.greetings = []
    store.save(config)
    store.remember_contact('123456', 'owner', NOW - 7200, 'incoming-1')
    store.set_capability('123456', 'owner', 'supported', '已验证', NOW - 7200)
    calls = []
    def transport(request):
        calls.append(request)
        return httpx.Response(200, json={'id': 'accepted'})
    client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    bot = Bot(store, client)
    bot.state = 'connected'
    bot.access_token = AsyncMock(return_value='test-token')
    bot.request = AsyncMock(return_value={'message': {'content': '今天过得怎么样？'}, 'prompt_eval_count': 20, 'eval_count': 8})
    from app.ollama import chat_response
    bot.generate = lambda config, messages, max_tokens: chat_response(bot.request, config, messages, max_tokens)
    clock = [NOW]
    service = ProactiveService(store, bot, clock=lambda: clock[0])
    yield store, config, bot, service, calls, clock
    store.close()


def test_defaults_validation_and_timezone():
    assert not Settings().proactive.enabled
    with pytest.raises(ValueError):
        ProactiveConfig(idle_min_minutes=240, idle_max_minutes=120)
    with pytest.raises(ValueError):
        ProactiveConfig(timezone='missing-zone')
    with pytest.raises(ValueError):
        ProactiveConfig(active_start='25:00')
    p = ProactiveConfig(active_start='22:00', active_end='08:00')
    assert not active_at(NOW, p)
    assert active_at(NOW + 11 * 3600, p)
    assert datetime.fromtimestamp(day_start(NOW, p), ZoneInfo(p.timezone)).hour == 0


def test_frequency_boundaries_and_midnight_window():
    p = ProactiveConfig(daily_limit=0, cooldown_minutes=0, unanswered_limit=20,
                        idle_min_minutes=5, idle_max_minutes=1440)
    assert p.active_start == '07:00' and p.active_end == '00:00'
    for hour, minute, expected in [(0, 0, False), (6, 59, False), (7, 0, True), (23, 59, True)]:
        at = datetime(2026, 10, 24, hour, minute, tzinfo=ZoneInfo(p.timezone)).timestamp()
        assert active_at(at, p) is expected
    ProactiveConfig(daily_limit=1000, cooldown_minutes=1440, unanswered_limit=1,
                    idle_min_minutes=1440, idle_max_minutes=1440)
    ProactiveConfig(idle_min_minutes=5, idle_max_minutes=5)
    for invalid in [dict(daily_limit=-1), dict(cooldown_minutes=-1), dict(cooldown_minutes=1441),
                    dict(unanswered_limit=0), dict(unanswered_limit=21), dict(idle_min_minutes=4),
                    dict(idle_max_minutes=1441), dict(idle_min_minutes=1441), dict(idle_max_minutes=4)]:
        with pytest.raises(ValueError):
            ProactiveConfig(**invalid)


@pytest.mark.asyncio
async def test_unlimited_daily_and_five_minute_idle_are_effective(setup):
    store, config, bot, service, calls, clock = setup
    config.proactive.daily_limit = 0
    config.proactive.cooldown_minutes = 0
    config.proactive.idle_min_minutes = config.proactive.idle_max_minutes = 5
    config.proactive.unanswered_limit = 20
    for i in range(12):
        event = store.reserve_proactive(f'old-{i}', '123456', 'owner', 'test', NOW - 3600)
        store.proactive_sent(event, NOW - 3600, NOW - 1)
    store.remember_contact('123456', 'owner', NOW - 299, 'recent-five')
    store.save(config)
    assert '最近 5 分钟' in service.snapshot()['reason']
    clock[0] += 1
    assert not service.snapshot()['reason']
    await service.execute('after-five-minutes', config, 'owner', 'idle', '关心一下')
    assert len(calls) == 1
    assert service.snapshot()['today_count'] == 13
    config.proactive.daily_limit = 13
    store.save(config)
    assert '本地上限' in service.snapshot()['reason']
    await bot.client.aclose()


@pytest.mark.asyncio
async def test_scheduled_send_is_independent_and_deduped_after_restart(setup):
    store, config, bot, service, calls, clock = setup
    config.proactive.greetings = [GreetingConfig(id='noon', time='12:00', mode='fixed', content='中午好')]
    store.save(config)
    await service.tick()
    await service.tick()
    service = ProactiveService(store, bot, clock=lambda: clock[0])
    await service.tick()
    assert len(calls) == 1
    assert calls[0].url.path == '/v2/users/owner/messages'
    assert json.loads(calls[0].content) == {'msg_type': 0, 'content': '中午好'}
    assert store.stats()['received'] == 0 and store.stats()['sent'] == 1
    assert store.proactive_records('123456')[0]['status'] == 'sent'
    bot.request.assert_not_called()
    assert store.contact('123456', 'owner')['unanswered'] == 1
    await bot.client.aclose()


@pytest.mark.asyncio
async def test_idle_pauses_after_two_unanswered_and_new_chat_resets(setup):
    store, config, bot, service, calls, clock = setup
    store.set_idle_time('123456', 'owner', NOW - 1)
    await service.tick()
    clock[0] += 600
    await service.tick()
    clock[0] += 600
    await service.tick()
    assert len(calls) == 2
    assert bot.request.await_count == 2
    assert store.stats()['total_tokens'] == 56
    assert '未获回应' in service.snapshot()['reason']
    store.remember_contact('123456', 'owner', clock[0], 'new-incoming')
    assert store.contact('123456', 'owner')['unanswered'] == 0
    assert store.contact('123456', 'owner')['next_idle'] == 0
    await service.tick()
    assert store.contact('123456', 'owner')['next_idle'] > clock[0]
    await bot.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('block', ['disabled', 'stopped', 'quiet', 'busy', 'recent', 'unverified', 'daily', 'cooldown'])
async def test_controls_block_before_generation(setup, block):
    store, config, bot, service, calls, clock = setup
    if block == 'disabled': config.proactive.enabled = False
    if block == 'stopped': bot.state = 'stopped'
    if block == 'quiet': config.proactive.active_start, config.proactive.active_end = '22:00', '08:00'
    if block == 'busy': bot.jobs.add('job')
    if block == 'recent': store.remember_contact('123456', 'owner', NOW - 60, 'recent')
    if block == 'unverified': store.set_capability('123456', 'owner', 'unknown', '', NOW)
    if block in ('daily', 'cooldown'):
        event_id = store.reserve_proactive('previous', '123456', 'owner', 'test', NOW - 60)
        store.proactive_sent(event_id, NOW - 60, NOW - 1)
        if block == 'daily': config.proactive.daily_limit = 1
    store.save(config)
    await service.execute('blocked', config, 'owner', 'idle', '关心一下')
    assert not calls
    bot.request.assert_not_called()
    assert store.proactive_records('123456')[0]['status'] == 'skipped'
    assert service.snapshot()['reason']
    await bot.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['stop', 'chat', 'config'])
async def test_cancel_when_state_changes_during_model_generation(setup, change):
    store, config, bot, service, calls, clock = setup
    async def generate(*args, **kwargs):
        if change == 'stop': bot.state = 'stopped'
        if change == 'chat': store.remember_contact('123456', 'owner', NOW, 'fresh-message')
        if change == 'config':
            modified = store.load()
            modified.proactive.enabled = False
            store.save(modified)
        return {'message': {'content': '测试'}, 'prompt_eval_count': 9, 'eval_count': 2}
    bot.request.side_effect = generate
    await service.execute('change', config, 'owner', 'idle', '关心一下')
    assert not calls
    assert store.stats()['total_tokens'] == 11
    assert store.proactive_records('123456')[0]['status'] == 'skipped'
    await bot.client.aclose()


@pytest.mark.asyncio
async def test_rejection_disables_further_automatic_attempts(setup):
    store, config, bot, service, calls, clock = setup
    await bot.client.aclose()
    def transport(request):
        calls.append(request)
        return httpx.Response(200, json={'code': 22009, 'message': 'private-upstream-content'})
    bot.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    await service.execute('reject', config, 'owner', 'idle', '关心一下')
    assert store.contact('123456', 'owner')['capability'] == 'rejected'
    assert store.proactive_records('123456')[0]['status'] == 'failed'
    store.set_idle_time('123456', 'owner', NOW - 1)
    await service.tick()
    assert len(calls) == 1 and store.stats()['sent'] == 0
    assert 'private-upstream' not in json.dumps(store.logs())
    await bot.client.aclose()


@pytest.mark.asyncio
async def test_timeout_result_unknown_is_not_retried(setup):
    store, config, bot, service, calls, clock = setup
    await bot.client.aclose()
    def transport(request):
        calls.append(request)
        raise httpx.ReadTimeout('response lost', request=request)
    bot.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    await service.execute('uncertain', config, 'owner', 'idle', '固定', generated=False)
    assert store.proactive_records('123456')[0]['status'] == 'unknown'
    service = ProactiveService(store, bot, clock=lambda: clock[0])
    await service.execute('uncertain', config, 'owner', 'idle', '固定', generated=False)
    assert len(calls) == 1
    assert store.proactive_count('123456', 'owner', day_start(NOW, config.proactive)) == 1
    await bot.client.aclose()


@pytest.mark.asyncio
async def test_reminder_expiry_cancel_and_reminder_ignores_chat_cooldown(setup):
    store, config, bot, service, calls, clock = setup
    store.remember_contact('123456', 'owner', NOW - 10, 'fresh')
    store.add_reminder('expired', '123456', 'owner', NOW - 400, '已过期', NOW - 500)
    store.add_reminder('cancelled', '123456', 'owner', NOW, '已取消', NOW - 500)
    store.cancel_reminder('123456', 'cancelled')
    store.add_reminder('due', '123456', 'owner', NOW, '拿快递', NOW - 500)
    await service.tick()
    assert len(calls) == 1 and json.loads(calls[0].content)['content'] == '提醒：拿快递'
    reminders = {r['id']: r for r in store.reminders('123456')}
    assert reminders['expired']['status'] == 'skipped'
    assert reminders['cancelled']['status'] == 'cancelled'
    assert reminders['due']['status'] == 'sent'
    assert store.contact('123456', 'owner')['unanswered'] == 0
    await bot.client.aclose()


@pytest.mark.asyncio
async def test_stop_while_fetching_token_prevents_send(setup):
    store, config, bot, service, calls, clock = setup
    async def token():
        bot.state = 'stopped'
        return 'test-token'
    bot.access_token.side_effect = token
    await service.execute('token-race', config, 'owner', 'idle', '固定', generated=False)
    assert not calls and store.proactive_records('123456')[0]['status'] == 'skipped'
    await bot.client.aclose()


@pytest.mark.asyncio
async def test_recovery_and_account_isolation(setup):
    store, config, bot, service, calls, clock = setup
    first = store.reserve_proactive('crash-send', '123456', 'owner', 'greeting', NOW)
    store.update_proactive(first, 'sending')
    store.reserve_proactive('crash-generate', '123456', 'owner', 'greeting', NOW)
    store.recover_proactive()
    records = store.proactive_records('123456')
    assert {r['status'] for r in records} == {'unknown', 'skipped'}
    assert not store.contacts('other-app') and not store.proactive_records('other-app')
    store.clear_history()
    assert store.contact('123456', 'owner')['capability'] == 'supported'
    await bot.client.aclose()


def test_proactive_api_auth_settings_and_reminders(tmp_path, monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-password-long-enough')
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/api/proactive').status_code == 401
        assert client.post('/api/proactive/preview', json={}).status_code == 401
        client.post('/api/login', json={'password': 'test-password-long-enough'})
        body = client.get('/api/settings').json()
        assert not body['proactive']['enabled']
        body['qq'].pop('secret_set')
        body['qq']['secret'] = ''
        body['proactive'].update(enabled=True, recipient_id='unknown')
        assert client.put('/api/settings', json=body).status_code == 400
        store = Store(tmp_path)
        store.remember_contact(body['qq']['app_id'], 'owner', NOW)
        store.close()
        body['proactive']['recipient_id'] = 'owner'
        assert client.put('/api/settings', json=body).status_code == 200
        assert client.post('/api/proactive/test', json={'recipient_id': 'owner'}).status_code == 400
        assert client.post('/api/proactive/reminders', json={'at': '2026-10-24T12:00', 'content': '提醒'}).status_code == 400
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        result = client.post('/api/proactive/reminders', json={'at': future, 'content': '拿快递'})
        assert result.status_code == 200
        reminder_id = result.json()['reminders'][0]['id']
        assert client.delete('/api/proactive/reminders/' + reminder_id).status_code == 200
        assert client.delete('/api/proactive/reminders/' + reminder_id).status_code == 400
