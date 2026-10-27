"""Bounded video evidence and durable public-interaction permissions.
No private persona, dialogue, memory or schedule is accepted by draft generation.
"""
import asyncio
import hashlib
import json
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Literal
from pydantic import Field, model_validator
from .config import StrictModel

PLATFORMS={'douyin':'com.ss.android.ugc.aweme','bilibili':'tv.danmaku.bili','xiaohongshu':'com.xingin.xhs'}

class PlatformPolicy(StrictModel):
    comments: bool=False
    mentions: bool=False
    owner_id: str=Field(default='',max_length=128)
    owner_name: str=Field(default='',max_length=80)
    cooldown_minutes: int=Field(default=30,ge=0,le=1440)
    daily_limit: int=Field(default=5,ge=1,le=100)

    @model_validator(mode='after')
    def mention_binding(self):
        if self.mentions and (not self.comments or not self.owner_id.strip() or not self.owner_name.strip()):
            raise ValueError('开启 @ 前请允许评论并填写 owner 账号 ID 和昵称')
        return self

class CompanionConfig(StrictModel):
    video_enabled: bool=True
    frame_interval_seconds: int=Field(default=3,ge=1,le=10)
    batch_frames: int=Field(default=6,ge=3,le=8)
    public_persona: str=Field(default='',max_length=1000)
    platforms: dict[Literal['douyin','bilibili','xiaohongshu'],PlatformPolicy]=Field(default_factory=dict)


def login_screen(tree):
    try:nodes=ET.fromstring(tree).iter('node')
    except ET.ParseError:return False
    for node in nodes:
        a=node.attrib
        if a.get('password')=='true':return True
        if 'EditText' in a.get('class',''):
            context=' '.join(a.get(k,'') for k in ('text','content-desc','resource-id','hint')).lower()
            if any(k in context for k in ('验证码','手机号','密码','verification','password','phone_number','otp')):return True
    return False


def ui_nodes(tree):
    try:return list(ET.fromstring(tree).iter('node'))
    except ET.ParseError:return []


def platform_on_screen(tree):
    packages={node.attrib.get('package') for node in ui_nodes(tree)}
    found=[key for key,pkg in PLATFORMS.items() if pkg in packages or key=='douyin' and 'com.ss.android.ugc.aweme.mobile' in packages]
    return found[0] if len(found)==1 else ''


def target_text(tree,x,y):
    hits=[]
    for node in ui_nodes(tree):
        bounds=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',node.attrib.get('bounds',''))
        if not bounds:continue
        a,b,c,d=map(int,bounds.groups())
        if a<=x<c and b<=y<d:
            text=' '.join(node.attrib.get(k,'') for k in ('text','content-desc','resource-id'))
            if text.strip():hits.append(((c-a)*(d-b),text))
    return min(hits,default=(0,''))[1]


def exact_identity(text, identity):
    return bool(identity and re.search(r'(?<![A-Za-z0-9_])'+re.escape(identity)+r'(?![A-Za-z0-9_])',text))


def mention_in_editor(text, owner_name, body):
    return text.strip() in {f'@{owner_name} {body}',f'{body} @{owner_name}',f'@{owner_name}{body}'}


def content_anchors(tree):
    anchors=[]
    for node in ui_nodes(tree):
        a=node.attrib;text=a.get('text','').strip();rid=a.get('resource-id','').lower()
        if len(text)>=2 and re.search(r'title|desc|author|user_name|nickname|note_name|video_name',rid) and 'EditText' not in a.get('class',''):
            anchors.append(text[:500])
    return list(dict.fromkeys(anchors))[:8]


def same_content(draft,tree):
    texts={n.attrib.get('text','').strip() for n in ui_nodes(tree)}
    # All recorded public title/author anchors must still be visible.
    anchors=draft.get('anchors',[])
    return len(anchors)>=2 and all(a in texts for a in anchors)


def public_editor(tree):
    return any('EditText' in n.attrib.get('class','') for n in ui_nodes(tree)) and bool(re.search(r'评论|回复|comment|reply|说点什么',tree,re.I))


class VideoBuffer:
    def __init__(self,observe,interval=3,limit=8):
        self.observe=observe;self.interval=interval;self.frames=deque(maxlen=limit)
        self.job=None;self.changed=asyncio.Event();self.error=None;self.total=0;self.started=None;self.last=None
    async def start(self):
        self.job=asyncio.create_task(self._run())
    async def _run(self):
        try:
            while True:
                frame=await self.observe()
                if login_screen(frame.get('hierarchy','')):raise ValueError('检测到登录或验证码页面，请 owner 接管')
                stamp=frame.get('at',time.time())
                if self.started is None:self.started=stamp
                self.last=stamp;self.total+=1
                digest=hashlib.sha256(frame['image'].encode()).hexdigest()
                # Keep timestamp changes even for duplicate frames; only drop bitmap duplicates.
                if not self.frames or self.frames[-1]['digest']!=digest:self.frames.append({**frame,'digest':digest})
                self.changed.set()
                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:raise
        except Exception as exc:self.error=exc;self.changed.set()
    async def wait_batch(self,count):
        initial=self.total
        while self.total-initial<count:
            self.changed.clear()
            if self.error:raise self.error
            await self.changed.wait()
    def snapshot(self):
        if self.error:raise self.error
        return {'frames':list(self.frames),'observed_seconds':max(0,(self.last or 0)-(self.started or 0)),'sampled_frames':self.total,'audio_available':False}
    async def close(self):
        if self.job:
            self.job.cancel();await asyncio.gather(self.job,return_exceptions=True)


class SocialJournal:
    def __init__(self,path):
        self.db=sqlite3.connect(Path(path),check_same_thread=False);self.db.row_factory=sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS publications(id TEXT PRIMARY KEY,bot_id TEXT,account_id TEXT,platform TEXT,
            content_id TEXT,text TEXT,mention INTEGER,state TEXT,detail TEXT,created REAL,owner_id TEXT,
            UNIQUE(bot_id,account_id,platform,content_id));''')
        if 'anchors' not in {r['name'] for r in self.db.execute('PRAGMA table_info(publications)')}:
            with self.db:self.db.execute("ALTER TABLE publications ADD COLUMN anchors TEXT NOT NULL DEFAULT '[]'")
        with self.db:self.db.execute("UPDATE publications SET state='unknown',detail='服务重启，未重试发布' WHERE state='sending'")
    def close(self):self.db.close()
    def list(self,bot_id):return [dict(r) for r in self.db.execute('SELECT * FROM publications WHERE bot_id=? ORDER BY created DESC LIMIT 50',(bot_id,))]
    def reserve(self,bot_id,account_id,platform,content_id,text,mention,cfg,anchors=None):
        import uuid
        policy=cfg.platforms.get(platform,PlatformPolicy())
        if not policy.comments:raise ValueError('此平台未授权自主评论')
        if mention and (not policy.mentions or not policy.owner_id.strip() or not policy.owner_name.strip()):raise ValueError('此平台未授权 @ 或未配置 owner 账号')
        if not content_id.strip() or len(content_id)>500 or not text.strip() or len(text)>1000:raise ValueError('缺少可靠内容标识或有效评论')
        now=time.time();day=datetime.fromtimestamp(now,ZoneInfo('Asia/Shanghai')).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        rows=self.db.execute('SELECT created FROM publications WHERE bot_id=? AND account_id=? AND platform=? ORDER BY created DESC',(bot_id,account_id,platform)).fetchall()
        if sum(r['created']>=day for r in rows)>=policy.daily_limit:raise ValueError('已达到当日评论上限')
        if rows and now-rows[0]['created']<policy.cooldown_minutes*60:raise ValueError('尚未达到评论冷却时间')
        ident=uuid.uuid4().hex
        try:
            with self.db:self.db.execute('INSERT INTO publications VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(ident,bot_id,account_id,platform,content_id,text,int(mention),'draft','待编辑与核对',now,policy.owner_id,json.dumps(anchors or [],ensure_ascii=False)))
        except sqlite3.IntegrityError:raise ValueError('此内容已经评论或结果未知，不重复发布') from None
        return ident
    def get(self,bot_id,ident):
        row=self.db.execute('SELECT * FROM publications WHERE id=? AND bot_id=?',(ident,bot_id)).fetchone()
        if not row:raise ValueError('评论草稿不存在')
        result=dict(row);result['anchors']=json.loads(result['anchors']);return result
    def finish(self,ident,state,detail):
        if state not in ('draft','mention_selected','sending','verified','unknown','cancelled'):raise ValueError('评论状态无效')
        with self.db:self.db.execute('UPDATE publications SET state=?,detail=? WHERE id=?',(state,detail[:1000],ident))
