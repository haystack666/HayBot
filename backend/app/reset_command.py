"""Owner-bound, short-lived confirmation for a complete conversation-memory reset."""
import asyncio
import re
import time
from urllib.parse import quote
from .message_quotes import receipt_metadata


WARNING = (
    '重置前请确认影响：\n'
    '1. 清空你与当前机器人的全部对话上下文、长期记忆（偏好、关系、共同经历和约定）、摘要及向量索引，并撤回情感与关系状态影响。\n'
    '2. 取消正在生成的旧回复，清理旧记忆任务，防止旧聊天再次恢复这些记忆。记忆产生的未来日程约定会同步移除。\n'
    '3. 后台聊天档案、机器人人格、配置和已有普通日程保留；其他用户和机器人不受影响。\n'
    '此操作不可通过机器人撤销。\n'
    '请在 2 分钟内发送 /reset 确认（或 /reset confirm）执行；发送 /reset 取消 可取消。仅发送 /reset 不会清空。'
)


class ResetCommands:
    def __init__(self, bot):
        self.bot, self.store = bot, bot.store
        self.confirmations = {}

    @staticmethod
    def action(text):
        words = text.strip().split()
        if not words or words[0].lower() != '/reset':
            return None
        if len(words) == 1:
            return 'request'
        if len(words) == 2:
            return {'confirm': 'confirm', '确认': 'confirm', 'cancel': 'cancel', '取消': 'cancel'}.get(words[1].lower(), 'help')
        return 'help'

    async def reply(self, content, config, data, group, target):
        path = 'groups' if group else 'users'
        receipt = await self.bot.api('POST', f'/v2/{path}/{quote(target, safe="")}/messages',
            json={'msg_type': 0, 'content': content, 'msg_id': data['id'], 'msg_seq': 1})
        if not isinstance(receipt, dict) or not receipt.get('id'):
            self.store.log('warn', 'QQ 未确认重置指令提示送达', category='message', event='reset.notice_unconfirmed')
            return False
        self.store.chat.record(config.account_id, 'group' if group else 'user', target, 'assistant', content,
            f'reset:{config.account_id}:{target}:{data["id"]}:1', at=time.time(), source='reset', **receipt_metadata(receipt))
        self.store.record_result('sent', '重置指令提示已发送', category='message', event='reset.notice_sent')
        return True

    async def handle(self, action, sid, key, config, data, group, target):
        now = time.monotonic()
        self.confirmations = {owner: value for owner, value in self.confirmations.items() if value['expires'] > now}
        source = self.store.scopes.source(sid, self.store.events.current.get().get('incoming_id'))
        if action == 'request':
            if len(self.confirmations) >= 500 and sid not in self.confirmations:
                self.confirmations.pop(next(iter(self.confirmations)))
            request = {'expires': now + 120, 'ready': False, 'incoming_id': source['id'], 'source_at': source['at']}
            self.confirmations[sid] = request
            try:
                delivered = await self.reply(WARNING, config, data, group, target)
                if self.confirmations.get(sid) is request:
                    if delivered:
                        request.update(ready=True, expires=time.monotonic() + 120,
                            incoming_id=self.store.db.execute('SELECT COALESCE(MAX(id),0) FROM chat_messages').fetchone()[0])
                    else:
                        self.confirmations.pop(sid, None)
            except BaseException:
                if self.confirmations.get(sid) is request:
                    self.confirmations.pop(sid, None)
                raise
            return
        if action == 'cancel':
            self.confirmations.pop(sid, None)
            await self.reply('已取消重置，没有清空你的上下文或长期记忆。', config, data, group, target)
            return
        if action != 'confirm':
            await self.reply('请先发送 /reset 查看影响，再发送 /reset 确认；也可发送 /reset 取消。', config, data, group, target)
            return
        request = self.confirmations.get(sid)
        if (not request or not request['ready'] or not source or source['id'] <= request['incoming_id']
                or source['at'] is not None and request['source_at'] is not None and source['at'] < request['source_at']):
            await self.reply('没有有效的重置确认，可能尚未发起、已过期或机器人已重启。请先发送 /reset 查看影响并重新确认。', config, data, group, target)
            return
        # Consume before any await: concurrent confirmations cannot erase newer conversations twice.
        self.confirmations.pop(sid, None)
        count = self.bot.memory.data.reset_scope(sid)
        if self.bot.browser:
            await self.bot.browser.cancel_scope(self.bot,sid)
        self.bot.inbox.clear_scope(sid)
        self.bot.last.pop(key, None)
        previous = self.bot.tasks_by_key.get(key)
        if previous and previous is not asyncio.current_task() and not previous.done():
            previous.cancel()
            await asyncio.wait({previous}, timeout=1)
            if self.bot.tasks_by_key.get(key) is previous:
                self.bot.tasks_by_key.pop(key, None)
                self.bot.pending.discard(key)
        day = self.bot.schedule.for_scope(sid)
        if not day.lock.locked():
            try:
                await day.sync_commitments()
            except Exception as error:
                from .event_logs import exception_details
                self.store.log('warn', '重置记忆后的日程约定等待同步', category='schedule', event='reset.schedule_pending', details=exception_details(error))
        self.bot.memory.wakeup.set()
        self.store.log('info', '用户已确认清空上下文与全部长期记忆', category='memory', event='memory.reset', details={'count': count})
        await self.reply('已清空你与当前机器人的全部对话上下文和长期记忆，现在可以重新开始。后台聊天档案、人格、配置与普通日程保留，其他用户不受影响。', config, data, group, target)
