import json
import time
from unittest.mock import AsyncMock
import pytest
import pytest_asyncio
import httpx
from app.main import create_app
from app.browser_tasks import BrowsingConfig

VID='1234567890123456789'

@pytest_asyncio.fixture
async def client(tmp_path,monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD','journal-test-password-long')
    app=create_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            c.app=app
            await c.post('/api/login',json={'password':'journal-test-password-long'})
            runtime=app.state.manager.get('default');cfg=runtime.store.load();cfg.qq.app_id='20002';runtime.store.save(cfg)
            app.state.browser_tasks.save_config('default',BrowsingConfig(enabled=True,qq_enabled=True,qq_owner_id='10001'))
            yield c


def seed(client,identifier='journal-one',state='completed',source='web',advanced=12):
    t=client.app.state.browser_tasks;now=time.time()
    steps=[{'op':'watch','reason':'继续看看糖葫芦和烤红薯的秋天约会细节','at':now,
        'current':{'id':VID,'title':'女朋友准备的秋天四件套','author':'校园日常'},
        'watch':{'advancedSeconds':advanced,'samples':[],'coverageRanges':[[0,12]],'fullDuration':28,'partial':True}},
        {'op':'next','reason':'想看看下一条','experience':{'video_id':VID,'reflection':'校园散步时准备小礼物的细节很甜'}}]
    with t.db:t.db.execute('INSERT INTO browser_tasks(id,bot_id,goal,state,origin,created,updated) VALUES (?,?,?,?,?,?,?)',
        (identifier,'default','按自己的兴趣刷视频',state,json.dumps({'source':source,'account_id':'20002','journal_owner_id':'10001'}),now,now))
    t.update(identifier,steps=steps,result='今天刷到校园恋爱短视频，秋天四件套里的糖葫芦和烤红薯挺甜。')
    return t,client.app.state.manager.get('default').bot


@pytest.mark.asyncio
async def test_actual_watch_creates_report_and_background_qq_recall(client):
    t,bot=seed(client)
    item=(await client.get('/api/bots/default/browser/journal/journal-one')).json()
    assert item['videos'][0]['title']=='女朋友准备的秋天四件套'
    assert item['videos'][0]['complete'] is False
    assert item['videos'][0]['url'].endswith(VID)
    assert '小礼物' in item['videos'][0]['impressions'][-1]
    bridge=client.app.state.manager.browser_qq
    assert '糖葫芦' in bridge.experience_context(bot,'10001',False,'今天看了些什么')
    assert bridge.experience_context(bot,'someone')==''
    assert bridge.experience_context(bot,'10001',True)==''
    # Turning off execution does not erase a real experience.
    cfg=t.config('default');cfg.enabled=False;t.save_config('default',cfg)
    assert '秋天四件套' in bridge.experience_context(bot,'10001')
    assert t.journal.recall('other','20002','10001','糖葫芦')==[]
    assert t.journal.recall('default','another-account','10001','糖葫芦')==[]
    assert t.journal.recall('default','20002','new-owner','糖葫芦')==[]


@pytest.mark.asyncio
async def test_no_playback_is_not_an_experience_and_partial_is_preserved(client):
    seed(client,advanced=0)
    assert (await client.get('/api/bots/default/browser/journal')).json()['total']==0


@pytest.mark.asyncio
async def test_forget_invalidates_generation_and_delete_cannot_be_resurrected(client):
    t,bot=seed(client);bridge=client.app.state.manager.browser_qq
    scope=bot.store.scopes.ensure('20002','user','10001','10001')['id'];stamp=bot.memory.stamp(scope)
    path='/api/bots/default/browser/journal/journal-one'
    assert (await client.patch(path,json={'remembered':False})).status_code==200
    assert not bot.memory.matches(scope,stamp)
    assert t.journal.recall('default','20002','10001')==[]
    t.update('journal-one',result='任务随后更新也不能恢复记忆')
    assert not t.journal.get('default','journal-one')['remembered']
    assert (await client.delete(path)).status_code==200
    assert (await client.post('/api/bots/default/browser/journal/backfill',json={})).json()['count']==0
    assert (await client.get(path)).status_code==404
    (await client.post('/api/logout'))
    assert (await client.get('/api/bots/default/browser/journal')).status_code==401


@pytest.mark.asyncio
async def test_live_topic_is_independent_of_qq_origin_and_deduplicated(client):
    t,bot=seed(client,state='running',source='auto');bridge=client.app.state.manager.browser_qq
    topic=bridge.proactive_topic(bot,'10001')
    assert topic['video']['id']==VID and bridge.topic_valid(bot,topic)
    assert bridge.proactive_topic(bot,'stranger') is None
    bridge.topic_sent(bot,topic)
    assert bridge.proactive_topic(bot,'10001') is None
    # The same video in another task is not a new excuse to repeat a message.
    seed(client,'journal-two',state='running')
    assert bridge.proactive_topic(bot,'10001') is None


@pytest.mark.asyncio
async def test_proactive_uses_live_topic_and_never_sends_json(client):
    t,bot=seed(client,state='running')
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps({'reply':'刚看到秋天四件套，烤红薯的细节好甜。','browser_topic':VID})}})
    # Generate only: no external QQ sending occurs in this test or preview.
    from app.proactive import ProactiveService
    service=ProactiveService(bot.store,bot)
    text=await service.generate(bot.store.load(),'10001','随意聊一句')
    assert text=='刚看到秋天四件套，烤红薯的细节好甜。'
    messages=bot.generate.call_args.args[1]
    assert '正在进行的真实浏览任务' in messages[0]['content'] and '糖葫芦' in messages[0]['content']
    assert service._browser_selection['video']['id']==VID
    assert client.app.state.manager.browser_qq.proactive_topic(bot,'10001') is not None


@pytest.mark.asyncio
async def test_report_listing_search_paging_and_memory_flag(client):
    seed(client)
    listing=(await client.get('/api/bots/default/browser/journal',params={'q':'四件套','limit':1})).json()
    assert listing['total']==1 and len(listing['items'])==1
    assert (await client.get('/api/bots/default/browser/journal',params={'offset':1})).json()['items']==[]
    assert (await client.patch('/api/bots/default/browser/journal/journal-one',json={'remembered':'false'})).status_code==422

@pytest.mark.asyncio
async def test_dm_model_and_send_run_without_video_decision_queue(client):
    import asyncio
    t=client.app.state.browser_tasks
    cfg=t.config('default');cfg.interactions.messages_enabled=True;t.save_config('default',cfg)
    t,bot=seed(client,state='running')
    view={'generation':0,'version':1,'account':{'id':'platform-self','verified':True},
        'conversation':{'id':'peer-sec','nickname':'朋友','handle':'friend','follows_me':True},
        'messages':[{'id':'incoming-real-1','direction':'inbound','text':'刚才的视频真有意思'}], 'pendingUnread':[]}
    calls=[];observes=0
    async def gateway(method,path,body):
        nonlocal observes
        calls.append((path,body['op']))
        assert path.endswith('/douyin/dm'), 'DM worker must never touch video action endpoint'
        if body['op']=='observe':
            observes+=1
            if observes>2:raise asyncio.CancelledError()
            return view
        assert body['op']=='reply_dm'
        return {**view,'interaction':{'status':'confirmed','message_id':'outbound-real-1'}}
    t.browser.gateway.request=gateway
    t.model=AsyncMock(return_value='{"reply":"对啊，那个细节挺有趣的。"}')
    main_blocker=asyncio.create_task(asyncio.Event().wait())
    try:
        with pytest.raises(asyncio.CancelledError):await t.dm.run(t.get('default','journal-one'),cfg,'capability')
        assert not main_blocker.done()
        rows=t.interactions.history('default')
        assert len(rows)==1 and rows[0]['op']=='reply_dm' and rows[0]['status']=='confirmed'
        assert t.dm.events('journal-one')[0]['state']=='confirmed'
        assert all('/douyin/dm' in path for path,op in calls)
    finally:
        main_blocker.cancel();await asyncio.gather(main_blocker,return_exceptions=True)


@pytest.mark.asyncio
async def test_dm_accepts_natural_text_from_persona_without_dropping_message(client):
    import asyncio
    t=client.app.state.browser_tasks
    cfg=t.config('default');cfg.interactions.messages_enabled=True;t.save_config('default',cfg)
    t,bot=seed(client,state='running')
    view={'generation':0,'version':1,'account':{'id':'platform-self','verified':True},
        'conversation':{'id':'peer-sec','nickname':'朋友','handle':'friend','follows_me':True},
        'messages':[{'id':'incoming-real-1','direction':'inbound','text':'在吗'}], 'pendingUnread':[]}
    sent=[];observes=0
    async def gateway(method,path,body):
        nonlocal observes
        if body['op']=='observe':
            observes+=1
            if observes>2:raise asyncio.CancelledError()
            return view
        sent.append(body['authorization']['text'])
        return {**view,'interaction':{'status':'confirmed','message_id':'outbound-real-1'}}
    t.browser.gateway.request=gateway
    t.model=AsyncMock(return_value='在呀，刚刚看到你的消息。')
    with pytest.raises(asyncio.CancelledError):await t.dm.run(t.get('default','journal-one'),cfg,'capability')
    assert sent==['在呀，刚刚看到你的消息。']
    assert t.dm.events('journal-one')[0]['state']=='confirmed'


@pytest.mark.asyncio
async def test_dm_replies_once_to_a_batch_even_if_visible_messages_reorder(client):
    import asyncio
    t=client.app.state.browser_tasks
    cfg=t.config('default');cfg.interactions.messages_enabled=True;t.save_config('default',cfg)
    t,bot=seed(client,state='running')
    peer={'id':'peer-sec','nickname':'朋友','handle':'friend','follows_me':True}
    batch=[{'id':'incoming-old-1','direction':'inbound','text':'在吗'},
        {'id':'incoming-old-2','direction':'inbound','text':'睡了吗'},
        {'id':'incoming-latest','direction':'inbound','text':'回我一下'}]
    base={'generation':0,'version':1,'account':{'id':'platform-self','verified':True},'conversation':peer,'pendingUnread':[]}
    observes=0;sent=[]
    async def gateway(method,path,body):
        nonlocal observes
        if body['op']=='observe':
            observes+=1
            if observes<=2:return {**base,'messages':batch}
            if observes==3:return {**base,'messages':batch[:2]}
            raise asyncio.CancelledError()
        sent.append(body['authorization']['message_id'])
        return {**base,'messages':batch,'interaction':{'status':'confirmed','message_id':'outbound-real-1'}}
    t.browser.gateway.request=gateway
    t.model=AsyncMock(return_value='{"reply":"在呀，刚看到你连着发的消息。"}')
    with pytest.raises(asyncio.CancelledError):await t.dm.run(t.get('default','journal-one'),cfg,'capability')
    assert sent==['incoming-latest'] and t.model.await_count==1


@pytest.mark.asyncio
async def test_dm_waits_for_unread_message_to_render_before_treating_chat_as_outbound(client):
    import asyncio
    t=client.app.state.browser_tasks
    cfg=t.config('default');cfg.interactions.messages_enabled=True;t.save_config('default',cfg)
    t,bot=seed(client,state='running')
    peer={'id':'peer-sec','nickname':'朋友','handle':'friend','follows_me':True}
    outbound={'id':'outbound-old','direction':'outbound','text':'晚点聊'}
    inbound={'id':'incoming-after-socket','direction':'inbound','text':'现在有空吗'}
    base={'generation':0,'account':{'id':'platform-self','verified':True},'conversation':peer}
    observes=0;sent=[]
    async def gateway(method,path,body):
        nonlocal observes
        if body['op']=='observe':
            observes+=1
            if observes==1:return {**base,'version':1,'messages':[outbound],'pendingUnread':[peer]}
            if observes==2:return {**base,'version':2,'messages':[outbound,inbound],'pendingUnread':[]}
            if observes==3:return {**base,'version':2,'messages':[outbound,inbound],'pendingUnread':[]}
            raise asyncio.CancelledError()
        if body['op']=='conversation':return {**base,'version':1,'messages':[outbound],'pendingUnread':[]}
        sent.append(body['authorization']['message_id'])
        return {**base,'version':2,'messages':[outbound,inbound], 'pendingUnread':[],
            'interaction':{'status':'confirmed','message_id':'outbound-real-1'}}
    t.browser.gateway.request=gateway
    t.model=AsyncMock(return_value='{"reply":"有空呀，刚看到。"}')
    with pytest.raises(asyncio.CancelledError):await t.dm.run(t.get('default','journal-one'),cfg,'capability')
    assert sent==['incoming-after-socket'] and t.model.await_count==1
    assert not any(item['detail']=='会话最近一条已由当前账号发出，未重复回复' for item in t.dm.events('journal-one'))


@pytest.mark.asyncio
async def test_dm_repairs_malformed_json_and_logs_bounded_diagnostics(client):
    import asyncio
    t=client.app.state.browser_tasks
    cfg=t.config('default');cfg.interactions.messages_enabled=True;t.save_config('default',cfg)
    t,bot=seed(client,state='running')
    view={'generation':0,'version':1,'account':{'id':'platform-self','verified':True},
        'conversation':{'id':'peer-sec','nickname':'朋友','handle':'friend','follows_me':True},
        'messages':[{'id':'incoming-real-1','direction':'inbound','text':'在吗'}], 'pendingUnread':[]}
    sent=[];observes=0
    async def gateway(method,path,body):
        nonlocal observes
        if body['op']=='observe':
            observes+=1
            if observes>2:raise asyncio.CancelledError()
            return view
        sent.append(body['authorization']['text'])
        return {**view,'interaction':{'status':'confirmed','message_id':'outbound-real-1'}}
    t.browser.gateway.request=gateway
    t.model=AsyncMock(side_effect=['```json\n{"reply":"少一个括号"\n```','{"reply":"在呀。"}'])
    with pytest.raises(asyncio.CancelledError):await t.dm.run(t.get('default','journal-one'),cfg,'capability')
    assert sent==['在呀。'] and t.model.await_count==2
    log=next(item for item in bot.store.logs() if item['event']=='browser.dm_format_invalid')
    assert log['details']['stage']=='browser_dm' and '少一个括号' not in json.dumps(log,ensure_ascii=False)


@pytest.mark.asyncio
async def test_dm_keeps_failed_inbound_and_recovers_after_unread_badge_is_gone(client):
    import asyncio
    from app.douyin_interactions import DouyinPerson
    t=client.app.state.browser_tasks
    cfg=t.config('default');cfg.interactions.messages_enabled=True
    cfg.interactions.whitelist=[DouyinPerson(handle='friend',nickname='朋友')];t.save_config('default',cfg)
    t,bot=seed(client,state='running')
    view={'generation':0,'version':1,'account':{'id':'platform-self','verified':True},
        'conversation':{'id':'peer-sec','nickname':'朋友','handle':'friend','follows_me':True},
        'conversations':[{'id':'peer-sec','nickname':'朋友','unread':False}],
        'messages':[{'id':'incoming-real-1','direction':'inbound','text':'在吗'}], 'pendingUnread':[]}
    t.browser.gateway.request=AsyncMock(return_value=view)
    t.model=AsyncMock(return_value='```json\n{"reply":\n```')
    await t.dm.run(t.get('default','journal-one'),cfg,'first-capability')
    assert t.dm.pending(t.get('default','journal-one'),view)[0]['message_id']=='incoming-real-1'

    seed(client,'journal-two',state='running')
    empty={**view,'conversation':None,'messages':[]}
    sent=[];observes=0
    async def gateway(method,path,body):
        nonlocal observes
        if body['op']=='observe':
            observes+=1
            if observes==1:return empty
            if observes>2:raise asyncio.CancelledError()
            return view
        if body['op']=='conversation':return view
        sent.append(body['authorization']['text'])
        return {**view,'interaction':{'status':'confirmed','message_id':'outbound-real-1'}}
    t.browser.gateway.request=gateway;t.model=AsyncMock(return_value='{"reply":"在呀。"}')
    with pytest.raises(asyncio.CancelledError):await t.dm.run(t.get('default','journal-two'),cfg,'second-capability')
    assert sent==['在呀。'] and not t.dm.pending(t.get('default','journal-two'),view)


@pytest.mark.asyncio
async def test_dm_never_treats_unknown_direction_as_already_replied(client):
    import asyncio
    from app.douyin_interactions import DouyinPerson
    t=client.app.state.browser_tasks
    cfg=t.config('default');cfg.interactions.messages_enabled=True
    cfg.interactions.whitelist=[DouyinPerson(handle='friend',nickname='朋友')];t.save_config('default',cfg)
    t,bot=seed(client,state='running')
    view={'generation':0,'version':1,'account':{'id':'platform-self','verified':True},
        'conversation':{'id':'peer-sec','nickname':'朋友','handle':'friend','follows_me':True},
        'conversations':[{'id':'peer-sec','nickname':'朋友','unread':False}],
        'messages':[{'id':'incoming-real-1','direction':'unknown','text':'在吗'}], 'pendingUnread':[]}
    t.dm.remember(t.get('default','journal-one'),view,view['conversation'],view['messages'][0])
    calls=0
    async def gateway(method,path,body):
        nonlocal calls
        calls+=1
        if calls>2:raise asyncio.CancelledError()
        return view
    t.browser.gateway.request=gateway
    with pytest.raises(asyncio.CancelledError):await t.dm.run(t.get('default','journal-one'),cfg,'capability')
    assert t.dm.pending(t.get('default','journal-one'),view)
    assert t.dm.events('journal-one')[0]['detail']=='无法确认会话最近一条消息的发送方向，已保留待处理状态'


@pytest.mark.asyncio
@pytest.mark.parametrize('direction',['inbound','outbound'])
async def test_dm_discards_draft_if_new_message_arrives_during_generation(client,direction):
    import asyncio
    t=client.app.state.browser_tasks
    cfg=t.config('default');cfg.interactions.messages_enabled=True;t.save_config('default',cfg)
    t,bot=seed(client,state='running')
    peer={'id':'peer-sec','nickname':'朋友','handle':'friend','follows_me':True}
    incoming={'id':'incoming-old','direction':'inbound','text':'在吗'}
    base={'generation':0,'version':1,'account':{'id':'platform-self','verified':True},
        'conversation':peer,'pendingUnread':[]}
    observes=0;sent=[]
    async def gateway(method,path,body):
        nonlocal observes
        if body['op']=='observe':
            observes+=1
            if observes==1:return {**base,'messages':[incoming]}
            if observes==2:return {**base,'version':2,'messages':[incoming,
                {'id':'new-message','direction':direction,'text':'更新了'}]}
            raise asyncio.CancelledError()
        sent.append(body)
        return {**base,'interaction':{'status':'confirmed','message_id':'should-not-send'}}
    t.browser.gateway.request=gateway
    t.model=AsyncMock(return_value='{"reply":"在呀。"}')
    with pytest.raises(asyncio.CancelledError):await t.dm.run(t.get('default','journal-one'),cfg,'capability')
    assert sent==[] and t.model.await_count==1
    assert t.dm.pending(t.get('default','journal-one'),base)[0]['message_id']=='incoming-old'
