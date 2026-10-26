"""Authenticated NapCat Qzone management; drafts are separate from chat archives."""
import time
from fastapi import Depends,HTTPException,Query,Request
from fastapi.responses import FileResponse
from pydantic import Field

from .config import StrictModel
from .qzone_store import QzoneConfig,PostWrite


def register_qzone_routes(app,scoped_runtime):
    prefix='/api/bots/{bot_id}/qzone'

    def service(runtime):
        if not runtime.qzone.supported():raise ValueError('QQ 空间功能仅支持 NapCat 机器人')
        return runtime.qzone

    @app.get(prefix)
    async def snapshot(runtime=Depends(scoped_runtime)):
        q=runtime.qzone;c=runtime.store.load();policy,epoch=q.data.config(c.account_id)
        return {'supported':q.supported(),'connected':q.ready(c.account_id),'config':policy.model_dump(),'epoch':epoch,'busy':q.lock.locked(),
            'owner':q.owner.snapshot(),'random':q.random.snapshot()}

    @app.put(prefix+'/config')
    async def config(body:QzoneConfig,runtime=Depends(scoped_runtime)):
        q=service(runtime);q.data.save_config(runtime.store.load().account_id,body)
        return body.model_dump()

    class Generate(StrictModel):
        instruction:str=Field(default='',max_length=2000)

    @app.post(prefix+'/generate')
    async def generate(body:Generate,runtime=Depends(scoped_runtime)):
        q=service(runtime)
        if q.lock.locked():raise HTTPException(409,'正在处理发布，请稍后生成')
        async with q.lock:return {'content':await q.generate(body.instruction)}

    @app.get(prefix+'/posts')
    async def posts(offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100),runtime=Depends(scoped_runtime)):
        return runtime.qzone.data.list(runtime.store.load().account_id,offset,limit)

    @app.post(prefix+'/posts',status_code=201)
    async def create(body:PostWrite,runtime=Depends(scoped_runtime)):
        q=service(runtime)
        return q.data.create(runtime.store.load().account_id,body)

    @app.put(prefix+'/posts/{pid}')
    async def update(pid:str,body:PostWrite,runtime=Depends(scoped_runtime)):
        q=service(runtime);return q.data.update(runtime.store.load().account_id,pid,body)

    @app.post(prefix+'/posts/{pid}/publish',status_code=202)
    async def publish(pid:str,runtime=Depends(scoped_runtime)):
        q=service(runtime);account=runtime.store.load().account_id
        if not q.ready(account):raise HTTPException(409,'请先启动并连接此 NapCat 机器人')
        q.submit(pid)
        return q.data.get(account,pid)

    @app.delete(prefix+'/posts/{pid}')
    async def remove(pid:str,runtime=Depends(scoped_runtime)):
        await service(runtime).remove(pid);return {'ok':True}

    @app.post(prefix+'/images',status_code=201)
    async def upload(request:Request,name:str=Query('配图',min_length=1,max_length=120),runtime=Depends(scoped_runtime)):
        q=service(runtime);raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>10*1024*1024:raise HTTPException(413,'单张配图不能超过10MB')
        return q.data.add_image(runtime.store.load().account_id,bytes(raw),name)

    @app.get(prefix+'/images/{mid}')
    async def image(mid:str,runtime=Depends(scoped_runtime)):
        path=service(runtime).data.image(runtime.store.load().account_id,mid)
        with path.open('rb') as f:jpeg=f.read(2)==b'\xff\xd8'
        return FileResponse(path,media_type='image/jpeg' if jpeg else 'image/png')
