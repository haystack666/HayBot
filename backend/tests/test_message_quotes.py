import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app.chat import ChatArchive
from app.message_quotes import conversation_text, scene_value, receipt_metadata
from app.napcat import normalize_event
from test_debounce import make, event, idle, close
from test_napcat import configure, message, napcat_server


def official(mid='new', text='那就去吧', group=None, ref='REFIDX_old==', original='我想看画画视频'):
    payload = event(mid, text, group=group)
    payload['d'].update(message_type=103,
        message_scene={'ext': ['ref_msg_idx=' + ref, 'msg_idx=REFIDX_' + mid + '==', 'auth_token=never-in-model']},
        msg_elements=[{'msg_idx': ref, 'content': original,
                       'author': {'id': 'bot-account', 'username': '小画家', 'bot': True}}])
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize('group', [None, 'our-group'])
async def test_official_quote_reaches_model_archive_and_history(tmp_path, group):
    store, bot = make(tmp_path)
    payload = official(group=group)
    try:
        await bot.receive(payload)
        await idle(bot)
        prompt = bot.generate.await_args.args[1][-1]['content']
        assert '我想看画画视频' in prompt and '那就去吧' in prompt and '小画家' in prompt
        assert 'never-in-model' not in prompt
        assert json.loads(prompt.split('\n', 1)[1])['quoted_message']['is_bot'] is True
        target = group or 'alice'
        archived = store.chat.find_platform('111', 'group' if group else 'user', target, 'REFIDX_new==')
        assert archived['content'] == '那就去吧'
        assert json.loads(archived['quote_context'])['content'] == '我想看画画视频'
        history = store.history(f'group:{group}:alice' if group else 'user:alice:alice', 6)
        assert history[0]['content'] == (bot.conversation_text(payload['d']) if group else prompt)
        page = store.chat.messages('111', archived['conversation_id'])
        assert page['items'][0]['quote_context']['sender_name'] == '小画家'
    finally:
        await close(store, bot)


@pytest.mark.asyncio
async def test_debounce_preserves_each_quote_next_to_its_own_reply(tmp_path):
    store, bot = make(tmp_path)
    try:
        await bot.receive(official('a', '这个喜欢', ref='REFIDX_a==', original='画画视频'))
        await bot.receive(event('b', '还有一件事'))
        await bot.receive(official('c', '这个不想看', ref='REFIDX_c==', original='卖课视频'))
        await idle(bot)
        assert bot.generate.await_count == 1
        prompt = bot.generate.await_args.args[1][-1]['content']
        assert prompt.index('画画视频') < prompt.index('这个喜欢') < prompt.index('还有一件事')
        assert prompt.index('还有一件事') < prompt.index('卖课视频') < prompt.index('这个不想看')
        assert bot.api.await_args.kwargs['json']['msg_id'] == 'c'
    finally:
        await close(store, bot)


@pytest.mark.asyncio
@pytest.mark.parametrize('group', [None, 'g'])
async def test_quote_without_new_text_is_not_discarded(tmp_path, group):
    store, bot = make(tmp_path)
    try:
        await bot.receive(official(text=' ', group=group))
        await idle(bot)
        assert bot.generate.await_count == 1
        prompt = bot.generate.await_args.args[1][-1]['content']
        assert '我想看画画视频' in prompt and '无新增文字' in prompt
    finally:
        await close(store, bot)


@pytest.mark.asyncio
async def test_quoted_command_is_background_not_executed(tmp_path):
    store, bot = make(tmp_path)
    try:
        await bot.receive(official(text='你刚才这句话什么意思', original='/reset 确认'))
        await idle(bot)
        assert bot.generate.await_count == 1
        assert not bot.reset.confirmations
        assert '/reset 确认' in bot.generate.await_args.args[1][-1]['content']
    finally:
        await close(store, bot)


@pytest.mark.asyncio
async def test_official_sent_reference_index_can_resolve_later_without_inline_content(tmp_path):
    store, bot = make(tmp_path)
    bot.api.return_value = {'id': 'actual-sent-id', 'ext_info': {'ref_idx': 'REFIDX_bot-bubble=='}}
    try:
        await bot.receive(event('first', '说句话'))
        await idle(bot)
        # Rolling context is irrelevant to resolving this exact bubble.
        store.clear_history()
        payload = official('next', ref='REFIDX_bot-bubble==')
        payload['d'].pop('msg_elements')
        await bot.receive(payload)
        await idle(bot)
        prompt = bot.generate.await_args.args[1][-1]['content']
        assert '我想听，快说说！' in prompt and '当前机器人' in prompt
        assert json.loads(prompt.split('\n', 1)[1])['quoted_message']['available']
    finally:
        await close(store, bot)


@pytest.mark.asyncio
async def test_official_incoming_index_and_legacy_message_reference(tmp_path):
    store, bot = make(tmp_path)
    try:
        original = event('old-id', '早一点的原话')
        original['d']['message_scene'] = {'ext': ['msg_idx=REFIDX_old==']}
        bot.capture_incoming(original)
        for ref in ('REFIDX_old==', 'old-id'):
            data = event('new-' + ref, '这个呢')['d']
            data['message_reference'] = {'message_id': ref}
            bot.capture_incoming({'t': 'C2C_MESSAGE_CREATE', 'd': data})
            assert data['_quote']['content'] == '早一点的原话'
            assert data['_quote']['is_bot'] is False
    finally:
        await close(store, bot)


@pytest.mark.asyncio
async def test_archive_reference_lookup_never_crosses_bot_or_conversation(tmp_path):
    store, bot = make(tmp_path)
    try:
        for app_id, kind, target in [('other-app', 'user', 'alice'), ('111', 'user', 'bob'), ('111', 'group', 'g')]:
            store.chat.record(app_id, kind, target, 'assistant', '不能泄露的原文', app_id + kind + target,
                              platform_id='old-id', platform_index='REFIDX_old==')
        payload = official()
        payload['d'].pop('msg_elements')
        await bot.receive(payload)
        await idle(bot)
        prompt = bot.generate.await_args.args[1][-1]['content']
        quote = json.loads(prompt.split('\n', 1)[1])['quoted_message']
        assert not quote['available'] and '不能泄露' not in prompt
        assert '那就去吧' in prompt
    finally:
        await close(store, bot)


@pytest.mark.asyncio
async def test_official_nested_quotes_media_and_card_are_bounded_and_attributed(tmp_path):
    store, bot = make(tmp_path)
    try:
        payload = official()
        node = payload['d']['msg_elements'][0]
        node.update(attachments=[{'content_type': 'image/png', 'url': 'https://qpic.cn/secret-token'}],
                    ark_data={'ark_name': '视频卡片', 'fields': {'title': '学习画猫', 'jump_url': 'https://b23.tv/example'}},
                    msg_elements=[{'content': '更早的原话', 'author': {'username': '小明'}}])
        await bot.receive(payload)
        await idle(bot)
        prompt = bot.generate.await_args.args[1][-1]['content']
        assert '更早的原话' in prompt and '小明' in prompt and '学习画猫' in prompt
        assert 'image/png' in prompt and '未读取' in prompt
        assert 'secret-token' not in prompt
        assert 'images' not in bot.generate.await_args.args[1][-1]
    finally:
        await close(store, bot)


@pytest.mark.asyncio
async def test_official_selects_matching_reference_not_first_element(tmp_path):
    store, bot = make(tmp_path)
    try:
        payload = official()
        payload['d']['msg_elements'].insert(0, {'msg_idx': 'unrelated', 'content': '不相干的消息'})
        bot.capture_incoming(payload)
        assert payload['d']['_quote']['content'] == '我想看画画视频'
        assert '不相干' not in conversation_text(payload['d'])
        mismatch = official('mismatch')
        mismatch['d']['msg_elements'][0]['msg_idx'] = 'different-index'
        bot.capture_incoming(mismatch)
        assert not mismatch['d']['_quote']['available']
    finally:
        await close(store, bot)


@pytest.mark.asyncio
async def test_official_group_example_with_no_element_index_and_empty_text(tmp_path):
    store, bot = make(tmp_path)
    try:
        payload = official(text=' ', group='g')
        payload['d']['msg_elements'] = [{'content': '=== 消息 1 ===\n学习计划已完成'}]
        await bot.receive(payload)
        await idle(bot)
        assert '学习计划已完成' in bot.generate.await_args.args[1][-1]['content']
    finally:
        await close(store, bot)


def napcat_reply(group=False, text='这个呢', ref=-123):
    raw = message(group=group)
    raw['message'] = [{'type': 'reply', 'data': {'id': str(ref)}},
                      *([{'type': 'at', 'data': {'qq': '10001'}}] if group else []),
                      *([{'type': 'text', 'data': {'text': text}}] if text else [])]
    return raw


def fetched(group=False, target=20002):
    return {'message_id': -123, 'message_type': 'group' if group else 'private',
            'group_id': 30003 if group else None, 'user_id': target,
            'sender': {'user_id': target, 'nickname': '原作者'},
            'message': [{'type': 'text', 'data': {'text': '之前那条画画消息'}}]}


@pytest.mark.asyncio
@pytest.mark.parametrize('group', [False, True])
async def test_napcat_get_msg_resolves_quote_and_feeds_shared_pipeline(tmp_path, group):
    store, bot = make(tmp_path)
    config = configure(store)
    bot.napcat.call = AsyncMock(return_value=fetched(group))
    try:
        payload = normalize_event(napcat_reply(group), config)
        await bot.napcat.resolve_quote(payload)
        bot.napcat.call.assert_awaited_once_with('get_msg', {'message_id': -123}, timeout=5)
        bot.api = AsyncMock(return_value={'id': 'reply'})
        await bot.receive(payload)
        await idle(bot)
        prompt = bot.generate.await_args.args[1][-1]['content']
        assert '之前那条画画消息' in prompt and '原作者' in prompt and '这个呢' in prompt
    finally:
        await close(store, bot)


@pytest.mark.asyncio
async def test_napcat_archived_outgoing_reply_needs_no_fetch(tmp_path):
    store, bot = make(tmp_path)
    config = configure(store)
    bot.napcat.call = AsyncMock()
    try:
        store.chat.record(config.account_id, 'user', '20002', 'assistant', '我想看画画视频', 'reply-key', platform_id='-123')
        payload = normalize_event(napcat_reply(text=''), config)
        assert payload is not None
        await bot.napcat.resolve_quote(payload)
        assert payload['d']['_quote']['is_bot'] is True
        assert payload['d']['_quote']['content'] == '我想看画画视频'
        bot.napcat.call.assert_not_awaited()
    finally:
        await close(store, bot)


@pytest.mark.asyncio
async def test_napcat_query_failure_keeps_new_message_and_explicit_unknown_quote(tmp_path):
    store, bot = make(tmp_path)
    config = configure(store)
    bot.napcat.call = AsyncMock(side_effect=TimeoutError())
    try:
        payload = normalize_event(napcat_reply(), config)
        await bot.napcat.resolve_quote(payload)
        await bot.receive(payload)
        await idle(bot)
        prompt = bot.generate.await_args.args[1][-1]['content']
        quote = json.loads(prompt.split('\n', 1)[1])['quoted_message']
        assert quote['available'] is False and '这个呢' in prompt
    finally:
        await close(store, bot)


@pytest.mark.asyncio
async def test_napcat_websocket_quote_fetch_and_response_end_to_end(tmp_path):
    store, bot = make(tmp_path)
    try:
        async with napcat_server(quoted_message=fetched()) as (url, calls, connections):
            configure(store, url)
            # Exercise the actual websocket reader, echo correlation, consumer and sender.
            bot.api = type(bot).api.__get__(bot, type(bot))
            await bot.napcat.start()
            await connections[0].send(json.dumps(napcat_reply()))
            async with asyncio.timeout(5):
                while bot.generate.await_count == 0:
                    await asyncio.sleep(.01)
            await idle(bot)
            assert '之前那条画画消息' in bot.generate.await_args.args[1][-1]['content']
            assert [call['action'] for call in calls] == ['get_login_info', 'get_status', 'get_msg', 'send_private_msg']
            assert calls[-1]['params']['user_id'] == 20002
            assert store.chat.find_platform('napcat:10001', 'user', '20002', '456')['role'] == 'assistant'
            await bot.napcat.close()
    finally:
        await close(store, bot)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['private-peer', 'group-peer', 'wrong-id', 'wrong-kind'])
async def test_napcat_rejects_quote_from_wrong_conversation_or_id(tmp_path, change):
    store, bot = make(tmp_path)
    config = configure(store)
    group = change == 'group-peer'
    response = fetched(group)
    if change == 'private-peer':
        response['sender']['user_id'] = response['user_id'] = 88888
    elif change == 'group-peer':
        response['group_id'] = 99999
    elif change == 'wrong-id':
        response['message_id'] = -999
    else:
        response['message_type'] = 'group'
    bot.napcat.call = AsyncMock(return_value=response)
    try:
        payload = normalize_event(napcat_reply(group), config)
        await bot.napcat.resolve_quote(payload)
        assert payload['d']['_quote']['available'] is False
        assert '之前那条' not in conversation_text(payload['d'])
    finally:
        await close(store, bot)


@pytest.mark.asyncio
async def test_quote_inbox_survives_recovery_with_encrypted_context(tmp_path):
    store, bot = make(tmp_path)
    bot.state = 'stopped'
    try:
        await bot.receive(official(original='独有引用原文'))
        encrypted = store.db.execute('SELECT payload FROM message_inbox').fetchone()[0]
        assert '独有引用原文' not in encrypted
        bot.inbox.recover()
        bot.state = 'connected'
        bot.inbox.start()
        await idle(bot)
        assert '独有引用原文' in bot.generate.await_args.args[1][-1]['content']
    finally:
        await close(store, bot)


def test_quote_limits_and_protocol_helpers():
    data = official()['d']
    assert scene_value(data, 'ref_msg_idx') == 'REFIDX_old=='
    assert receipt_metadata({'id': '-1', 'ext_info': {'ref_idx': 'REFIDX_out=='}}) == {
        'platform_id': '-1', 'platform_index': 'REFIDX_out=='}
    node = data['msg_elements'][0]
    node['content'] = '画' * 100000
    node['msg_elements'] = [node]  # Malformed cyclic objects are also bounded.
    from app.message_quotes import quoted_body
    body = quoted_body(node)
    assert len(body['content']) == 4000 and body['truncated']
    assert len(json.dumps(body)) < 25000
    node = {'content': '开始'}
    parent = node
    for _ in range(100):
        child = {'content': '下一层'}
        parent['msg_elements'] = [child]
        parent = child
    assert json.dumps(quoted_body(node), ensure_ascii=False).count('下一层') == 2


@pytest.mark.asyncio
async def test_existing_archive_schema_is_migrated_without_losing_messages(tmp_path):
    store, bot = make(tmp_path)
    try:
        bot.capture_incoming(event('old', '保留的历史'))
        # Simulate the schema before quote support, then reopen the archive migration.
        with store.db:
            store.db.execute('DROP INDEX chat_platform_id')
            store.db.execute('DROP INDEX chat_platform_index')
            for column in ('platform_id', 'platform_index', 'quote_context'):
                store.db.execute('ALTER TABLE chat_messages DROP COLUMN ' + column)
        migrated = ChatArchive(store.db)
        row = migrated.find_platform('111', 'user', 'alice', 'old')
        assert row['content'] == '保留的历史' and row['quote_context'] == ''
    finally:
        await close(store, bot)


@pytest.mark.asyncio
async def test_phone_intent_keeps_current_message_when_quote_is_long(tmp_path):
    from test_android_qq import setup_bridge, payload
    manager, tasks, bridge, bot = await setup_bridge(tmp_path)
    try:
        current = '我只是问这句话是什么意思'
        quoted = '/手机 打开哔哩哔哩。' + '这是之前的聊天内容。' * 400
        quoted = quoted[:4000]
        packet = payload(current)
        packet['d']['_quote'] = {'id': 'old', 'available': True, 'content': quoted}
        bot.generate = AsyncMock(side_effect=[{'message': {'content': '{"request":"none"}'}},
                                             {'message': {'content': '是在说之前那个手机任务。'}}])
        await bot.handle(packet)
        classifier_input = json.loads(bot.generate.await_args_list[0].args[1][-1]['content'])
        assert classifier_input['current_message'] == current
        assert quoted in classifier_input['quoted_context']
        assert tasks.list('default') == []
    finally:
        await tasks.close()
        await manager.close()
