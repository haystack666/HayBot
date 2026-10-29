import sqlite3
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.browser_tasks import BrowseDecision
from app.douyin_interactions import InteractionConfig, InteractionLedger


@pytest.fixture
def ledger(tmp_path):
    db=sqlite3.connect(tmp_path/'policy.sqlite3');db.row_factory=sqlite3.Row
    return InteractionLedger(db)


def cfg(**kwargs):
    return InteractionConfig(comments_enabled=True,replies_enabled=True,likes_enabled=True,messages_enabled=True,shares_enabled=True,
        owner={'handle':'owner','nickname':'主人'},deepseek_probability=100,other_probability=100,**kwargs)


def decision(op='comment',**kwargs):
    return BrowseDecision(op=op,reason='实际内容值得回应',text='这段解释很清楚',**{'id':'1234567890123',**kwargs})


def observation(**kwargs):
    return {'account':{'id':'self-sec','verified':True},'current':{'id':'1234567890123','title':'猫咪'},'watched':True,
        'owner':{'id':'owner-sec','handle':'owner','nickname':'主人'},**kwargs}


def reserve(ledger,op=None,obs=None,config=None,task='first',bot='one'):
    return ledger.reserve({'id':task,'bot_id':bot},op or decision(),obs or observation(),config or cfg())


def test_daily_account_quota_crosses_bots_and_unknown_prevents_replay(ledger):
    first=reserve(ledger,config=cfg(comment_daily_limit=1))
    ledger.settle(first['operation_id'],{'status':'unknown'})
    assert ledger.availability('self-sec','next',cfg(comment_daily_limit=1))['comments_remaining']==0
    with pytest.raises(HTTPException):reserve(ledger,task='second',bot='two')
    nextobs=observation(current={'id':'2234567890123','title':'新视频'})
    with pytest.raises(HTTPException):reserve(ledger,decision(id='2234567890123'),nextobs,cfg(comment_daily_limit=1),task='second',bot='two')
    # A different signed-in Douyin account has its own quota.
    reserve(ledger,obs=observation(account={'id':'another','verified':True}),config=cfg(comment_daily_limit=1),bot='two')


def test_probability_cannot_be_rerolled_and_other_topics_are_allowed(ledger):
    denied=InteractionConfig(deepseek_probability=100,other_probability=0)
    assert not ledger.opportunity('self','video','猫咪',denied)['allowed']
    assert not ledger.opportunity('self','video','DeepSeek',denied)['allowed']
    assert ledger.opportunity('self','ds','DeepSeek 最新模型',denied)['allowed']
    assert ledger.opportunity('self','other','猫咪',cfg())['allowed']


def test_only_incoming_followers_or_exact_whitelist_can_receive_replies(ledger):
    op=decision('reply_dm',peer_id='peer',message_id='incoming-1')
    peer={'id':'peer','handle':'friend','nickname':'同名','follows_me':False}
    obs=observation(conversation=peer,messages=[{'id':'incoming-1','direction':'inbound'}])
    with pytest.raises(HTTPException):reserve(ledger,op,obs)
    peer['follows_me']=True
    first=reserve(ledger,op,obs,cfg(dm_total_limit=1));ledger.settle(first['operation_id'],{'status':'confirmed'})
    peer2={'id':'peer2','handle':'stranger','nickname':'其他人','follows_me':True}
    obs2=observation(conversation=peer2,messages=[{'id':'incoming-2','direction':'inbound'}])
    with pytest.raises(HTTPException):reserve(ledger,decision('reply_dm',peer_id='peer2',message_id='incoming-2'),obs2,cfg(dm_total_limit=1))
    white=cfg(dm_total_limit=0,whitelist=[{'handle':'friend','nickname':'同名'}])
    peer['follows_me']=False
    obs['messages']=[{'id':'incoming-3','direction':'inbound'}]
    reserve(ledger,decision('reply_dm',peer_id='peer',message_id='incoming-3'),obs,white)
    obs['messages']=[]
    with pytest.raises(HTTPException):reserve(ledger,op,obs,white)
    obs['messages']=[{'id':'incoming-4','direction':'inbound'}];peer['handle']='impersonator'
    with pytest.raises(HTTPException):reserve(ledger,decision('reply_dm',peer_id='peer',message_id='incoming-4'),obs,white)


def test_reply_requires_own_confirmed_parent_and_separate_quota(ledger):
    first=reserve(ledger,config=cfg(comment_daily_limit=1))
    ledger.settle(first['operation_id'],{'status':'confirmed','cid':'own-comment'})
    obs=observation(comments=[{'id':'reply-from-person','video_id':'1234567890123','parent_id':'own-comment','author_id':'other'}])
    reserve(ledger,decision('reply_comment',comment_id='reply-from-person'),obs,cfg(comment_daily_limit=1,reply_daily_limit=1))
    obs['comments']=[{'id':'random-comment','parent_id':'stranger-comment','author_id':'other'}]
    with pytest.raises(HTTPException):reserve(ledger,decision('reply_comment',comment_id='random-comment'),obs)


def test_owner_share_identity_draft_and_like_has_no_quota(ledger):
    with pytest.raises(HTTPException):reserve(ledger,decision('share'),observation(owner={'id':'evil','handle':'evil','nickname':'主人'}))
    with pytest.raises(HTTPException):reserve(ledger,decision('like'),observation(watched=False))
    for n in range(15):
        video=str(1234567890123+n)
        reserve(ledger,decision('like',id=video),observation(current={'id':video,'title':'猫'}),cfg(comment_daily_limit=0))
    with pytest.raises(ValueError):InteractionConfig(whitelist=[{'handle':'same','nickname':'一'},{'handle':'same','nickname':'二'}])


def test_owner_share_accepts_one_text_and_one_sticker_and_recovers_pending(ledger):
    first=reserve(ledger,decision('share'))
    ledger.settle(first['operation_id'],{'status':'confirmed','message_id':'share-card','video_id':'1234567890123'})
    obs=observation(conversation={'id':'owner-sec'})
    reserve(ledger,decision('share_note'),obs)
    reserve(ledger,BrowseDecision(op='share_note',reason='配图',sticker='好耶'),obs)
    with pytest.raises(HTTPException):reserve(ledger,decision('share_note'),obs)
    second=InteractionLedger(ledger.db)
    assert second.count('self-sec','share_note')==2
    statuses={r[0] for r in ledger.db.execute("SELECT status FROM douyin_operations WHERE op='share_note'")}
    assert statuses=={'unknown'}


def test_disabled_missing_identity_and_unwatched_actions_never_reserve(ledger):
    for obs, config in [(observation(),InteractionConfig()),(observation(account={'id':'self-sec','verified':False}),cfg()),(observation(watched=False),cfg())]:
        with pytest.raises(HTTPException):reserve(ledger,obs=obs,config=config)
    assert ledger.count('self-sec','comment')==0


def test_inbox_interval_defaults_and_strict_bounds():
    from pydantic import ValidationError
    assert InteractionConfig().dm_check_interval_seconds == 5
    for value in (0,3601,1.5,'5',True):
        with pytest.raises(ValidationError):
            InteractionConfig(dm_check_interval_seconds=value)
    assert InteractionConfig(dm_check_interval_seconds=1).dm_check_interval_seconds == 1
