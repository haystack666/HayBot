import json

import pytest

from app import group_identity
from app.bot import Bot
from app.config import GroupOwner
from app.napcat import normalize_event
from test_debounce import close
from test_group_chat import setup, group_event, idle, model
from test_napcat import configure, message


def bind(store, bot, transport, name='林诗语'):
    if transport=='napcat':configure(store)
    c=store.load();c.group_chat.character_name=name
    c.group_chat.owners=[GroupOwner(account_id=c.account_id,sender_id='owner')]
    c.rules.prompt='你是'+name+'，按原角色语气和主人聊天。'
    store.save(c);bot.platform_name=name;bot.platform_id='official-self';bot.napcat.nickname='诶嘿'
    return c


@pytest.mark.asyncio
@pytest.mark.parametrize('transport',['qq_official','napcat'])
async def test_peer_sends_are_never_current_bots_own_history_even_with_same_name(tmp_path,transport):
    store,bot=setup(tmp_path);c=bind(store,bot,transport)
    own=group_identity.identity(bot,c)['platform_id']
    try:
        p=group_event('peer-said','我刚才说我不是大肥鱼','peer')
        p['d']['author']['nickname']='林诗语'
        bot.capture_incoming(p)
        p=group_event('owner-one','林诗语在吗','owner',at=True);bot.capture_incoming(p)
        store.chat.record(c.account_id,'group','g','assistant','我在，我是林诗语。','own-reply',
                          reply_to=f'in:{c.account_id}:g:owner-one',status='sent')
        latest=store.db.execute('SELECT MAX(id) FROM chat_messages').fetchone()[0]
        messages=bot.group_chat.public_messages(c,'g',latest)
        peer=next(item for item in messages if item['message_id']=='peer-said')
        me=next(item for item in messages if item['role']=='assistant')
        assert peer['speaker']=={'relation':'participant','id':'peer','display_name':'林诗语'}
        assert me['speaker']=={'relation':'self','id':own,'display_name':'林诗语'}
        assert me['reply_to_sender_id']=='owner'
        assert me['addressee']['other_ids']==['owner']
        current=next(item for item in messages if item['message_id']=='owner-one')
        assert current['addressee']['to_self'] is True
    finally:await close(store,bot)


@pytest.mark.asyncio
@pytest.mark.parametrize('transport',['qq_official','napcat'])
async def test_explicit_other_recipient_is_background_not_a_reply_target(tmp_path,transport):
    store,bot=setup(tmp_path);c=bind(store,bot,transport);calls=model(bot)
    try:
        p=group_event('ask-peer','人呢？？？','owner')
        p['d']['mentions']=[{'id':'peer','username':'大肥鱼','bot':True}]
        await bot.receive(p);await idle(bot)
        assert not calls
        bot.api.assert_not_awaited()
        assert store.db.execute('SELECT state FROM group_decisions').fetchone()[0]=='silent'
        assert store.db.execute("SELECT content FROM chat_messages WHERE role='user'").fetchone()[0]=='人呢？？？'
        p=group_event('ask-self','你是林诗语还是大肥鱼？','owner',at=True)
        await bot.receive(p);await idle(bot)
        assert [call[0] for call in calls]==['decision','reply']
        background=calls[0][1]['recent_group_messages']
        other=next(item for item in background if item['message_id']=='ask-peer')
        assert other['addressee']=={'to_self':False,'other_ids':['peer'],'to_all':False}
        assert other['speaker']['relation']=='participant'
        assert calls[0][1]['self']['character_name']=='林诗语'
        current=json.loads(calls[1][1][-1]['content'].split('\n',1)[1])
        assert current['addressee']['to_self'] is True
        assert current['speaker']['id']=='owner'
    finally:await close(store,bot)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['self','both','all'])
async def test_self_and_multiple_mentions_or_all_remain_eligible(tmp_path,kind):
    store,bot=setup(tmp_path);c=bind(store,bot,'qq_official');calls=model(bot,reply=False)
    try:
        p=group_event('one','大家觉得呢')
        p['d']['mentions']=[{'id':uid} for uid in ({'self':['official-self'],'both':['official-self','peer'],'all':['all']}[kind])]
        await bot.receive(p);await idle(bot)
        assert len(calls)==1
        recipient=calls[0][1]['pending_messages'][0]['addressee']
        assert recipient['to_self'] or recipient['to_all']
    finally:await close(store,bot)


@pytest.mark.asyncio
async def test_two_bots_observe_same_group_with_distinct_self_and_peer_attribution(tmp_path):
    sa,a=setup(tmp_path/'a');sb,b=setup(tmp_path/'b')
    ca=bind(sa,a,'qq_official','大肥鱼');cb=bind(sb,b,'napcat','林诗语')
    calls_a=model(a);calls_b=model(b)
    try:
        # Each transport sees the peer through its own platform namespace.
        for store,bot,c,peer,peer_name in [(sa,a,ca,'peer-openid','林诗语'),(sb,b,cb,'20002','大肥鱼')]:
            parent=group_event('parent','人呢','owner');bot.capture_incoming(parent)
            p=group_event('peer','我刚才那套戏演砸了','peer')
            p['d']['author'].update(member_openid=peer,nickname=peer_name);bot.capture_incoming(p)
        await a.receive(group_event('ask-a','你叫什么，刚才那句话是你说的吗','owner',at=True))
        await b.receive(group_event('ask-b','你叫什么，刚才那句话是你说的吗','owner',at=True))
        await idle(a);await idle(b)
        for calls,name,peer_name in [(calls_a,'大肥鱼','林诗语'),(calls_b,'林诗语','大肥鱼')]:
            decision=calls[0][1]
            assert decision['self']['character_name']==name
            peer=next(item for item in decision['recent_group_messages'] if item['message_id']=='peer')
            assert peer['speaker']['display_name']==peer_name
            assert peer['speaker']['relation']=='participant'
            assert not any(item['speaker']['relation']=='self' for item in decision['recent_group_messages'])
            prompt=calls[1][1][0]['content']
            assert f'"character_name": "{name}"' in prompt
            assert '不能认领为自己的经历' in prompt
        assert sa.db.execute("SELECT COUNT(*) FROM chat_messages WHERE platform_id='ask-b'").fetchone()[0]==0
        assert sb.db.execute("SELECT COUNT(*) FROM chat_messages WHERE platform_id='ask-a'").fetchone()[0]==0
    finally:
        await close(sa,a);await close(sb,b)


@pytest.mark.asyncio
async def test_pure_napcat_at_is_received_and_keeps_exact_recipient(tmp_path):
    store,bot=setup(tmp_path);c=bind(store,bot,'napcat');calls=model(bot,reply=False)
    try:
        raw=message(group=True)
        raw['message']=[{'type':'at','data':{'qq':'10001'}}]
        p=normalize_event(raw,c)
        assert p and p['t']=='GROUP_AT_MESSAGE_CREATE'
        await bot.receive(p);await idle(bot)
        assert calls[0][1]['pending_messages'][0]['current_message']=='[仅提及消息，无新增文字]'
        assert calls[0][1]['pending_messages'][0]['addressee']['to_self'] is True
    finally:await close(store,bot)
