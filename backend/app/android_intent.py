"""Task wording distinguishes who chooses content from who is notified."""
import re


def interest_scope(goal):
    if re.search(r'共同兴趣|兴趣交集|都喜欢|兼顾.{0,8}(?:兴趣|喜好|偏好)|(?:主人|我)(?:与|和)(?:角色|你).{0,4}(?:兴趣|喜好|偏好)',goal):return 'shared'
    if re.search(r'(?:你|她|角色|自己)(?:自己|的)?(?:喜欢|感兴趣|喜好|兴趣|偏好)|按你.{0,4}(?:喜好|兴趣|偏好)',goal):return 'character'
    if re.search(r'我喜欢|我的(?:喜好|兴趣|偏好|口味)|主人(?:的)?(?:喜欢|感兴趣|喜好|兴趣|偏好|口味)|适合(?:我|主人)|推荐给我',goal):return 'owner'
    return 'character'


def video_mention_delivery(goal):
    return bool(re.search(r'视频|哔哩哔哩|bilibili|b站',goal,re.I) and re.search(r'(?:@|艾特|提及)\s*(?:我|主人|owner)|分享给?(?:我|主人)|给(?:我|主人)分享',goal,re.I) and not explicit_links(goal))


def explicit_links(goal):
    positive=re.sub(r'(?:不要|不用|不需要|无需|不必|别)(?:再|去)?(?:发|找|收集|复制|获取)?(?:给我|我)?(?:链接|网址|url|links?)', '',goal,flags=re.I)
    return bool(re.search(r'链接|网址|url|\blinks?\b',positive,re.I))


def wants_links(goal):
    if video_mention_delivery(goal):return False
    return explicit_links(goal) or bool(re.search(r'分享',goal) and not re.search(r'视频|哔哩哔哩|bilibili|b站',goal,re.I))


def intent_error(goal,decision):
    social=decision.get('social') or {}
    action=decision.get('action') or {}
    if re.search(r'(?:不要|不用|不许|禁止)(?:再|去)?(?:打开|使用|启动)?(?:浏览器|Chrome)',goal,re.I) and (action.get('kind')=='open' or action.get('kind')=='launch' and action.get('app')=='chrome'):
        return '本次明确禁止打开浏览器，请在原应用内完成任务'
    comment_scope=re.sub(r'(?:以前|已经|曾经|已).{0,10}(?:评论过|发表过评论).{0,12}(?:不要|别|禁止)(?:再|重复)(?:发|发表|发送|发布)?评论','',goal)
    if re.search(r'(?:不要|不用|无需|禁止|不许)(?:再|自行|自动|发表|发送|发布|任何){0,3}评论',comment_scope) and social.get('kind') in ('draft','publish'):
        return '本次明确禁止发表评论，只能浏览和观看，不得创建或发布评论草稿'
    plan=' '.join((decision.get('plan') or {}).get('milestones',[]))
    if interest_scope(goal)=='character' and re.search(r'主人(?:的|与角色|和角色)?(?:兴趣|喜好|偏好)|主人的?与角色.{0,3}(?:兴趣|喜好|偏好)',plan):
        return '本次按角色自己的兴趣选片，@或分享给主人只是通知方式；请重写计划，不把主人偏好混入选片标准'
    if video_mention_delivery(goal):
        if re.search(r'(?:复制|获取|收集|整理|发送|分享|发给).{0,8}(?:链接|网址)|分享面板',plan):
            return '本次分享给我表示在视频评论区真实@主人；未要求链接，不得制定收集链接或打开分享面板的计划'
        action=decision.get('action') or {}
        if action.get('kind')=='open' or action.get('kind')=='launch' and action.get('app')=='chrome':
            return '本次分享通过视频评论区@主人完成，不需要浏览器或打开链接'
        social=decision.get('social') or {}
        if social.get('kind')=='draft' and not social.get('mention'):
            return '本次需要真实@主人，请使用mention:true的评论草稿'
    return ''
