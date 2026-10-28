import json
from unittest.mock import AsyncMock

import pytest

from app.meme_service import decode_reply
from app.reply_envelope import extract_envelope, public_reply
from test_memes import delivery_bot
from test_reply_segments import event, make_bot


REPLY = '再眯五分钟……被窝里还挺暖和的，我不想动。'
MEME = 'a9c159a7f3f93257b1f720f658984919a3fcac2699974e48b66296b0f4dd45f5'


def envelope(reply=REPLY, meme=MEME):
    return json.dumps({'reply': reply, 'schedule_update': None, 'meme_id': meme}, ensure_ascii=False)


@pytest.mark.parametrize('raw', [
    envelope(),
    '```json\n' + envelope() + '\n```',
    REPLY + '\n\n' + envelope(),
    '下面是回复：\n```json\n' + envelope() + '\n```',
    envelope() + '\n我已经选好表情包了。',
    REPLY + '\n\n' + envelope() + '\n这是传输格式。',
    envelope(envelope()),
])
def test_public_reply_never_leaks_transport_fields(raw):
    assert public_reply(raw) == REPLY
    assert decode_reply(raw, [{'id': MEME}]) == (REPLY, None, {'id': MEME})


@pytest.mark.parametrize('raw', [
    REPLY + '\n{"reply":"断了',
    REPLY + '\n,"schedule_update":null,"meme_id":"' + MEME + '"}',
    REPLY + ',"schedule_update":null,"meme_id":"' + MEME + '"}',
    REPLY + '\n```json\n{"reply":"断了',
])
def test_incomplete_suffix_recovers_only_complete_public_prose(raw):
    assert public_reply(raw) == REPLY
    assert decode_reply(raw, [{'id': MEME}]) == (REPLY, None, None)


@pytest.mark.parametrize('raw', [
    '{"reply":"断了',
    '{"schedule_update":null,"meme_id":"' + MEME + '"}',
    '{"reply":null,"schedule_update":null}',
    ',"schedule_update":null,"meme_id":"' + MEME + '"}',
    envelope() + '\n' + envelope('第二个回复'),
    REPLY + '\n' + envelope() + '\n{"reply":"另一个没写完',
    '[' + envelope() + ']',
    '{"message":' + envelope() + '}',
])
def test_invalid_or_ambiguous_envelope_is_rejected(raw):
    with pytest.raises(ValueError):
        public_reply(raw)


@pytest.mark.parametrize('raw', [
    '普通文字，不必改变。',
    '我们去 {公园} 看看吧。',
    'API 返回的是 {"result":"ok","count":2}。',
    '```python\nprint({"name": "Alice"})\n```',
    '示例：{"reply_code":200,"message":"ok"}',
    '链接 https://example.test/api?x=1 记得看。',
    '许多括号' + '{test}' * 100,
])
def test_ordinary_prose_code_and_unrelated_json_are_preserved(raw):
    assert public_reply(raw) == raw


@pytest.mark.asyncio
@pytest.mark.parametrize('group', [False, True])
async def test_reported_mixed_output_sends_body_once_then_one_meme(tmp_path, group):
    library, store, bot, item, _, calls = await delivery_bot(tmp_path)
    config = store.load()
    config.qq.group_reply = group
    config.rules.split_length = 100
    store.save(config)
    bot.generate = AsyncMock(return_value={'message': {'content': REPLY + '\n\n' + envelope(meme=item['id'])}})
    try:
        assert await bot.handle(event(group=group)) is True
        messages = [body for path, body in calls if path.endswith('/messages')]
        assert len(messages) == 2
        assert messages[0]['msg_type'] == 0 and messages[0]['content'] == REPLY
        assert messages[1]['msg_type'] == 7
        assert bot.generate.await_count == 1
        key = 'group:g1:alice' if group else 'user:alice:alice'
        history = store.history(key, 6)[-1]['content']
        assert 'schedule_update' not in history and 'meme_id' not in history
        assert history.count(REPLY) == 1
        assert '表情包' in history
    finally:
        await bot.client.aclose()
        store.close()
        library.close()


@pytest.mark.asyncio
async def test_mixed_reply_works_without_schedule_or_meme_protocol_enabled(tmp_path):
    store, bot, _ = make_bot(tmp_path)
    bot.generate = AsyncMock(return_value={'message': {'content': REPLY + '\n' + envelope()}})
    try:
        await bot.handle(event())
        sent = ''.join(call.kwargs['json']['content'] for call in bot.api.await_args_list)
        assert sent == REPLY
        assert 'schedule_update' not in store.history('user:alice:alice', 6)[-1]['content']
    finally:
        await bot.client.aclose()
        store.close()


@pytest.mark.asyncio
async def test_mixed_schedule_metadata_is_not_applied(tmp_path):
    from test_schedule_dialogue import configured, schedule_bot, NOW, UPDATE
    from app.store import Store
    store = Store(tmp_path)
    configured(store)
    bot, _ = schedule_bot(store, [NOW])
    try:
        raw = '已经写出的正文。\n' + json.dumps({'reply': '好。', 'schedule_update': UPDATE}, ensure_ascii=False)
        reply, update = bot.schedule.dialogue.decode(raw)
        assert reply == '好。' and update is None
    finally:
        await bot.client.aclose()
        store.close()


@pytest.mark.asyncio
async def test_history_repairs_existing_leak_without_altering_user_or_archive(tmp_path):
    store, bot, _ = make_bot(tmp_path)
    raw = REPLY + '\n\n' + envelope() + '\n[发送表情包：困困的鲸鱼少女]'
    key = 'user:alice:alice'
    try:
        store.save_history(key, [{'role': 'user', 'content': envelope()}, {'role': 'assistant', 'content': raw}], 6)
        store.chat.record('111', 'user', 'alice', 'assistant', raw, 'original-sent')
        history = store.history(key, 6)
        assert history[0]['content'] == envelope()
        assert history[1]['content'] == REPLY + '\n[发送表情包：困困的鲸鱼少女]'
        assert store.db.execute("SELECT content FROM chat_messages WHERE event_key='original-sent'").fetchone()[0] == raw
        await bot.handle(event())
        previous = bot.generate.await_args.args[1][2]['content']
        assert 'schedule_update' not in previous and 'meme_id' not in previous
    finally:
        await bot.client.aclose()
        store.close()


@pytest.mark.asyncio
async def test_send_guard_cleans_before_splitting_and_archiving(tmp_path):
    from app.reply_delivery import ReplyDelivery
    store, bot, _ = make_bot(tmp_path)
    try:
        day = bot.schedule
        sid = store.scopes.ensure('111', 'user', 'alice', 'alice')['id']
        day = bot.schedule.for_scope(sid)
        delivery = ReplyDelivery(bot, store.load(), event()['d'], False, 'alice', 'alice', sid,
                                 'user:alice:alice', day, day.stamp(), bot.memory.stamp(sid), [], '测试')
        await delivery.send(REPLY + '\n' + envelope())
        assert ''.join(call.kwargs['json']['content'] for call in bot.api.await_args_list) == REPLY
        assert all('meme_id' not in row['content'] for row in store.db.execute('SELECT content FROM chat_messages'))
    finally:
        await bot.client.aclose()
        store.close()
