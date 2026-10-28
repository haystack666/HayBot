"""Bounded structured diagnostics; chat bodies stay in their existing archive."""
import contextlib
import contextvars
import functools
import json
import math
import re
import time
from urllib.parse import urlsplit, urlunsplit

CATEGORIES = ('system', 'qq', 'message', 'model', 'memory', 'schedule', 'proactive', 'config', 'diary')
LEVELS = ('debug', 'info', 'warn', 'error')
FIELDS = {'model', 'provider', 'provider_type', 'duration_ms', 'input_tokens', 'output_tokens', 'total_tokens',
          'http_status', 'error_type', 'error_code', 'retry_in', 'attempt', 'message_id', 'stage', 'reason', 'count',
          'indexed', 'dimensions', 'state', 'trigger', 'revision', 'queue_size', 'image_count', 'sent_message_id',
          'request_url', 'request_operation', 'segment_index', 'segment_count', 'batch_count', 'batch_id', 'incoming_ids', 'scope_id', 'trace_id', 'incoming_id', 'outgoing_id', 'push_id',
          'user_name', 'user_id', 'kind', 'target', 'app_id'}


def category_for(message):
    for word, category in [('主动', 'proactive'), ('日程', 'schedule'), ('记忆', 'memory'), ('模型', 'model'),
                           ('QQ', 'qq'), ('回复', 'message'), ('上下文', 'config'), ('配置', 'config')]:
        if word in message:
            return category
    return 'system'


def exception_details(error):
    response = getattr(error, 'response', None)
    status = getattr(response, 'status_code', None) or getattr(error, 'status', None)
    from pydantic import ValidationError
    reason = '; '.join('.'.join(map(str, item['loc'])) + ': ' + item['type'] for item in error.errors(include_input=False, include_context=False, include_url=False)) if isinstance(error, ValidationError) else str(error)
    result = {'error_type': type(error).__name__, 'reason': reason[:4000]}
    if type(status) is int:
        result['http_status'] = status
    return result


def redaction_snapshot(method):
    @functools.wraps(method)
    def wrapped(self, *args, **kwargs):
        if self.redaction_keys.get() is not None:
            return method(self, *args, **kwargs)
        token = self.redaction_keys.set(self.secrets())
        try:
            return method(self, *args, **kwargs)
        finally:
            self.redaction_keys.reset(token)
    return wrapped


class EventLogs:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.secret_resolver = lambda: []
        self.redaction_keys = contextvars.ContextVar('redaction_keys_' + str(id(self)), default=None)
        self.current = contextvars.ContextVar('log_context_' + str(id(self)), default={})
        columns = {row['name'] for row in self.db.execute('PRAGMA table_info(logs)')}
        with self.db:
            for name, default in [('category', 'system'), ('event', ''), ('details', '{}'), ('app_id', ''), ('scope_id', ''), ('trace_id', '')]:
                if name not in columns:
                    self.db.execute(f"ALTER TABLE logs ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")
            if 'app_id' not in columns:
                self.db.execute('UPDATE logs SET app_id=?', (self.store.load().account_id,))
            self.db.execute('CREATE INDEX IF NOT EXISTS logs_app_page ON logs(app_id,id)')
            self.db.execute('CREATE INDEX IF NOT EXISTS logs_trace ON logs(app_id,trace_id,id)')

    def secrets(self):
        config=self.store.load()
        values = [config.qq.secret,config.napcat.token]
        try:
            values.extend(self.secret_resolver())
        except Exception:
            pass
        return sorted({value for value in values if isinstance(value, str) and value}, key=len, reverse=True)

    def text(self, value, limit=2000):
        value = str(value)
        for secret in (self.redaction_keys.get() if self.redaction_keys.get() is not None else self.secrets()):
            value = value.replace(secret, '[已隐藏]')
        value = re.sub(r'(?i)\b(?:Bearer|QQBot)\s+[^\s,;，。；\"\'}]+', 'Bearer [已隐藏]', value)
        value = re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[已隐藏]', value)
        value = re.sub(r'(?i)((?:api[_-]?key|app[_-]?secret|client[_-]?secret|access_token|refresh_token|authorization)\s*[=:]\s*)[^\s,;&]+', r'\1[已隐藏]', value)
        return value[:limit]

    def clean(self, values):
        result = {}
        for key, value in values.items():
            if key not in FIELDS or value is None:
                continue
            if key == 'incoming_ids' and isinstance(value, list) and len(value) <= 10 and all(type(mid) is int and mid > 0 for mid in value):
                result[key] = value
                continue
            if isinstance(value, str):
                if key == 'request_url':
                    try:
                        parsed = urlsplit(value)
                        hostname = parsed.hostname or ''
                        authority = ('[' + hostname + ']' if ':' in hostname else hostname) + (':' + str(parsed.port) if parsed.port else '')
                        value = urlunsplit((parsed.scheme, authority, parsed.path, '', ''))
                    except ValueError:
                        value = '[地址无效]'
                result[key] = self.text(value, 2000 if key == 'reason' else 500)
            elif type(value) in (int, float) and math.isfinite(value):
                result[key] = value
            elif type(value) is bool:
                result[key] = value
        return result

    def push(self, **values):
        return self.current.set({**self.current.get(), **values})

    def reset(self, token):
        self.current.reset(token)

    @contextlib.contextmanager
    def context(self, **values):
        token = self.push(**values)
        try:
            yield
        finally:
            self.reset(token)

    @redaction_snapshot
    def write(self, level, message, category=None, event='', details=None):
        if level not in LEVELS:
            level = 'info'
        values = self.clean({**self.current.get(), **(details or {})})
        app_id = values.pop('app_id', self.store.load().account_id)
        message = self.text(message)
        category = category if category in CATEGORIES else category_for(message)
        cursor = self.db.execute('''INSERT INTO logs(at,level,message,category,event,details,app_id,scope_id,trace_id)
            VALUES (?,?,?,?,?,?,?,?,?)''', (time.time(), level, message, category, self.text(event, 100),
            json.dumps(values, ensure_ascii=False), app_id, values.get('scope_id', ''), values.get('trace_id', '')))
        self.db.execute('DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY id DESC LIMIT 10000)')
        return cursor.lastrowid

    def public(self, row):
        item = dict(row)
        try:
            details = json.loads(item.get('details') or '{}')
        except (ValueError, TypeError):
            details = {}
        item['details'] = self.clean(details if isinstance(details, dict) else {})
        item['message'] = self.text(item['message'])
        item['event'] = self.text(item.get('event', ''), 100)
        owner = None
        if item.get('scope_id'):
            try:
                owner = self.store.scopes.get(item['scope_id'])
            except ValueError:
                pass
        item['user'] = self.text(owner['label'], 150) if owner else ''
        return item

    @redaction_snapshot
    def query(self, *, level='', category='', query='', start=None, end=None, before=None, after=None, limit=50, trace_id=''):
        if before is not None and after is not None:
            raise ValueError('不能同时向前和向后读取日志')
        if level and level not in LEVELS or category and category not in CATEGORIES:
            raise ValueError('日志级别或分类无效')
        if not 1 <= limit <= 200 or len(query) > 200 or len(trace_id) > 100:
            raise ValueError('日志查询范围无效')
        if any(value is not None and (not math.isfinite(value) or value < 0) for value in (start, end)) or start is not None and end is not None and start > end:
            raise ValueError('日志时间范围无效')
        where, args = ['(app_id=? OR app_id=\'\')'], [self.store.load().account_id]
        for column, value, operation in [('category', category, '='), ('at', start, '>='), ('at', end, '<='), ('trace_id', trace_id, '=')]:
            if value is not None and value != '':
                where.append(f'{column}{operation}?'); args.append(value)
        if query:
            escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            where.append("(message LIKE ? ESCAPE '\\' OR details LIKE ? ESCAPE '\\' OR event LIKE ? ESCAPE '\\')")
            args.extend(['%' + escaped + '%'] * 3)
        predicate = ' AND '.join(where)
        summary = {name: 0 for name in LEVELS}
        for row in self.db.execute(f'SELECT level,COUNT(*) count FROM logs WHERE {predicate} GROUP BY level', args):
            if row['level'] in summary:
                summary[row['level']] = row['count']
        if level:
            where.append('level=?'); args.append(level)
        total = self.db.execute('SELECT COUNT(*) FROM logs WHERE ' + ' AND '.join(where), args).fetchone()[0]
        if before is not None:
            where.append('id<?'); args.append(before)
        if after is not None:
            where.append('id>?'); args.append(after)
        order = 'ASC' if after is not None else 'DESC'
        rows = self.db.execute('SELECT * FROM logs WHERE ' + ' AND '.join(where) + f' ORDER BY id {order} LIMIT ?', (*args, limit+1)).fetchall()
        items = [self.public(row) for row in rows[:limit]]
        return {'items': items, 'total': total, 'summary': summary, 'has_more': len(rows) > limit,
                'next_before': min(item['id'] for item in items) if len(rows) > limit and after is None else None,
                'latest_id': max((item['id'] for item in items), default=None), 'retention': 10000}

    @redaction_snapshot
    def detail(self, event_id):
        row = self.db.execute("SELECT * FROM logs WHERE id=? AND (app_id=? OR app_id='')", (event_id, self.store.load().account_id)).fetchone()
        if not row:
            return None
        item = self.public(row)
        details, messages, conversation = item['details'], [], ''
        if item['scope_id']:
            try:
                owner = self.store.scopes.get(item['scope_id'])
                mids = details.get('incoming_ids') or [details.get('incoming_id')]
                sources = [source for mid in mids if type(mid) is int and (source := self.store.scopes.source(owner['id'], mid))]
                if sources:
                    conversation = sources[-1]['conversation_id']
                    for source in sources:
                        messages.append({'role': source['role'], 'content': self.text(source['content'], 12000), 'id': source['id']})
                    source = sources[-1]
                    replies = self.db.execute("SELECT * FROM chat_messages WHERE (event_key=? OR reply_to=?) AND conversation_id=? AND role='assistant' ORDER BY id", (source['event_key'].replace('in:', 'reply:', 1), source['event_key'], conversation)).fetchall()
                    for reply in replies:
                        messages.append({'role': 'assistant', 'content': self.text(reply['content'], 12000), 'id': reply['id']})
                push_id = details.get('push_id')
                if type(push_id) is int:
                    push = self.db.execute("SELECT content FROM proactive_events WHERE id=? AND app_id=? AND recipient=? AND status='sent'", (push_id, owner['app_id'], owner['target'])).fetchone() if owner['kind'] == 'user' else None
                    if push:
                        messages.append({'role': 'assistant', 'content': self.text(push['content'], 12000)})
            except ValueError:
                pass
        related = self.query(trace_id=item['trace_id'], limit=100)['items'] if item['trace_id'] else [item]
        related.sort(key=lambda value: value['id'])
        return {**item, 'messages': messages, 'conversation_id': conversation, 'related': related}
