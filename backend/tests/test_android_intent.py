import pytest
from app.android_intent import interest_scope,video_mention_delivery,wants_links,intent_error
from app.android_companion import CompanionConfig,interest_material

@pytest.mark.parametrize('goal',[
    '再试一下宝贝，这次看你喜欢的视频，记得@我哦',
    '再试一下宝贝，这次看你喜欢的视频，记得分享给我哦',
    '打开哔哩哔哩挑选一个喜欢的视频，并在评论区@主人',
    'B站找你喜欢的视频，然后艾特主人',
    '看你感兴趣的视频，提及主人',
])
def test_own_choice_with_owner_notification(goal):
    assert interest_scope(goal)=='character'
    assert video_mention_delivery(goal)
    assert not wants_links(goal)
    cfg=CompanionConfig(owner_interests='足球',public_persona='简短')
    assert interest_material(cfg,'喜欢数码',goal)==''
    assert intent_error(goal,{'plan':{'milestones':['根据主人与角色兴趣比较视频']}})
    assert intent_error(goal,{'plan':{'milestones':['获取分享链接并发送给主人']}})
    assert intent_error(goal,{'social':{'kind':'draft','mention':False}})
    assert not intent_error(goal,{'plan':{'milestones':['按角色自己的兴趣比较视频','评论区真实@主人']}})

@pytest.mark.parametrize('goal',[
    '这次看你喜欢的视频，把链接发我',
    '看你喜欢的视频，复制链接发给我',
    '浏览酷安动态整理分享链接发给主人',
])
def test_only_explicit_link_request_collects_video_links(goal):
    assert wants_links(goal)
    assert not video_mention_delivery(goal)


def test_owner_and_shared_interest_are_explicit_not_implied_by_at():
    cfg=CompanionConfig(owner_interests='足球',character_interest_mode='custom',character_interests='数码')
    owner='按我的喜好找视频，记得@我'
    assert interest_scope(owner)=='owner'
    assert interest_material(cfg,'游戏',owner)=='足球'
    assert interest_material(cfg,'游戏','看你喜欢的视频并分享给我')=='数码'
    assert set(interest_material(cfg,'游戏','找我们都喜欢的视频').splitlines())=={'数码','足球'}
    assert not wants_links('看你喜欢的视频，不用发链接，@我就好')
    assert not wants_links('B站看你喜欢的视频分享给我，不需要链接')
    assert not wants_links('B站查看BV，不需要链接')
    assert intent_error('B站查看BV，不要打开浏览器',{'action':{'kind':'launch','app':'chrome'}})


def test_interest_reference_resolves_only_current_interest_source():
    from app.android_companion import interest_options,resolve_interest_basis
    material='喜欢数码。喜欢音乐；喜欢动画'
    assert interest_options(material)=={'兴趣1':'喜欢数码','兴趣2':'喜欢音乐','兴趣3':'喜欢动画'}
    assert resolve_interest_basis('兴趣2',material)=='喜欢音乐'
    assert resolve_interest_basis('音乐',material)=='音乐'
    assert not resolve_interest_basis('优先选择原创、信息清楚、有实际演示或具体依据的内容。',material)
    assert not resolve_interest_basis('兴趣4',material)
    assert resolve_interest_basis('本次探索','')=='本次探索'


def test_legacy_persona_mode_never_derives_character_interests():
    cfg=CompanionConfig(character_interest_mode='persona',public_persona='喜欢电影',owner_interests='足球')
    assert interest_material(cfg,'喜欢数码','看你喜欢的视频')==''
    cfg.character_interests='用户填写的音乐兴趣'
    assert interest_material(cfg,'喜欢数码','看你喜欢的视频')=='用户填写的音乐兴趣'


@pytest.mark.parametrize('goal',['只浏览，不要发表评论','看看视频，禁止评论','不用发送评论'])
def test_browse_only_goal_rejects_comment_creation_and_publication(goal):
    assert intent_error(goal,{'social':{'kind':'draft','platform':'bilibili'}})
    assert intent_error(goal,{'social':{'kind':'publish','platform':'bilibili'}})
    assert not intent_error(goal,{'watch':{'frames':3,'interval_seconds':1}})


def test_duplicate_comment_prohibition_does_not_ban_commenting_on_new_videos():
    goal='看你喜欢的视频分享给我，以前评论过的视频不要再评论'
    assert not intent_error(goal,{'social':{'kind':'draft','platform':'bilibili','mention':True}})
    assert intent_error('这条已经发过评论，本次禁止再发表评论',{'social':{'kind':'draft','platform':'bilibili'}})
