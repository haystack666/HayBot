"""Private host Chrome gateway. Only the management session can use this service.

Host credentials and control leases never enter model prompts or QQ messages.
The browser session ID is derived from the catalog, never supplied by the client.
"""
import asyncio
import hmac
import os
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import HTTPException


class BrowserGateway:
    def __init__(self):
        self.url = os.getenv('BROWSER_RUNTIME_URL', '').rstrip('/')
        self.token = os.getenv('BROWSER_RUNTIME_TOKEN', '')
        self.host = os.getenv('BROWSER_RUNTIME_HOST', '')
        self.client = httpx.AsyncClient(timeout=65, trust_env=False, follow_redirects=False)

    @property
    def configured(self):
        return bool(self.url and self.token)

    def connection(self):
        if not self.configured:
            raise HTTPException(503, '尚未连接宿主浏览器运行时，请配置 BROWSER_RUNTIME_URL 和 BROWSER_RUNTIME_TOKEN')
        parsed = urlsplit(self.url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise HTTPException(503, '宿主浏览器运行时地址配置无效')
        # Docker connects through host.docker.internal; the loopback host service
        # still validates its canonical Host and does not trust arbitrary origins.
        host = self.host or f'127.0.0.1:{parsed.port or (443 if parsed.scheme == "https" else 80)}'
        return parsed, {'Authorization': 'Bearer ' + self.token, 'Host': host}

    async def request(self, method, path, body=None):
        _, headers = self.connection()
        try:
            response = await self.client.request(method, self.url + path, headers=headers, json=body)
        except httpx.HTTPError:
            raise HTTPException(503, '宿主浏览器运行时未连接或响应超时；请检查服务，已提交的操作不会自动重试') from None
        if response.status_code in (401, 403):
            raise HTTPException(503, '宿主浏览器运行时凭证或 Host 配置不匹配')
        try:
            value = response.json()
        except ValueError:
            raise HTTPException(502, '宿主浏览器运行时返回无效响应') from None
        if not response.is_success:
            # Host error messages are bounded predefined messages. No raw transport
            # errors (which can contain URLs/credentials) are exposed to the UI.
            raise HTTPException(response.status_code if 400 <= response.status_code < 500 else 502,
                                value.get('detail', '浏览器操作失败') if isinstance(value, dict) else '浏览器操作失败')
        return value

    def socket(self, path):
        parsed, headers = self.connection()
        canonical_host = headers.pop('Host')
        options = {'host': parsed.hostname, 'port': parsed.port or (443 if parsed.scheme == 'https' else 80)}
        if parsed.scheme == 'https':
            options['server_hostname'] = parsed.hostname
        # A second Host in additional_headers is ambiguous. Use the canonical
        # loopback URI and explicitly route the socket to the configured host.
        return urlunsplit(('wss' if parsed.scheme == 'https' else 'ws', canonical_host, path, '', '')), headers, options

    async def close(self):
        await self.client.aclose()


class BrowserService:
    def __init__(self):
        self.gateway = BrowserGateway()
        self.viewers = {}
        self.locks = {}

    @staticmethod
    def path(bot_id):
        # IDs originate in BotRegistry (default or UUID hex).
        return '/api/sessions/bot-' + bot_id

    def lock(self, bot_id):
        return self.locks.setdefault(bot_id, asyncio.Lock())

    def viewer(self, connection_id, bot_id, auth):
        if not isinstance(connection_id, str):
            raise HTTPException(422, '画面连接标识无效')
        viewer = self.viewers.get(connection_id)
        if not viewer or not viewer['active'] or viewer['bot_id'] != bot_id or not hmac.compare_digest(viewer['auth'], auth):
            raise HTTPException(409, '画面连接已失效，请重新连接并接管当前 Bot')
        return viewer

    def control(self, connection_id, bot_id, auth, lease):
        viewer = self.viewer(connection_id, bot_id, auth)
        if not isinstance(lease, str) or not lease or not hmac.compare_digest(viewer.get('lease', '').encode(), lease.encode()):
            raise HTTPException(409, '操作权限已失效，请重新接管')
        return viewer

    async def disconnect(self, bot_id=None):
        targets = [v for v in self.viewers.values() if bot_id is None or v['bot_id'] == bot_id]
        for viewer in targets:
            viewer['active'] = False
            viewer['lease'] = ''
        await asyncio.gather(*(v['upstream'].close() for v in targets), return_exceptions=True)

    async def stop_bot(self, bot_id):
        await self.disconnect(bot_id)
        if self.gateway.configured:
            async with self.lock(bot_id):
                await self.gateway.request('POST', self.path(bot_id) + '/stop', {})

    async def close(self):
        await self.disconnect()
        await self.gateway.close()
