"""Account-scoped public drafts, assets, policies and durable publish state."""
import hashlib
import io
import json
import time
import uuid
from pathlib import Path
from typing import Annotated,Literal

from PIL import Image,ImageOps
from pydantic import Field,field_validator,model_validator
from .config import StrictModel,ProactiveConfig
from .memes import checked_image


QQNumber=Annotated[str,Field(pattern=r'^[1-9][0-9]{4,19}$')]
ImageId=Annotated[str,Field(pattern=r'^[a-f0-9]{64}$')]


class Audience(StrictModel):
    visibility: Literal[1,4,16,64,128]=64
    targets: list[QQNumber]=Field(default_factory=list,max_length=100)

    @model_validator(mode='after')
    def validate_audience(self):
        if self.visibility in (16,128) and not self.targets:raise ValueError('指定可见范围时请填写 QQ 号')
        self.targets=list(dict.fromkeys(self.targets))
        if self.visibility not in (16,128):self.targets=[]
        return self


class PostWrite(Audience):
    content: str=Field(min_length=1,max_length=2000)
    images: list[ImageId]=Field(default_factory=list,max_length=9)
    scheduled_at: float|None=Field(default=None,ge=0,allow_inf_nan=False)

    @field_validator('content')
    @classmethod
    def text(cls,value):
        value=value.strip()
        if not value:raise ValueError('请输入动态正文')
        return value


class QzoneConfig(Audience):
    auto_enabled: bool=False
    owner_id: str=Field(default='',pattern=r'^(?:[1-9][0-9]{4,19})?$')
    active_start: str=Field(default='07:00',pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    active_end: str=Field(default='00:00',pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    interval_min_minutes: int=Field(default=60,ge=5,le=1440)
    interval_max_minutes: int=Field(default=240,ge=5,le=1440)
    event_min_minutes: int=Field(default=5,ge=1,le=1440)
    event_max_minutes: int=Field(default=25,ge=1,le=1440)
    cooldown_minutes: int=Field(default=30,ge=0,le=1440)
    daily_limit: int=Field(default=3,ge=0,le=1000)
    share_probability: float=Field(default=.5,ge=0,le=1,allow_inf_nan=False)
    timezone: str='Asia/Shanghai'
    times: list[Annotated[str,Field(pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')]]=Field(default_factory=lambda:['12:00'],max_length=8)
    mode: Literal['generated','fixed']='generated'
    content: str=Field(default='',max_length=2000)
    instruction: str=Field(default='用自然口吻分享一条简短的角色生活感想。',max_length=2000)
    public_context: str=Field(default='',max_length=4000)

    @field_validator('timezone')
    @classmethod
    def zone(cls,value):return ProactiveConfig.valid_timezone(value)

    @model_validator(mode='after')
    def valid_schedule(self):
        if len(set(self.times))!=len(self.times):raise ValueError('发布时间不能重复')
        if self.interval_max_minutes<self.interval_min_minutes or self.event_max_minutes<self.event_min_minutes:
            raise ValueError('随机间隔上限不能小于下限')
        if self.auto_enabled and self.mode=='fixed' and not self.content.strip():raise ValueError('请填写固定发布内容')
        return self


class QzoneStore:
    def __init__(self,store):
        self.store,self.db=store,store.db
        self.clock=time.time
        root=Path(self.db.execute('PRAGMA database_list').fetchone()[2]).parent
        self.assets=root/'qzone-assets';self.assets.mkdir(exist_ok=True)
        self.db.executescript('''CREATE TABLE IF NOT EXISTS qzone_config(account_id TEXT PRIMARY KEY,value TEXT NOT NULL,epoch INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS qzone_posts(id TEXT PRIMARY KEY,account_id TEXT NOT NULL,content TEXT NOT NULL,
            images TEXT NOT NULL,visibility INTEGER NOT NULL,targets TEXT NOT NULL,scheduled_at REAL,status TEXT NOT NULL,
            tid TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',created REAL NOT NULL,updated REAL NOT NULL,
            origin TEXT NOT NULL,origin_key TEXT NOT NULL,epoch INTEGER NOT NULL,UNIQUE(account_id,origin_key));
            CREATE TABLE IF NOT EXISTS qzone_images(account_id TEXT NOT NULL,id TEXT NOT NULL,name TEXT NOT NULL,
            size INTEGER NOT NULL,created REAL NOT NULL,PRIMARY KEY(account_id,id));
            CREATE INDEX IF NOT EXISTS qzone_page ON qzone_posts(account_id,created DESC,id);
            CREATE INDEX IF NOT EXISTS qzone_due ON qzone_posts(account_id,status,scheduled_at);''')
        columns={row['name'] for row in self.db.execute('PRAGMA table_info(qzone_posts)')}
        for field in ('source_owner','source_stamp','trigger'):
            if field not in columns:self.db.execute(f"ALTER TABLE qzone_posts ADD COLUMN {field} TEXT NOT NULL DEFAULT ''")
        with self.db:
            self.db.execute("UPDATE qzone_posts SET status='unknown',error='发布时服务中断，结果未知，不自动重发' WHERE status='sending'")
            self.db.execute("UPDATE qzone_posts SET status='delete_unknown',error='删除时服务中断，请在 QQ 空间核对' WHERE status='deleting'")
            self.db.execute("UPDATE qzone_posts SET status='failed',error='服务中断，尚未发送，请手动重新操作' WHERE status IN ('queued','generating')")

    def config(self,account):
        row=self.db.execute('SELECT * FROM qzone_config WHERE account_id=?',(account,)).fetchone()
        return (QzoneConfig.model_validate_json(row['value']),row['epoch']) if row else (QzoneConfig(),0)

    def save_config(self,account,value):
        _,epoch=self.config(account)
        with self.db:self.db.execute('INSERT OR REPLACE INTO qzone_config VALUES (?,?,?)',(account,value.model_dump_json(),epoch+1))

    def decode(self,row):
        if row is None:raise ValueError('当前账号中不存在此动态')
        value=dict(row)
        for key in ('images','targets'):value[key]=json.loads(value[key])
        return value

    def get(self,account,pid):return self.decode(self.db.execute('SELECT * FROM qzone_posts WHERE account_id=? AND id=?',(account,pid)).fetchone())

    def list(self,account,offset=0,limit=30):
        return {'items':[self.decode(r) for r in self.db.execute('SELECT * FROM qzone_posts WHERE account_id=? ORDER BY created DESC,id LIMIT ? OFFSET ?',(account,limit,offset))],
            'total':self.db.execute('SELECT COUNT(*) FROM qzone_posts WHERE account_id=?',(account,)).fetchone()[0]}

    def create(self,account,value,origin='manual',origin_key=None,epoch=0,now=None):
        now=self.clock() if now is None else now
        for mid in value.images:self.image(account,mid)
        if value.scheduled_at is not None and value.scheduled_at<now:raise ValueError('定时发布时间必须在未来')
        pid=uuid.uuid4().hex
        with self.db:self.db.execute('''INSERT OR IGNORE INTO qzone_posts
            (id,account_id,content,images,visibility,targets,scheduled_at,status,created,updated,origin,origin_key,epoch)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',(pid,account,value.content,json.dumps(value.images),value.visibility,json.dumps(value.targets),value.scheduled_at,
                'scheduled' if value.scheduled_at else 'draft',now,now,origin,origin_key or pid,epoch))
        row=self.db.execute('SELECT id FROM qzone_posts WHERE account_id=? AND origin_key=?',(account,origin_key or pid)).fetchone()
        return self.get(account,row['id'])

    def update(self,account,pid,value):
        row=self.get(account,pid)
        if row['status'] not in ('draft','scheduled','failed'):raise ValueError('此动态不能编辑')
        if value.scheduled_at is not None and value.scheduled_at<=self.clock():raise ValueError('请选择未来时间')
        for mid in value.images:self.image(account,mid)
        with self.db:self.db.execute('UPDATE qzone_posts SET content=?,images=?,visibility=?,targets=?,scheduled_at=?,status=?,updated=?,error=? WHERE id=? AND account_id=?',
            (value.content,json.dumps(value.images),value.visibility,json.dumps(value.targets),value.scheduled_at,'scheduled' if value.scheduled_at else 'draft',self.clock(),'',pid,account))
        return self.get(account,pid)

    def state(self,account,pid,status,error='',tid=None):
        with self.db:
            self.db.execute('UPDATE qzone_posts SET status=?,error=?,updated=?,tid=COALESCE(?,tid) WHERE account_id=? AND id=?',(status,error,self.clock(),tid,account,pid))

    def add_image(self,account,raw,name):
        checked_image(raw)
        with Image.open(io.BytesIO(raw)) as im:
            im.seek(0);frame=ImageOps.exif_transpose(im).convert('RGBA');frame.thumbnail((2048,2048))
            buf=io.BytesIO();frame.save(buf,'PNG',optimize=True);raw=buf.getvalue()
            if len(raw)>4*1024*1024:
                bg=Image.new('RGBA',frame.size,'white');bg.alpha_composite(frame);buf=io.BytesIO();bg.convert('RGB').save(buf,'JPEG',quality=90);raw=buf.getvalue()
        mid=hashlib.sha256(raw).hexdigest();(self.assets/mid).write_bytes(raw)
        with self.db:self.db.execute('INSERT OR IGNORE INTO qzone_images VALUES (?,?,?,?,?)',(account,mid,name[:120],len(raw),time.time()))
        return {'id':mid,'name':name[:120],'size':len(raw)}

    def image(self,account,mid):
        row=self.db.execute('SELECT * FROM qzone_images WHERE account_id=? AND id=?',(account,mid)).fetchone()
        if not row or not (self.assets/mid).is_file():raise ValueError('图片不存在或不属于当前账号')
        return self.assets/mid
