"""Persistent random opportunities with owner events, quiet hours and publishing limits."""
import json
import random
import uuid
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

from .proactive import active_at
from .qzone_store import PostWrite


class RandomSharing:
    def __init__(self,service):
        self.q=service;self.db=service.store.db;self.was_ready=False;self.connection=None
        self.db.executescript('''CREATE TABLE IF NOT EXISTS qzone_random_state(account_id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,epoch INTEGER NOT NULL,next_check REAL NOT NULL,last_trigger TEXT NOT NULL,
            last_message_id INTEGER NOT NULL,last_reason TEXT NOT NULL,trigger TEXT NOT NULL);''')

    def snapshot(self):
        c=self.q.store.load();row=self.db.execute('SELECT * FROM qzone_random_state WHERE account_id=?',(c.account_id,)).fetchone()
        return dict(row) if row else {'next_check':None,'last_reason':'尚未安排随机评估','trigger':''}

    def set(self,account,owner,epoch,next_check,signature,message_id,reason,trigger):
        with self.db:self.db.execute('INSERT OR REPLACE INTO qzone_random_state VALUES (?,?,?,?,?,?,?,?)',
            (account,owner,epoch,next_check,signature,message_id,reason,trigger))

    def later(self,now,p,low=None,high=None):
        result=now+random.uniform(low or p.interval_min_minutes,high or p.interval_max_minutes)*60
        local=datetime.fromtimestamp(result,ZoneInfo(p.timezone))
        # Put a persisted opportunity in the next active period, never at its exact start.
        if not active_at(result,p):
            hour,minute=map(int,p.active_start.split(':'));start=local.replace(hour=hour,minute=minute,second=0,microsecond=0)
            if start.timestamp()<=result:start+=timedelta(days=1)
            result=start.timestamp()+random.uniform(5,30)*60
        return result

    async def tick(self):
        q=self.q;c=q.store.load();p,epoch=q.data.config(c.account_id);now=q.clock()
        if not p.auto_enabled or not p.owner_id or not q.ready(c.account_id):
            self.was_ready=False;return
        connection=q.bot.napcat.ws
        resumed=not self.was_ready or self.connection is not connection
        self.was_ready=True;self.connection=connection
        source=q.owner.collect()
        if not source['available']:return
        state=self.snapshot()
        if state.get('owner_id')!=p.owner_id or state.get('epoch')!=epoch:
            self.set(c.account_id,p.owner_id,epoch,self.later(now,p),source['signature'],source['latest_message_id'],'等待随机分享机会','spontaneous');return
        due=state['next_check'];trigger=state['trigger']
        if due<=now and (resumed or now-due>300):
            self.set(c.account_id,p.owner_id,epoch,self.later(now,p),source['signature'],source['latest_message_id'],'连接恢复，重新等待随机机会，不补发',trigger);return
        if source['signature']!=state['last_trigger']:
            trigger='owner_chat' if source['latest_message_id']!=state['last_message_id'] else 'schedule'
            due=min(due,self.later(now,p,p.event_min_minutes,p.event_max_minutes))
            self.set(c.account_id,p.owner_id,epoch,due,source['signature'],source['latest_message_id'],'发现新的 Owner 素材，随机等待后再评估',trigger)
        if due>now:return
        if not active_at(now,p):
            self.set(c.account_id,p.owner_id,epoch,self.later(now,p),source['signature'],source['latest_message_id'],'当前不在活跃时段，延后评估',trigger);return
        local=datetime.fromtimestamp(now,ZoneInfo(p.timezone));start=local.replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        rows=self.db.execute("SELECT content,updated FROM qzone_posts WHERE account_id=? AND origin IN ('random','auto') AND (tid!='' OR status IN ('sending','unknown','queued')) ORDER BY updated DESC LIMIT 1000",(c.account_id,)).fetchall()
        reason=''
        if rows and now-rows[0]['updated']<p.cooldown_minutes*60:reason='刚分享过，先过会儿再说'
        if p.daily_limit and sum(r['updated']>=start for r in rows)>=p.daily_limit:reason='今日已达到分享上限'
        if not reason and random.random()>=p.share_probability:reason='这次没有强烈的分享欲，跳过'
        self.set(c.account_id,p.owner_id,epoch,self.later(now,p),source['signature'],source['latest_message_id'],reason or '正在判断是否值得分享',trigger)
        if reason:return
        if p.mode=='fixed':decision={'share':True,'content':p.content,'reason':''}
        else:
            try:decision=await q.decide(trigger)
            except Exception:
                self.set(c.account_id,p.owner_id,epoch,self.later(now,p),source['signature'],source['latest_message_id'],'本次生成未成功，不补发',trigger);return
        if q.data.config(c.account_id)[1]!=epoch or q.owner.stamp()!=source['stamp']:return
        content=decision['content']
        if not decision['share'] or not content or any(r['content'].strip()==content.strip() for r in rows[:10]):
            self.set(c.account_id,p.owner_id,epoch,self.later(now,p),source['signature'],source['latest_message_id'],decision['reason'] or '这件事暂时不需要单独发动态',trigger);return
        post=q.data.create(c.account_id,PostWrite(content=content,visibility=p.visibility,targets=p.targets),origin='random',origin_key='random:'+uuid.uuid4().hex,epoch=epoch,now=now)
        with self.db:self.db.execute('UPDATE qzone_posts SET source_owner=?,source_stamp=?,trigger=? WHERE id=?',
            (p.owner_id,source['stamp'],trigger,post['id']))
        q.submit(post['id'],automatic=True,deadline=now+300)
