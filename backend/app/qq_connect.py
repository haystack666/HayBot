"""QQ official QR binding protocol, independently implemented in Python.

Protocol reference: Tencent's @tencent-connect/qqbot-connector 1.2.0 and
https://github.com/tencent-connect/openclaw-qqbot/blob/main/src/setup/login.ts
The AES binding key and decrypted AppSecret never leave this backend.
"""
import asyncio
import base64
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException
from .config import QQConfig


@dataclass
class Binding:
    id: str
    owner: str = field(repr=False)
    task_id: str = field(repr=False)
    key: bytes = field(repr=False)
    qr_url: str = field(repr=False)
    expires_at: float
    state: str = 'waiting'
    app_id: str = ''
    secret: str = field(default='', repr=False)
    bot_id: str = ''
    task: asyncio.Task | None = field(default=None, repr=False)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


class QQConnect:
    def __init__(self, manager, client=None, clock=time.time):
        self.manager = manager
        self.client = client or httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False)
        self.clock = clock
        self.sessions = {}
        self.attempts = []
        self.create_lock = asyncio.Lock()

    async def request(self, operation, body):
        response = await self.client.post('https://q.qq.com/lite/' + operation, json=body, timeout=15)
        if not response.is_success:
            raise ValueError('QQ 扫码服务暂时不可用，请稍后重试')
        try:
            payload = response.json()
        except ValueError:
            raise ValueError('QQ 扫码服务返回格式异常，请重试') from None
        if not isinstance(payload, dict) or payload.get('retcode') != 0 or not isinstance(payload.get('data'), dict):
            raise ValueError('QQ 扫码服务未接受请求，请稍后重试或使用手动添加')
        return payload['data']

    def prune(self):
        now = self.clock()
        for sid, session in list(self.sessions.items()):
            if session.expires_at <= now:
                if session.task:
                    session.task.cancel()
                session.secret, session.key = '', b''
                self.sessions.pop(sid, None)

    async def start(self, owner, still_valid=lambda: True):
        async with self.create_lock:
            self.prune()
            now = self.clock()
            self.attempts = [at for at in self.attempts if at > now - 60]
            if len(self.attempts) >= 10 or len(self.sessions) >= 8:
                raise HTTPException(429, '扫码请求过于频繁，请关闭旧二维码或稍后重试')
            self.attempts.append(now)
            key = os.urandom(32)
            payload = await self.request('create_bind_task', {'key': base64.b64encode(key).decode()})
            if not still_valid():
                raise HTTPException(401, '登录已失效，请重新登录后扫码')
            task_id = payload.get('task_id')
            if not isinstance(task_id, str) or not task_id or len(task_id) > 512:
                raise ValueError('QQ 扫码任务无效，请重试')
            sid = secrets.token_urlsafe(32)
            # Default source is deliberately empty: Tencent labels this a third-party bot.
            url = 'https://q.qq.com/qqbot/openclaw/connect.html?' + urlencode({'task_id': task_id, 'source': '', '_wv': '2'})
            session = Binding(sid, owner, task_id, key, url, now + 600)
            self.sessions[sid] = session
            session.task = asyncio.create_task(self.poll(session))
            return self.snapshot(session)

    async def poll(self, session):
        failures = 0
        try:
            while self.clock() < session.expires_at:
                await asyncio.sleep(2)
                try:
                    payload = await self.request('poll_bind_result', {'task_id': session.task_id})
                    failures = 0
                except (httpx.HTTPError, ValueError):
                    failures += 1
                    if failures >= 5:
                        session.state = 'error'
                        return
                    continue
                status = payload.get('status', 0)
                if status == 3:
                    session.state = 'expired'
                    return
                if status != 2:
                    continue
                app_id = payload.get('bot_appid')
                if type(app_id) not in (str, int) or not re.fullmatch(r'\d{1,50}', str(app_id)):
                    raise ValueError('invalid app ID')
                encrypted = payload.get('bot_encrypt_secret')
                if not isinstance(encrypted, str) or len(encrypted) > 4096:
                    raise ValueError('invalid encrypted secret')
                value = base64.b64decode(encrypted, validate=True)
                if len(value) < 29:
                    raise ValueError('invalid ciphertext')
                secret = AESGCM(session.key).decrypt(value[:12], value[12:], None).decode('utf-8')
                credentials = QQConfig(app_id=str(app_id), secret=secret)
                if not credentials.secret.strip():
                    raise ValueError('empty secret')
                session.app_id, session.secret = credentials.app_id, credentials.secret
                session.state = 'authorized'
                return
            session.state = 'expired'
        except asyncio.CancelledError:
            raise
        except Exception:
            session.state = 'error'
            session.secret = ''
        finally:
            session.key = b''

    def get(self, sid, owner):
        self.prune()
        session = self.sessions.get(sid)
        if not session or not secrets.compare_digest(session.owner, owner):
            raise HTTPException(404, '扫码会话不存在或已失效，请重新生成二维码')
        return session

    def snapshot(self, session):
        messages = {'waiting': '请使用手机 QQ 扫码，并在 QQ 页面确认授权',
                    'authorized': 'QQ 已授权，确认后完成添加', 'expired': '二维码已过期，请重新生成',
                    'error': 'QQ 扫码绑定失败，请重新生成二维码或使用手动添加',
                    'completed': '机器人已添加，凭证已加密保存'}
        result = {'session_id': session.id, 'state': session.state, 'message': messages[session.state],
                  'expires_at': session.expires_at, 'qr_url': session.qr_url if session.state == 'waiting' else '',
                  'app_id': session.app_id, 'bot_id': session.bot_id}
        if session.state == 'completed':
            runtime = self.manager.get(session.bot_id)
            result.update(bot_state=runtime.bot.state, start_error=runtime.start_error)
        if session.state == 'authorized':
            existing = self.manager.existing_app(session.app_id)
            if existing:
                runtime = self.manager.runtimes.get(existing['id'])
                result['existing_bot'] = {'id': existing['id'], 'name': existing['name'], 'archived': bool(existing['archived']),
                                          'state': runtime.bot.state if runtime else 'stopped'}
        return result

    async def complete(self, sid, owner, name, replace_existing=False):
        session = self.get(sid, owner)
        async with session.lock:
            if session.state == 'completed':
                return self.snapshot(session)
            if session.state != 'authorized' or not session.secret:
                raise HTTPException(409, '请先完成 QQ 扫码授权')
            bot = await self.manager.bind_credentials(session.app_id, session.secret, name, replace_existing,
                still_valid=lambda: self.sessions.get(sid) is session and session.expires_at > self.clock() and session.state == 'authorized')
            session.bot_id = bot['id']
            session.secret = ''
            session.state = 'completed'
            self.manager.get(bot['id']).request_start()
            return self.snapshot(session)

    async def cancel(self, sid, owner):
        session = self.get(sid, owner)
        async with session.lock:
            if session.task:
                session.task.cancel()
                await asyncio.gather(session.task, return_exceptions=True)
            session.secret, session.key = '', b''
            self.sessions.pop(sid, None)

    async def cancel_all(self):
        sessions = list(self.sessions.values())
        self.sessions.clear()
        for session in sessions:
            if session.task:
                session.task.cancel()
            session.secret, session.key = '', b''
        await asyncio.gather(*(session.task for session in sessions if session.task), return_exceptions=True)

    async def close(self):
        await self.cancel_all()
        await self.client.aclose()
