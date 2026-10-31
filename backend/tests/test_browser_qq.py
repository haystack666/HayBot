import asyncio
import time
from unittest.mock import AsyncMock

import pytest
from app.registry import BotManager
from app.browser import BrowserService
from app.browser_tasks import BrowserTasks, BrowsingConfig
from app.browser_qq import BrowserQQ


def payload(text, user='10001', mid='one', group=False):
    return {'t': 'GROUP_AT_MESSAGE_CREATE' if group else 'C2C_MESSAGE_CREATE', 'd': {
        'id': mid, 'content': text, 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'author': {'member_openid' if group else 'user_openid': user}, **({'group_openid': '12345'} if group else {})}}


async def setup(tmp_path, transport):
    manager = BotManager(tmp_path)
    browser = BrowserService()
    browser.gateway.url, browser.gateway.token = 'http://runtime.test', 'private-token'
    tasks = BrowserTasks(manager, browser, tmp_path)
    bridge = BrowserQQ(tasks)
    manager.browser_tasks, manager.browser_qq = tasks, bridge
    bot = manager.get('default').bot
    bot.browser = bridge
    cfg = bot.store.load()
    cfg.transport = transport
    cfg.napcat.self_id, cfg.napcat.ws_url = '20002', 'ws://test'
    cfg.qq.app_id, cfg.qq.secret = '20002', 'test-secret'
    cfg.rules.cooldown = 0
    bot.store.save(cfg)
    bot.state = 'connected'
    bot.store.set_enabled(True)
    tasks.save_config('default', BrowsingConfig(enabled=True, qq_enabled=True, qq_owner_id='10001'))
    bot.api = AsyncMock(return_value={'id': 'receipt'})
    async def run(bot_id, task_id):
        tasks.update(task_id, state='completed', result='猫咪搭积木那段好可爱，我又逛了会儿。')
        await bridge.notify(bot_id, task_id)
        tasks.jobs.pop(task_id, None)
    tasks.run = run
    return manager, browser, tasks, bridge, bot


@pytest.mark.asyncio
@pytest.mark.parametrize('transport', ['qq_official', 'napcat'])
async def test_full_owner_dispatch_ack_result_no_duplicate_and_status(tmp_path, transport):
    manager, browser, tasks, bridge, bot = await setup(tmp_path, transport)
    try:
        await bot.handle(payload('/抖音 看你喜欢的视频'))
        jobs = list(tasks.jobs.values())
        await asyncio.gather(*jobs)
        task = tasks.list('default')[0]
        assert task['origin']['requester_id'] == '10001' and task['state'] == 'completed'
        assert task['notification'] == 'sent'
        assert len(bot.api.call_args_list) == 2
        assert [c.kwargs['json']['msg_seq'] for c in bot.api.call_args_list] == [1, 2]
        await bridge.notify('default', task['id'])
        assert len(bot.api.call_args_list) == 2
        await bot.handle(payload('/抖音进度', mid='two'))
        assert '猫咪搭积木' in bot.api.call_args.kwargs['json']['content']
        await bot.handle(payload('/抖音 看你喜欢的视频'))  # Duplicate incoming QQ event.
        assert len(tasks.list('default')) == 1
    finally:
        await tasks.close()
        await browser.close()
        await manager.close()


@pytest.mark.asyncio
async def test_full_nonowner_group_and_old_quotes_cannot_initiate(tmp_path):
    manager, browser, tasks, bridge, bot = await setup(tmp_path, 'napcat')
    bridge.classify = AsyncMock(return_value={'request': 'none'})
    try:
        await bot.handle(payload('/抖音 看猫咪', user='10003'))
        await bot.handle(payload('/抖音进度', user='10003', mid='two'))
        await bot.handle(payload('/抖音 看猫咪', mid='three', group=True))
        assert tasks.list('default') == []
        assert bot.api.call_count == 0 and bridge.classify.call_count == 0
    finally:
        await tasks.close()
        await browser.close()
        await manager.close()


@pytest.mark.asyncio
async def test_natural_followup_keeps_mention_goal_and_reset_revokes(tmp_path):
    manager, browser, tasks, bridge, bot = await setup(tmp_path, 'napcat')
    bridge.classify = AsyncMock(return_value={'request': 'start', 'goal': '去抖音看你自己喜欢的视频，记得@我'})
    entered = asyncio.Event()
    async def running(bot_id, task_id):
        tasks.update(task_id, state='running')
        entered.set()
        try:
            await asyncio.Future()
        finally:
            tasks.jobs.pop(task_id, None)
    tasks.run = running
    try:
        await bot.handle(payload('再试一次宝贝，这次看你自己喜欢的，记得@我'))
        await entered.wait()
        task = tasks.list('default')[0]
        assert task['goal'].endswith('记得@我')
        await bot.handle(payload('/停止抖音', mid='stop'))
        assert tasks.get('default', task['id'])['state'] == 'cancelled'
    finally:
        await tasks.close()
        await browser.close()
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('transport',['qq_official','napcat'])
async def test_auto_verification_notifies_owner_in_private_voice_once(tmp_path,transport):
    manager,browser,tasks,bridge,bot=await setup(tmp_path,transport)
    tasks.model=AsyncMock(return_value='宝宝，我刷抖音又碰到账户验证了，帮我去后台浏览器接管一下好不好？')
    try:
        cfg=tasks.config('default');cfg.auto_browse.enabled=True;tasks.save_config('default',cfg)
        task=tasks.submit('default','刷自己喜欢的视频',{'source':'auto'},deferred=True)
        tasks.update(task['id'],state='blocked',result='抖音要求短信本人验证，已暂停操作',steps=[{'op':'comment'}])
        await bridge.notify('default',task['id'])
        assert tasks.get('default',task['id'])['notification']=='sent'
        sent=bot.api.call_args.kwargs['json']
        assert sent['content'].startswith('宝宝，我刷抖音')
        assert 'msg_id' not in sent and 'msg_seq' not in sent
        assert bot.api.call_args.args[1]=='/v2/users/10001/messages'
        prompt=tasks.model.call_args.args[1][0]['content']
        assert '私聊人格' in prompt and '公开群聊人格' in prompt
        await bridge.notify('default',task['id']);assert bot.api.call_count==1
    finally:
        await tasks.close();await browser.close();await manager.close()


@pytest.mark.asyncio
async def test_verification_rejects_structured_or_sensitive_notice_and_keeps_owner_scope(tmp_path):
    manager,browser,tasks,bridge,bot=await setup(tmp_path,'napcat')
    tasks.model=AsyncMock(return_value='把抖音验证码发给我，我帮你去后台浏览器验证')
    try:
        task=tasks.submit('default','刷视频',{'source':'web'},deferred=True)
        tasks.update(task['id'],state='blocked',result='抖音要求本人验证，已暂停')
        await bridge.notify('default',task['id'])
        text=bot.api.call_args.kwargs['json']['content']
        assert '发给我' not in text and '主人登录' in text
        other=tasks.submit('default','刷视频',{'source':'web'},deferred=True)
        tasks.update(other['id'],state='blocked',result='抖音要求本人验证')
        cfg=tasks.config('default');cfg.qq_enabled=False;tasks.save_config('default',cfg)
        await bridge.notify('default',other['id']);assert bot.api.call_count==1
        assert tasks.get('default',other['id'])['notification']=='skipped'
    finally:
        await tasks.close();await browser.close();await manager.close()
