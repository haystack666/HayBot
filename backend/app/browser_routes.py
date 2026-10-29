"""Authenticated management HTTP and read-only live WebSocket relay for Chrome."""
import asyncio
import hmac
import json
import os

import websockets
from fastapi import Depends, HTTPException, Request, WebSocket
from pydantic import Field

from .config import StrictModel
from .browser_tasks import BrowsingConfig


class BrowserTaskBody(StrictModel):
    goal: str = Field(min_length=1, max_length=3000)


class ViewerBody(StrictModel):
    connectionId: str = Field(min_length=1, max_length=64)


class ControlBody(ViewerBody):
    lease: str = Field(min_length=1, max_length=64)


class BrowserSettingsBody(StrictModel):
    headless: bool = Field(strict=True)
    acknowledgeHeadlessRisk: bool = Field(default=False, strict=True)


def register_browser_routes(app, scoped_runtime):
    def service():
        return app.state.browser

    def authorization(request, runtime):
        auth = request.cookies.get('hay_session', '')
        if runtime.closing or not auth or not hmac.compare_digest(auth, app.state.session):
            raise HTTPException(401, '请先登录')
        return auth

    @app.get('/api/bots/{bot_id}/browser/douyin/config')
    async def browsing_config(runtime=Depends(scoped_runtime)):
        tasks = app.state.browser_tasks
        return {'config': tasks.config(runtime.id).model_dump(), 'qq_account_bound': tasks.bound(runtime.id)}

    @app.put('/api/bots/{bot_id}/browser/douyin/config')
    async def save_browsing_config(body: BrowsingConfig, request: Request, runtime=Depends(scoped_runtime)):
        authorization(request, runtime)
        return app.state.browser_tasks.save_config(runtime.id, body)

    @app.get('/api/bots/{bot_id}/browser/douyin/tasks')
    async def browsing_tasks(runtime=Depends(scoped_runtime)):
        return {'tasks': app.state.browser_tasks.list(runtime.id), 'operations': app.state.browser_tasks.interactions.history(runtime.id)}

    @app.post('/api/bots/{bot_id}/browser/douyin/tasks')
    async def start_browsing(body: BrowserTaskBody, request: Request, runtime=Depends(scoped_runtime)):
        authorization(request, runtime)
        return app.state.browser_tasks.submit(runtime.id, body.goal)

    @app.post('/api/bots/{bot_id}/browser/douyin/tasks/{task_id}/stop')
    async def stop_browsing(task_id: str, request: Request, runtime=Depends(scoped_runtime)):
        authorization(request, runtime)
        return await app.state.browser_tasks.cancel(runtime.id, task_id)

    @app.get('/api/bots/{bot_id}/browser')
    async def status(runtime=Depends(scoped_runtime)):
        s = service()
        if not s.gateway.configured:
            return {'configured': False, 'session': None}
        return {'configured': True, 'session': await s.gateway.request('GET', s.path(runtime.id))}

    @app.api_route('/api/bots/{bot_id}/browser/environment', methods=['GET', 'POST'])
    async def environment(request: Request, runtime=Depends(scoped_runtime)):
        return await service().gateway.request(request.method, '/api/environment')

    @app.post('/api/bots/{bot_id}/browser/settings')
    async def settings(body: BrowserSettingsBody, request: Request, runtime=Depends(scoped_runtime)):
        s = service()
        async with s.lock(runtime.id):
            authorization(request, runtime)
            if not body.headless:
                raise HTTPException(400, '当前仅支持无头模式；实时查看与接管仍可使用，请刷新管理页面')
            return await s.gateway.request('POST', s.path(runtime.id) + '/settings', body.model_dump())

    @app.post('/api/bots/{bot_id}/browser/{operation}')
    async def lifecycle(operation: str, request: Request, runtime=Depends(scoped_runtime)):
        if operation not in ('start', 'stop'):
            raise HTTPException(404, '操作不存在')
        s = service()
        async with s.lock(runtime.id):
            authorization(request, runtime)
            if operation == 'stop':
                await app.state.browser_tasks.cancel_bot(runtime.id)
                await s.disconnect(runtime.id)
            return await s.gateway.request('POST', s.path(runtime.id) + '/' + operation, {})

    @app.post('/api/bots/{bot_id}/browser/control/claim')
    async def claim(body: ViewerBody, request: Request, runtime=Depends(scoped_runtime)):
        s = service()
        async with s.lock(runtime.id):
            auth = authorization(request, runtime)
            viewer = s.viewer(body.connectionId, runtime.id, auth)
            result = await s.gateway.request('POST', s.path(runtime.id) + '/claim', body.model_dump())
            authorization(request, runtime)
            s.viewer(body.connectionId, runtime.id, auth)
            for other in s.viewers.values():
                if other['bot_id'] == runtime.id:
                    other['lease'] = ''
            viewer['lease'] = result['lease']
            await app.state.browser_tasks.cancel_bot(runtime.id)
            return result

    @app.post('/api/bots/{bot_id}/browser/control/release')
    async def release(body: ControlBody, request: Request, runtime=Depends(scoped_runtime)):
        s = service()
        async with s.lock(runtime.id):
            viewer = s.control(body.connectionId, runtime.id, authorization(request, runtime), body.lease)
            result = await s.gateway.request('POST', s.path(runtime.id) + '/release', {'lease': body.lease})
            viewer['lease'] = ''
            return result

    @app.post('/api/bots/{bot_id}/browser/control/action')
    async def action(body: dict, request: Request, runtime=Depends(scoped_runtime)):
        s = service()
        if len(json.dumps(body, ensure_ascii=False).encode()) > 32768:
            raise HTTPException(413, '操作内容过大')
        payload = dict(body)
        connection_id = payload.pop('connectionId', '')
        async with s.lock(runtime.id):
            s.control(connection_id, runtime.id, authorization(request, runtime), payload.get('lease', ''))
            return await s.gateway.request('POST', s.path(runtime.id) + '/action', payload)

    @app.post('/api/bots/{bot_id}/browser/login/{operation}')
    async def login(operation: str, body: ControlBody, request: Request, runtime=Depends(scoped_runtime)):
        if operation not in ('begin', 'finish'):
            raise HTTPException(404, '操作不存在')
        s = service()
        async with s.lock(runtime.id):
            s.control(body.connectionId, runtime.id, authorization(request, runtime), body.lease)
            return await s.gateway.request('POST', s.path(runtime.id) + '/login/' + operation, {'lease': body.lease})

    @app.websocket('/api/bots/{bot_id}/browser/live')
    async def live(ws: WebSocket, bot_id: str):
        auth = ws.cookies.get('hay_session', '')
        allowed = os.getenv('PUBLIC_ORIGIN') or ('https' if ws.url.scheme == 'wss' else 'http') + '://' + ws.headers.get('host', '')
        if not auth or not hmac.compare_digest(auth, app.state.session) or ws.headers.get('origin') != allowed:
            await ws.close(code=1008)
            return
        try:
            runtime = app.state.manager.get(bot_id)
        except HTTPException:
            await ws.close(code=1008)
            return
        s, workers, viewer, connection_id = service(), [], None, None
        current = asyncio.current_task()
        runtime.requests.add(current)

        def valid():
            return not runtime.closing and hmac.compare_digest(auth, app.state.session) and (viewer is None or viewer['active'])

        try:
            url, headers, options = s.gateway.socket(s.path(bot_id) + '/live')
            async with websockets.connect(url, additional_headers=headers, proxy=None, open_timeout=25,
                                          max_size=4 * 1024 * 1024, max_queue=2, ping_interval=15, ping_timeout=15, **options) as upstream:
                if not valid():
                    return
                await ws.accept()

                async def outbound():
                    nonlocal viewer, connection_id
                    async for message in upstream:
                        if not valid():
                            return
                        if not isinstance(message, str):
                            raise ValueError('Unexpected browser payload')
                        value = json.loads(message)
                        if value.get('type') == 'state':
                            if value.get('connectionId'):
                                if connection_id is not None:
                                    raise ValueError('Duplicate viewer identity')
                                connection_id = value['connectionId']
                                viewer = {'bot_id': bot_id, 'auth': auth, 'upstream': upstream, 'active': True, 'lease': ''}
                                s.viewers[connection_id] = viewer
                            state = value.get('state', {})
                            if viewer and (state.get('state') != 'owner_control' or state.get('controller') != connection_id):
                                viewer['lease'] = ''
                        await asyncio.wait_for(ws.send_text(message), timeout=10)

                async def inbound():
                    # Management input uses bounded HTTP requests only.
                    await ws.receive()

                async def watch_auth():
                    while valid():
                        await asyncio.sleep(.25)

                workers = [asyncio.create_task(outbound()), asyncio.create_task(inbound()), asyncio.create_task(watch_auth())]
                done, _ = await asyncio.wait(workers, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if not task.cancelled() and task.exception():
                        raise task.exception()
        except (Exception, asyncio.CancelledError):
            pass
        finally:
            if viewer:
                viewer['active'] = False
                viewer['lease'] = ''
            if connection_id:
                s.viewers.pop(connection_id, None)
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            runtime.requests.discard(current)
            try:
                await ws.close(code=1000 if valid() else 1008)
            except Exception:
                pass
