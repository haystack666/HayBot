"""Private, encrypted, bot-local diaries with account scope and revision history."""
import json
import time
import uuid
from datetime import date

from pydantic import Field, field_validator
from .config import StrictModel, ProactiveConfig


class DiaryConfig(StrictModel):
    enabled: bool = True
    time: str = Field(default='23:30', pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    timezone: str = 'Asia/Shanghai'
    owner_id: str = Field(default='', pattern=r'^[A-Za-z0-9_-]{0,128}$')
    include_groups: bool = True
    allow_sharing: bool = True
    instruction: str = Field(default='', max_length=2000)

    @field_validator('timezone')
    @classmethod
    def valid_zone(cls, value):
        return ProactiveConfig.valid_timezone(value)


class DiaryWrite(StrictModel):
    day: date | None = None


class DiaryStore:
    def __init__(self, store, clock=time.time):
        self.store, self.db, self.clock = store, store.db, clock
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS diary_config (
                account_id TEXT PRIMARY KEY, value TEXT NOT NULL, revision INTEGER NOT NULL,
                enabled_since REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS diary_entries (
                id TEXT PRIMARY KEY, account_id TEXT NOT NULL, day TEXT NOT NULL,
                timezone TEXT NOT NULL, owner_id TEXT NOT NULL, status TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '',
                source_stamp TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 0,
                created REAL NOT NULL, updated REAL NOT NULL, error TEXT NOT NULL DEFAULT '',
                run_id TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
                retry_at REAL NOT NULL DEFAULT 0, automatic_at REAL NOT NULL DEFAULT 0,
                UNIQUE(account_id,day));
            CREATE TABLE IF NOT EXISTS diary_versions (
                entry_id TEXT NOT NULL, revision INTEGER NOT NULL, content TEXT NOT NULL,
                evidence TEXT NOT NULL, created REAL NOT NULL, origin TEXT NOT NULL,
                PRIMARY KEY(entry_id,revision));
            CREATE INDEX IF NOT EXISTS diary_page ON diary_entries(account_id,day DESC);
        ''')
        with self.db:
            self.db.execute("UPDATE diary_entries SET status=CASE WHEN revision>0 THEN 'ready' ELSE 'failed' END, "
                            "run_id='',error='写作时服务中断，可重新写作',retry_at=? WHERE status='writing'", (clock()+60,))

    def config(self, account):
        row = self.db.execute('SELECT * FROM diary_config WHERE account_id=?', (account,)).fetchone()
        if row is None:
            value = DiaryConfig()
            with self.db:
                self.db.execute('INSERT INTO diary_config VALUES (?,?,0,?)', (account,value.model_dump_json(),self.clock()))
            return value, 0, self.clock()
        return DiaryConfig.model_validate_json(row['value']), row['revision'], row['enabled_since']

    def save_config(self, account, value):
        old, revision, since = self.config(account)
        if value == old:
            return
        if value.enabled and not old.enabled:
            since = self.clock()
        with self.db:
            self.db.execute('UPDATE diary_config SET value=?,revision=?,enabled_since=? WHERE account_id=?',
                            (value.model_dump_json(),revision+1,since,account))

    def pack(self, value):
        return self.store.cipher.encrypt(json.dumps(value,ensure_ascii=False).encode()).decode()

    def unpack(self, value, default):
        return json.loads(self.store.cipher.decrypt(value.encode())) if value else default

    def row(self, account, day):
        row = self.db.execute('SELECT * FROM diary_entries WHERE account_id=? AND day=?', (account,day)).fetchone()
        return dict(row) if row else None

    def get(self, account, entry_id):
        row = self.db.execute("SELECT * FROM diary_entries WHERE account_id=? AND id=? AND status!='deleted'", (account,entry_id)).fetchone()
        if row is None:
            raise ValueError('当前账号中不存在这篇日记')
        item = dict(row)
        return {key:item[key] for key in ('id','day','timezone','owner_id','status','revision','created','updated','error')} | {
            'content':self.unpack(item['content'],''), 'sources':self.unpack(item['evidence'],{})}

    def list(self, account, offset=0, limit=30):
        rows = self.db.execute("SELECT id FROM diary_entries WHERE account_id=? AND status!='deleted' ORDER BY day DESC LIMIT ? OFFSET ?",
                               (account,limit,offset)).fetchall()
        items = []
        for row in rows:
            item = self.get(account,row['id'])
            item.pop('sources')
            item['preview'] = item.pop('content')[:100]
            items.append(item)
        return {'items':items,'total':self.db.execute("SELECT COUNT(*) FROM diary_entries WHERE account_id=? AND status!='deleted'", (account,)).fetchone()[0]}

    def versions(self, account, entry_id):
        self.get(account,entry_id)
        return [{'revision':r['revision'],'created':r['created'],'origin':r['origin'],
                 'content':self.unpack(r['content'],'')} for r in self.db.execute(
                     'SELECT * FROM diary_versions WHERE entry_id=? ORDER BY revision DESC', (entry_id,))]

    def begin(self, account, day, timezone, owner, automatic=False):
        now, token = self.clock(), uuid.uuid4().hex
        row = self.row(account,day)
        with self.db:
            if row:
                if row['status']=='writing':
                    raise ValueError('这一天的日记正在写作')
                self.db.execute("UPDATE diary_entries SET status='writing',run_id=?,error='',attempts=attempts+?,retry_at=0 WHERE id=?",
                                (token,int(automatic),row['id']))
                return row['id'], token
            entry = uuid.uuid4().hex
            self.db.execute('''INSERT INTO diary_entries
                (id,account_id,day,timezone,owner_id,status,created,updated,run_id,attempts)
                VALUES (?,?,?,?,?,'writing',?,?,?,?)''', (entry,account,day,timezone,owner,now,now,token,int(automatic)))
            return entry, token

    def finish(self, account, entry_id, token, text, evidence, stamp, timezone, owner, origin):
        now = self.clock()
        row = self.db.execute("SELECT revision FROM diary_entries WHERE account_id=? AND id=? AND status='writing' AND run_id=?", (account,entry_id,token)).fetchone()
        if row is None:
            raise ValueError('日记已被删除或写作已取消')
        revision = row['revision']+1
        content, sources = self.pack(text), self.pack(evidence)
        with self.db:
            self.db.execute('INSERT INTO diary_versions VALUES (?,?,?,?,?,?)', (entry_id,revision,content,sources,now,origin))
            self.db.execute("""UPDATE diary_entries SET status='ready',content=?,evidence=?,source_stamp=?,revision=?,
                updated=?,run_id='',error='',timezone=?,owner_id=?,automatic_at=CASE WHEN ?='automatic' THEN ? ELSE automatic_at END
                WHERE id=? AND account_id=?""", (content,sources,stamp,revision,now,timezone,owner,origin,now,entry_id,account))
        return self.get(account,entry_id)

    def fail(self, account, entry_id, token, error):
        with self.db:
            self.db.execute("""UPDATE diary_entries SET status=CASE WHEN revision>0 THEN 'ready' ELSE 'failed' END,
                run_id='',error=?,retry_at=? WHERE account_id=? AND id=? AND run_id=?""",
                (self.store.events.text(error,300),self.clock()+600,account,entry_id,token))

    def delete(self, account, entry_id):
        self.get(account,entry_id)
        with self.db:
            self.db.execute('DELETE FROM diary_versions WHERE entry_id=?', (entry_id,))
            self.db.execute("UPDATE diary_entries SET status='deleted',content='',evidence='',source_stamp='',run_id='',error='' WHERE account_id=? AND id=?", (account,entry_id))
