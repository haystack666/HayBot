"""Authenticated companion API; run on loopback, never expose Docker to HayBot."""
from __future__ import annotations
import asyncio
import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from .engine import AndroidEngine, DeviceCreate, Action, RuntimeFailure


class Lease(BaseModel):
    lease: str = Field(default='', max_length=64)


def create_app(engine=None, token=None):
    owned = engine is None
    token = token or os.getenv('HAYBOT_ANDROID_TOKEN', '')
    @asynccontextmanager
    async def lifespan(app):
        if len(token) < 32:
            raise RuntimeError('HAYBOT_ANDROID_TOKEN must be at least32characters')
        app.state.engine = engine or AndroidEngine(os.getenv('HAYBOT_ANDROID_DATA', '.android-runtime'))
        app.state.operations = {}
        yield
        for task in app.state.operations.values():
            if not task.done(): task.cancel()
        await asyncio.gather(*app.state.operations.values(), return_exceptions=True)
        if owned: app.state.engine.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    @app.middleware('http')
    async def auth(request: Request, call_next):
        if request.headers.get('origin'):
            return JSONResponse({'detail': '请通过 HayBot 后台访问'}, status_code=403)
        if not hmac.compare_digest(request.headers.get('authorization', '').encode(), ('Bearer ' + token).encode()):
            return JSONResponse({'detail': '运行时认证失败'}, status_code=401)
        if int(request.headers.get('content-length', '0') or 0) > 16384:
            return JSONResponse({'detail': '请求过大'}, status_code=413)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(RuntimeFailure)
    async def failure(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=409)

    @app.get('/health')
    async def health(): return await app.state.engine.health()

    @app.get('/bots/{bot_id}/devices')
    async def devices(bot_id: str): return {'devices': app.state.engine.list(bot_id)}

    @app.post('/bots/{bot_id}/devices', status_code=201)
    async def create(bot_id: str, body: DeviceCreate): return await app.state.engine.create(bot_id, body)

    def idle(device_id):
        job = app.state.operations.get(device_id)
        if job and not job.done(): raise HTTPException(409, '设备操作正在进行，请稍后重试')

    @app.post('/bots/{bot_id}/devices/{device_id}/start', status_code=202)
    async def start(bot_id: str, device_id: str):
        e = app.state.engine; e.get(bot_id, device_id); idle(device_id)
        async def run():
            try: await e.start(bot_id, device_id)
            except Exception: e.state(device_id, 'error', '启动失败，请检查运行时日志和镜像')
        e.state(device_id, 'starting')
        app.state.operations[device_id] = asyncio.create_task(run())
        return e.get(bot_id, device_id)

    @app.get('/bots/{bot_id}/devices/{device_id}')
    async def status(bot_id: str, device_id: str):
        job = app.state.operations.get(device_id)
        return app.state.engine.get(bot_id, device_id) if job and not job.done() else await app.state.engine.status(bot_id, device_id)

    @app.post('/bots/{bot_id}/devices/{device_id}/stop')
    async def stop(bot_id: str, device_id: str):
        idle(device_id)
        return await app.state.engine.stop(bot_id, device_id)

    @app.delete('/bots/{bot_id}/devices/{device_id}')
    async def delete(bot_id: str, device_id: str, destroy_data: bool = False, confirm: str = Query(default='', max_length=64)):
        idle(device_id)
        if destroy_data and confirm != device_id: raise HTTPException(422, '彻底销毁需要确认设备 ID')
        return await app.state.engine.delete(bot_id, device_id, destroy_data)

    @app.get('/bots/{bot_id}/devices/{device_id}/apps')
    async def apps(bot_id: str, device_id: str):
        from .provisioning import status
        job=app.state.operations.get(device_id)
        return await status(app.state.engine,bot_id,device_id,refresh=not job or job.done())

    @app.post('/bots/{bot_id}/devices/{device_id}/apps/{app_id}/install', status_code=202)
    async def install(bot_id: str, device_id: str, app_id: str):
        from .provisioning import APPS, save
        e=app.state.engine;e.get(bot_id,device_id);idle(device_id)
        if app_id not in APPS: raise HTTPException(404,'应用不存在')
        e.check_lease(device_id,'');e.require_automation(device_id)
        save(e,device_id,app_id,'queued','等待初始化')
        async def run():
            try: await e.provision(bot_id,device_id,app_id)
            except Exception: pass  # provision persists a bounded diagnostic
        app.state.operations[device_id]=asyncio.create_task(run())
        return {'accepted':True}

    @app.post('/bots/{bot_id}/devices/{device_id}/claim')
    async def claim(bot_id: str, device_id: str, body: Lease):
        idle(device_id)
        return {'lease': await app.state.engine.claim(bot_id, device_id, body.lease)}

    @app.post('/bots/{bot_id}/devices/{device_id}/revoke')
    async def revoke(bot_id: str, device_id: str, body: Lease):
        return await app.state.engine.revoke(bot_id, device_id, body.lease)

    @app.post('/bots/{bot_id}/devices/{device_id}/release')
    async def release(bot_id: str, device_id: str, body: Lease):
        await app.state.engine.release(bot_id, device_id, body.lease)
        return {'ok': True}

    @app.post('/bots/{bot_id}/devices/{device_id}/takeover')
    async def takeover(bot_id: str, device_id: str):
        idle(device_id)
        return await app.state.engine.takeover(bot_id, device_id)

    @app.post('/bots/{bot_id}/devices/{device_id}/login/{operation}')
    async def login(bot_id: str, device_id: str, operation: str):
        if operation not in ('begin', 'finish'): raise HTTPException(404, '操作不存在')
        return await app.state.engine.login(bot_id, device_id, operation == 'begin')

    @app.get('/bots/{bot_id}/devices/{device_id}/observe')
    async def observe(bot_id: str, device_id: str, lease: str = Query(default='', max_length=64), automated: bool = False):
        idle(device_id)
        return await app.state.engine.observe(bot_id, device_id, lease, automated=automated)

    @app.post('/bots/{bot_id}/devices/{device_id}/action')
    async def action(bot_id: str, device_id: str, body: Action, lease: str = Query(default='', max_length=64)):
        idle(device_id)
        return await app.state.engine.action(bot_id, device_id, body, lease)

    return app

app = create_app()
