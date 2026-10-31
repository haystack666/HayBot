"""Scoped, versioned durable memory with provenance and forget barriers."""
import hashlib
import json
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from contextlib import contextmanager


class StaleMemory(ValueError):
    pass


CATEGORIES = {'fact', 'preference', 'boundary', 'relationship', 'episode', 'commitment'}


def absolute(value):
    if value is None or value == '':
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.timestamp()
    except (TypeError, AttributeError, ValueError):
        raise ValueError('约定时间必须包含具体日期、时间和时区') from None


class MemoryStore:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self._transaction_depth = 0
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT, scope_id TEXT NOT NULL, category TEXT NOT NULL,
                key TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
                pinned INTEGER NOT NULL DEFAULT 0, confidence REAL NOT NULL DEFAULT 1, importance INTEGER NOT NULL DEFAULT 50,
                created REAL NOT NULL, updated REAL NOT NULL, expires_at REAL, source_ids TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1, due_at REAL, end_at REAL, commitment_state TEXT NOT NULL DEFAULT 'pending',
                UNIQUE(scope_id,category,key));
            CREATE INDEX IF NOT EXISTS memory_scope ON memories(scope_id,status,id);
            CREATE TABLE IF NOT EXISTS memory_tombstones (scope_id TEXT NOT NULL, category TEXT NOT NULL,
                key TEXT NOT NULL, content_hash TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY(scope_id,category,key));
            CREATE TABLE IF NOT EXISTS memory_superseded_sources (scope_id TEXT NOT NULL, source_id INTEGER NOT NULL,
                reason TEXT NOT NULL, PRIMARY KEY(scope_id,source_id));
            CREATE TABLE IF NOT EXISTS memory_summaries (scope_id TEXT PRIMARY KEY, content TEXT NOT NULL,
                source_ids TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS memory_summary_versions (id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope_id TEXT NOT NULL, content TEXT NOT NULL, source_ids TEXT NOT NULL, updated REAL NOT NULL,
                epoch INTEGER NOT NULL, valid INTEGER NOT NULL DEFAULT 1, reason TEXT NOT NULL DEFAULT '',
                working_state TEXT NOT NULL DEFAULT '[]');
            CREATE INDEX IF NOT EXISTS summary_owner ON memory_summary_versions(scope_id,id);
            CREATE TABLE IF NOT EXISTS memory_audit (id INTEGER PRIMARY KEY AUTOINCREMENT,scope_id TEXT NOT NULL,
                memory_id INTEGER,action TEXT NOT NULL,before_value TEXT,after_value TEXT,at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS memory_vectors (memory_id INTEGER NOT NULL,index_key TEXT NOT NULL,
                revision INTEGER NOT NULL,dimensions INTEGER NOT NULL,vector TEXT NOT NULL,PRIMARY KEY(memory_id,index_key));
            CREATE TABLE IF NOT EXISTS memory_index (scope_id TEXT PRIMARY KEY,index_key TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',error TEXT NOT NULL DEFAULT '',updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS memory_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT,scope_id TEXT NOT NULL,
                source_key TEXT NOT NULL UNIQUE,source_ids TEXT NOT NULL,epoch INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',created REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
                retry_at REAL NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '');
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(content,tokenize='trigram');
        ''')
        with self.db:
            self.db.execute("UPDATE memory_jobs SET status='pending' WHERE status='running'")
            self.db.execute('''INSERT INTO memory_summary_versions(scope_id,content,source_ids,updated,epoch,reason)
                SELECT s.scope_id,s.content,s.source_ids,s.updated,u.epoch,'legacy_migration'
                FROM memory_summaries s JOIN user_scopes u ON u.id=s.scope_id
                WHERE NOT EXISTS (SELECT 1 FROM memory_summary_versions v WHERE v.scope_id=s.scope_id)''')

    @contextmanager
    def transaction(self):
        """Nested memory writes share one SQLite commit; never await inside this block."""
        if self._transaction_depth:
            yield
            return
        self._transaction_depth += 1
        try:
            with self.db:
                # Start before validation reads too, so all derived state shares a snapshot.
                if not self.db.in_transaction:
                    self.db.execute('BEGIN IMMEDIATE')
                yield
        finally:
            self._transaction_depth -= 1

    def epoch(self, sid):
        return self.store.scopes.get(sid)['epoch']

    def check(self, sid, expected_epoch=None):
        owner = self.store.scopes.get(sid)
        if expected_epoch is not None and expected_epoch != owner['epoch']:
            raise StaleMemory('记忆已被编辑或遗忘，本次旧任务未保存')
        return owner

    def expire(self, sid):
        self.check(sid)
        rows = self.db.execute("SELECT id FROM memories WHERE scope_id=? AND status='active' AND expires_at IS NOT NULL AND expires_at<=?", (sid, time.time())).fetchall()
        if not rows:
            return
        with self.transaction():
            for row in rows:
                mid = row['id']
                old = self.get(sid, mid)
                from .emotion import retract_sources
                retract_sources(self.db, sid, old['source_ids'], 'source_expired')
                self.db.executemany('INSERT OR IGNORE INTO memory_superseded_sources VALUES (?,?,?)',
                                    [(sid, source, 'expired') for source in old['source_ids']])
                self.db.execute("UPDATE memories SET status='expired',revision=revision+1 WHERE scope_id=? AND id=?", (sid, mid))
                self.db.execute('DELETE FROM memory_vectors WHERE memory_id=?', (mid,))
                self.db.execute('DELETE FROM memory_fts WHERE rowid=?', (mid,))
                self._audit(sid, mid, 'expire', None, None)
            self.invalidate(sid, manual=False)

    def get(self, sid, mid):
        self.check(sid)
        row = self.db.execute('SELECT * FROM memories WHERE scope_id=? AND id=?', (sid, mid)).fetchone()
        if not row:
            raise ValueError('此用户中不存在该条记忆')
        item = dict(row); item['source_ids'] = json.loads(item['source_ids']); item['pinned'] = bool(item['pinned'])
        return item

    def list(self, sid, offset=0, limit=100, include_inactive=False):
        self.check(sid)
        condition = '' if include_inactive else " AND status='active' AND (expires_at IS NULL OR expires_at>?)"
        params = [sid] + ([] if include_inactive else [time.time()])
        rows = self.db.execute('SELECT id FROM memories WHERE scope_id=?' + condition + ' ORDER BY pinned DESC,updated DESC,id DESC LIMIT ? OFFSET ?', (*params, limit, offset)).fetchall()
        count = self.db.execute('SELECT COUNT(*) FROM memories WHERE scope_id=?' + condition, params).fetchone()[0]
        return {'items': [self.get(sid, row['id']) for row in rows], 'total': count}

    def _audit(self, sid, mid, action, before, after):
        self.db.execute('INSERT INTO memory_audit(scope_id,memory_id,action,before_value,after_value,at) VALUES (?,?,?,?,?,?)',
                        (sid, mid, action, json.dumps(before, ensure_ascii=False) if before else None,
                         json.dumps(after, ensure_ascii=False) if after else None, time.time()))

    def put(self, sid, category, key, content, source_ids, *, explicit=False, expected_epoch=None,
            pinned=False, confidence=1., importance=50, expires_at=None, due_at=None, end_at=None, commitment_state='pending'):
        owner = self.check(sid, expected_epoch)
        content, key = content.strip(), key.strip().casefold()
        if category not in CATEGORIES or not 1 <= len(key) <= 120 or not 1 <= len(content) <= 800:
            raise ValueError('记忆类型、标识或内容无效')
        if not 0 <= confidence <= 1 or not 0 <= importance <= 100 or commitment_state not in ('pending', 'fulfilled', 'canceled'):
            raise ValueError('记忆重要度、可信度或约定状态无效')
        sources = list(dict.fromkeys(source_ids))
        if len(sources) > 16 or any(type(source) is not int or not self.store.scopes.source(sid, source) for source in sources):
            raise ValueError('记忆来源不属于此用户')
        if not explicit and any(source <= owner['source_floor'] for source in sources):
            raise StaleMemory('旧聊天位于遗忘屏障之前，未重新提取')
        blocked = self.db.execute('SELECT 1 FROM memory_tombstones WHERE scope_id=? AND category=? AND key=?', (sid, category, key)).fetchone()
        if blocked and not explicit:
            return None
        previous = self.db.execute('SELECT id FROM memories WHERE scope_id=? AND category=? AND key=?', (sid, category, key)).fetchone()
        existing = self.get(sid, previous['id']) if previous else None
        if category == 'commitment' and existing and commitment_state in ('canceled', 'fulfilled'):
            due_at = existing['due_at'] if due_at is None else due_at
            end_at = existing['end_at'] if end_at is None else end_at
        due_at, end_at, expires_at = absolute(due_at), absolute(end_at), absolute(expires_at)
        if category == 'commitment':
            if due_at is None or end_at is None or not due_at < end_at <= due_at + 86400:
                raise ValueError('约定必须包含有效的开始和结束时间，最长 24 小时')
        else:
            due_at, end_at = None, None
        row = self.db.execute('SELECT id FROM memories WHERE scope_id=? AND category=? AND key=?', (sid, category, key)).fetchone()
        old = self.get(sid, row['id']) if row else None
        if old and old['source_ids'] and sources and not explicit and max(sources) <= max(old['source_ids']):
            return old
        if old and old['status'] == 'active' and all(old[k] == v for k, v in (
            ('content', content), ('due_at', due_at), ('end_at', end_at), ('commitment_state', commitment_state),
            ('pinned', bool(pinned if explicit else pinned or old['pinned'])), ('importance', importance),
            ('confidence', confidence), ('expires_at', expires_at))):
            if sources:
                merged = sorted(set(old['source_ids'] + sources))[-16:]
                with self.transaction():
                    self.db.execute('UPDATE memories SET source_ids=? WHERE scope_id=? AND id=?', (json.dumps(merged), sid, old['id']))
                old['source_ids'] = merged
            return old
        now = time.time()
        with self.transaction():
            if old and old['content'] != content:
                from .emotion import retract_sources
                retract_sources(self.db, sid, old['source_ids'], 'source_corrected')
                self.db.executemany('INSERT OR IGNORE INTO memory_superseded_sources VALUES (?,?,?)',
                                    [(sid, source, 'corrected') for source in old['source_ids'] if source not in sources])
            self.db.execute('''INSERT INTO memories(scope_id,category,key,content,pinned,confidence,importance,created,updated,
                expires_at,source_ids,due_at,end_at,commitment_state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(scope_id,category,key) DO UPDATE SET content=excluded.content,status='active',
                pinned=excluded.pinned,confidence=excluded.confidence,importance=excluded.importance,
                updated=excluded.updated,expires_at=excluded.expires_at,source_ids=excluded.source_ids,
                revision=memories.revision+1,due_at=excluded.due_at,end_at=excluded.end_at,commitment_state=excluded.commitment_state''',
                (sid, category, key, content, int(bool(pinned if explicit else pinned or old and old['pinned'])), confidence, importance, now, now, expires_at, json.dumps(sources), due_at, end_at, commitment_state))
            mid = self.db.execute('SELECT id FROM memories WHERE scope_id=? AND category=? AND key=?', (sid, category, key)).fetchone()[0]
            self.db.execute('DELETE FROM memory_fts WHERE rowid=?', (mid,))
            self.db.execute('INSERT INTO memory_fts(rowid,content) VALUES (?,?)', (mid, content))
            self.db.execute('DELETE FROM memory_vectors WHERE memory_id=?', (mid,))
            if explicit:
                self.db.execute('DELETE FROM memory_tombstones WHERE scope_id=? AND category=? AND key=?', (sid, category, key))
            result = self.get(sid, mid)
            self._audit(sid, mid, 'update' if old else 'create', old, result)
            if old or explicit:
                self.invalidate(sid, manual=explicit)
        return result

    def invalidate(self, sid, manual=True):
        owner = self.check(sid)
        floor = self.db.execute('SELECT COALESCE(MAX(id),0) FROM chat_messages').fetchone()[0] if manual else 0
        self.db.execute('UPDATE user_scopes SET epoch=epoch+1,source_floor=MAX(source_floor,?) WHERE id=?', (floor, sid))
        self.db.execute('DELETE FROM memory_summaries WHERE scope_id=?', (sid,))
        # Invalid versions retain only coverage metadata, never stale/forgotten prose.
        self.db.execute("UPDATE memory_summary_versions SET valid=0,content='',working_state='[]',reason=? WHERE scope_id=? AND valid=1",
                        ('manual_change' if manual else 'fact_change_or_expiry', sid))
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='context_diagnostics'").fetchone():
            self.db.execute('DELETE FROM context_diagnostics WHERE scope_id=?', (sid,))
        self.db.execute('DELETE FROM history WHERE key=?', (self.store.scopes.history_key(sid),))
        if manual:
            self.db.execute("UPDATE memory_jobs SET status='canceled' WHERE scope_id=? AND status IN ('pending','running')", (sid,))
        else:
            self.db.execute("UPDATE memory_jobs SET epoch=? WHERE scope_id=? AND status='pending'", (owner['epoch'] + 1, sid))

    def reset_scope(self, sid):
        """Forget this owner's state atomically; old archives remain behind a source barrier."""
        self.check(sid)
        with self.transaction():
            count = self.db.execute('SELECT COUNT(*) FROM memories WHERE scope_id=?', (sid,)).fetchone()[0]
            self.invalidate(sid)
            from .emotion import retract_sources
            retract_sources(self.db, sid, reason='scope_forgotten')
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='message_inbox'").fetchone():
                self.db.execute("UPDATE message_inbox SET status='canceled',payload='',updated=? WHERE scope_id=? AND status IN ('queued','generating','sending')", (time.time(), sid))
            self.db.execute('DELETE FROM memory_vectors WHERE memory_id IN (SELECT id FROM memories WHERE scope_id=?)', (sid,))
            self.db.execute('DELETE FROM memory_fts WHERE rowid IN (SELECT id FROM memories WHERE scope_id=?)', (sid,))
            for table in ('memories', 'memory_tombstones', 'memory_superseded_sources', 'memory_summaries', 'memory_summary_versions', 'memory_index', 'memory_jobs', 'memory_audit'):
                self.db.execute(f'DELETE FROM {table} WHERE scope_id=?', (sid,))
            self._audit(sid, None, 'reset', None, {'count': count})
        return count

    def forget(self, sid, mid):
        old = self.get(sid, mid)
        with self.transaction():
            from .emotion import retract_sources
            retract_sources(self.db, sid, old['source_ids'], 'source_forgotten')
            self.db.execute("UPDATE memories SET status='forgotten',content='',source_ids='[]',revision=revision+1,updated=? WHERE scope_id=? AND id=?", (time.time(), sid, mid))
            self.db.execute('INSERT OR REPLACE INTO memory_tombstones VALUES (?,?,?,?,?)',
                (sid, old['category'], old['key'], hashlib.sha256(old['content'].encode()).hexdigest(), time.time()))
            self.db.execute('DELETE FROM memory_fts WHERE rowid=?', (mid,))
            self.db.execute('DELETE FROM memory_vectors WHERE memory_id=?', (mid,))
            self.invalidate(sid)
            self._audit(sid, mid, 'forget', {'id': mid, 'content': '[已遗忘]'}, None)
            # Do not retain erased memory prose inside the memory audit.
            self.db.execute("UPDATE memory_audit SET before_value=NULL,after_value=NULL WHERE scope_id=? AND memory_id=? AND action!='forget'", (sid, mid))

    def summary(self, sid):
        self.check(sid)
        row = self.db.execute('SELECT content FROM memory_summaries WHERE scope_id=?', (sid,)).fetchone()
        return row['content'] if row else ''

    def summary_versions(self, sid, limit=12):
        self.check(sid)
        return [{**dict(row), 'source_ids': json.loads(row['source_ids']),
                 'working_state': json.loads(row['working_state'])} for row in self.db.execute(
                     'SELECT * FROM memory_summary_versions WHERE scope_id=? ORDER BY id DESC LIMIT ?', (sid, limit))]

    def set_summary(self, sid, content, source_ids, epoch, working_state=None):
        owner = self.check(sid, epoch)
        if not isinstance(content, str) or len(content) > 2400:
            raise ValueError('摘要长度无效')
        if any(type(mid) is not int or mid <= owner['source_floor'] or not self.store.scopes.source(sid, mid) for mid in source_ids):
            raise StaleMemory('摘要来源无效或位于遗忘屏障之前')
        previous = self.summary_versions(sid, 1)
        coverage = sorted(set(source_ids + (previous[0]['source_ids'] if previous and previous[0]['valid'] else [])))
        excluded = {row['source_id'] for row in self.db.execute('SELECT source_id FROM memory_superseded_sources WHERE scope_id=?', (sid,))}
        coverage = [mid for mid in coverage if mid not in excluded]
        with self.transaction():
            self.db.execute('INSERT OR REPLACE INTO memory_summaries VALUES (?,?,?,?)', (sid, content, json.dumps(coverage), time.time()))
            self.db.execute('''INSERT INTO memory_summary_versions(scope_id,content,source_ids,updated,epoch,working_state)
                VALUES (?,?,?,?,?,?)''', (sid, content, json.dumps(coverage), time.time(), epoch, json.dumps(working_state or [], ensure_ascii=False)))
            self.db.execute('''DELETE FROM memory_summary_versions WHERE scope_id=? AND id NOT IN (
                SELECT id FROM memory_summary_versions WHERE scope_id=? ORDER BY id DESC LIMIT 12)''', (sid, sid))

    def audit(self, sid, limit=50, before=None):
        self.check(sid)
        return [{**dict(row), 'before': json.loads(row['before_value']) if row['before_value'] else None,
                 'after': json.loads(row['after_value']) if row['after_value'] else None}
                for row in self.db.execute('SELECT * FROM memory_audit WHERE scope_id=? AND (? IS NULL OR id<?) ORDER BY id DESC LIMIT ?', (sid, before, before, limit))]

    def appointments(self, sid, day, timezone):
        self.check(sid)
        start = datetime.fromisoformat(day).replace(tzinfo=ZoneInfo(timezone))
        end = start + timedelta(days=1)
        return [self.get(sid, row['id']) for row in self.db.execute('''SELECT id FROM memories WHERE scope_id=?
            AND category='commitment' AND status='active' AND commitment_state='pending' AND due_at<? AND end_at>? AND (expires_at IS NULL OR expires_at>?)
            ORDER BY due_at,id''', (sid, end.timestamp(), start.timestamp(), time.time()))]

    def save_vector(self, sid, mid, index_key, vector, revision, epoch):
        self.check(sid, epoch)
        item = self.get(sid, mid)
        if item['revision'] != revision or item['status'] != 'active':
            return False
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO memory_vectors VALUES (?,?,?,?,?)', (mid, index_key, revision, len(vector), json.dumps(vector)))
        return True

    def vectors(self, sid, index_key):
        self.check(sid)
        return [{**dict(row), 'vector': json.loads(row['vector'])} for row in self.db.execute('''SELECT m.id,m.content,m.pinned,m.importance,v.vector
            FROM memories m JOIN memory_vectors v ON v.memory_id=m.id AND v.revision=m.revision
            WHERE m.scope_id=? AND m.status='active' AND (m.expires_at IS NULL OR m.expires_at>?) AND v.index_key=?''', (sid, time.time(), index_key))]

    def lexical(self, sid, query, limit=40):
        self.check(sid)
        words = re.findall(r'[A-Za-z0-9_]+|[\u3400-\u9fff]{2,}', query[:300])
        terms = list(dict.fromkeys([word[:32] for word in words] + [word[i:i+2] for word in words for i in range(min(30, len(word)-1))]))[:60]
        matched = set()
        fts_terms = [term for term in terms if len(term) >= 3]
        if fts_terms:
            expression = ' OR '.join('"' + term.replace('"', '""') + '"' for term in fts_terms)
            matched = {row['rowid'] for row in self.db.execute('SELECT f.rowid FROM memory_fts f JOIN memories m ON m.id=f.rowid WHERE memory_fts MATCH ? AND m.scope_id=? LIMIT ?', (expression, sid, limit))}
        rows = self.list(sid, limit=5000)['items']
        def score(item):
            return (100 if item['id'] in matched else 0) + sum(term.casefold() in item['content'].casefold() for term in terms) + (2 if item['pinned'] else 0)
        return sorted([item for item in rows if score(item) > 0], key=lambda item: (score(item), item['importance'], item['updated']), reverse=True)[:limit]
