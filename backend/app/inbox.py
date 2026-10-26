"""Durable per-owner trailing-edge debounce; one active batch per conversation."""
import asyncio
import copy
import json
import time
import uuid

from .event_logs import exception_details
from .images import image_attachments


class ConversationInbox:
    def __init__(self, bot):
        self.bot, self.store, self.db = bot, bot.store, bot.store.db
        self.task = None
        self.active = {}
        self.wakeup = asyncio.Event()
        self.db.executescript('''CREATE TABLE IF NOT EXISTS message_inbox (
            message_id INTEGER PRIMARY KEY, scope_id TEXT NOT NULL, app_id TEXT NOT NULL,
            payload TEXT NOT NULL, received REAL NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
            batch_id TEXT NOT NULL DEFAULT '', updated REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS inbox_dispatch ON message_inbox(app_id,status,scope_id,message_id);
        ''')
        self.recover()

    def recover(self):
        with self.db:
            self.db.execute("UPDATE message_inbox SET status='queued',batch_id='' WHERE status='generating'")
            uncertain = self.db.execute("UPDATE message_inbox SET status='uncertain',payload='',updated=? WHERE status='sending'", (time.time(),)).rowcount
        if uncertain:
            self.store.log('warn', '上次中断时部分消息发送结果不确定，已保留档案，不自动重发', category='message', event='message.batch_uncertain', details={'count': uncertain})

    def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run())
        self.wakeup.set()

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        tasks = list(self.active.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.active.clear()
        self.recover()

    def enqueue(self, payload, owner, source):
        # Reuse the Bot key; pending CDN URLs/message content are never duplicated in plaintext.
        if self.db.execute('SELECT 1 FROM message_inbox WHERE message_id=?', (source['id'],)).fetchone():
            return False
        legacy = self.db.execute('SELECT at FROM seen WHERE id=?', (f'{owner["target"]}:{payload["d"]["id"]}',)).fetchone()
        if legacy and source['recorded_at'] <= legacy['at']:
            return False
        encrypted = self.store.cipher.encrypt(json.dumps(payload, ensure_ascii=False).encode()).decode()
        with self.db:
            if not self.store._claim(f'inbox:{owner["app_id"]}:{owner["id"]}:{payload["d"]["id"]}'):
                return False
            self.db.execute('INSERT INTO message_inbox(message_id,scope_id,app_id,payload,received,updated) VALUES (?,?,?,?,?,?)',
                (source['id'], owner['id'], owner['app_id'], encrypted, time.time(), time.time()))
            self.db.execute("DELETE FROM message_inbox WHERE message_id IN (SELECT message_id FROM message_inbox WHERE status NOT IN ('queued','generating','sending') ORDER BY message_id DESC LIMIT -1 OFFSET 10000)")
        self.store.log('debug', '消息已进入会话缓冲', category='message', event='message.buffered',
            details={'scope_id': owner['id'], 'incoming_id': source['id'], 'queue_size': self.snapshot()['queued']})
        self.start()
        return True

    def snapshot(self):
        app_id = self.store.load().account_id
        row = self.db.execute("SELECT COUNT(*) n,COUNT(DISTINCT scope_id) owners FROM message_inbox WHERE app_id=? AND status='queued'", (app_id,)).fetchone()
        return {'queued': row['n'], 'conversations': row['owners'], 'active': len(self.active)}

    def clear_scope(self, sid):
        with self.db:
            self.db.execute("UPDATE message_inbox SET status='canceled',payload='',updated=? WHERE scope_id=? AND status IN ('queued','generating','sending')", (time.time(), sid))
        task = self.active.get(sid)
        if task and task is not asyncio.current_task():
            task.cancel()
        self.wakeup.set()

    def live(self, batch):
        return (batch['app_id'] == self.store.load().account_id and
                self.db.execute("SELECT COUNT(*) FROM message_inbox WHERE batch_id=? AND scope_id=? AND status IN ('generating','sending')", (batch['id'], batch['scope_id'])).fetchone()[0] == len(batch['ids']))

    def mark_sending(self, batch):
        if not self.live(batch):
            return False
        with self.db:
            self.db.execute("UPDATE message_inbox SET status='sending',updated=? WHERE batch_id=? AND status='generating'", (time.time(), batch['id']))
        return True

    def pack(self, rows, config):
        selected, texts, attachments = [], [], []
        for row in rows:
            payload = json.loads(self.store.cipher.decrypt(row['payload'].encode()))
            text = self.bot.message_text(payload['d'])
            images = image_attachments(payload['d'])
            if selected and (len('\n'.join([*texts, text])) > 12000 or len(attachments) + len(images) > 3):
                break
            selected.append((row, payload))
            texts.append(text)
            attachments.extend(images)
        payload = copy.deepcopy(selected[-1][1])
        payload['d']['content'] = '\n'.join(texts)
        payload['d']['attachments'] = attachments
        return {'id': uuid.uuid4().hex, 'scope_id': rows[0]['scope_id'], 'app_id': rows[0]['app_id'],
                'ids': [row['message_id'] for row, _ in selected], 'payload': payload,
                'reply_to': self.db.execute('SELECT event_key FROM chat_messages WHERE id=?', (selected[-1][0]['message_id'],)).fetchone()[0]}

    def retire(self, batch, status):
        with self.db:
            self.db.execute("UPDATE message_inbox SET status=?,payload='',updated=? WHERE batch_id=? AND status IN ('generating','sending')", (status, time.time(), batch['id']))

    async def process(self, batch):
        try:
            result = await self.bot.handle(batch['payload'], batch=batch)
            if result:
                status = 'done'
            elif self.db.execute("SELECT 1 FROM chat_messages WHERE reply_to=? AND role='assistant' LIMIT 1", (batch['reply_to'],)).fetchone():
                status = 'partial'
            else:
                status = 'failed'
            self.retire(batch, status)
            self.store.log('info' if result else 'warn', '合并消息处理完成' if result else '合并消息未完整回复，请查看处理链路', category='message', event='message.batch_completed' if result else 'message.batch_failed',
                details={'scope_id': batch['scope_id'], 'trace_id': batch['id'], 'batch_count': len(batch['ids']), 'state': status})
        except asyncio.CancelledError:
            # Sending may have succeeded remotely: never automatically replay that phase.
            with self.db:
                self.db.execute("UPDATE message_inbox SET status='uncertain',payload='',updated=? WHERE batch_id=? AND status='sending'", (time.time(), batch['id']))
                self.db.execute("UPDATE message_inbox SET status='queued',batch_id='' WHERE batch_id=? AND status='generating'", (batch['id'],))
            raise
        except Exception as error:
            self.retire(batch, 'failed')
            self.store.log('error', '消息队列处理异常，原始消息已保留', category='message', event='message.batch_failed', details={'scope_id': batch['scope_id'], **exception_details(error)})

    def finished(self, sid, task):
        if self.active.get(sid) is task:
            self.active.pop(sid, None)
        self.bot.jobs.discard(task)
        self.wakeup.set()

    async def run(self):
        while True:
            self.wakeup.clear()
            delay = 1.0
            if self.bot.state == 'connected':
                config, now = self.store.load(), time.time()
                with self.db:
                    self.db.execute("UPDATE message_inbox SET status='canceled',payload='' WHERE app_id!=? AND status='queued'", (config.account_id,))
                scopes = self.db.execute("SELECT scope_id,MIN(message_id) first_id FROM message_inbox WHERE app_id=? AND status='queued' GROUP BY scope_id ORDER BY first_id", (config.account_id,)).fetchall()
                for scope in scopes:
                    sid = scope['scope_id']
                    if sid in self.active or len(self.active) >= 4:
                        continue
                    try:
                        owner = self.store.scopes.get(sid)
                        key = self.store.scopes.history_key(sid)
                        if key in self.bot.pending:
                            continue
                        cap = config.rules.debounce_max_messages if config.rules.debounce_enabled else 1
                        rows = self.db.execute("SELECT * FROM message_inbox WHERE scope_id=? AND status='queued' ORDER BY message_id LIMIT ?", (sid, cap)).fetchall()
                        if not rows:
                            continue
                        due = min(rows[-1]['received'] + config.rules.debounce_seconds, rows[0]['received'] + config.rules.debounce_max_wait) if config.rules.debounce_enabled else now
                        if len(rows) >= cap:
                            due = now
                        due = max(due, self.bot.last.get(key, 0) + config.rules.cooldown)
                        if due > now:
                            delay = min(delay, max(.01, due-now))
                            continue
                        batch = self.pack(rows, config)
                        if not (config.qq.group_reply if owner['kind'] == 'group' else config.qq.private_reply):
                            with self.db:
                                self.db.executemany("UPDATE message_inbox SET status='canceled',payload='' WHERE message_id=?", [(mid,) for mid in batch['ids']])
                            continue
                        source = self.store.scopes.source(sid, batch['ids'][-1])
                        if source and source['at'] is not None and now-source['at'] > 240:
                            with self.db:
                                self.db.executemany("UPDATE message_inbox SET status='expired',payload='' WHERE message_id=?", [(mid,) for mid in batch['ids']])
                            self.store.log('warn', '待处理消息已超过 QQ 回复时限，档案保留，未自动重发', category='message', event='message.batch_expired', details={'scope_id': sid, 'batch_count': len(batch['ids'])})
                            continue
                        with self.db:
                            self.db.executemany("UPDATE message_inbox SET status='generating',batch_id=?,updated=? WHERE message_id=? AND status='queued'", [(batch['id'], now, mid) for mid in batch['ids']])
                        task = asyncio.create_task(self.process(batch))
                        self.active[sid] = task
                        self.bot.jobs.add(task)
                        task.add_done_callback(lambda task, sid=sid: self.finished(sid, task))
                    except Exception as error:
                        # A broken owner must not block unrelated conversations.
                        with self.db:
                            self.db.execute("UPDATE message_inbox SET status='failed',payload='' WHERE scope_id=? AND status='queued'", (sid,))
                        self.store.log('error', '此会话队列无法处理，档案已保留', category='message', event='message.batch_failed', details={'scope_id': sid, **exception_details(error)})
            try:
                await asyncio.wait_for(self.wakeup.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
