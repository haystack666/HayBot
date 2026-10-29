"""Account-scoped write permissions and durable, conservative quota accounting."""
import json
import re
import secrets
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import Field, model_validator
from .config import StrictModel


class DouyinPerson(StrictModel):
    handle: str = Field(default='', max_length=80, pattern=r'^[\w.-]*$')
    nickname: str = Field(default='', max_length=80)

    @model_validator(mode='after')
    def paired(self):
        if bool(self.handle.strip()) != bool(self.nickname.strip()):
            raise ValueError('请同时填写抖音号和昵称')
        return self


class InteractionConfig(StrictModel):
    comments_enabled: bool = False
    replies_enabled: bool = False
    likes_enabled: bool = False
    messages_enabled: bool = False
    shares_enabled: bool = False
    owner: DouyinPerson = Field(default_factory=DouyinPerson)
    whitelist: list[DouyinPerson] = Field(default_factory=list, max_length=100)
    comment_daily_limit: int = Field(default=10, ge=0, le=500, strict=True)
    reply_daily_limit: int = Field(default=10, ge=0, le=500, strict=True)
    comment_task_limit: int = Field(default=3, ge=0, le=100, strict=True)
    deepseek_probability: int = Field(default=50, ge=0, le=100, strict=True)
    other_probability: int = Field(default=15, ge=0, le=100, strict=True)
    dm_check_interval_seconds: int = Field(default=5, ge=1, le=3600, strict=True)
    dm_total_limit: int = Field(default=20, ge=0, le=10000, strict=True)
    share_task_limit: int = Field(default=3, ge=0, le=100, strict=True)
    share_daily_limit: int = Field(default=10, ge=0, le=500, strict=True)
    public_style: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def distinct(self):
        handles = [p.handle for p in self.whitelist]
        if any(not p for p in handles) or len(set(handles)) != len(handles):
            raise ValueError('白名单中的抖音号必须填写且不能重复')
        if self.shares_enabled and not self.owner.handle:
            raise ValueError('开启站内分享前请填写 Owner 的抖音号和昵称')
        return self


WRITE_OPS = frozenset(('like', 'comment', 'reply_comment', 'reply_dm', 'share', 'share_note'))
SPENT = "('pending','confirmed','unknown')"


class InteractionLedger:
    def __init__(self, db):
        self.db = db
        db.executescript('''
          CREATE TABLE IF NOT EXISTS douyin_operations(
            id TEXT PRIMARY KEY, account TEXT NOT NULL, bot_id TEXT NOT NULL, task_id TEXT NOT NULL,
            day TEXT NOT NULL, op TEXT NOT NULL, target TEXT NOT NULL, inbound TEXT NOT NULL DEFAULT '',
            exempt INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, receipt TEXT NOT NULL DEFAULT '{}',
            payload TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
          CREATE INDEX IF NOT EXISTS douyin_quota ON douyin_operations(account,day,op,status);
          CREATE TABLE IF NOT EXISTS douyin_opportunities(account TEXT NOT NULL, day TEXT NOT NULL,
            video TEXT NOT NULL, allowed INTEGER NOT NULL, probability INTEGER NOT NULL,
            PRIMARY KEY(account,day,video));
          CREATE TABLE IF NOT EXISTS douyin_operation_checks(id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id TEXT NOT NULL, status TEXT NOT NULL, receipt TEXT NOT NULL, checked REAL NOT NULL);
        ''')
        if 'details' not in {row[1] for row in db.execute('PRAGMA table_info(douyin_operations)')}:
            db.execute("ALTER TABLE douyin_operations ADD COLUMN details TEXT NOT NULL DEFAULT '{}'")
        with db:
            db.execute("UPDATE douyin_operations SET status='unknown' WHERE status='pending'")

    @staticmethod
    def day():
        return datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()

    def count(self, account, op, *, day=None, task=None, nonwhite=False):
        clauses, args = ['account=?', 'op=?', f'status IN {SPENT}'], [account, op]
        for field, value in (('day', day), ('task_id', task)):
            if value is not None:
                clauses.append(field+'=?'); args.append(value)
        if nonwhite:
            clauses.append('exempt=0')
        return self.db.execute('SELECT count(*) FROM douyin_operations WHERE '+' AND '.join(clauses), args).fetchone()[0]

    def opportunity(self, account, video, title, cfg):
        day = self.day()
        row = self.db.execute('SELECT allowed,probability FROM douyin_opportunities WHERE account=? AND day=? AND video=?', (account,day,video)).fetchone()
        if row:
            return {'allowed': bool(row['allowed']), 'probability': row['probability']}
        probability = cfg.deepseek_probability if re.search(r'(?i)(?<![a-z])deep\s*seek(?![a-z])|深度求索|(?<![a-z])ds(?![a-z])', title) else cfg.other_probability
        allowed = secrets.randbelow(100) < probability
        with self.db:
            self.db.execute('INSERT INTO douyin_opportunities VALUES (?,?,?,?,?)', (account,day,video,int(allowed),probability))
        return {'allowed': allowed, 'probability': probability}

    @staticmethod
    def person(peer, person):
        return bool(person.handle and peer.get('handle') == person.handle and peer.get('nickname') == person.nickname and peer.get('id'))

    def own_comment(self, account, cid):
        for row in self.db.execute("SELECT receipt FROM douyin_operations WHERE account=? AND op IN ('comment','reply_comment') AND status='confirmed'", (account,)):
            if json.loads(row['receipt']).get('cid') == cid:
                return True
        return False

    def published(self, bot_id):
        row=self.db.execute("SELECT account FROM douyin_operations WHERE bot_id=? ORDER BY created DESC LIMIT 1",(bot_id,)).fetchone()
        if not row:
            return []
        result=[]
        for item in self.db.execute("SELECT account,receipt FROM douyin_operations WHERE account=? AND op IN ('comment','reply_comment') AND status='confirmed' ORDER BY created DESC LIMIT 100",(row['account'],)):
            receipt=json.loads(item['receipt'])
            if receipt.get('cid') and receipt.get('video_id'):
                result.append({'account_id':item['account'],'cid':receipt['cid'],'video_id':receipt['video_id']})
        return result

    def availability(self, account, task, cfg):
        if not account:
            return {'account_verified':False}
        return {'account_verified':True,
            'comments_remaining': max(0,min(cfg.comment_daily_limit-self.count(account,'comment',day=self.day()),cfg.comment_task_limit-self.count(account,'comment',task=task))),
            'replies_remaining': max(0,cfg.reply_daily_limit-self.count(account,'reply_comment',day=self.day())),
            'nonwhite_dm_remaining': max(0,cfg.dm_total_limit-self.count(account,'reply_dm',nonwhite=True)),
            'shares_remaining': max(0,min(cfg.share_daily_limit-self.count(account,'share',day=self.day()),cfg.share_task_limit-self.count(account,'share',task=task)))}

    def reserve(self, task, decision, observation, cfg):
        account = observation.get('account',{}).get('id','')
        if not account or not observation.get('account',{}).get('verified'):
            raise HTTPException(409,'尚未确认当前登录的抖音账号，请先读取自己的抖音主页')
        op, target, inbound, exempt = decision.op, '', '', False
        payload = {'text':decision.text, 'mention_owner':decision.mention_owner, 'sticker':decision.sticker}
        flags = {'like':'likes_enabled','comment':'comments_enabled','reply_comment':'replies_enabled','reply_dm':'messages_enabled','share':'shares_enabled','share_note':'shares_enabled'}
        if not getattr(cfg, flags[op]):
            raise HTTPException(409,'此类互动尚未在设置中开启')
        current=observation.get('current') or {}
        if op in ('like','comment','reply_comment','share'):
            target = current.get('id','')
            if not target or decision.id != target:
                raise HTTPException(409,'只能操作当前实际观察到的视频')
            payload['video_id']=target
            if op != 'reply_comment' and not observation.get('watched'):
                raise HTTPException(409,'请先实际观看视频，再决定是否互动')
        if op == 'comment':
            chance = self.opportunity(account,target,current.get('title',''),cfg)
            if not chance['allowed']:
                raise HTTPException(409,'本条视频没有获得本日评论机会，请继续浏览，不要重复抽取')
        if op == 'reply_comment':
            comment=next((c for c in observation.get('comments',[]) if c['id']==decision.comment_id),None)
            if not comment or comment.get('video_id') != current.get('id') or comment.get('author_id')==account or not self.own_comment(account,comment.get('parent_id','')):
                raise HTTPException(409,'只允许回复实际回复过自己已发布评论的人')
            inbound=decision.comment_id; target += ':'+inbound
            payload.update(comment_id=inbound,parent_id=comment['parent_id'])
        if op == 'reply_dm':
            peer=observation.get('conversation') or {}
            incoming=next((m for m in observation.get('messages',[]) if m.get('id')==decision.message_id and m.get('direction')=='inbound'),None)
            if not peer.get('id') or peer['id']!=decision.peer_id or not incoming:
                raise HTTPException(409,'未确认对方先发来的真实消息，不能主动私信')
            exempt=any(self.person(peer,p) for p in cfg.whitelist)
            if not exempt and peer.get('follows_me') is not True:
                raise HTTPException(409,'非白名单仅可回复已确认关注自己的用户')
            target, inbound=peer['id'],incoming['id']
            payload.update(peer_id=target,message_id=inbound)
        if op in ('share','share_note'):
            peer=observation.get('owner') or {}
            if not self.person(peer,cfg.owner):
                raise HTTPException(409,'尚未核对 Owner 的真实抖音号与昵称')
            payload['peer_id']=peer['id']
            if op=='share_note':
                share=self.db.execute("SELECT receipt,payload FROM douyin_operations WHERE account=? AND task_id=? AND op='share' AND status='confirmed' ORDER BY created DESC LIMIT 1",(account,task['id'])).fetchone()
                if not share or (observation.get('conversation') or {}).get('id')!=peer['id']:
                    raise HTTPException(409,'仅可在已确认的 Owner 视频分享后发送附言或表情')
                share_id=json.loads(share['receipt']).get('message_id','')
                if not share_id:
                    raise HTTPException(409,'视频卡片没有可靠消息回执，不能补发附言')
                target=share_id+(':text' if decision.text else ':sticker')
                payload['share_id']=share_id
        if decision.mention_owner:
            if op not in ('comment','reply_comment') or not self.person(observation.get('owner') or {},cfg.owner):
                raise HTTPException(409,'@ 前必须核对 Owner 的真实抖音账号')
            payload['mention_id']=(observation.get('owner') or {})['id']
        if op in ('comment','reply_comment','reply_dm') and (not decision.text.strip() or decision.sticker):
            raise HTTPException(422,'评论与私信回复需要纯文字正文')
        if op=='share_note' and (not decision.text.strip() and not decision.sticker):
            raise HTTPException(422,'分享附言需要文字或表情')
        details = {}
        if payload.get('video_id'):
            details = {'video_id': payload['video_id'], 'video_title': str(current.get('title') or '')[:2000]}
        if op == 'share_note':
            shared = self.db.execute("SELECT payload,details FROM douyin_operations WHERE account=? AND task_id=? AND op='share' AND status='confirmed' ORDER BY created DESC LIMIT 1", (account,task['id'])).fetchone()
            details = json.loads(shared['details'])
            details['video_id'] = json.loads(shared['payload']).get('video_id','')
        if op in ('share','share_note','reply_dm'):
            peer = observation.get('owner' if op in ('share','share_note') else 'conversation') or {}
            details['recipient'] = str(peer.get('nickname') or peer.get('handle') or '')[:160]
        with self.db:
            remaining=self.availability(account,task['id'],cfg)
            key={'comment':'comments_remaining','reply_comment':'replies_remaining','share':'shares_remaining'}.get(op)
            if key and remaining[key]<=0 or op=='reply_dm' and not exempt and remaining['nonwhite_dm_remaining']<=0:
                raise HTTPException(409,'该类互动额度已用完')
            # One initial comment/share/like per video, one response per inbound;
            # uncertain submissions reserve quota and prevent later-task replays.
            duplicate=self.db.execute(f'SELECT 1 FROM douyin_operations WHERE account=? AND op=? AND target=? AND inbound=? AND status IN {SPENT}',(account,op,target,inbound)).fetchone()
            if duplicate:
                raise HTTPException(409,'该目标已操作或结果待核对，禁止重复发送')
            identifier=uuid.uuid4().hex; now=time.time()
            self.db.execute('INSERT INTO douyin_operations (id,account,bot_id,task_id,day,op,target,inbound,exempt,status,receipt,payload,created,updated,details) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (identifier,account,task['bot_id'],task['id'],self.day(),op,target,inbound,int(exempt),'pending','{}',json.dumps(payload,ensure_ascii=False),now,now,json.dumps(details,ensure_ascii=False)))
        return {'operation_id':identifier,'account_id':account,**payload}

    def settle(self, identifier, result):
        status=result.get('status')
        if status not in ('confirmed','failed','unknown'):
            status='unknown'
        with self.db:
            self.db.execute("UPDATE douyin_operations SET status=?,receipt=?,updated=? WHERE id=? AND status='pending'",(status,json.dumps(result,ensure_ascii=False),time.time(),identifier))

    def history(self, bot_id):
        rows = self.db.execute("""SELECT id,op,target,status,receipt,created,payload,details,task_id FROM douyin_operations
            WHERE bot_id=? AND (status IN ('pending','unknown') OR id IN
              (SELECT id FROM douyin_operations WHERE bot_id=? ORDER BY created DESC LIMIT 50)) ORDER BY created DESC""",(bot_id,bot_id)).fetchall()
        result, task_steps = [], {}
        has_tasks = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='browser_tasks'").fetchone()
        for row in rows:
            value = dict(row)
            payload = json.loads(value.pop('payload'))
            details = json.loads(value.pop('details'))
            task_id = value.pop('task_id')
            video_id = str(details.get('video_id') or payload.get('video_id') or '')
            if value['op'] == 'share_note' and not video_id:
                # Legacy notes point at a previously confirmed card, not at the
                # video currently open when the message was sent.
                for shared in self.db.execute("SELECT payload,receipt,details FROM douyin_operations WHERE bot_id=? AND task_id=? AND op='share'", (bot_id,task_id)):
                    if json.loads(shared['receipt']).get('message_id') == payload.get('share_id'):
                        video_id = str(json.loads(shared['payload']).get('video_id') or '')
                        details = {**json.loads(shared['details']), **details}
                        break
            if not details.get('video_title') and video_id and has_tasks:
                if task_id not in task_steps:
                    task = self.db.execute('SELECT steps FROM browser_tasks WHERE id=? AND bot_id=?', (task_id,bot_id)).fetchone()
                    task_steps[task_id] = json.loads(task['steps']) if task else []
                for step in task_steps[task_id]:
                    candidates = [step.get('current') or {}, *(step.get('items') or [])]
                    match = next((c for c in candidates if str(c.get('id') or '') == video_id and c.get('title')), None)
                    if match:
                        details['video_title'] = str(match['title'])[:2000]
                        break
            value['details'] = {
                'video_id': video_id,
                'video_title': details.get('video_title') or '',
                'video_url': 'https://www.douyin.com/video/' + video_id if re.fullmatch(r'[0-9]{5,30}', video_id) else '',
                'text': payload.get('text') or '',
                'sticker': payload.get('sticker') or '',
                'mention_owner': bool(payload.get('mention_owner')),
                'recipient': details.get('recipient') or '',
            }
            result.append(value)
        return result

    def verification_grant(self, bot_id, identifier):
        row=self.db.execute('SELECT * FROM douyin_operations WHERE bot_id=? AND id=?',(bot_id,identifier)).fetchone()
        if not row:
            raise HTTPException(404,'互动记录不存在')
        if row['status']!='unknown':
            raise HTTPException(409,'仅可核对结果未知的互动，不能重新提交')
        return {'operation_id':row['id'],'account_id':row['account'],'op':row['op'],**json.loads(row['payload'])}

    def reconcile(self, bot_id, identifier, result):
        grant=self.verification_grant(bot_id,identifier)
        if any(result.get(k)!=grant[k] for k in ('operation_id','account_id','op')) or result.get('reconciled') is not True:
            raise HTTPException(409,'核对结果与原账号或互动不匹配')
        confirmed=result.get('status')=='confirmed'
        if confirmed:
            valid=(grant['op']=='like' and result.get('video_id')==grant.get('video_id') and result.get('liked') is True and result.get('evidence')=='fresh_video_detail'
                or grant['op'] in ('comment','reply_comment') and result.get('video_id')==grant.get('video_id') and result.get('cid') and result.get('evidence')=='own_published_comment'
                or grant['op']=='share' and result.get('video_id')==grant.get('video_id') and result.get('peer_id')==grant.get('peer_id') and result.get('message_id') and result.get('evidence')=='owner_conversation_card')
            if not valid:raise HTTPException(409,'核对缺少可靠平台证据')
        # Absence is not proof of rejection; unknowns continue reserving quota.
        receipt={**result,'status':'confirmed' if confirmed else 'unknown','checked_at':time.time()}
        with self.db:
            self.db.execute('INSERT INTO douyin_operation_checks(operation_id,status,receipt,checked) VALUES (?,?,?,?)',
                (identifier,receipt['status'],json.dumps(receipt,ensure_ascii=False),receipt['checked_at']))
            self.db.execute("UPDATE douyin_operations SET status=?,receipt=?,updated=? WHERE bot_id=? AND id=? AND status='unknown'",
                (receipt['status'],json.dumps(receipt,ensure_ascii=False),receipt['checked_at'],bot_id,identifier))
        return receipt
