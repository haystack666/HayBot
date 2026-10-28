"""Persistent, bot-local chat records, independent of the model's rolling context."""
import hashlib
import json
import time


class ChatArchive:
    def __init__(self, db):
        self.db = db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS chat_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chat_conversations (
                id TEXT PRIMARY KEY, app_id TEXT NOT NULL, kind TEXT NOT NULL,
                target_id TEXT NOT NULL, title TEXT NOT NULL, updated REAL NOT NULL,
                UNIQUE(app_id,kind,target_id)
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES chat_conversations(id),
                event_key TEXT NOT NULL UNIQUE, role TEXT NOT NULL,
                sender_id TEXT NOT NULL DEFAULT '', sender_name TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL, attachment_count INTEGER NOT NULL DEFAULT 0,
                at REAL, recorded_at REAL NOT NULL, source TEXT NOT NULL,
                status TEXT NOT NULL, historical INTEGER NOT NULL DEFAULT 0, reply_to TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS chat_message_page ON chat_messages(conversation_id,id);
            CREATE INDEX IF NOT EXISTS chat_conversation_page ON chat_conversations(app_id,updated DESC,id);
        ''')

        columns = {row['name'] for row in self.db.execute('PRAGMA table_info(chat_messages)')}
        if 'reply_to' not in columns:
            with self.db:
                self.db.execute("ALTER TABLE chat_messages ADD COLUMN reply_to TEXT NOT NULL DEFAULT ''")
        if 'meme_id' not in columns:
            with self.db:
                self.db.execute("ALTER TABLE chat_messages ADD COLUMN meme_id TEXT NOT NULL DEFAULT ''")
        with self.db:
            for column in ('platform_id', 'platform_index', 'quote_context', 'participant_context'):
                if column not in columns:
                    self.db.execute(f"ALTER TABLE chat_messages ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            self.db.execute('CREATE INDEX IF NOT EXISTS chat_platform_id ON chat_messages(conversation_id,platform_id)')
            self.db.execute('CREATE INDEX IF NOT EXISTS chat_platform_index ON chat_messages(conversation_id,platform_index)')
        self.db.execute('CREATE INDEX IF NOT EXISTS chat_reply_parent ON chat_messages(conversation_id,reply_to,id)')

    def _record(self, app_id, kind, target, role, content, event_key, *, sender_id='', sender_name='',
                attachment_count=0, at=None, source='reply', status='sent', historical=False, activity_at=None, reply_to='', meme_id='',
                platform_id='', platform_index='', quote_context=None, participant_context=None):
        if not content and not attachment_count:
            return False
        if self.db.execute('SELECT 1 FROM chat_messages WHERE event_key=?', (event_key,)).fetchone():
            return False
        conversation_id = hashlib.sha256(json.dumps([app_id, kind, target]).encode()).hexdigest()[:32]
        title = ('群聊 · ' if kind == 'group' else '单聊 · ') + target[-6:]
        if kind == 'user':
            contact = self.db.execute('SELECT name FROM proactive_contacts WHERE app_id=? AND id=?', (app_id, target)).fetchone()
            if contact:
                title = contact['name']
            if role == 'user' and sender_name:
                title = sender_name
        now = time.time()
        activity = activity_at if activity_at is not None else at if at is not None else now
        self.db.execute('INSERT OR IGNORE INTO chat_conversations VALUES (?,?,?,?,?,?)',
                        (conversation_id, app_id, kind, target, title, activity))
        self.db.execute('''INSERT INTO chat_messages
            (conversation_id,event_key,role,sender_id,sender_name,content,attachment_count,at,recorded_at,source,status,historical,reply_to,meme_id,
             platform_id,platform_index,quote_context,participant_context)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (conversation_id, event_key, role, sender_id, sender_name, content, attachment_count, at, now, source, status, int(historical), reply_to,meme_id,
             platform_id, platform_index, json.dumps(quote_context, ensure_ascii=False) if quote_context else '',
             json.dumps(participant_context, ensure_ascii=False) if participant_context else ''))
        self.db.execute('UPDATE chat_conversations SET updated=MAX(updated,?) WHERE id=?', (activity, conversation_id))
        if kind == 'user' and role == 'user' and sender_name:
            self.db.execute('UPDATE chat_conversations SET title=? WHERE id=?', (title, conversation_id))
        return True

    def record(self, *args, **kwargs):
        with self.db:
            return self._record(*args, **kwargs)

    def recent_group(self, app_id, target, *, before, floor=0, limit=12):
        """Public, attributed messages only; respect reset/forget and clear-history barriers."""
        cleared = self.db.execute("SELECT value FROM chat_meta WHERE key='history_floor'").fetchone()
        floor = max(floor, int(cleared['value']) if cleared else 0)
        rows = self.db.execute('''SELECT m.*, p.id parent_id, p.sender_id parent_sender,
                    p.platform_id parent_platform_id
            FROM chat_messages m JOIN chat_conversations c ON c.id=m.conversation_id
            LEFT JOIN chat_messages p ON p.conversation_id=m.conversation_id AND p.event_key=m.reply_to
            LEFT JOIN user_scopes s ON s.app_id=c.app_id AND s.kind='group' AND s.target=c.target_id
                AND s.sender_id=CASE WHEN m.role='user' THEN m.sender_id ELSE p.sender_id END
            WHERE c.app_id=? AND c.kind='group' AND c.target_id=? AND m.id<? AND m.id>?
                AND m.recorded_at>? AND m.historical=0
                AND ((m.role='user' AND m.status='received' AND m.source='incoming')
                    OR (m.role='assistant' AND m.status='sent' AND p.id>?))
                AND CASE WHEN m.role='user' THEN m.id ELSE p.id END > COALESCE(s.source_floor,0)
            ORDER BY m.id DESC LIMIT ?''',
            (app_id, target, before, floor, time.time()-1800, floor, max(0,min(limit,20)))).fetchall()
        result, budget = [], 6000
        from .reply_envelope import public_reply
        for row in rows:
            content = row['content']
            if row['role'] == 'assistant':
                try:
                    content = public_reply(content)
                except ValueError:
                    content = '[此前一次回复格式异常，正文不可用]'
            item = {'message_id': row['platform_id'] or str(row['id']), 'role': row['role'],
                    'sender_id': row['sender_id'] if row['role']=='user' else '',
                    'sender_name': row['sender_name'] if row['role']=='user' else '当前机器人',
                    'content': content[:1000], 'attachment_count': row['attachment_count']}
            if len(content)>1000:
                item['truncated'] = True
            if row['role']=='assistant':
                item['reply_to_sender_id'] = row['parent_sender']
                item['reply_to_message_id'] = row['parent_platform_id']
            if row['participant_context']:
                item['participants'] = json.loads(row['participant_context'])
            cost = len(json.dumps(item,ensure_ascii=False))
            if cost > budget:
                break
            result.append(item)
            budget -= cost
        return list(reversed(result))

    def find_platform(self, app_id, kind, target, reference):
        if not reference:
            return None
        # Message IDs and reference indexes are only meaningful inside this bot/account and chat.
        row = self.db.execute('''SELECT m.* FROM chat_messages m
            JOIN chat_conversations c ON c.id=m.conversation_id
            WHERE c.app_id=? AND c.kind=? AND c.target_id=?
              AND (m.platform_id=? OR m.platform_index=? OR m.event_key=?)
            ORDER BY m.id DESC LIMIT 1''',
            (app_id, kind, target, reference, reference, f'in:{app_id}:{target}:{reference}')).fetchone()
        return dict(row) if row else None

    @staticmethod
    def quote_body(row):
        result = {'content': row['content'][:4000], 'sender_id': row['sender_id'],
                  'sender_name': row['sender_name'] or ('当前机器人' if row['role'] == 'assistant' else ''),
                  'is_bot': row['role'] == 'assistant'}
        if row['attachment_count']:
            result.update(attachment_count=row['attachment_count'], attachment_note='原消息含附件，原图或文件未读取。')
        if len(row['content']) > 4000:
            result['truncated'] = True
        return result

    def import_legacy(self, app_id):
        if self.db.execute("SELECT 1 FROM chat_meta WHERE key='legacy_imported'").fetchone():
            return
        with self.db:
            pending = []
            for row in self.db.execute('SELECT key,value,updated FROM history').fetchall():
                parts = row['key'].split(':', 2)
                if len(parts) != 3 or parts[0] not in ('user', 'group'):
                    continue
                kind, target, sender = parts
                try:
                    messages = json.loads(row['value'])
                except (ValueError, TypeError):
                    continue
                if not isinstance(messages, list):
                    continue
                skip_assistant = False
                for index, message in enumerate(messages):
                    if not isinstance(message, dict):
                        continue
                    role, content = message.get('role'), message.get('content')
                    if role not in ('user', 'assistant') or not isinstance(content, str):
                        continue
                    if role == 'user' and content == '[按设置发送的主动消息]':
                        skip_assistant = True
                        continue
                    if skip_assistant:
                        skip_assistant = False
                        if role == 'assistant':
                            continue
                    pending.append((row['updated'] or 0, len(pending),
                                    (app_id, kind, target, role, content, f'context:{row["key"]}:{index}'),
                                    dict(sender_id=sender if role == 'user' else '', source='legacy_context',
                                         status='historical', historical=True, activity_at=row['updated'] or 0)))
            # Confirmed proactive messages have their own real send timestamps. Synthetic
            # user prompts from the model context are never displayed as user messages.
            for row in self.db.execute("SELECT * FROM proactive_events WHERE status='sent' AND content!='' ORDER BY created,id").fetchall():
                at = row['sent_at'] or row['created']
                pending.append((at, len(pending),
                                (row['app_id'], 'user', row['recipient'], 'assistant', row['content'], f'push:{row["id"]}'),
                                dict(at=at, source=row['kind'], historical=True)))
            for _, _, args, kwargs in sorted(pending, key=lambda item: item[:2]):
                self._record(*args, **kwargs)
            self.db.execute("INSERT INTO chat_meta VALUES ('legacy_imported','1')")

    def conversations(self, app_id, limit=50, offset=0):
        rows = self.db.execute('''SELECT c.*,
            (SELECT COUNT(*) FROM chat_messages WHERE conversation_id=c.id) AS message_count,
            (SELECT substr(content,1,120) FROM chat_messages WHERE conversation_id=c.id ORDER BY id DESC LIMIT 1) AS preview,
            (SELECT attachment_count FROM chat_messages WHERE conversation_id=c.id ORDER BY id DESC LIMIT 1) AS attachment_count
            FROM chat_conversations c WHERE app_id=? ORDER BY updated DESC,id DESC LIMIT ? OFFSET ?''',
            (app_id, limit + 1, offset)).fetchall()
        return {'items': [dict(row) for row in rows[:limit]], 'next_offset': offset + limit if len(rows) > limit else None}

    def messages(self, app_id, conversation_id, limit=100, before=None, after=None):
        conversation = self.db.execute('''SELECT c.*, (SELECT COUNT(*) FROM chat_messages WHERE conversation_id=c.id) AS message_count
            FROM chat_conversations c WHERE id=? AND app_id=?''', (conversation_id, app_id)).fetchone()
        if not conversation:
            return None
        sql = 'SELECT id,role,sender_id,sender_name,content,attachment_count,at,source,status,historical,meme_id,quote_context FROM chat_messages WHERE conversation_id=?'
        args = [conversation_id]
        if before is not None:
            sql += ' AND id<?'; args.append(before)
        if after is not None:
            sql += ' AND id>?'; args.append(after)
        sql += ' ORDER BY id ' + ('ASC' if after is not None else 'DESC') + ' LIMIT ?'
        rows = self.db.execute(sql, (*args, limit + 1)).fetchall()
        items = [dict(row) for row in rows[:limit]]
        for item in items:
            item['quote_context'] = json.loads(item['quote_context']) if item['quote_context'] else None
        if app_id.startswith('napcat:'):
            for item in items:
                if item['meme_id']:item['meme_original']=True
        if after is None:
            items.reverse()
        return {'conversation': dict(conversation), 'items': items, 'has_more': len(rows) > limit}
