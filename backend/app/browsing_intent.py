"""Explicit browsing interests and link requests."""
import re


def interest_scope(goal):
    if re.search(r'共同兴趣|兴趣交集|都喜欢|兼顾.{0,8}(?:兴趣|喜好|偏好)|(?:主人|我)(?:与|和)(?:角色|你).{0,4}(?:兴趣|喜好|偏好)',goal):return 'shared'
    if re.search(r'(?:你|她|角色|自己)(?:自己|的)?(?:喜欢|感兴趣|喜好|兴趣|偏好)|按你.{0,4}(?:喜好|兴趣|偏好)',goal):return 'character'
    if re.search(r'我喜欢|我的(?:喜好|兴趣|偏好|口味)|主人(?:的)?(?:喜欢|感兴趣|喜好|兴趣|偏好|口味)|适合(?:我|主人)|推荐给我',goal):return 'owner'
    return 'character'


def explicit_links(goal):
    positive=re.sub(r'(?:不要|不用|不需要|无需|不必|别)(?:再|去)?(?:发|找|收集|复制|获取)?(?:给我|我)?(?:链接|网址|url|links?)', '',goal,flags=re.I)
    return bool(re.search(r'链接|网址|url|\blinks?\b',positive,re.I))
