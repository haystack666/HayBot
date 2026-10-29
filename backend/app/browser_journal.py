"""Bot/account/owner-scoped browser experiences derived from durable evidence."""
import json
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import HTTPException


class BrowserJournal:
    def __init__(self, tasks):
        self.tasks, self.db = tasks, tasks.db
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS browser_journal(task_id TEXT PRIMARY KEY,bot_id TEXT NOT NULL,
            account_id TEXT NOT NULL,owner_id TEXT NOT NULL,body TEXT NOT NULL,
            remembered INTEGER NOT NULL DEFAULT 1,deleted INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,updated REAL NOT NULL);
          CREATE INDEX IF NOT EXISTS browser_journal_bot ON browser_journal(bot_id,created);
          CREATE TABLE IF NOT EXISTS browser_journal_epochs(bot_id TEXT PRIMARY KEY,revision INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS browser_journal_topics(bot_id TEXT NOT NULL,account_id TEXT NOT NULL,
            recipient TEXT NOT NULL,video_id TEXT NOT NULL,sent REAL NOT NULL,
            PRIMARY KEY(bot_id,account_id,recipient,video_id));
        ''')

    def epoch(self, bot_id):
        row=self.db.execute('SELECT revision FROM browser_journal_epochs WHERE bot_id=?',(bot_id,)).fetchone()
        return row[0] if row else 0

    def revise(self, bot_id):
        self.db.execute('INSERT INTO browser_journal_epochs VALUES (?,1) ON CONFLICT(bot_id) DO UPDATE SET revision=revision+1',(bot_id,))

    @staticmethod
    def videos(steps):
        videos={}
        for step in steps:
            current,watch=step.get('current') or {},step.get('watch') or {}
            vid=str(current.get('id') or '')
            if not re.fullmatch(r'[0-9]{5,30}',vid) or not isinstance(watch.get('advancedSeconds'),(int,float)) or watch['advancedSeconds']<1:
                continue
            video=videos.setdefault(vid,{'id':vid,'title':str(current.get('title') or '')[:2000],
                'author':str(current.get('author') or '')[:200],'url':'https://www.douyin.com/video/'+vid,
                'advanced_seconds':0,'coverage_ranges':[],'full_duration':None,'complete':False,'impressions':[]})
            video['advanced_seconds']+=watch['advancedSeconds']
            if watch.get('coverageRanges') is not None:video['coverage_ranges']=watch['coverageRanges']
            if watch.get('fullDuration'):video['full_duration']=watch['fullDuration']
            if watch.get('partial') is False:video['complete']=True
            reason=str(step.get('reason') or '').strip()[:800]
            if reason and reason not in video['impressions']:video['impressions'].append(reason)
        for step in steps:
            reflection=step.get('experience') or {}
            video=videos.get(reflection.get('video_id'))
            text=str(reflection.get('reflection') or '').strip()[:800]
            if video and text and text not in video['impressions']:video['impressions'].append(text)
        return list(videos.values())

    def capture(self, task, *, backfill=False):
        videos=self.videos(task['steps'])
        if not videos:return None
        bot_id=task['bot_id'];cfg=self.tasks.config(bot_id)
        runtime=self.tasks.manager.get(bot_id)
        old=self.db.execute('SELECT * FROM browser_journal WHERE task_id=? AND bot_id=?',(task['id'],bot_id)).fetchone()
        if old and old['deleted']:return None  # A tombstone prevents backfill resurrection.
        origin=task['origin'];owner=origin.get('requester_id') if origin.get('source')=='qq' else origin.get('journal_owner_id',cfg.qq_owner_id)
        account=origin.get('account_id') or runtime.store.load().account_id
        if old:account,owner=old['account_id'],old['owner_id']
        # New tasks snapshot identity at submission. Historical imports are marked
        # separately and explicitly initiated by the administrator.
        body={'id':task['id'],'goal':task['goal'],'state':task['state'],'source':origin.get('source','web'),
            'summary':task['result'][:6000] if task['state']=='completed' else '',
            'result':task['result'][:6000],'videos':videos,'created':task['created'],'updated':task['updated'],
            'historical_import':bool(backfill or old and json.loads(old['body']).get('historical_import'))}
        with self.db:
            self.db.execute('''INSERT INTO browser_journal(task_id,bot_id,account_id,owner_id,body,created,updated)
                VALUES (?,?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET body=excluded.body,updated=excluded.updated''',
                (task['id'],bot_id,account,owner or '',json.dumps(body,ensure_ascii=False),task['created'],time.time()))
        return {**body,'remembered':bool(old['remembered']) if old else True}

    def unpack(self,row):
        return {**json.loads(row['body']),'remembered':bool(row['remembered'])}

    def get(self,bot_id,task_id):
        row=self.db.execute('SELECT * FROM browser_journal WHERE bot_id=? AND task_id=? AND deleted=0',(bot_id,task_id)).fetchone()
        if not row:raise HTTPException(404,'浏览手记不存在')
        value=self.unpack(row)
        # Always read the ledger's final state, including later reconciliation.
        value['interactions']=self.tasks.interactions.history(bot_id,task_id=task_id)
        return value

    def listing(self,bot_id,offset=0,limit=20,query=''):
        rows=self.db.execute('SELECT * FROM browser_journal WHERE bot_id=? AND deleted=0 ORDER BY created DESC',(bot_id,)).fetchall()
        values=[self.unpack(r) for r in rows]
        if query:values=[v for v in values if query.casefold() in json.dumps(v,ensure_ascii=False).casefold()]
        return {'items':values[offset:offset+limit],'total':len(values)}

    def change(self,bot_id,task_id,remembered=None,delete=False):
        self.get(bot_id,task_id)
        with self.db:
            if delete:self.db.execute('UPDATE browser_journal SET deleted=1,remembered=0 WHERE bot_id=? AND task_id=?',(bot_id,task_id))
            else:self.db.execute('UPDATE browser_journal SET remembered=? WHERE bot_id=? AND task_id=?',(int(remembered),bot_id,task_id))
            self.revise(bot_id)

    def backfill(self,bot_id):
        count=0
        for row in self.db.execute('SELECT * FROM browser_tasks WHERE bot_id=? ORDER BY created DESC LIMIT 200',(bot_id,)).fetchall():
            if self.capture(self.tasks.unpack(row),backfill=True):count+=1
        return {'count':count}

    @staticmethod
    def relevance(query, text):
        # Character bigrams support Chinese titles without an external embedding
        # service; ASCII words and literal title matches support names/links.
        query=query.casefold()[:2000];text=text.casefold()
        words=set(re.findall(r'[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}',query))
        grams={word[i:i+2] for word in words for i in range(len(word)-1)}
        return sum(g in text for g in grams)+sum(4 for word in words if word in text)

    def recall(self,bot_id,account,owner,query=''):
        rows=self.db.execute('''SELECT * FROM browser_journal WHERE bot_id=? AND account_id=? AND owner_id=?
            AND remembered=1 AND deleted=0 ORDER BY created DESC LIMIT 300''',(bot_id,account,owner)).fetchall()
        local_day=datetime.now(ZoneInfo('Asia/Shanghai')).date()
        days=next((n for word,n in [('前天',2),('昨天',1),('今天',0)] if word in query),None)
        explicit=re.search(r'20[0-9]{2}-[01][0-9]-[0-3][0-9]',query)
        wanted=explicit[0] if explicit else (local_day-timedelta(days=days)).isoformat() if days is not None else None
        if wanted:rows=[r for r in rows if datetime.fromtimestamp(r['created'],ZoneInfo('Asia/Shanghai')).date().isoformat()==wanted]
        ranked=sorted(rows,key=lambda r:(self.relevance(query,r['body']),r['created']),reverse=True)
        chosen=list(dict.fromkeys([*(r['task_id'] for r in ranked[:3]),*(r['task_id'] for r in rows[:2])]))[:4]
        selected=[next(r for r in rows if r['task_id']==key) for key in chosen]
        result=[]
        for row in selected:
            item=self.unpack(row)
            videos=sorted(item['videos'],key=lambda v:self.relevance(query,json.dumps(v,ensure_ascii=False)),reverse=True)[:4]
            videos=[{**v,'impressions':[s[:240] for s in v['impressions'][-3:]],'coverage_ranges':v['coverage_ranges'][:12]} for v in videos]
            result.append({'task_id':item['id'],'date':datetime.fromtimestamp(item['created'],ZoneInfo('Asia/Shanghai')).isoformat(),
                'state':item['state'],'summary':item['summary'][:1800],'videos':videos})
        return result

    def topic(self,bot_id,account,owner):
        live=self.db.execute("SELECT id FROM browser_tasks WHERE bot_id=? AND state='running' ORDER BY created DESC LIMIT 1",(bot_id,)).fetchone()
        if not live:return None
        row=self.db.execute('''SELECT * FROM browser_journal WHERE task_id=? AND bot_id=? AND account_id=? AND owner_id=?
            AND remembered=1 AND deleted=0''',(live[0],bot_id,account,owner)).fetchone()
        if not row:return None
        entry=self.unpack(row)
        if time.time()-entry['updated']>900:return None
        for video in reversed(entry['videos']):
            if self.db.execute('SELECT 1 FROM browser_journal_topics WHERE bot_id=? AND account_id=? AND recipient=? AND video_id=?',(bot_id,account,owner,video['id'])).fetchone():continue
            return {'task_id':entry['id'],'video':video,'epoch':self.epoch(bot_id),'account':account,'owner':owner}
        return None

    def mark_topic(self,bot_id,topic):
        with self.db:self.db.execute('INSERT OR IGNORE INTO browser_journal_topics VALUES (?,?,?,?,?)',
            (bot_id,topic['account'],topic['owner'],topic['video']['id'],time.time()))
