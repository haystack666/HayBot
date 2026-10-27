"""Parse a single, fully specified device decision before any phone side effect."""
import json
import re
from typing import Literal
from urllib.parse import urlsplit
from pydantic import Field, model_validator, ValidationError
from .config import StrictModel

class DecisionFormatError(ValueError):
    pass

class DeviceAction(StrictModel):
    kind: Literal['tap','swipe','text','key','open','wait']
    x: int | None = Field(default=None,ge=0,le=2560,strict=True)
    y: int | None = Field(default=None,ge=0,le=2560,strict=True)
    x2: int | None = Field(default=None,ge=0,le=2560,strict=True)
    y2: int | None = Field(default=None,ge=0,le=2560,strict=True)
    duration_ms: int = Field(default=350,ge=100,le=3000,strict=True)
    text: str = Field(default='',max_length=2000)
    key: Literal['home','back','recent','enter','delete','wake'] | None = None
    url: str = Field(default='',max_length=2048)

    @model_validator(mode='after')
    def complete(self):
        required={'tap':['x','y'],'swipe':['x','y','x2','y2'],'key':['key']}.get(self.kind,[])
        missing=[name for name in required if getattr(self,name) is None]
        if missing:raise ValueError(f'{self.kind} 缺少参数：'+','.join(missing))
        if self.kind=='text' and (not self.text or '\0' in self.text):raise ValueError('text 缺少有效文字')
        if self.kind=='open':
            u=urlsplit(self.url)
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or any(ord(c)<32 for c in self.url):raise ValueError('open 只允许HTTP/HTTPS网页')
        return self

class Decision(StrictModel):
    reason: str = Field(default='',max_length=2000)
    done: bool = Field(default=False,strict=True)
    blocked: bool = Field(default=False,strict=True)
    result: str = Field(default='',max_length=2000)
    action: DeviceAction | None = None
    @model_validator(mode='after')
    def one(self):
        if sum([self.done,self.blocked,self.action is not None])!=1:raise ValueError('必须且只能返回一个action或done/blocked结果')
        if (self.done or self.blocked) and not self.result.strip():raise ValueError('缺少结果说明')
        return self

def public_body(raw):
    if not isinstance(raw,str):return ''
    if '<think>' in raw and '</think>' not in raw:return '[未闭合的思考块，内容已隐藏]'
    return re.sub(r'<think>.*?</think>','',raw,flags=re.S).strip()

def parse_decision(raw):
    text=public_body(raw)
    if not text or text=='[未闭合的思考块，内容已隐藏]':raise DecisionFormatError('模型没有返回可执行的JSON正文')
    if len(text)>32000:raise DecisionFormatError('模型返回的操作内容过长')
    start=text.find('{')
    if start<0 or '[' in text[:start]:raise DecisionFormatError('模型必须返回一个JSON对象，不能返回数组或空正文')
    try:
        value,end=json.JSONDecoder().raw_decode(text,start)
    except ValueError:raise DecisionFormatError('模型JSON不完整或格式错误，未提取其中的嵌套动作') from None
    if '{' in text[end:] or '[' in text[end:]:raise DecisionFormatError('模型返回多个对象或数组，无法确定唯一动作')
    found=[value]
    try:return Decision.model_validate(found[0]).model_dump(exclude_none=True,exclude_unset=True)
    except ValidationError as exc:
        messages=[]
        for e in exc.errors()[:3]:
            # Never echo validation inputs (which could contain phone text).
            messages.append('.'.join(str(x) for x in e['loc'])+': '+e['msg'])
        raise DecisionFormatError('操作格式无效：'+'；'.join(messages)) from None
