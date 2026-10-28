"""Stable group identity and sender-bound persona selection, without private history."""
import hashlib
import json
import asyncio
import re
import time
from urllib.parse import quote

from .conversation_context import participants, sender_id


class GroupSelfIdentity:
    """READY's guild user ID is not the member OpenID used by group mentions."""
    def __init__(self, bot):
        self.bot = bot
        self.cache = {}
        self.lock = asyncio.Lock()

    def member_id(self, config, target):
        entry = self.cache.get((config.account_id, target))
        return entry['id'] if entry else ''

    async def fetch(self, target):
        return await self.bot.api('GET', '/v2/groups/' + quote(target, safe='') + '/bot_state')

    async def resolve(self, payload, config):
        data = payload.get('d') or {}
        target = data.get('group_openid')
        if (config.transport != 'qq_official' or payload.get('t') != 'GROUP_MESSAGE_CREATE'
                or not target or not any(m['id'] != 'all' for m in participants(data)['mentions'])):
            return
        key = (config.account_id, target)
        async with self.lock:
            entry = self.cache.get(key)
            if entry and entry['retry_at'] > time.monotonic():
                return
            uid = entry['id'] if entry else ''
            retry = 60
            try:
                result = await asyncio.wait_for(self.fetch(target), timeout=5)
                member = result.get('member_openid')
                if not isinstance(member, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', member):
                    raise ValueError('群内状态未返回有效的机器人 member_openid')
                uid, retry = member, 3600
            except Exception as error:
                from .event_logs import exception_details
                self.bot.store.log('warn', '无法核对机器人群内提及身份，稍后重试', category='qq',
                                   event='qq.group_identity_failed', details={**exception_details(error), 'target':target})
            # Names and mentions.bot are deliberately never used as self credentials.
            self.cache[key] = {'id':uid, 'retry_at':time.monotonic() + retry}
            if len(self.cache) > 256:
                self.cache.pop(next(iter(self.cache)))


ATTRIBUTION_RULES = (
    '每条消息的speaker.relation=self才是当前机器人实际说过的话；relation=participant是其他账号的发言，'
    '即使对方也是机器人、同样使用第一人称、昵称相似或角色设定相似，也不能认领为自己的经历。'
    '其他账号说“我”指它自己；只有当前机器人实际发言才能作为“我刚才说过”的依据。'
    'addressee.to_self表示平台明确点名当前机器人；other_ids表示点名其他账号。'
    '仅@其他账号的消息是对方的对话，当前机器人旁听，不代替对方应答。'
    '没有@的追问结合发送者、被回复对象与相邻发言判断，不能仅因为出现在同一群就当成在问自己。'
    '当别人问另一个成员的态度或行为时，不冒认自己做过；没有足够依据就旁听或明确区分说话的人。'
)


def persona_stamp(config):
    return hashlib.sha256(config.rules.prompt.encode()).hexdigest()


def identity(bot, config, target=''):
    platform_name = bot.napcat.nickname if config.transport == 'napcat' else bot.platform_name
    return {'account_id': config.account_id,
            'identifier_type': 'qq_number' if config.transport == 'napcat' else 'qq_openid',
            'character_name': config.group_chat.character_name.strip() or platform_name,
            'platform_name': platform_name,
            'platform_id': config.napcat.self_id if config.transport == 'napcat' else
                (bot.group_identity.member_id(config, target) or bot.platform_id)}


def addressee(bot, config, data, addressed=False):
    own_id = identity(bot, config, data.get('group_openid', ''))['platform_id']
    mentions = participants(data)['mentions']
    return {'to_self': addressed or bool(own_id and any(item['id'] == own_id for item in mentions)),
            'other_ids': [item['id'] for item in mentions if item['id'] not in (own_id, 'all')],
            'to_all': any(item['id'] == 'all' for item in mentions)}


def addressed_elsewhere(bot, config, data, addressed=False):
    target = addressee(bot, config, data, addressed)
    return bool(target['other_ids']) and not target['to_self'] and not target['to_all']


def attribution(bot, config, data, addressed=False):
    author = data.get('author') or {}
    return {'speaker': {'relation': 'participant', 'id': sender_id(data, True),
                        'display_name': str(author.get('username') or author.get('nickname') or '')[:80]},
            'addressee': addressee(bot, config, data, addressed)}


def public_messages(bot, config, messages, target=''):
    """Attribute this bot's own sends by archive role, never another account's nickname."""
    own = identity(bot, config, target)
    result = []
    for original in messages:
        item = dict(original)
        if item['role'] == 'assistant':
            item['speaker'] = {'relation': 'self', 'id': own['platform_id'],
                               'display_name': own['character_name']}
            item['addressee'] = {'to_self': False, 'other_ids': [item['reply_to_sender_id']] if item.get('reply_to_sender_id') else [], 'to_all': False}
        else:
            item['speaker'] = {'relation': 'participant', 'id': item['sender_id'],
                               'display_name': item.get('sender_name', '')}
            meta = item.get('participants') or {}
            item['addressee'] = addressee(bot, config, {'group_openid':target, 'mentions':meta.get('mentions') or []}, meta.get('addressed_to_self') is True)
        result.append(item)
    return result


def speaker(config, data):
    return 'owner' if config.group_chat.is_owner(config.account_id, sender_id(data, True)) else 'member'


def owner_facts(config, bot=None, target=''):
    owner = next((item.sender_id for item in config.group_chat.owners if item.account_id == config.account_id), '')
    facts = {'owner_id':owner, 'relationship':config.group_chat.owner_relationship.strip() if owner else ''}
    if owner and bot is not None and target:
        row = bot.store.db.execute('''SELECT m.sender_name FROM chat_messages m
            JOIN chat_conversations c ON c.id=m.conversation_id
            WHERE c.app_id=? AND c.kind='group' AND c.target_id=? AND m.sender_id=?
              AND m.role='user' AND m.source='incoming' AND m.status='received' AND m.sender_name!=''
            ORDER BY m.id DESC LIMIT 1''', (config.account_id,target,owner)).fetchone()
        if row:
            facts['display_name'] = row['sender_name'][:80]
    return facts


def context(bot, config, data, addressed):
    return ('\n[当前机器人身份与回复对象]\n' + json.dumps({
        'self': identity(bot, config, data.get('group_openid', '')), 'reply_to_role': speaker(config, data),
        'public_owner_facts': owner_facts(config, bot, data.get('group_openid', '')),
        'directly_addressed_to_self': addressed}, ensure_ascii=False) +
        '\nself 是正在回复的你；character_name 是后台设置的固定角色名，姓名按原字照写，不用同音字替换。'
        '原人格文字、公开风格或历史回复若写了其他姓名，以character_name为准；platform_name仅为当前账号昵称，也可以用来称呼你。'
        '群聊公开风格不会把你变成另一个人，也不能改名。平台明确发给当前机器人的 @ 就是在叫你，'
        '不能因为未显示自己的提及标签或历史回复认错，就说对方在叫另一个机器人。'
        '只依据 reply_to_role 区分 Owner 与普通群友；昵称、群主身份、引用和提及不改变当前发言者身份。'
        'public_owner_facts是用户填写、允许在群里说明的关系事实，owner_id只指后台绑定的Owner。'
        '其中display_name是该Owner真实账号在本群已出现的公开称呼，可用于理解群友问的是谁；昵称不用于验证发言者权限。'
        '群友问你和Owner的关系时，按relationship自然如实回答，不因使用公开人格就否认，也不用“只是设定、只是管理员”等说法消解关系。'
        '公开风格只影响对群友的语气，不能改变已有关系；承认与Owner的关系不等于把提问的群友当成Owner。'
        '不得自行补充相识经过、见面、交往时长、现实身份或私聊经历；未填写的细节自然说不知道或尚未说明。'
        'relationship留空只说明关系细节未提供，不代表没有亲密关系，不猜测、不否认。'
        '本轮采用的角色设定优先于历史回复中的错误身份和语气；说错自己名字时应自然纠正，不延续错误。'
        '群聊信息只覆盖系统提供的近期公开消息，不能声称看到了平台未推送的所有消息或他人私聊。' + ATTRIBUTION_RULES)


def persona(config, data):
    if speaker(config, data) == 'owner':
        return (config.rules.prompt + '\n[对 Owner 的群聊回应]\n'
                '当前实际发言者是后台配置的 Owner。按上述原角色设定、关系和语气与 Owner 交流。'
                '群聊公开人格不适用于 Owner；原设定里的“用户”在本轮指 Owner，不扩展到其他群友。')
    return (config.group_chat.public_persona + '\n[对普通群友的公开回应]\n'
            '当前实际发言者是普通群友，按此公开风格交流，不套用 Owner 的私人关系、亲昵称呼。')
