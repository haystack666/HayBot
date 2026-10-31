"""Shared encrypted provider catalog and protocol adapters. No remote conversation state."""
import json
import hashlib
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, quote

from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import Field, field_validator, model_validator
from .config import StrictModel
from .provider_catalog import CATALOG, ProviderType, protocol
from .ollama import ContextLimitError, chat_response as ollama_chat
from .context_manager import drop_oldest_turn


class ProviderConfig(StrictModel):
    name: str = Field(default='', max_length=60)
    default_model: str = Field(default='', max_length=200)
    type: ProviderType = 'ollama'
    purpose: Literal['chat', 'tts', 'stt', 'image', 'embedding', 'rerank'] = 'chat'
    embedding_dimensions: int | None = Field(default=None, ge=1, le=65536)
    base_url: str = Field(default='', max_length=2048)
    api_key: str = Field(default='', max_length=4096, repr=False)
    clear_api_key: bool = False
    api_secret: str = Field(default='',max_length=4096,repr=False)
    clear_api_secret: bool = False
    app_id: str = Field(default='',max_length=200)
    resource_id: str = Field(default='',max_length=200)
    region: str = Field(default='',max_length=100)
    api_version: str = Field(default='',max_length=60)
    default_voice: str = Field(default='',max_length=200)
    language: str = Field(default='auto',max_length=30)
    speech_speed: float = Field(default=1.0,ge=0.5,le=2.0)
    speech_instructions: str = Field(default='',max_length=1000)
    vision: bool = True
    ollama_api: Literal['auto', 'native', 'openai'] = 'auto'
    chat_thinking: bool = False
    send_temperature: bool = True
    token_limit_field: Literal['max_tokens', 'max_completion_tokens'] = 'max_tokens'
    anthropic_version: Literal['2023-06-01', '2026-10-21'] = '2023-06-01'

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        return value.strip()

    @field_validator('base_url')
    @classmethod
    def valid_url(cls, value):
        value = value.strip().rstrip('/')
        if not value:return value
        u = urlsplit(value)
        if u.scheme not in ('http', 'https', 'wss') or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError('请输入有效的 HTTP 或 HTTPS 服务地址')
        try:
            u.port
        except ValueError:
            raise ValueError('服务端口无效') from None
        return value

    @field_validator('api_key','api_secret','app_id','resource_id','api_version')
    @classmethod
    def valid_key(cls, value):
        value = value.strip()
        if any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError('API Key 格式无效')
        return value

    @model_validator(mode='after')
    def valid_clear(self):
        expected = CATALOG[self.type]['purpose']
        self.base_url = self.valid_url(self.base_url or CATALOG[self.type]['url'])
        if urlsplit(self.base_url).scheme=='wss' and self.type!='xfyun_stt':raise ValueError('此供应商需要 HTTP 或 HTTPS 地址')
        if self.type=='xfyun_stt' and urlsplit(self.base_url).scheme!='wss':raise ValueError('讯飞识别需要 WSS 服务地址')
        if self.purpose not in ('chat', expected):
            raise ValueError('供应商用途与接口类型不一致')
        self.purpose = expected
        for key in ('api_key','api_secret'):
            if getattr(self,'clear_'+key) and getattr(self,key):raise ValueError('不能同时填写和清除凭证')
        return self

    @property
    def secret_values(self):return [self.api_key,self.api_secret]


class ProviderHTTPError(ValueError):
    def __init__(self, status):
        self.status = status
        hints = {401: 'API Key 无效或未填写', 403: '访问被拒绝，请检查权限',
                 404: '接口或模型不存在，请检查地址与模型名称', 429: '请求限流或额度不足'}
        super().__init__(f'接口请求失败（HTTP {status}）' + (f'：{hints[status]}' if status in hints else ''))


def read_response(response):
    try:
        data = response.json()
    except ValueError:
        raise ProviderHTTPError(response.status_code) if not response.is_success else ValueError('接口返回了无效 JSON 数据') from None
    if not isinstance(data, dict):
        raise ValueError('接口返回格式无效')
    error = data.get('error')
    error_text = error if isinstance(error, str) else error.get('message', '') if isinstance(error, dict) else ''
    error_text = error_text if isinstance(error_text, str) else ''
    error_code = error.get('code', '') if isinstance(error, dict) else ''
    if response.status_code in (400, 413) and (error_code == 'context_length_exceeded' or any(
            text in error_text.lower() for text in ('exceeds the available context size', 'exceed_context_size',
                                                    'maximum context length', 'context window exceeded'))):
        raise ContextLimitError('上下文超过模型容量，请缩短本条消息或系统提示词')
    if response.is_success and type(data.get('code')) is int and data['code'] != 0:
        raise ValueError(f'接口业务错误（{data["code"]}）')
    if not response.is_success or data.get('code', 0) != 0 or error:
        raise ProviderHTTPError(response.status_code)
    return data


class ProviderStore:
    def __init__(self, directory):
        root = Path(directory)
        key = root / 'providers.key'
        if not key.exists():
            fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(Fernet.generate_key())
        self.cipher = Fernet(key.read_bytes())
        self.db = sqlite3.connect(root / 'providers.sqlite3')
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS providers (id TEXT PRIMARY KEY, value TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS provider_checks (id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,state TEXT NOT NULL,checked REAL NOT NULL);
        ''')

    def get(self, provider_id):
        row = self.db.execute('SELECT * FROM providers WHERE id=?', (provider_id,)).fetchone()
        if not row:
            raise HTTPException(404, '模型供应商不存在')
        value = json.loads(row['value'])
        for key in ('api_key','api_secret'):
            if value.get(key):value[key] = self.cipher.decrypt(value[key].encode()).decode()
        return ProviderConfig.model_validate(value)

    def ids(self):
        return [r['id'] for r in self.db.execute('SELECT id FROM providers ORDER BY created,id')]

    def public(self, provider_id):
        provider=self.get(provider_id)
        value = provider.model_dump(exclude={'clear_api_key','clear_api_secret'})
        for key in ('api_key','api_secret'):value[key+'_set']=bool(value.pop(key))
        check=self.db.execute('SELECT * FROM provider_checks WHERE id=?',(provider_id,)).fetchone()
        current=check and check['fingerprint']==self.fingerprint(provider)
        return {'id':provider_id,**value,'check_state':check['state'] if current else 'untested','checked_at':check['checked'] if current else None}

    def prepare(self, config, provider_id=''):
        result = config.model_copy(deep=True)
        if provider_id:
            old = self.get(provider_id)
            # Never silently carry credentials to a different address or protocol.
            if (old.base_url,old.type,old.app_id)==(result.base_url,result.type,result.app_id):
                for key in ('api_key','api_secret'):
                    if not getattr(result,key) and not getattr(result,'clear_'+key):setattr(result,key,getattr(old,key))
        for key in ('api_key','api_secret'):
            if getattr(result,'clear_'+key):setattr(result,key,'')
            setattr(result,'clear_'+key,False)
        return result

    def save(self, config, provider_id=''):
        config = self.prepare(config, provider_id)
        others = [self.get(pid).name for pid in self.ids() if pid != provider_id]
        if not config.name:
            prefix = {'openai_chat': 'openai', 'openai_responses': 'responses'}.get(config.type, config.type)
            index = 1
            while f'{prefix}-{index}'.casefold() in {name.casefold() for name in others}:
                index += 1
            config.name = f'{prefix}-{index}'
        if config.name.casefold() in {name.casefold() for name in others}:
            raise ValueError('供应商名称已存在，请使用其他名称')
        now = time.time()
        if provider_id:
            created = self.db.execute('SELECT created FROM providers WHERE id=?', (provider_id,)).fetchone()['created']
        else:
            provider_id, created = uuid.uuid4().hex, now
        value = config.model_dump(exclude={'clear_api_key','clear_api_secret'})
        for key in ('api_key','api_secret'):
            if value[key]:value[key] = self.cipher.encrypt(value[key].encode()).decode()
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO providers VALUES (?,?,?,?)', (provider_id, json.dumps(value), created, now))
        return provider_id

    def legacy(self, url, model=''):
        for pid in self.ids():
            p = self.get(pid)
            if p.type == 'ollama' and p.base_url == url:
                return pid
        return self.save(ProviderConfig(base_url=url, default_model=model))

    def delete(self, provider_id):
        self.get(provider_id)
        with self.db:
            self.db.execute('DELETE FROM providers WHERE id=?', (provider_id,))
            self.db.execute('DELETE FROM provider_checks WHERE id=?',(provider_id,))

    @staticmethod
    def fingerprint(config):
        return hashlib.sha256(json.dumps(config.model_dump(exclude={'name','clear_api_key','clear_api_secret'}),sort_keys=True).encode()).hexdigest()

    def checked(self,provider_id,config,state):
        if provider_id and provider_id in self.ids() and self.fingerprint(self.get(provider_id))==self.fingerprint(config):
            with self.db:self.db.execute('INSERT OR REPLACE INTO provider_checks VALUES (?,?,?,?)',(provider_id,self.fingerprint(config),state,time.time()))

    def close(self):
        self.db.close()


def ollama_native(provider):
    return provider.type == 'ollama' and provider.ollama_api != 'openai' and not (
        provider.ollama_api == 'auto' and urlsplit(provider.base_url).path.rstrip('/').endswith('/v1'))


def endpoint(provider, operation):
    base = provider.base_url.rstrip('/')
    path = urlsplit(base).path.rstrip('/')
    if ollama_native(provider):
        return base + ('' if path.endswith('/api') else '/api') + '/' + operation
    # Explicit /v1 and reverse-proxy prefixes are preserved. Root OpenAI / Anthropic
    # URLs get /v1; DeepSeek supports its root /chat/completions endpoint.
    if not path and provider.type != 'deepseek':
        base += '/v1'
    return base + '/' + operation


def headers(provider):
    result = {}
    kind=protocol(provider)
    if provider.api_key:
        if kind in ('gemini','gemini_tts'):result['x-goog-api-key']=provider.api_key
        elif kind in ('xiaomi','xiaomi_tts','xiaomi_stt','azure'):result['api-key']=provider.api_key
        elif kind == 'anthropic':
            result['x-api-key'] = provider.api_key
        else:
            result['Authorization'] = 'Bearer ' + provider.api_key
    if kind == 'anthropic':
        result['anthropic-version'] = provider.anthropic_version
    return result


async def list_models(request, provider):
    if provider.purpose!='chat':raise ValueError('此服务不提供统一模型列表，请填写模型名称后执行实际测试')
    if protocol(provider)=='gemini':
        models=[];cursor='';seen=set()
        for _ in range(50):
            data=await request('GET',provider.base_url+'/models',headers=headers(provider),timeout=15,**({'params':{'pageToken':cursor}} if cursor else {}))
            if not isinstance(data.get('models'),list):raise ValueError('模型列表格式无效')
            models.extend(m['name'].removeprefix('models/') for m in data['models'] if isinstance(m,dict) and isinstance(m.get('name'),str) and 'generateContent' in m.get('supportedGenerationMethods',['generateContent']))
            cursor=data.get('nextPageToken')
            if not cursor:return list(dict.fromkeys(models))
            if not isinstance(cursor,str) or cursor in seen:raise ValueError('模型列表分页无效')
            seen.add(cursor)
        raise ValueError('模型列表过大，请手动填写模型名称')
    models, cursors, params = [], set(), {}
    for _ in range(50):
        data = await request('GET', endpoint(provider, 'tags' if ollama_native(provider) else 'models'), headers=headers(provider), timeout=15, **({'params': params} if params else {}))
        collection = data.get('models' if ollama_native(provider) else 'data')
        if not isinstance(collection, list):
            raise ValueError('模型列表格式无效，请检查服务地址与协议')
        key = 'name' if ollama_native(provider) else 'id'
        models.extend(item[key] for item in collection if isinstance(item, dict) and isinstance(item.get(key), str) and item[key])
        if provider.type != 'anthropic' or not data.get('has_more'):
            return list(dict.fromkeys(models))
        cursor = data.get('last_id')
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            raise ValueError('模型列表分页无效')
        cursors.add(cursor)
        params = {'after_id': cursor}
    raise ValueError('模型列表过大，请手动填写模型名称')


def image_url(encoded):
    # load_images normalizes all frames to JPEG.
    return 'data:image/jpeg;base64,' + encoded


def text_parts(parts):
    if isinstance(parts, str):
        return parts
    if isinstance(parts, list):
        return '\n'.join(part['text'] for part in parts if isinstance(part, dict) and part.get('type') in ('text', 'output_text') and isinstance(part.get('text'), str))
    return ''


def normalized(data, kind):
    usage = data.get('usage') or {}
    if not isinstance(usage, dict):
        usage = {}
    if kind == 'openai_responses':
        finish = data.get('incomplete_details', {}).get('reason') if isinstance(data.get('incomplete_details'),dict) else None
        text = '\n'.join(text_parts(item.get('content')) for item in data.get('output', []) if isinstance(item, dict) and item.get('type') == 'message' and item.get('role', 'assistant') == 'assistant')
        inputs, outputs = usage.get('input_tokens', 0), usage.get('output_tokens', 0)
    elif kind == 'anthropic':
        finish = data.get('stop_reason')
        text = text_parts(data.get('content'))
        def token_count(key):
            value = usage.get(key, 0)
            return value if type(value) is int and value >= 0 else 0
        inputs = sum(token_count(key) for key in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))
        outputs = usage.get('output_tokens', 0)
    else:
        choices = data.get('choices') or []
        first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        finish = first.get('finish_reason')
        message = first.get('message') or {}
        text = text_parts(message.get('content')) if isinstance(message, dict) else ''
        inputs, outputs = usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0)
    return {'message': {'content': text}, 'prompt_eval_count': inputs, 'eval_count': outputs, **({'finish_reason':finish} if finish else {})}


async def generate(request, provider, selection, messages, max_tokens, *, thinking=None, json_output=False):
    if provider.purpose != 'chat':
        raise ValueError('此供应商不支持对话生成，请选择对话供应商')
    kind=protocol(provider)
    if kind=='gemini':
        from .gemini import generate_content
        working = list(messages)
        while True:
            try:
                return await generate_content(request,provider,selection,working,max_tokens)
            except ContextLimitError:
                reduced = drop_oldest_turn(working)
                if reduced is None:
                    raise
                working = reduced
    if ollama_native(provider):
        # Reuse existing precise context-overflow retry and Ollama tuning.
        config = selection.model_copy(update={'url': provider.base_url.removesuffix('/api')})
        async def authenticated(method, url, **kwargs):
            kwargs['headers'] = headers(provider)
            if json_output:
                kwargs['json'] = {**kwargs['json'], 'format':'json'}
            return await request(method, url, **kwargs)
        return await ollama_chat(authenticated, config, messages, max_tokens, thinking=thinking)
    working = list(messages)
    while True:
        body = {'model': selection.model, 'stream': False}
        if json_output and (kind == 'xiaomi' or provider.type == 'deepseek'):
            body['response_format'] = {'type':'json_object'}
        if provider.type == 'ollama' and thinking is not None:
            body['reasoning_effort'] = 'medium' if thinking else 'none'
        if provider.send_temperature and not (provider.type == 'anthropic' and provider.anthropic_version == '2026-10-21'):
            body['temperature'] = selection.temperature
        if kind == 'responses':
            inputs = []
            for message in working:
                if message.get('images'):
                    content = [{'type': 'input_text', 'text': message['content']}, *[{'type': 'input_image', 'image_url': image_url(image)} for image in message['images']]]
                else:
                    content = message['content']
                inputs.append({'role': message['role'], 'content': content})
            body.update(input=inputs, max_output_tokens=max_tokens, store=False)
            operation = 'responses'
        elif kind == 'anthropic':
            body['system'] = '\n'.join(message['content'] for message in working if message['role'] == 'system')
            converted = []
            for message in working:
                if message['role'] == 'system':
                    continue
                content = [{'type': 'text', 'text': message['content']}, *[{'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': image}} for image in message.get('images', [])]]
                # Anthropic requires alternating turns; merge adjacent same-role inputs.
                if converted and converted[-1]['role'] == message['role']:
                    converted[-1]['content'].extend(content)
                else:
                    converted.append({'role': message['role'], 'content': content})
            body.update(messages=converted, max_tokens=max_tokens)
            operation = 'messages'
        else:
            converted = []
            for message in working:
                content = message['content']
                if message.get('images'):
                    content = [{'type': 'text', 'text': content}, *[{'type': 'image_url', 'image_url': {'url': image_url(image)}} for image in message['images']]]
                converted.append({'role': message['role'], 'content': content})
            body.update(messages=converted)
            body['max_tokens' if provider.type == 'deepseek' else provider.token_limit_field] = max_tokens
            operation = 'chat/completions'
        try:
            url=endpoint(provider,operation);params={}
            if kind=='azure' and provider.api_version:
                base=provider.base_url.rstrip('/').removesuffix('/v1').removesuffix('/openai')
                url=base+'/openai/deployments/'+quote(selection.model,safe='')+'/'+operation
                params={'api-version':provider.api_version}
            data = await request('POST',url,headers=headers(provider),timeout=selection.timeout,json=body,**({'params':params} if params else {}))
            return normalized(data, 'openai_responses' if kind=='responses' else 'anthropic' if kind=='anthropic' else provider.type)
        except ContextLimitError:
            reduced = drop_oldest_turn(working)
            if reduced is None:
                raise
            working = reduced
