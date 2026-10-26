import os
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class QQConfig(StrictModel):
    app_id: str = Field(default='', pattern=r'^\d*$', max_length=50)
    secret: str = Field(default='', max_length=300)
    private_reply: bool = True
    group_reply: bool = False


class NapCatConfig(StrictModel):
    self_id: str = Field(default='', pattern=r'^(?:[1-9][0-9]{4,19})?$')
    ws_url: str = Field(default='', max_length=2048)
    token: str = Field(default='', max_length=4096, repr=False)
    clear_token: bool = False
    token_set: bool = Field(default=False,exclude=True)
    group_require_at: bool = True

    @field_validator('ws_url')
    @classmethod
    def valid_ws(cls, value):
        value=value.strip()
        if not value:return value
        try:
            u=urlsplit(value)
            if u.scheme not in ('ws','wss') or not u.hostname or u.username or u.password or u.query or u.fragment:
                raise ValueError
            u.port
        except ValueError:
            raise ValueError('请输入有效 ws:// 或 wss:// 地址，Token 请单独填写') from None
        return value

    @field_validator('token')
    @classmethod
    def valid_token(cls,value):
        value=value.strip()
        if any(ord(c)<33 or ord(c)>126 for c in value):raise ValueError('NapCat Token 格式无效')
        return value

    @model_validator(mode='after')
    def valid_clear(self):
        if self.token and self.clear_token:raise ValueError('不能同时填写并清除 Token')
        return self


class OllamaConfig(StrictModel):
    # Retain the persisted field name for existing installations and API clients.
    provider_id: str = Field(default='', pattern=r'^(?:[a-f0-9]{32})?$')
    url: str = Field(default_factory=lambda: os.getenv('OLLAMA_URL', 'http://host.docker.internal:11434'))
    model: str = Field(default_factory=lambda: os.getenv('OLLAMA_MODEL', 'qwen3:0.6b'), max_length=200)
    temperature: float = Field(default=0.7, ge=0, le=2)
    timeout: int = Field(default=120, ge=5, le=600)
    max_tokens: int = Field(default=1024, ge=128, le=32768)

    @field_validator('url')
    @classmethod
    def valid_url(cls, v):
        u = urlsplit(v)
        if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError('请输入有效的 HTTP 或 HTTPS 服务地址')
        return v.rstrip('/')


class RulesConfig(StrictModel):
    prompt: str = Field(default='你是一个友好、简洁的中文 AI 助手。请使用中文回答。', max_length=20000)
    rounds: int = Field(default=6, ge=0, le=30)
    max_length: int = Field(default=1500, ge=10, le=2000)
    cooldown: int = Field(default=3, ge=0, le=300)
    split_enabled: bool = True
    split_length: int = Field(default=100, ge=20, le=500)
    split_max_parts: int = Field(default=4, ge=1, le=4)
    split_delay: float = Field(default=0.8, ge=0, le=5, allow_inf_nan=False)

    debounce_enabled: bool = True
    debounce_seconds: float = Field(default=3, ge=.2, le=10, allow_inf_nan=False)
    debounce_max_wait: float = Field(default=10, ge=1, le=60, allow_inf_nan=False)
    debounce_max_messages: int = Field(default=10, ge=1, le=10)

    @model_validator(mode='after')
    def debounce_window(self):
        if self.debounce_max_wait < self.debounce_seconds:
            raise ValueError('最长收集时间不能短于静默等待时间')
        return self


class GreetingConfig(StrictModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    name: str = Field(default='定时问候', min_length=1, max_length=30)
    time: str = Field(pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    enabled: bool = True
    mode: Literal['generated', 'fixed'] = 'generated'
    content: str = Field(min_length=1, max_length=500)


class ProactiveConfig(StrictModel):
    enabled: bool = False
    recipient_id: str = Field(default='', max_length=128)
    timezone: str = 'Asia/Shanghai'
    active_start: str = Field(default='07:00', pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    active_end: str = Field(default='00:00', pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    daily_limit: int = Field(default=0, ge=0)
    cooldown_minutes: int = Field(default=120, ge=0, le=1440)
    idle_enabled: bool = True
    idle_min_minutes: int = Field(default=120, ge=5, le=1440)
    idle_max_minutes: int = Field(default=240, ge=5, le=1440)
    unanswered_limit: int = Field(default=2, ge=1, le=20)
    greetings: list[GreetingConfig] = Field(default_factory=lambda: [
        GreetingConfig(id='morning', name='早安', time='09:00', content='自然地问早安，简短关心今天的安排。'),
        GreetingConfig(id='evening', name='晚安', time='22:30', content='自然地问晚安，温柔提醒适当休息。'),
    ], max_length=8)

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('请选择有效时区') from None
        return value

    @model_validator(mode='after')
    def valid_intervals(self):
        if self.idle_max_minutes < self.idle_min_minutes:
            raise ValueError('搭话间隔上限不能小于下限')
        if len({rule.id for rule in self.greetings}) != len(self.greetings):
            raise ValueError('定时问候标识不能重复')
        return self


class ScheduleConfig(StrictModel):
    enabled: bool = False
    premise: str = Field(default='', max_length=6000)
    timezone: str = 'Asia/Shanghai'

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        return ProactiveConfig.valid_timezone(value)

    @model_validator(mode='after')
    def require_premise(self):
        self.premise = self.premise.strip()
        if self.enabled and not self.premise:
            raise ValueError('启用每日日程前，请填写角色生活设定')
        return self


class MemoryModelConfig(StrictModel):
    provider_id: str = Field(default='', pattern=r'^(?:[a-f0-9]{32})?$')
    model: str = Field(default='', max_length=200)


class MemoryConfig(StrictModel):
    enabled: bool = False
    embedding: MemoryModelConfig = Field(default_factory=MemoryModelConfig)
    rerank: MemoryModelConfig = Field(default_factory=MemoryModelConfig)
    extraction_turns: int = Field(default=6, ge=1, le=30)
    top_k: int = Field(default=8, ge=1, le=30)
    recall_limit: int = Field(default=40, ge=5, le=100)
    context_chars: int = Field(default=6000, ge=500, le=16000)
    timeout: int = Field(default=20, ge=5, le=120)

    @model_validator(mode='after')
    def valid_models(self):
        if self.enabled and (not self.embedding.provider_id or not self.embedding.model.strip()):
            raise ValueError('启用记忆前请配置 Embedding 供应商和模型')
        for selection in (self.embedding, self.rerank):
            selection.model = selection.model.strip()
            if bool(selection.provider_id) != bool(selection.model):
                raise ValueError('记忆模型的供应商与模型名称必须同时配置')
        return self


class MemeConfig(StrictModel):
    enabled: bool = False
    embedding: MemoryModelConfig = Field(default_factory=MemoryModelConfig)
    rerank: MemoryModelConfig = Field(default_factory=MemoryModelConfig)
    packs: list[str] = Field(default_factory=lambda: ['deepseek-fanart-v1', 'custom'], max_length=30)
    chance: float = Field(default=.35, ge=0, le=1, allow_inf_nan=False)
    cooldown_seconds: int = Field(default=120, ge=0, le=86400)
    repeat_window: int = Field(default=8, ge=0, le=100)
    top_k: int = Field(default=6, ge=1, le=10)
    min_similarity: float = Field(default=.2, ge=-1, le=1, allow_inf_nan=False)
    timeout: int = Field(default=20, ge=5, le=120)

    @model_validator(mode='after')
    def valid_models(self):
        for selection in (self.embedding, self.rerank):
            selection.model = selection.model.strip()
            if bool(selection.provider_id) != bool(selection.model):
                raise ValueError('表情包模型的供应商和模型名称必须同时配置')
        if any(len(p) > 100 or not p.strip() for p in self.packs):
            raise ValueError('表情包集合名称无效')
        return self


class Settings(StrictModel):
    transport: Literal['qq_official','napcat'] = 'qq_official'
    napcat: NapCatConfig = Field(default_factory=NapCatConfig)
    qq: QQConfig = Field(default_factory=QQConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    rules: RulesConfig = Field(default_factory=RulesConfig)
    proactive: ProactiveConfig = Field(default_factory=ProactiveConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    memes: MemeConfig = Field(default_factory=MemeConfig)

    @property
    def account_id(self):
        return ('napcat:'+self.napcat.self_id if self.napcat.self_id else '') if self.transport=='napcat' else self.qq.app_id
