from urllib.parse import quote
from fastapi import Depends, HTTPException, Query
from pydantic import Field, field_validator
from .config import StrictModel
from .android import AndroidConfig, AndroidUnavailable

class DeviceBody(StrictModel):
    name: str = Field(default='Android', min_length=1, max_length=60)
    width: int = Field(default=720, ge=320, le=1440)
    height: int = Field(default=1280, ge=480, le=2560)
    dpi: int = Field(default=240, ge=120, le=640)
    memory_mb: int = Field(default=2048, ge=1024, le=8192)
    initialize: bool = True
    google_play: bool = True

class TaskBody(StrictModel):
    goal: str = Field(min_length=1, max_length=3000)
    device_id: str = Field(default='', pattern=r'^(?:[0-9a-f]{32})?$')


class DeviceRenameBody(StrictModel):
    name: str = Field(min_length=1, max_length=60)

    @field_validator('name')
    @classmethod
    def valid_name(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError('手机名称需为 1–60 个字符，不能包含换行或控制字符')
        return value


def register_android_routes(app, scoped_runtime):
    def service(): return app.state.android
    def path(runtime, device_id=''):
        base = '/bots/' + quote(runtime.id, safe='') + '/devices'
        if device_id:
            import re
            if not re.fullmatch('[0-9a-f]{32}', device_id): raise HTTPException(404, '设备不存在')
            base += '/' + device_id
        return base

    @app.exception_handler(AndroidUnavailable)
    async def unavailable(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': str(exc)}, status_code=503)

    @app.get('/api/bots/{bot_id}/android')
    async def status(runtime=Depends(scoped_runtime)):
        s=service(); health={'ready':False,'detail':'未配置安卓运行时'}; devices=[]
        if s.gateway.configured:
            try:
                health=await s.gateway.request('GET','/health')
                devices=(await s.gateway.request('GET',path(runtime)))['devices']
            except ValueError as exc: health={'ready':False,'detail':str(exc)}
        for d in devices:
            if s.login_paused(runtime.id,d['id']):d['owner_login']=True
        return {'configured':s.gateway.configured,'runtime':health,'devices':devices,'config':s.config(runtime.id).model_dump(),'tasks':s.list(runtime.id),'publications':s.social.list(runtime.id)}

    @app.put('/api/bots/{bot_id}/android/config')
    async def config(body:AndroidConfig,runtime=Depends(scoped_runtime)):
        return service().save_config(runtime.id,body)

    @app.post('/api/bots/{bot_id}/android/devices',status_code=201)
    async def create(body:DeviceBody,runtime=Depends(scoped_runtime)):
        return await service().gateway.request('POST',path(runtime),body.model_dump())

    @app.get('/api/bots/{bot_id}/android/devices/{device_id}')
    async def device(device_id:str,runtime=Depends(scoped_runtime)):
        result=await service().gateway.request('GET',path(runtime,device_id))
        if service().login_paused(runtime.id,device_id):result['owner_login']=True
        return result

    @app.patch('/api/bots/{bot_id}/android/devices/{device_id}')
    async def rename(device_id:str,body:DeviceRenameBody,runtime=Depends(scoped_runtime)):
        result=await service().gateway.request('PATCH',path(runtime,device_id),body.model_dump())
        if service().login_paused(runtime.id,device_id):result['owner_login']=True
        return result

    @app.post('/api/bots/{bot_id}/android/devices/{device_id}/control/{operation}')
    async def operate(device_id:str,operation:str,runtime=Depends(scoped_runtime)):
        if operation not in ('start','stop','takeover'): raise HTTPException(404,'操作不存在')
        if operation in ('stop','takeover'):
            for task in service().list(runtime.id):
                if task['state'] in ('queued','running'):await service().cancel(runtime.id,task['id'])
        result = await service().gateway.request('POST',path(runtime,device_id)+'/'+operation)
        if operation in ('stop','takeover'):
            service().acknowledge_takeover(runtime.id)
        return result

    @app.post('/api/bots/{bot_id}/android/devices/{device_id}/login/{operation}')
    async def login(device_id:str, operation:str, runtime=Depends(scoped_runtime)):
        if operation not in ('begin','finish'): raise HTTPException(404,'操作不存在')
        # Durable backend fence also invalidates already-captured QQ images.
        if operation=='begin':service().set_login(runtime.id,device_id,True)
        result = await service().gateway.request('POST',path(runtime,device_id)+'/login/'+operation)
        if operation=='finish':service().set_login(runtime.id,device_id,False)
        if operation == 'begin':
            for task in service().list(runtime.id):
                if task['state'] in ('queued','running'): await service().cancel(runtime.id,task['id'])
        return result

    @app.delete('/api/bots/{bot_id}/android/devices/{device_id}')
    async def delete(device_id:str,destroy_data:bool=False,confirm:str=Query(default='',max_length=64),runtime=Depends(scoped_runtime)):
        if service().busy(runtime.id):raise HTTPException(409,'请先停止安卓任务')
        if destroy_data and confirm!=device_id:raise HTTPException(422,'请确认要永久销毁此设备数据')
        return await service().gateway.request('DELETE',path(runtime,device_id)+f'?destroy_data={str(destroy_data).lower()}&confirm={quote(confirm,safe="")}')

    @app.get('/api/bots/{bot_id}/android/devices/{device_id}/observe')
    async def observe(device_id:str,runtime=Depends(scoped_runtime)):
        return await service().gateway.request('GET',path(runtime,device_id)+'/observe')

    @app.post('/api/bots/{bot_id}/android/devices/{device_id}/manual')
    async def manual(device_id:str,body:dict,runtime=Depends(scoped_runtime)):
        if service().busy(runtime.id):raise HTTPException(409,'请先人工接管或停止任务')
        return await service().gateway.request('POST',path(runtime,device_id)+'/action',body)

    @app.post('/api/bots/{bot_id}/android/devices/{device_id}/google-play',status_code=202)
    async def google_play(device_id:str,body:dict,runtime=Depends(scoped_runtime)):
        if service().busy(runtime.id):raise HTTPException(409,'请先停止安卓任务')
        return await service().gateway.request('POST',path(runtime,device_id)+'/google-play',body)

    @app.get('/api/bots/{bot_id}/android/devices/{device_id}/apps')
    async def apps(device_id:str,runtime=Depends(scoped_runtime)):
        return await service().gateway.request('GET',path(runtime,device_id)+'/apps')

    @app.post('/api/bots/{bot_id}/android/devices/{device_id}/desktop',status_code=202)
    async def desktop(device_id:str,runtime=Depends(scoped_runtime)):
        if service().busy(runtime.id):raise HTTPException(409,'请先停止安卓任务')
        return await service().gateway.request('POST',path(runtime,device_id)+'/desktop')

    @app.post('/api/bots/{bot_id}/android/devices/{device_id}/apps/{app_id}/install',status_code=202)
    async def install(device_id:str,app_id:str,runtime=Depends(scoped_runtime)):
        from urllib.parse import quote
        if service().busy(runtime.id):raise HTTPException(409,'请先停止安卓任务')
        return await service().gateway.request('POST',path(runtime,device_id)+'/apps/'+quote(app_id,safe='')+'/install')

    @app.post('/api/bots/{bot_id}/android/tasks',status_code=202)
    async def task(body:TaskBody,runtime=Depends(scoped_runtime)):
        # Missing runtime does not prevent presenting task configuration in the web UI.
        if not service().config(runtime.id).enabled:raise HTTPException(409,'请先启用安卓任务并配置视觉模型')
        if not service().gateway.configured:raise AndroidUnavailable('安卓运行时未配置')
        devices=(await service().gateway.request('GET',path(runtime)))['devices']
        device_id=body.device_id or (devices[0]['id'] if devices else '')
        if device_id not in [d['id'] for d in devices]:raise HTTPException(404,'当前 Bot 未绑定此设备')
        return service().submit(runtime.id,device_id,body.goal)

    @app.post('/api/bots/{bot_id}/android/tasks/{task_id}/cancel')
    async def cancel(task_id:str,runtime=Depends(scoped_runtime)):
        return await service().cancel(runtime.id,task_id)

    @app.post('/api/bots/{bot_id}/android/tasks/{task_id}/resume',status_code=202)
    async def resume(task_id:str,runtime=Depends(scoped_runtime)):
        task=service().get(runtime.id,task_id)
        devices=(await service().gateway.request('GET',path(runtime)))['devices']
        if task['device_id'] not in [d['id'] for d in devices]:raise HTTPException(404,'当前 Bot 未绑定此设备')
        return service().resume(runtime.id,task_id)

    @app.post('/api/bots/{bot_id}/android/tasks/{task_id}/deliver')
    async def deliver(task_id:str,runtime=Depends(scoped_runtime)):
        import json,re
        s=service();task=s.get(runtime.id,task_id);cfg=s.config(runtime.id)
        if task['state']!='completed' or task['origin'].get('source')!='web':raise HTTPException(409,'仅支持已完成的网页任务结果')
        if task['notification'] in ('sent','sending','unknown'):raise HTTPException(409,'已发送或发送结果未知，不自动重发')
        if not re.search(r'发(?:送)?给(?:主人|我)|告诉(?:主人|我)',task['goal']):raise HTTPException(409,'原任务未要求发送给主人')
        if runtime.store.load().transport!='napcat' or not cfg.qq_enabled or not cfg.qq_owner_id or not s.valid_origin(task):raise HTTPException(409,'授权主人或账号已变化，不能发送')
        origin={**task['origin'],'notify_owner':cfg.qq_owner_id}
        with s.db:s.db.execute('UPDATE android_tasks SET origin=?,notification=? WHERE id=?',(json.dumps(origin),'ready',task_id))
        await s.completion_callback(runtime.id,task_id)
        return s.get(runtime.id,task_id)

    @app.get('/api/bots/{bot_id}/android/tasks/{task_id}/diagnostics')
    async def diagnostics(task_id:str,runtime=Depends(scoped_runtime)):
        return {'attempts':service().diagnostics(runtime.id,task_id)}
