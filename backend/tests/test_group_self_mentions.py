"""Regression cases from official full-stream @ events, with sends mocked."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app import group_identity
from app.group_chat import explicitly_addressed
from test_debounce import close
from test_group_chat import setup, group_event, idle, model
from test_group_identity import bind

SELF = 'F490F2C0CB48216CAE26DA912CF1051B'
PEER = '191636581A519983B8A9E62710706BD2'


def full_mention(mid='one', uid=SELF, group='g', text='吃中午饭没'):
    p=group_event(mid, '<@'+uid+'> '+text, 'owner', group)
    p['d']['mentions']=[{'id':uid,'member_openid':uid,'username':'大肥鱼','bot':True}]
    return p


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['mentions','natural','quiet'])
async def test_full_event_uses_bot_state_member_id_in_all_reply_paths(tmp_path,mode):
    store,bot=setup(tmp_path);c=bind(store,bot,'qq_official','大肥鱼')
    c.group_chat.mode=mode;store.save(c)
    bot.platform_id='12083135328495717232'
    bot.group_identity.fetch=AsyncMock(return_value={'member_openid':SELF})
    calls=model(bot)
    try:
        await bot.receive(full_mention());await idle(bot)
        bot.group_identity.fetch.assert_awaited_once_with('g')
        assert bot.api.await_count==1
        archive=json.loads(store.db.execute("SELECT participant_context FROM chat_messages WHERE role='user'").fetchone()[0])
        assert archive['addressed_to_self'] is True
        prompt=next(call[1][0]['content'] for call in calls if call[0]=='reply')
        assert '"directly_addressed_to_self": true' in prompt
        assert '"platform_id": "'+SELF+'"' in prompt
        if mode!='mentions':
            item=calls[0][1]['pending_messages'][0]
            assert item['addressed_to_bot'] and item['addressee']=={'to_self':True,'other_ids':[],'to_all':False}
        await bot.receive(full_mention('two'));await idle(bot)
        assert bot.api.await_count==2 and bot.group_identity.fetch.await_count==1
    finally:await close(store,bot)


@pytest.mark.asyncio
async def test_same_name_peer_bot_is_not_self_and_cache_is_group_account_scoped(tmp_path):
    store,bot=setup(tmp_path);c=bind(store,bot,'qq_official','大肥鱼');calls=model(bot)
    bot.group_identity.fetch=AsyncMock(side_effect=[{'member_openid':SELF},{'member_openid':'other-group-self'},{'member_openid':'other-account-self'}])
    try:
        await bot.receive(full_mention(uid=PEER));await idle(bot)
        assert not calls
        bot.api.assert_not_awaited()
        assert explicitly_addressed(full_mention(),bot,c)
        await bot.group_identity.resolve(full_mention(group='other'),c)
        assert not explicitly_addressed(full_mention(group='other'),bot,c)
        c.qq.app_id='222';store.save(c)
        assert not explicitly_addressed(full_mention(),bot,c)
        await bot.group_identity.resolve(full_mention(),c)
        assert not explicitly_addressed(full_mention(),bot,c)
        assert bot.group_identity.fetch.await_count==3
    finally:await close(store,bot)


@pytest.mark.asyncio
async def test_lookup_failure_does_not_guess_from_nickname_bot_flag_or_spam_api(tmp_path):
    store,bot=setup(tmp_path);c=bind(store,bot,'qq_official','大肥鱼');calls=model(bot)
    bot.group_identity.fetch=AsyncMock(side_effect=ValueError('no permission'))
    try:
        for mid in ('one','two'):
            await bot.receive(full_mention(mid));await idle(bot)
        assert not calls
        assert bot.group_identity.fetch.await_count==1
        assert not explicitly_addressed(full_mention(),bot,c)
        key=(c.account_id,'g');bot.group_identity.cache[key]['retry_at']=0
        bot.group_identity.fetch=AsyncMock(return_value={'member_openid':SELF})
        await bot.receive(full_mention('three'));await idle(bot)
        assert bot.api.await_count==1
    finally:await close(store,bot)


@pytest.mark.asyncio
async def test_full_self_at_bypasses_unsolicited_limit_and_long_cooldown(tmp_path):
    store,bot=setup(tmp_path);c=bind(store,bot,'qq_official','大肥鱼');calls=model(bot)
    c.group_chat.max_replies_per_hour=1;c.group_chat.cooldown_seconds=600;c.rules.cooldown=0;store.save(c)
    bot.group_identity.fetch=AsyncMock(return_value={'member_openid':SELF})
    bot.group_chat.log(c,'g','sent','prior')
    try:
        await bot.receive(full_mention());await idle(bot)
        assert [call[0] for call in calls]==['decision','reply']
        assert bot.api.await_count==1
    finally:await close(store,bot)


@pytest.mark.asyncio
async def test_full_self_at_and_legacy_at_duplicate_send_once(tmp_path):
    store,bot=setup(tmp_path);bind(store,bot,'qq_official','大肥鱼');model(bot)
    bot.group_identity.fetch=AsyncMock(return_value={'member_openid':SELF})
    try:
        p=full_mention();await bot.receive(p)
        await bot.receive({**p,'t':'GROUP_AT_MESSAGE_CREATE'});await idle(bot)
        assert bot.api.await_count==1
        assert store.db.execute('SELECT COUNT(*) FROM group_inbox').fetchone()[0]==1
    finally:await close(store,bot)


@pytest.mark.asyncio
async def test_long_official_id_is_selected_through_short_local_alias(tmp_path):
    store,bot=setup(tmp_path);calls=model(bot);mid='official-platform-id-'+'x'*220
    try:
        await bot.receive(group_event(mid,at=True));await idle(bot)
        alias=calls[0][1]['pending_messages'][0]['message_id']
        assert len(alias)<32 and alias!=mid
        assert bot.api.await_args.kwargs['json']['msg_id']==mid
        assert store.db.execute("SELECT reason FROM group_decisions WHERE state='sent'").fetchone()
    finally:await close(store,bot)


@pytest.mark.asyncio
@pytest.mark.parametrize('broken',['', '我来判断一下', '{"reply":true,"reason":"还没说完'])
async def test_bad_decision_retried_once_and_only_complete_valid_choice_can_send(tmp_path,broken):
    store,bot=setup(tmp_path);calls=model(bot);original=bot.generate.side_effect;attempt=0
    async def generate(selection,messages,*args,**kwargs):
        nonlocal attempt
        if '先判断现在是否值得开口' in messages[0]['content']:
            attempt+=1
            if attempt==1:return {'message':{'content':broken}}
        return await original(selection,messages,*args,**kwargs)
    bot.generate.side_effect=generate
    try:
        await bot.receive(group_event(at=True));await idle(bot)
        assert attempt==2 and bot.api.await_count==1
        assert store.db.execute("SELECT COUNT(*) FROM logs WHERE event='group.decision_retry'").fetchone()[0]==1
    finally:await close(store,bot)


@pytest.mark.parametrize('transport',['qq_official','napcat'])
def test_public_relationship_is_explicit_account_bound_and_never_changes_member_to_owner(tmp_path,transport):
    # This test does not start async jobs; close the HTTP client via asyncio.run.
    store,bot=setup(tmp_path);c=bind(store,bot,transport,'林诗语')
    c.group_chat.owner_relationship='Owner 是我的男朋友，我是他的女朋友。'
    try:
        member=group_event(user='member')['d']
        assert group_identity.speaker(c,member)=='member'
        prompt=group_identity.persona(c,member)+group_identity.context(bot,c,member,True)
        assert 'Owner 是我的男朋友' in prompt
        assert '"reply_to_role": "member"' in prompt
        assert '原角色语气和主人聊天' not in prompt
        assert '不因使用公开人格就否认' in prompt
        assert group_identity.owner_facts(c)['owner_id']=='owner'
        c.group_chat.owners=[]
        assert group_identity.owner_facts(c)=={'owner_id':'','relationship':''}
    finally:
        asyncio.run(bot.client.aclose());store.close()


@pytest.mark.asyncio
async def test_real_gateway_full_event_resolves_group_member_before_routing(tmp_path):
    from websockets.asyncio.server import serve
    store,bot=setup(tmp_path);calls=model(bot)
    c=store.load();c.group_chat.mode='mentions';store.save(c)
    bot.group_identity.fetch=group_identity.GroupSelfIdentity.fetch.__get__(bot.group_identity)
    async def gateway(ws):
        await ws.send(json.dumps({'op':10,'d':{'heartbeat_interval':1000}}));await ws.recv()
        await ws.send(json.dumps({'op':0,'t':'READY','s':1,'d':{'session_id':'fixture','user':{'id':'12083135328495717232','username':'大肥鱼'}}}))
        await ws.send(json.dumps({'op':0,'s':2,**full_mention()}));await ws.wait_closed()
    try:
        async with serve(gateway,'127.0.0.1',0) as server:
            async def api(method,path,**kwargs):
                if path=='/gateway':return {'url':'ws://127.0.0.1:'+str(server.sockets[0].getsockname()[1])}
                if path=='/v2/groups/g/bot_state':return {'member_openid':SELF}
                return {'id':'sent'}
            bot.api=AsyncMock(side_effect=api);bot.access_token=AsyncMock(return_value='fixture-token')
            bot.task=asyncio.create_task(bot.run())
            async with asyncio.timeout(3):
                while not any(call[0]=='reply' for call in calls):await asyncio.sleep(.01)
            await idle(bot)
            assert any(call.args==('GET','/v2/groups/g/bot_state') for call in bot.api.await_args_list)
            assert sum(call.args==('POST','/v2/groups/g/messages') for call in bot.api.await_args_list)==1
            assert bot.platform_id=='12083135328495717232'
            assert bot.group_identity.member_id(c,'g')==SELF
    finally:await close(store,bot)


@pytest.mark.asyncio
async def test_owner_public_name_comes_only_from_bound_id_in_same_group_and_account(tmp_path):
    store,bot=setup(tmp_path);c=bind(store,bot,'qq_official')
    c.group_chat.owner_relationship='Owner 是我的男朋友。'
    try:
        for app,target,user,name in [(c.account_id,'g','owner','Haystack'),
                (c.account_id,'g','stranger','假的主人'),(c.account_id,'other','owner','别群名字'),
                ('different-app','g','owner','别账号名字')]:
            store.chat.record(app,'group',target,'user','公开消息','name-'+app+target+user,
                sender_id=user,sender_name=name,source='incoming',status='received')
        facts=group_identity.owner_facts(c,bot,'g')
        assert facts=={'owner_id':'owner','relationship':'Owner 是我的男朋友。','display_name':'Haystack'}
        assert 'display_name' not in group_identity.owner_facts(c,bot,'unknown')
    finally:await close(store,bot)
