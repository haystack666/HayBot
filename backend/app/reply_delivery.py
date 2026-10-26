"""Send and archive confirmed QQ bubbles; logical conversation state stays one turn."""
import asyncio
import time
from urllib.parse import quote

from .reply_segments import split_reply
from .schedule import ScheduleChanged
from .event_logs import exception_details


class ReplyDelivery:
    def __init__(self, bot, config, data, group, target, user, sid, key, day, schedule_stamp, memory_stamp, old, question, batch=None):
        self.bot, self.store, self.config, self.data = bot, bot.store, config, data
        self.group, self.target, self.user, self.sid, self.key = group, target, user, sid, key
        self.day, self.schedule_stamp, self.memory_stamp = day, schedule_stamp, memory_stamp
        self.batch = batch
        self.old, self.question, self.confirmed, self.source_ids = old, question, [], []
        self.meme_context = ''

    def state_current(self):
        return (self.day.matches(self.schedule_stamp) and self.bot.memory.matches(self.sid, self.memory_stamp)
                and (self.batch is None or self.bot.inbox.live(self.batch)))

    def current(self):
        return self.state_current() and not self.bot.schedule_reply_expired(self.data, command='对话')

    def save_prefix(self):
        if self.confirmed and self.state_current():
            self.store.save_history(self.key, [*self.old, {'role': 'user', 'content': self.question},
                {'role': 'assistant', 'content': '\n\n'.join(self.confirmed)}], self.config.rules.rounds)
            self.bot.last[self.key] = time.time()
            if len(self.bot.last) > 500:
                self.bot.last.pop(next(iter(self.bot.last)))

    async def post(self, part, sequence, total):
        path = 'groups' if self.group else 'users'
        if self.batch is not None and not self.bot.inbox.mark_sending(self.batch):
            raise ScheduleChanged('消息批次已取消，停止发送')
        receipt = await self.bot.api('POST', f'/v2/{path}/{quote(self.target, safe="")}/messages', before_send=self.current,
            json={'msg_type': 0, 'content': part, 'msg_id': self.data['id'], 'msg_seq': sequence})
        if not isinstance(receipt, dict) or not receipt.get('id'):
            self.store.log('warn', 'QQ 未确认本段送达，已停止后续分段', category='message', event='message.segment_unconfirmed',
                details={'segment_index': sequence, 'segment_count': total})
            return None
        self.confirmed.append(part)
        incoming = f'in:{self.config.account_id}:{self.target}:{self.data["id"]}'
        key = f'reply:{self.config.account_id}:{self.target}:{self.data["id"]}' if sequence == 1 else f'reply-part:{self.config.account_id}:{self.target}:{self.data["id"]}:{sequence}'
        self.store.chat.record(self.config.account_id, 'group' if self.group else 'user', self.target, 'assistant', part, key,
            at=time.time(), status='sent' if self.state_current() else 'sent_stale', reply_to=incoming)
        self.source_ids.append(self.store.db.execute('SELECT id FROM chat_messages WHERE event_key=?', (key,)).fetchone()[0])
        self.store.record_result('sent', f'对话回复第 {sequence}/{total} 段已发送', category='message', event='message.segment_sent',
            details={'segment_index': sequence, 'segment_count': total, 'sent_message_id': receipt['id']})
        return receipt

    async def send_meme(self, meme, sequence):
        if not self.current() or not self.bot.memes.current(meme):
            return
        try:
            guard=lambda: self.current() and self.bot.memes.current(meme)
            if self.config.transport=='napcat':
                path=self.bot.memes.catalog.image(meme['id'])
                data=await asyncio.to_thread(path.read_bytes)
                if not guard():return
                if self.batch is not None and not self.bot.inbox.mark_sending(self.batch):return
                receipt=await self.bot.napcat.send_image(self.group,self.target,data,before_send=guard)
            else:
                file_info = await self.bot.memes.upload(meme, self.group, self.target, self.current)
                if not isinstance(file_info,str) or not file_info:
                    self.store.log('warn','QQ 未返回有效的表情包媒体凭据，文字已保留',category='message',event='meme.upload_unconfirmed')
                    return
                if not guard():return
                if self.batch is not None and not self.bot.inbox.mark_sending(self.batch):return
                receipt = await self.bot.api('POST', f'/v2/{"groups" if self.group else "users"}/{quote(self.target, safe="")}/messages',
                    before_send=guard,json={'msg_type':7,'content':' ','media':{'file_info':file_info},'msg_id':self.data['id'],'msg_seq':sequence})
            if not isinstance(receipt,dict) or not receipt.get('id'):
                self.store.log('warn','QQ 未确认表情包送达',category='message',event='meme.unconfirmed');return
            description = meme['description']
            label = '[发送表情包：' + description['visual'][:220] + (f'；图中文字：{description["text"][:180]}' if description['text'] else '') + ']'
            self.meme_context = '\n' + label
            key = f'reply-part:{self.config.account_id}:{self.target}:{self.data["id"]}:{sequence}'
            self.store.chat.record(self.config.account_id,'group' if self.group else 'user',self.target,'assistant',label,key,
                attachment_count=1,meme_id=meme['id'],at=time.time(),source='meme',status='sent' if self.state_current() else 'sent_stale',
                reply_to=f'in:{self.config.account_id}:{self.target}:{self.data["id"]}')
            self.source_ids.append(self.store.db.execute('SELECT id FROM chat_messages WHERE event_key=?',(key,)).fetchone()[0])
            self.bot.memes.sent(self.sid,meme)
            self.store.record_result('sent','表情包已发送',category='message',event='meme.sent',details={'sent_message_id':receipt['id']})
        except asyncio.CancelledError: raise
        except Exception as error:
            self.store.log('warn','表情包发送失败，文字回复已保留',category='message',event='meme.send_failed',details=exception_details(error))

    async def send(self, content, prepared=None, update=None, meme=None, meme_candidates=None):
        rules = self.config.rules
        if meme and not self.bot.memes.current(meme): meme = None
        # Reserve a media bubble; existing maximum is conservative (four total).
        max_parts = min(rules.split_max_parts, 3) if meme or meme_candidates else rules.split_max_parts
        parts = split_reply(content, rules.split_length, max_parts) if rules.split_enabled else [content]
        complete, receipt = False, None
        try:
            for index, part in enumerate(parts, 1):
                if index > 1 and rules.split_delay:
                    await asyncio.sleep(rules.split_delay)
                if not self.current():
                    raise ScheduleChanged('日程、记忆或回复时限已变化，已停止后续分段')
                if prepared and index == len(parts):
                    # No lock while pacing; only the final receipt and day commit are coupled.
                    async with self.day.lock:
                        if not self.current():
                            raise ScheduleChanged('日程或记忆已变化，已停止后续分段')
                        latest = self.day.dialogue.prepare(update)
                        receipt = await self.post(part, index, len(parts))
                        if receipt and self.state_current():
                            self.day.dialogue.apply(latest, {'kind': 'group' if self.group else 'user', 'target': self.target,
                                'sender_id': self.user, 'message_id': self.data['id']})
                            self.schedule_stamp = self.day.stamp()
                        else:
                            self.store.log('warn', '整条回复尚未确认有效送达，未应用对话日程调整')
                else:
                    receipt = await self.post(part, index, len(parts))
                if receipt is None:
                    return None
            if not meme and meme_candidates and self.current():
                meme = await self.bot.memes.choose(self.question,'\n\n'.join(self.confirmed),meme_candidates)
            if meme:
                await self.send_meme(meme,len(parts)+1)
            complete = True
            return receipt
        finally:
            if not complete:
                self.save_prefix()
