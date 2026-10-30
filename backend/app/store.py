import json
import os
import sqlite3
import time
from pathlib import Path
from cryptography.fernet import Fernet
from .config import Settings
from .chat import ChatArchive


class Store:
    def __init__(self, directory):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        key = root / 'secret.key'
        if not key.exists():
            fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(Fernet.generate_key())
        self.cipher = Fernet(key.read_bytes())
        self.db = sqlite3.connect(root / 'hayqqbot.sqlite3')
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, at REAL, level TEXT, message TEXT);
            CREATE TABLE IF NOT EXISTS history (key TEXT PRIMARY KEY, value TEXT, updated REAL);
            CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY, at REAL);
            CREATE TABLE IF NOT EXISTS runtime (id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY CHECK(id=1),
                received INTEGER NOT NULL DEFAULT 0,
                sent INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS proactive_contacts (
                app_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL,
                last_received REAL NOT NULL DEFAULT 0, last_inbound_id TEXT NOT NULL DEFAULT '',
                last_proactive REAL NOT NULL DEFAULT 0, unanswered INTEGER NOT NULL DEFAULT 0,
                next_idle REAL NOT NULL DEFAULT 0, capability TEXT NOT NULL DEFAULT 'unknown',
                capability_detail TEXT NOT NULL DEFAULT '', checked_at REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(app_id, id)
            );
            CREATE TABLE IF NOT EXISTS proactive_events (
                id INTEGER PRIMARY KEY, event_key TEXT NOT NULL UNIQUE,
                app_id TEXT NOT NULL, recipient TEXT NOT NULL, kind TEXT NOT NULL,
                created REAL NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '', sent_at REAL, reminder_id TEXT
            );
            CREATE INDEX IF NOT EXISTS proactive_event_time ON proactive_events(app_id, recipient, created);
            CREATE TABLE IF NOT EXISTS proactive_reminders (
                id TEXT PRIMARY KEY, app_id TEXT NOT NULL, recipient TEXT NOT NULL,
                at REAL NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                detail TEXT NOT NULL DEFAULT '', created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS speech_state (
                app_id TEXT NOT NULL, scope_id TEXT NOT NULL,
                last_auto_voice REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(app_id, scope_id)
            );
        ''')
        # 只在首次升级时恢复旧版留下的记录，之后以累计表为准，避免重启重复回填。
        with self.db:
            self.db.execute('''
                INSERT OR IGNORE INTO statistics(id, received, sent, errors)
                SELECT 1,
                    (SELECT COUNT(*) FROM seen),
                    (SELECT COUNT(*) FROM logs WHERE message IN ('单聊回复已发送', '群聊回复已发送')),
                    (SELECT COUNT(*) FROM logs WHERE level='error' AND message LIKE '回复失败：%')
            ''')
        self.chat = ChatArchive(self.db)
        self.chat.import_legacy(self.load().account_id)
        from .scopes import ScopeStore
        self.scopes = ScopeStore(self)
        from .event_logs import EventLogs
        self.events = EventLogs(self)

    def load(self):
        row = self.db.execute('SELECT value FROM settings WHERE id=1').fetchone()
        if not row:
            return Settings()
        value = json.loads(row['value'])
        if value['qq']['secret']:
            value['qq']['secret'] = self.cipher.decrypt(value['qq']['secret'].encode()).decode()
        if value.get('napcat',{}).get('token'):
            value['napcat']['token']=self.cipher.decrypt(value['napcat']['token'].encode()).decode()
        return Settings.model_validate(value)

    def save(self, settings):
        value = settings.model_dump()
        if value['qq']['secret']:
            value['qq']['secret'] = self.cipher.encrypt(value['qq']['secret'].encode()).decode()
        if value.get('napcat',{}).get('token'):
            value['napcat']['token']=self.cipher.encrypt(value['napcat']['token'].encode()).decode()
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES (1, ?)', (json.dumps(value),))

    def log(self, level, message, *, category=None, event='', details=None):
        with self.db:
            return self._log(level, message, category=category, event=event, details=details)

    def _log(self, level, message, **kwargs):
        return self.events.write(level, message, **kwargs)

    def stats(self):
        row = self.db.execute('SELECT received,sent,errors,input_tokens,output_tokens FROM statistics WHERE id=1').fetchone()
        result = dict(row)
        result['total_tokens'] = result['input_tokens'] + result['output_tokens']
        return result

    def record_result(self, result, message, **log_fields):
        if result not in ('sent', 'errors'):
            raise ValueError('未知统计类型')
        with self.db:
            self.db.execute(f'UPDATE statistics SET {result}={result}+1 WHERE id=1')
            self._log('error' if result == 'errors' else 'info', message, **log_fields)

    def record_usage(self, response):
        def count(name):
            value = response.get(name, 0)
            return value if type(value) is int and 0 <= value <= 2**31 - 1 else 0

        with self.db:
            self.db.execute('UPDATE statistics SET input_tokens=input_tokens+?, output_tokens=output_tokens+? WHERE id=1',
                            (count('prompt_eval_count'), count('eval_count')))

    def logs(self):
        return self.events.query(limit=100)['items']

    def claim(self, message_id):
        with self.db:
            return self._claim(message_id)

    def _claim(self, message_id):
        self.db.execute('DELETE FROM seen WHERE at < ?', (time.time() - 86400,))
        cur = self.db.execute('INSERT OR IGNORE INTO seen VALUES (?,?)', (message_id, time.time()))
        accepted = bool(cur.rowcount)
        if accepted:
            self.db.execute('UPDATE statistics SET received=received+1 WHERE id=1')
        self.db.execute('DELETE FROM seen WHERE id IN (SELECT id FROM seen ORDER BY at DESC LIMIT -1 OFFSET 20000)')
        return accepted

    def history(self, key, rounds):
        if not rounds:
            return []
        row = self.db.execute('SELECT value FROM history WHERE key=?', (key,)).fetchone()
        messages = json.loads(row['value'])[-rounds * 2:] if row else []
        from .reply_envelope import public_reply
        for message in messages:
            if message.get('role') == 'assistant' and isinstance(message.get('content'), str):
                try:
                    message['content'] = public_reply(message['content'], history=True)
                except ValueError:
                    message['content'] = '[此前一次回复格式异常，正文不可用]'
        return messages

    def save_history(self, key, messages, rounds):
        with self.db:
            if rounds:
                self.db.execute('INSERT OR REPLACE INTO history VALUES (?,?,?)', (key, json.dumps(messages[-rounds * 2:]), time.time()))
                self.db.execute('DELETE FROM history WHERE key IN (SELECT key FROM history ORDER BY updated DESC LIMIT -1 OFFSET 500)')

    def clear_history(self):
        with self.db:
            self.db.execute('DELETE FROM history')
            self.db.execute("INSERT OR REPLACE INTO chat_meta(key,value) VALUES ('history_floor',?)",
                            (str(self.db.execute('SELECT COALESCE(MAX(id),0) FROM chat_messages').fetchone()[0]),))

    def last_auto_voice(self, app_id, scope_id):
        row=self.db.execute('SELECT last_auto_voice FROM speech_state WHERE app_id=? AND scope_id=?',(app_id,scope_id)).fetchone()
        return row['last_auto_voice'] if row else 0

    def mark_auto_voice(self, app_id, scope_id, at=None):
        with self.db:
            self.db.execute('''INSERT INTO speech_state(app_id,scope_id,last_auto_voice) VALUES (?,?,?)
                ON CONFLICT(app_id,scope_id) DO UPDATE SET last_auto_voice=excluded.last_auto_voice''',(app_id,scope_id,at or time.time()))

    def contact(self, app_id, recipient):
        row = self.db.execute('SELECT * FROM proactive_contacts WHERE app_id=? AND id=?', (app_id, recipient)).fetchone()
        return dict(row) if row else None

    def contacts(self, app_id):
        return [dict(row) for row in self.db.execute(
            'SELECT * FROM proactive_contacts WHERE app_id=? ORDER BY last_received DESC LIMIT 100', (app_id,))]

    def remember_contact(self, app_id, recipient, at, message_id=''):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO proactive_contacts(app_id,id,name) VALUES (?,?,?)',
                            (app_id, recipient, '单聊 · ' + recipient[-6:]))
            if message_id:
                self.db.execute('''UPDATE proactive_contacts SET last_received=?, last_inbound_id=?,
                    unanswered=0, next_idle=0 WHERE app_id=? AND id=? AND last_inbound_id!=?''',
                    (at, message_id, app_id, recipient, message_id))
            else:
                self.db.execute('UPDATE proactive_contacts SET last_received=MAX(last_received,?) WHERE app_id=? AND id=?',
                                (at, app_id, recipient))

    def set_capability(self, app_id, recipient, state, detail, at):
        with self.db:
            self.db.execute('UPDATE proactive_contacts SET capability=?,capability_detail=?,checked_at=? WHERE app_id=? AND id=?',
                            (state, detail, at, app_id, recipient))

    def set_idle_time(self, app_id, recipient, at):
        with self.db:
            self.db.execute('UPDATE proactive_contacts SET next_idle=? WHERE app_id=? AND id=?', (at, app_id, recipient))

    def proactive_count(self, app_id, recipient, since, kind=None):
        sql = '''SELECT COUNT(*) FROM proactive_events WHERE app_id=? AND recipient=? AND COALESCE(sent_at,created)>=?
                 AND status IN ('sending','sent','unknown')'''
        args = [app_id, recipient, since]
        if kind:
            sql += ' AND kind=?'
            args.append(kind)
        return self.db.execute(sql, args).fetchone()[0]

    def reserve_proactive(self, key, app_id, recipient, kind, at, reminder_id=None):
        with self.db:
            cur = self.db.execute('''INSERT OR IGNORE INTO proactive_events
                (event_key,app_id,recipient,kind,created,status,reminder_id) VALUES (?,?,?,?,?,'generating',?)''',
                (key, app_id, recipient, kind, at, reminder_id))
            return cur.lastrowid if cur.rowcount else None

    def update_proactive(self, event_id, status, detail='', content=None):
        with self.db:
            self.db.execute('UPDATE proactive_events SET status=?,detail=? WHERE id=?', (status, detail, event_id))
            if content is not None:
                self.db.execute('UPDATE proactive_events SET content=? WHERE id=?', (content, event_id))
            row = self.db.execute('SELECT reminder_id FROM proactive_events WHERE id=?', (event_id,)).fetchone()
            if row and row['reminder_id'] and status in ('sent','failed','skipped','unknown'):
                self.db.execute("UPDATE proactive_reminders SET status=?,detail=? WHERE id=? AND status!='cancelled'", (status, detail, row['reminder_id']))

    def proactive_sent(self, event_id, at, next_idle, receipt=None):
        with self.db:
            row = self.db.execute('SELECT * FROM proactive_events WHERE id=?', (event_id,)).fetchone()
            if not row or row['status'] == 'sent':
                return
            self.db.execute("UPDATE proactive_events SET status='sent',sent_at=?,detail='QQ 已接收' WHERE id=?", (at, event_id))
            self.db.execute('''UPDATE proactive_contacts SET last_proactive=?, next_idle=?,
                unanswered=unanswered+? WHERE app_id=? AND id=?''',
                (at, next_idle, int(row['kind'] in ('idle','greeting')), row['app_id'], row['recipient']))
            if row['reminder_id']:
                self.db.execute("UPDATE proactive_reminders SET status='sent',detail='QQ 已接收' WHERE id=?", (row['reminder_id'],))
            from .message_quotes import receipt_metadata
            self.chat._record(row['app_id'], 'user', row['recipient'], 'assistant', row['content'],
                              f'push:{event_id}', at=at, source=row['kind'], **receipt_metadata(receipt))
            self.db.execute('UPDATE statistics SET sent=sent+1 WHERE id=1')
            self._log('info', '主动消息已发送')

    def proactive_records(self, app_id):
        return [dict(row) for row in self.db.execute(
            'SELECT id,recipient,kind,created,status,detail,sent_at FROM proactive_events WHERE app_id=? ORDER BY id DESC LIMIT 50', (app_id,))]

    def recover_proactive(self):
        with self.db:
            self.db.execute("UPDATE proactive_reminders SET status='unknown',detail='发送时服务重启，结果未知，不自动重发' WHERE id IN (SELECT reminder_id FROM proactive_events WHERE status='sending')")
            self.db.execute("UPDATE proactive_reminders SET status='skipped',detail='生成时服务重启，未发送' WHERE id IN (SELECT reminder_id FROM proactive_events WHERE status='generating')")
            self.db.execute("UPDATE proactive_events SET status='unknown',detail='发送时服务重启，结果未知，不自动重发' WHERE status='sending'")
            self.db.execute("UPDATE proactive_events SET status='skipped',detail='生成时服务重启，未发送' WHERE status='generating'")

    def add_reminder(self, reminder_id, app_id, recipient, at, content, now):
        with self.db:
            self.db.execute('INSERT INTO proactive_reminders(id,app_id,recipient,at,content,created) VALUES (?,?,?,?,?,?)',
                            (reminder_id, app_id, recipient, at, content, now))

    def reminders(self, app_id):
        return [dict(row) for row in self.db.execute(
            'SELECT * FROM proactive_reminders WHERE app_id=? ORDER BY at DESC LIMIT 100', (app_id,))]

    def cancel_reminder(self, app_id, reminder_id):
        with self.db:
            return bool(self.db.execute("UPDATE proactive_reminders SET status='cancelled',detail='已取消' WHERE app_id=? AND id=? AND status='pending'", (app_id, reminder_id)).rowcount)

    def expire_reminders(self, now):
        with self.db:
            self.db.execute("UPDATE proactive_reminders SET status='skipped',detail='超过提醒时间 5 分钟，未补发' WHERE status='pending' AND at<?", (now - 300,))

    def enabled(self):
        row = self.db.execute('SELECT enabled FROM runtime WHERE id=1').fetchone()
        return bool(row and row['enabled'])

    def set_enabled(self, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO runtime VALUES (1,?)', (int(value),))

    def close(self):
        self.db.close()
