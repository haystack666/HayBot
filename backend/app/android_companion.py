"""Bounded video evidence and durable public-interaction permissions.
No private persona, dialogue, memory or schedule is accepted by draft generation.
"""
import asyncio
import base64
import io
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
from PIL import Image
from .config import StrictModel
from .android_intent import interest_scope

PLATFORMS={'douyin':'com.ss.android.ugc.aweme','bilibili':'tv.danmaku.bili','xiaohongshu':'com.xingin.xhs'}

class PlatformPolicy(StrictModel):
    comments: bool=False
    posting_account_id: str=Field(default='',max_length=128)
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
    owner_interests: str=Field(default='',max_length=2000)
    character_interest_mode: Literal['persona','custom']='custom'
    character_interests: str=Field(default='',max_length=2000)
    content_constraints: str=Field(default='',max_length=2000)
    buffering_wait_seconds: int=Field(default=120,ge=30,le=600)
    video_enabled: bool=True
    frame_interval_seconds: int=Field(default=3,ge=1,le=10)
    batch_frames: int=Field(default=6,ge=3,le=8)
    public_persona: str=Field(default='',max_length=1000)
    platforms: dict[Literal['douyin','bilibili','xiaohongshu'],PlatformPolicy]=Field(default_factory=dict)


def interest_material(config,persona,goal=''):
    character=config.character_interests  # Legacy mode is accepted on read, never infers interests from persona.
    scope=interest_scope(goal)
    if scope=='owner':return config.owner_interests.strip()
    if scope=='shared':return '\n'.join(x for x in (character,config.owner_interests) if x.strip())
    return character.strip()


def interest_options(material):
    return {f'兴趣{i+1}':part[:500] for i,part in enumerate([p.strip() for p in re.split(r'[\n。；]+',material) if p.strip()][:30])}


def resolve_interest_basis(basis,material):
    basis=basis.strip()
    if basis in interest_options(material):return interest_options(material)[basis]
    if basis and basis in material:return basis
    if not material.strip() and basis=='本次探索':return basis
    return ''


def video_buffering(tree):
    return platform_on_screen(tree)=='bilibili' and bool(re.search(r'正在缓冲|缓冲中|加载视频中', ' '.join(n.get('text','')+' '+n.get('content-desc','') for n in ui_nodes(tree))))


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


def share_control(tree,x,y):
    target=target_text(tree,x,y).strip()
    return bool(re.match(r'^(?:复制(?:分享)?链接|copy link|分享)(?:\s|$|[，,]\s*\d+个分享)',target,re.I) or re.search(r'/(?:frame_share|share|share_button)\s*$',target,re.I))


def exact_identity(text, identity):
    return bool(identity and re.search(r'(?<![A-Za-z0-9_])'+re.escape(identity)+r'(?![A-Za-z0-9_])',text))


def mention_in_editor(text, owner_name, body):
    return text.strip() in {f'@{owner_name} {body}',f'{body} @{owner_name}',f'@{owner_name}{body}'}


def blue_mention_editor(observation, owner_name):
    """Corroborate candidate selection with a blue token in the empty editor.

    UI XML does not expose Android text spans. Check before the body is entered,
    so blue comment text cannot be mistaken for the mention token.
    """
    try:
        with Image.open(io.BytesIO(base64.b64decode(observation.get('image',''),validate=True))) as image:
            image=image.convert('RGB')
            for n in ui_nodes(observation.get('hierarchy','')):
                a=n.attrib
                if 'EditText' not in a.get('class','') or a.get('text','').strip()!='@'+owner_name:continue
                m=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',a.get('bounds',''))
                if not m:continue
                x,y,x2,y2=map(int,m.groups())
                if not 0<=x<x2<=image.width or not 0<=y<y2<=image.height:continue
                # Require blue across several columns, excluding a thin caret.
                columns=set()
                for px in range(x+2,x2-2):
                    for py in range(y+2,y2-2):
                        r,g,b=image.getpixel((px,py))
                        if b>120 and b-r>35 and g-r>15:columns.add(px);break
                if len(columns)>=8:return True
    except (ValueError,OSError):pass
    return False


def content_anchors(tree):
    anchors=[]
    for node in ui_nodes(tree):
        a=node.attrib;text=a.get('text','').strip();rid=a.get('resource-id','').lower()
        if len(text)>=2 and re.search(r'title|desc|author|user_name|nickname|note_name|video_name',rid) and 'EditText' not in a.get('class',''):
            anchors.append(text[:500])
    return list(dict.fromkeys(anchors))[:8]


def bilibili_inline_metadata(nodes):
    """Compose intro: official BV follows play count, danmaku and timestamp."""
    if not any(n.get('package')==PLATFORMS['bilibili'] and n.get('text','').strip()=='简介' for n in nodes):return None
    matches=[]
    for index,node in enumerate(nodes):
        if node.get('package')!=PLATFORMS['bilibili']:continue
        text=node.get('text','').strip()
        if not re.match(r'^playCount\S+\s+danmaku\S+\s+\d{4}年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2}\s+BV[A-Za-z0-9]{10}\s*$',text):continue
        title=next((n.get('text','').strip() for n in reversed(nodes[:index]) if n.get('package')==PLATFORMS['bilibili'] and n.get('text','').strip()),'')
        if title and title not in ('简介','评论') and not title.startswith('评论（'):
            matches.append((title,re.search(r'BV[A-Za-z0-9]{10}',text).group()))
    return matches[0] if len(matches)==1 else None


def page_context(tree,platform):
    """Conservative local identity from observed video metadata, never model IDs."""
    package=PLATFORMS.get(platform)
    titles=[];authors=[];nodes=ui_nodes(tree)
    if platform=='bilibili':
        # The detail page shares id/title with ads and recommendations. Scope
        # identity to the main title between the author header and play stats.
        primary_authors=[n for n in nodes if n.get('resource-id','').endswith('/author_name') and n.get('text')]
        if len(primary_authors)==1 and any(n.get('resource-id','').endswith('/views') for n in nodes):
            start=nodes.index(primary_authors[0]);tail=nodes[start+1:]
            end=next((i for i,n in enumerate(tail) if n.get('resource-id','').endswith('/views')),len(tail))
            primary_titles=[n.get('text','').strip() for n in tail[:end] if n.get('resource-id','').endswith(('/title','/video_title')) and n.get('text','').strip()]
            if len(primary_titles)==1:
                anchors=[primary_titles[0],primary_authors[0].get('text','').strip()]
                return identified_context(platform,anchors,nodes)
    if platform=='bilibili':
        inline=bilibili_inline_metadata(nodes)
        if inline:return identified_context(platform,[inline[0]],nodes)
    if not any(re.search(r'comment_layout|video_title|video_detail|player_container|note_title',n.attrib.get('resource-id','')) for n in nodes):return None
    for n in nodes:
        a=n.attrib
        if a.get('package')!=package:continue
        rid=a.get('resource-id','').rsplit('/',1)[-1]
        text=' '.join(a.get('text','').splitlines()[:1]).strip()
        if not text or len(text)>500 or 'EditText' in a.get('class',''):continue
        if rid in ('title','video_title','note_title') and text not in ('热门评论','全部评论','评论','简介'):
            titles.append(text)
        if rid in ('up_name','author_name') or rid in ('name','nickname') and not re.search(r'热门评论|全部评论|最新评论|按热度|primary_message|comment_list|reply_list',tree):
            authors.append(text)
    titles=list(dict.fromkeys(titles));authors=list(dict.fromkeys(authors))
    # A feed with several visible videos is not a unique content page.
    if len(titles)!=1 or len(authors)!=1:return None
    anchors=[titles[0],authors[0]]
    return identified_context(platform,anchors,nodes)


def identified_context(platform,anchors,nodes):
    fingerprint=hashlib.sha256(json.dumps([platform,*anchors],ensure_ascii=False).encode()).hexdigest()
    fallback='ui:v1:'+fingerprint
    identifiers=set()
    if platform=='bilibili':
        inline=bilibili_inline_metadata(nodes)
        if inline:identifiers.add('bilibili:'+inline[1])
        intro=any(n.get('text','').strip()=='简介' or n.get('content-desc','').strip()=='简介' for n in nodes)
        for node in nodes:
            # Do not extract IDs from comments or unrelated recommendations.
            value=node.get('text','')+' '+node.get('content-desc','')
            dedicated=node.get('resource-id','').rsplit('/',1)[-1] in ('bvid','aid','video_id','share_url','video_url')
            labelled=bool(re.fullmatch(r'\s*(?:BV号[：:]?\s*)?BV[A-Za-z0-9]{10}\s*',value))
            # Bilibili's expanded intro puts the official BV first in id/desc,
            # followed by description and tags in the same accessibility node.
            if intro and node.get('resource-id')=='tv.danmaku.bili:id/desc':
                leading=re.match(r'\s*(BV[A-Za-z0-9]{10})(?=\s|$)',node.get('text',''))
                if leading:identifiers.add('bilibili:'+leading.group(1))
                continue
            if not dedicated and not (intro and labelled):continue
            identifiers.update('bilibili:'+m for m in re.findall(r'(?<![A-Za-z0-9])(BV[A-Za-z0-9]{10}|av\d+)(?![A-Za-z0-9])',value))
    return {'platform':platform,'content_id':sorted(identifiers)[0] if identifiers else fallback,'anchors':anchors,'identity_aliases':sorted(identifiers|{fallback}),'identity_source':'platform_id' if identifiers else 'title_author_fallback'}


def comment_surface(tree):
    return bool(re.search(r'评论|回复|comment|reply|选择.*@|@的人|@提及用户候选|请输入或搜索想@',tree,re.I)) or any(n.get('resource-id','')=='tv.danmaku.bili:id/edit' for n in ui_nodes(tree))


def bind_page_context(observation,previous=None):
    tree=observation.get('hierarchy','');platform=platform_on_screen(tree)
    if not platform or login_screen(tree):return None
    current=page_context(tree,platform)
    if current:
        if previous and current['platform']==previous['platform'] and len(current['anchors'])==1 and len(previous.get('anchors',[]))>=2 and current['anchors'][0]==previous['anchors'][0]:
            if previous['content_id'].startswith('bilibili:') and previous['content_id']!=current['content_id']:return current
            merged=identified_context(platform,previous['anchors'],ui_nodes(tree))
            return merged
        if previous and current['platform']==previous['platform'] and current.get('anchors')==previous.get('anchors') and previous.get('content_id','').startswith('bilibili:') and current['content_id'].startswith('ui:v1:'):return previous
        return current
    if previous and previous['platform']==platform and comment_surface(tree):
        for n in ui_nodes(tree):
            rid=n.attrib.get('resource-id','').rsplit('/',1)[-1]
            text=' '.join(n.attrib.get('text','').splitlines()[:1]).strip()
            if rid in ('title','video_title','note_title') and text and text not in ('热门评论','全部评论','评论','简介','选择要@的人','选择联系人','@的人') and text!=previous['anchors'][0]:return None
        return previous
    return None


def keeps_page_context(tree,action):
    """Only known comment controls may carry identity into an overlay.

    Unknown taps, video swipes, launching apps and opening URLs invalidate it.
    A task holds the device lease, so manual takeover also fences this context.
    """
    kind=action['kind']
    if kind=='wait':return True
    if kind=='text':return public_editor(tree) or comment_surface(tree)
    if kind=='key':return action.get('key') in ('back','delete') and comment_surface(tree)
    if kind!='tap':return False
    x,y=action['x'],action['y'];hits=[]
    for n in ui_nodes(tree):
        a=n.attrib
        if a.get('package') not in PLATFORMS.values():continue
        m=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',a.get('bounds',''))
        if not m:continue
        left,top,right,bottom=map(int,m.groups())
        if left<=x<right and top<=y<bottom:
            rid=a.get('resource-id','').rsplit('/',1)[-1]
            label=a.get('text','') or a.get('content-desc','')
            if rid or label:hits.append(((right-left)*(bottom-top),rid,label,a.get('class','')))
    if platform_on_screen(tree)=='bilibili':
        # Compose toolbar has unlabeled nodes. Its @ cell is the second
        # square after the small "转到动态" control, aligned below id/edit.
        for n in ui_nodes(tree):
            if n.get('resource-id','')!='tv.danmaku.bili:id/edit':continue
            m=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',n.get('bounds',''))
            if m:
                left,top,right,bottom=map(int,m.groups())
                if left+(right-left)*0.24<=x<left+(right-left)*0.35 and bottom<=y<bottom+(right-left)*0.11:return True
    if not hits:return False
    _,rid,label,cls=min(hits)
    return 'EditText' in cls or rid in ('comment_layout','comment_icon','comment_text','comment','comment_editor','reply_editor','input','at','mention') or bool(re.fullmatch(r'评论(?:[（(].*?[）)])?|添加@|@某人|@',label))


def same_content(draft,tree,context=None):
    if draft.get('content_id','').startswith(('bilibili:','ui:v1:')):
        current=bind_page_context({'hierarchy':tree},context)
        if not current or current['platform']!=draft['platform']:return False
        old=draft['content_id'];new=current['content_id']
        if old.startswith('bilibili:') and new.startswith('bilibili:'):return old==new
        return old==new or old in current.get('identity_aliases',[]) or new in draft.get('identity_aliases',[]) or bool(draft.get('anchors') and draft['anchors']==current.get('anchors'))
    texts={n.attrib.get('text','').strip() for n in ui_nodes(tree)}
    # All recorded public title/author anchors must still be visible.
    anchors=draft.get('anchors',[])
    return len(anchors)>=2 and all(a in texts for a in anchors)


def empty_editor(node):
    if 'EditText' not in node.get('class',''):return False
    text=node.get('text','').strip();hint=node.get('hint','').strip()
    return not text or bool(hint and text==hint) or bool(re.fullmatch(r'评论千万条，等你发一条|发一条友善的评论|不发没关系.*|轻轻敲醒.*|说点什么.*|添加评论.*|发表评论.*|写评论.*',text))


def model_ui_tree(tree):
    """Keep app controls ahead of keyboard noise and distinguish hints from input."""
    try:root=ET.fromstring(tree)
    except ET.ParseError:return tree
    compact=ET.Element('hierarchy')
    for node in root.iter('node'):
        package=node.get('package','')
        if package=='com.android.systemui' or 'inputmethod' in package:continue
        attrs={key:node.get(key) for key in ('package','resource-id','class','text','hint','content-desc','bounds','focused','clickable','scrollable','enabled','selected') if node.get(key)}
        if 'EditText' in node.get('class','') and node.get('hint') and node.get('text')==node.get('hint'):
            attrs['text']=''
        if attrs.get('text') or attrs.get('hint') or attrs.get('content-desc') or 'EditText' in attrs.get('class','') or any(attrs.get(key)=='true' for key in ('clickable','scrollable')):
            ET.SubElement(compact,'node',attrs)
    return ET.tostring(compact,encoding='unicode')


def public_editor(tree):
    if not comment_surface(tree) and not re.search(r'说点什么',tree,re.I):return False
    for n in ui_nodes(tree):
        a=n.attrib
        if 'EditText' not in a.get('class',''):continue
        if re.search(r'search|搜索',' '.join(a.get(k,'') for k in ('resource-id','hint','content-desc')),re.I):continue
        text=a.get('text','').strip()
        if a.get('focused')=='true' or not empty_editor(n):return True
    return False


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
        self.db.execute('CREATE TABLE IF NOT EXISTS publication_identities(account_id TEXT,platform TEXT,identity TEXT,publication_id TEXT,PRIMARY KEY(account_id,platform,identity))')
        if 'anchors' not in {r['name'] for r in self.db.execute('PRAGMA table_info(publications)')}:
            with self.db:self.db.execute("ALTER TABLE publications ADD COLUMN anchors TEXT NOT NULL DEFAULT '[]'")
        with self.db:self.db.execute("UPDATE publications SET state='unknown',detail='服务重启，未重试发布' WHERE state='sending'")
    def close(self):self.db.close()
    def list(self,bot_id):return [dict(r) for r in self.db.execute('SELECT * FROM publications WHERE bot_id=? ORDER BY created DESC LIMIT 50',(bot_id,))]
    def seen(self,account_id,platform,content_id,anchors=None,aliases=None):
        if any(self.db.execute('SELECT 1 FROM publication_identities WHERE account_id=? AND platform=? AND identity=?',(account_id,platform,identity)).fetchone() for identity in {content_id,*(aliases or [])}):return True
        rows=self.db.execute('SELECT content_id,anchors FROM publications WHERE account_id=? AND platform=? AND state!=?',(account_id,platform,'cancelled')).fetchall()
        wanted={a.strip() for a in anchors or []}
        return any(r['content_id']==content_id or len(wanted)>=2 and wanted<={a.strip() for a in json.loads(r['anchors'])} for r in rows)
    def availability(self,bot_id,account_id,platform,cfg,now=None):
        policy=cfg.platforms.get(platform,PlatformPolicy())
        if not policy.comments:return {'allowed':False,'reason':'此平台未授权自主评论'}
        now=time.time() if now is None else now
        day=datetime.fromtimestamp(now,ZoneInfo('Asia/Shanghai')).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        rows=self.db.execute('SELECT created FROM publications WHERE bot_id=? AND account_id=? AND platform=? AND state IN ("sending","unknown","verified") ORDER BY created DESC',(bot_id,account_id,platform)).fetchall()
        count=sum(r['created']>=day for r in rows)
        if count>=policy.daily_limit:return {'allowed':False,'reason':'已达到当日评论上限','daily_count':count}
        remaining=max(0,rows[0]['created']+policy.cooldown_minutes*60-now) if rows else 0
        if remaining:return {'allowed':False,'reason':'尚未达到评论冷却时间','retry_after_seconds':int(remaining)+1,'daily_count':count}
        return {'allowed':True,'daily_count':count}
    def bind_account(self,bot_id,platform,previous,current):
        """First explicit account binding retains this bot's legacy reservations."""
        if previous==current:return
        rows=self.db.execute('SELECT id,content_id FROM publications WHERE bot_id=? AND account_id=? AND platform=?',(bot_id,previous,platform)).fetchall()
        try:
            with self.db:
                for row in rows:
                    identities={row['content_id'],*(r['identity'] for r in self.db.execute('SELECT identity FROM publication_identities WHERE publication_id=?',(row['id'],)))}
                    for identity in identities:self.db.execute('INSERT OR IGNORE INTO publication_identities VALUES (?,?,?,?)',(current,platform,identity,row['id']))
                self.db.execute('UPDATE publications SET account_id=? WHERE bot_id=? AND account_id=? AND platform=?',(current,bot_id,previous,platform))
        except sqlite3.IntegrityError:raise ValueError('旧评论记录与新平台账号记录冲突，未修改账号绑定；请核对实际登录账号') from None
    def reserve(self,bot_id,account_id,platform,content_id,text,mention,cfg,anchors=None,aliases=None):
        import uuid
        policy=cfg.platforms.get(platform,PlatformPolicy())
        if not policy.comments:raise ValueError('此平台未授权自主评论')
        if mention and (not policy.mentions or not policy.owner_id.strip() or not policy.owner_name.strip()):raise ValueError('此平台未授权 @ 或未配置 owner 账号')
        if not content_id.strip() or len(content_id)>500 or not text.strip() or len(text)>1000:raise ValueError('缺少可靠内容标识或有效评论')
        if self.seen(account_id,platform,content_id,anchors,aliases):raise ValueError('当前平台账号已为此内容创建评论记录，不重复评论；请选择其他视频')
        if content_id.startswith('ui:v1:') and anchors:
            prior=self.db.execute('SELECT anchors FROM publications WHERE bot_id=? AND account_id=? AND platform=?',(bot_id,account_id,platform)).fetchall()
            for row in prior:
                observed={' '.join(a.splitlines()[:1]).strip() for a in json.loads(row['anchors']) if isinstance(a,str)}
                if len(set(anchors))>=2 and set(anchors)<=observed:raise ValueError('此内容已有评论记录，不重复发布')
        now=time.time()
        available=self.availability(bot_id,account_id,platform,cfg,now)
        if not available['allowed']:raise ValueError(available['reason'])
        ident=uuid.uuid4().hex
        try:
            with self.db:
                self.db.execute('INSERT INTO publications VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(ident,bot_id,account_id,platform,content_id,text,int(mention),'draft','待编辑与核对',now,policy.owner_id,json.dumps(anchors or [],ensure_ascii=False)))
                for identity in {content_id,*(aliases or [])}:self.db.execute('INSERT INTO publication_identities VALUES (?,?,?,?)',(account_id,platform,identity,ident))
        except sqlite3.IntegrityError:raise ValueError('此内容已经评论或结果未知，不重复发布') from None
        return ident
    def get(self,bot_id,ident):
        row=self.db.execute('SELECT * FROM publications WHERE id=? AND bot_id=?',(ident,bot_id)).fetchone()
        if not row:raise ValueError('评论草稿不存在')
        result=dict(row);result['anchors']=json.loads(result['anchors']);return result
    def finish(self,ident,state,detail):
        if state not in ('draft','mention_selected','sending','verified','unknown','cancelled'):raise ValueError('评论状态无效')
        with self.db:self.db.execute('UPDATE publications SET state=?,detail=? WHERE id=?',(state,detail[:1000],ident))
