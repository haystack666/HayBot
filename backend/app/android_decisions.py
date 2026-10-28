"""Parse a single, fully specified device decision before any phone side effect."""
import json
import re
from typing import Literal, Annotated
from urllib.parse import urlsplit
from pydantic import Field, model_validator, ValidationError
from .config import StrictModel
from .android_progress import TaskPlan,TaskCheckpoint

class DecisionFormatError(ValueError):
    pass

Pixel = Annotated[int, Field(ge=0,le=2560,strict=True)]

class DeviceAction(StrictModel):
    kind: Literal['tap','swipe','text','key','open','wait','launch']
    x: int | None = Field(default=None,ge=0,le=2560,strict=True)
    y: int | None = Field(default=None,ge=0,le=2560,strict=True)
    x2: int | None = Field(default=None,ge=0,le=2560,strict=True)
    y2: int | None = Field(default=None,ge=0,le=2560,strict=True)
    start: tuple[Pixel,Pixel] | None = None
    end: tuple[Pixel,Pixel] | None = None
    duration_ms: int = Field(default=350,ge=100,le=3000,strict=True)
    text: str = Field(default='',max_length=2000)
    key: Literal['home','back','recent','enter','delete','wake'] | None = None
    url: str = Field(default='',max_length=2048)
    app: Literal['via','coolapk','playstore','douyin','bilibili','xiaohongshu','chrome'] | None = None

    @model_validator(mode='after')
    def complete(self):
        if self.start is not None or self.end is not None:
            if self.kind!='swipe' or self.start is None or self.end is None:
                raise ValueError('滑动必须同时包含start和end两个坐标点')
            if any(getattr(self,name) is not None for name in ('x','y','x2','y2')):
                raise ValueError('不能混用start/end与x/y/x2/y2坐标')
            self.x,self.y=self.start
            self.x2,self.y2=self.end
        required={'tap':['x','y'],'swipe':['x','y','x2','y2'],'key':['key'],'launch':['app']}.get(self.kind,[])
        missing=[name for name in required if getattr(self,name) is None]
        if missing:raise ValueError(f'{self.kind} 缺少参数：'+','.join(missing))
        if self.kind=='text' and (not self.text or '\0' in self.text):raise ValueError('text 缺少有效文字')
        if self.kind=='open':
            u=urlsplit(self.url)
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or any(ord(c)<32 for c in self.url):raise ValueError('open 只允许HTTP/HTTPS网页')
        return self

class Watch(StrictModel):
    frames: int = Field(default=6,ge=3,le=8,strict=True)
    interval_seconds: int = Field(default=3,ge=1,le=10,strict=True)

class Social(StrictModel):
    kind: Literal['select','draft','mention','publish','verify']
    interest_basis: str = Field(default='',max_length=500)
    selection_reason: str = Field(default='',max_length=1000)
    platform: Literal['douyin','bilibili','xiaohongshu']
    content_id: str = Field(default='',max_length=500)
    draft_id: str = Field(default='',pattern=r'^(?:[0-9a-f]{32})?$')
    mention: bool = False
    x: int = Field(default=0,ge=0,le=2560,strict=True)
    y: int = Field(default=0,ge=0,le=2560,strict=True)

class Decision(StrictModel):
    reason: str = Field(default='',max_length=2000)
    done: bool = Field(default=False,strict=True)
    blocked: bool = Field(default=False,strict=True)
    result: str = Field(default='',max_length=2000)
    action: DeviceAction | None = None
    watch: Watch | None = None
    social: Social | None = None
    plan: TaskPlan | None = None
    checkpoint: TaskCheckpoint | None = None
    @model_validator(mode='after')
    def one(self):
        if sum([self.done,self.blocked,self.action is not None,self.watch is not None,self.social is not None,self.plan is not None,self.checkpoint is not None])!=1:raise ValueError('必须且只能返回一个action、plan、checkpoint或done/blocked结果')
        if (self.done or self.blocked) and not self.result.strip():raise ValueError('缺少结果说明')
        return self

def public_body(raw):
    if not isinstance(raw,str):return ''
    if '<think>' in raw and '</think>' not in raw:return '[未闭合的思考块，内容已隐藏]'
    return re.sub(r'<think>.*?</think>','',raw,flags=re.S).strip()

def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise DecisionFormatError('JSON字段重复：'+key[:40]+'；滑动请使用start/end坐标点')
        result[key]=value
    return result

def action_protocol(width,height):
    x=width//2;top=height//4;bottom=height*3//4
    examples=[
        {'plan':{'milestones':['按目标自主安排浏览','核对所需互动结果'],'estimated_steps':40,'estimated_minutes':10}},
        {'reason':'轻触目标','action':{'kind':'tap','x':x,'y':height//2}},
        {'reason':'向上滑动','action':{'kind':'swipe','start':[x,bottom],'end':[x,top],'duration_ms':500}},
        {'reason':'向下滑动','action':{'kind':'swipe','start':[x,top],'end':[x,bottom],'duration_ms':500}},
        {'reason':'输入文字','action':{'kind':'text','text':'示例文字'}},
        {'reason':'返回桌面','action':{'kind':'key','key':'home'}},
        {'reason':'打开明确要求的网址','action':{'kind':'open','url':'https://example.com/'}},
        {'reason':'等待界面更新','action':{'kind':'wait','duration_ms':500}},
        {'watch':{'frames':6,'interval_seconds':3}},
        {'social':{'kind':'select','platform':'bilibili','interest_basis':'兴趣1','selection_reason':'根据当前真实标题或画面的具体理由'}},
        {'social':{'kind':'draft','platform':'bilibili','mention':True}},
        {'social':{'kind':'mention','platform':'bilibili','draft_id':'a'*32,'x':x,'y':height//2}},
        {'social':{'kind':'publish','platform':'bilibili','draft_id':'a'*32,'x':x,'y':height//2}},
        {'social':{'kind':'verify','platform':'bilibili','draft_id':'a'*32}},
    ]
    return '以下仅为格式示例，不是任务。plan、checkpoint、watch、social、action、done/blocked均为可用的顶层决策，每次只输出一个对象。需要规划、观看或社交时使用对应决策，不要用wait代替；wait仅等待界面或网络变化。滑动统一使用start:[起点x,起点y]和end:[终点x,终点y]，不要使用容易重复的y/y2键。字段不许重复。\n'+'\n'.join(json.dumps(item,ensure_ascii=False) for item in examples)

def parse_decision(raw):
    text=public_body(raw)
    if not text or text=='[未闭合的思考块，内容已隐藏]':raise DecisionFormatError('模型没有返回可执行的JSON正文')
    if len(text)>32000:raise DecisionFormatError('模型返回的操作内容过长')
    start=text.find('{')
    if start<0 or '[' in text[:start]:raise DecisionFormatError('模型必须返回一个JSON对象，不能返回数组或空正文')
    try:
        value,end=json.JSONDecoder(object_pairs_hook=unique_object).raw_decode(text,start)
    except DecisionFormatError:raise
    except ValueError:raise DecisionFormatError('模型JSON不完整或格式错误，未提取其中的嵌套动作') from None
    if '{' in text[end:] or '[' in text[end:]:raise DecisionFormatError('模型返回多个对象或数组，无法确定唯一动作')
    try:
        decision=Decision.model_validate(value)
        output=decision.model_dump(exclude_none=True,exclude_unset=True)
        if decision.action:
            output['action']=decision.action.model_dump(exclude_none=True,exclude_unset=True,exclude={'start','end'})
        return output
    except ValidationError as exc:
        messages=[]
        for e in exc.errors()[:3]:
            # Never echo validation inputs (which could contain phone text).
            messages.append('.'.join(str(x) for x in e['loc'])+': '+e['msg'])
        raise DecisionFormatError('操作格式无效：'+'；'.join(messages)) from None
