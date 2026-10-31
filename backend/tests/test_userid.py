from unittest.mock import AsyncMock

import pytest
from app.bot import Bot
from app.store import Store


@pytest.mark.asyncio
@pytest.mark.parametrize('transport', ['qq_official', 'napcat'])
@pytest.mark.parametrize('group', [False, True])
async def test_userid_returns_actual_sender_without_llm_and_deduplicates(tmp_path,transport,group):
    store=Store(tmp_path);c=store.load();c.transport=transport;c.qq.app_id='111';c.qq.group_reply=True
    c.napcat.self_id='22222';c.napcat.ws_url='ws://test';store.save(c)
    bot=Bot(store);bot.generate=AsyncMock();bot.send_schedule_text=AsyncMock()
    user='123456789' if transport=='napcat' else 'sender-openid'
    data={'id':'userid-test','content':'/userid','author':{'member_openid' if group else 'user_openid':user}}
    if group:data['group_openid']='987654321' if transport=='napcat' else 'group-openid'
    event={'t':'GROUP_AT_MESSAGE_CREATE' if group else 'C2C_MESSAGE_CREATE','d':data}
    try:
        assert bot.is_command('/userid')
        await bot.handle(event);await bot.handle(event)
        bot.send_schedule_text.assert_awaited_once()
        sent=bot.send_schedule_text.call_args.args
        assert sent[0]==f"你的{'QQ 号' if transport=='napcat' else '群成员 OpenID' if group else 'OpenID'}：{user}"
        assert sent[4]==(data['group_openid'] if group else user)
        bot.generate.assert_not_awaited()
    finally:
        await bot.client.aclose();store.close()
