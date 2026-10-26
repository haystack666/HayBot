"""Persistent owners for user-specific character state, never display-name identities."""
import hashlib
import json
import time


class ScopeStore:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript('''CREATE TABLE IF NOT EXISTS user_scopes (
            id TEXT PRIMARY KEY, app_id TEXT NOT NULL, kind TEXT NOT NULL, target TEXT NOT NULL,
            sender_id TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', updated REAL NOT NULL,
            epoch INTEGER NOT NULL DEFAULT 0, source_floor INTEGER NOT NULL DEFAULT 0, processed_through INTEGER NOT NULL DEFAULT 0,
            UNIQUE(app_id,kind,target,sender_id));''')
        columns = {row['name'] for row in self.db.execute('PRAGMA table_info(user_scopes)')}
        if 'processed_through' not in columns:
            with self.db:
                self.db.execute('ALTER TABLE user_scopes ADD COLUMN processed_through INTEGER NOT NULL DEFAULT 0')
        # An archive establishes owner identities, not durable facts or shared schedules.
        for row in self.db.execute('''SELECT DISTINCT c.app_id,c.kind,c.target_id,m.sender_id,m.sender_name
            FROM chat_conversations c JOIN chat_messages m ON m.conversation_id=c.id
            WHERE m.role='user' AND m.source='incoming' ''').fetchall():
            sender = row['sender_id'] or (row['target_id'] if row['kind'] == 'user' else '')
            if sender:
                self.ensure(row['app_id'], row['kind'], row['target_id'], sender, row['sender_name'])

    def ensure(self, app_id, kind, target, sender_id, name=''):
        if kind not in ('user', 'group') or not all(isinstance(v, str) and 0 < len(v) <= 128 for v in (target, sender_id)):
            raise ValueError('用户范围无效')
        if kind == 'user' and target != sender_id:
            raise ValueError('单聊用户范围不一致')
        sid = hashlib.sha256(json.dumps([app_id, kind, target, sender_id], ensure_ascii=False).encode()).hexdigest()[:32]
        name = name.strip()[:80] if isinstance(name, str) else ''
        with self.db:
            self.db.execute('''INSERT INTO user_scopes (id,app_id,kind,target,sender_id,name,updated) VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=CASE WHEN excluded.name!='' THEN excluded.name ELSE user_scopes.name END,
                updated=excluded.updated''', (sid, app_id, kind, target, sender_id, name, time.time()))
        return self.get(sid, app_id)

    def get(self, sid, app_id=None):
        app_id = self.store.load().account_id if app_id is None else app_id
        row = self.db.execute('SELECT * FROM user_scopes WHERE id=? AND app_id=?', (sid, app_id)).fetchone()
        if not row:
            raise ValueError('当前机器人中不存在此用户范围')
        result = dict(row)
        result['label'] = result['name'] or ('群成员 · ' if result['kind'] == 'group' else '用户 · ') + result['sender_id'][-6:]
        if result['kind'] == 'group':
            result['label'] += '（群 ' + result['target'][-6:] + '）'
        return result

    def list(self):
        app_id = self.store.load().account_id
        return [self.get(row['id']) for row in self.db.execute('SELECT id FROM user_scopes WHERE app_id=? ORDER BY updated DESC,id', (app_id,))]

    def history_key(self, sid):
        item = self.get(sid)
        return f'{item["kind"]}:{item["target"]}:{item["sender_id"]}'

    def source(self, sid, message_id):
        owner = self.get(sid)
        row = self.db.execute('''SELECT m.* FROM chat_messages m JOIN chat_conversations c ON c.id=m.conversation_id
            WHERE m.id=? AND c.app_id=? AND c.kind=? AND c.target_id=?
            AND ((m.role='user' AND (m.sender_id=? OR (m.sender_id='' AND c.kind='user')))
              OR (m.role='assistant' AND m.status='sent'))''',
            (message_id, owner['app_id'], owner['kind'], owner['target'], owner['sender_id'])).fetchone()
        if row and owner['kind'] == 'group' and row['role'] == 'assistant':
            # Group archive is shared; an outgoing reply belongs to its triggering sender.
            event = row['reply_to'] or row['event_key'].replace('reply:', 'in:', 1)
            source = self.db.execute('''SELECT sender_id FROM chat_messages WHERE event_key=? AND role='user' AND conversation_id=? ''',
                                     (event, row['conversation_id'])).fetchone() if event else None
            if not source or source['sender_id'] != owner['sender_id']:
                return None
        return dict(row) if row else None
