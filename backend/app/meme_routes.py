"""Authenticated management APIs for the shared library and per-Bot policy."""
import asyncio
from fastapi import Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse

from .config import MemeConfig, StrictModel
from pydantic import Field
from .memes import MemeEdit


class DescribeMemeBody(StrictModel):
    provider_id: str = Field(default='', pattern=r'^(?:[a-f0-9]{32})?$')
    model: str = Field(default='', max_length=200)


def register_meme_routes(app, scoped_runtime):
    prefix='/api/bots/{bot_id}/memes'
    from .meme_gallery import MemeGallery
    gallery = MemeGallery()

    @app.get(prefix+'/gallery')
    async def online_gallery(category: str=Query('',max_length=120),q: str=Query('',max_length=120),
                             offset: int=Query(0,ge=0),limit: int=Query(48,ge=1,le=100),runtime=Depends(scoped_runtime)):
        result = await gallery.list(category,q,offset,limit)
        app.state.manager.memes.sync_gallery((await gallery.load())['items'])
        return result

    @app.get(prefix)
    async def listing(q: str=Query('',max_length=120),offset: int=Query(0,ge=0),limit: int=Query(48,ge=1,le=100),local_only: bool=False,runtime=Depends(scoped_runtime)):
        result=app.state.manager.memes.list(q,offset,limit,exclude_packs=['aigengtu'] if local_only else None)
        result['packs']=[dict(r) for r in app.state.manager.memes.db.execute('SELECT pack,COUNT(*) AS count FROM memes WHERE deleted=0 GROUP BY pack ORDER BY pack')]
        return result

    @app.get(prefix+'/config')
    async def config(runtime=Depends(scoped_runtime)):
        return runtime.store.load().memes.model_dump()

    @app.put(prefix+'/config')
    async def save_config(c:MemeConfig,runtime=Depends(scoped_runtime)):
        async with runtime.control_lock,app.state.manager.config_lock:
            for purpose in ('embedding','rerank'):
                selection=getattr(c,purpose)
                if selection.provider_id and app.state.manager.providers.get(selection.provider_id).purpose != purpose:
                    raise ValueError('表情包模型供应商用途不匹配')
            if c.enabled and (not c.embedding.provider_id or (not c.local_enabled and 'aigengtu' not in c.packs)):
                raise ValueError('启用表情包前请选择 Embedding 模型和至少一个集合')
            if runtime.bot.memes.lock.locked():raise HTTPException(409,'正在构建索引，请完成后再修改配置')
            config=runtime.store.load();config.memes=c;runtime.store.save(config)
            runtime.store.log('info','表情包策略已保存',category='model',event='meme.config_saved')
            return c.model_dump()

    @app.get(prefix+'/index')
    async def index(runtime=Depends(scoped_runtime)):
        return runtime.bot.memes.status()

    @app.post(prefix+'/rebuild',status_code=202)
    async def rebuild(runtime=Depends(scoped_runtime)):
        if not runtime.bot.memes.fingerprint():raise ValueError('请先保存 Embedding 配置')
        if 'aigengtu' in runtime.store.load().memes.packs:
            app.state.manager.memes.sync_gallery((await gallery.load())['items'])
        runtime.bot.memes.schedule_rebuild()
        return {'ok':True}

    @app.post(prefix+'/upload',status_code=201)
    async def upload(request:Request,name:str=Query('自定义表情包',min_length=1,max_length=120),runtime=Depends(scoped_runtime)):
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>10*1024*1024:raise HTTPException(413,'图片必须小于 10 MB')
        return app.state.manager.memes.add(bytes(raw),name)

    @app.get(prefix+'/{mid}/image')
    async def image(mid:str,sent:bool=False,runtime=Depends(scoped_runtime)):
        library=app.state.manager.memes
        path=await library.ensure_image(mid)
        item=library.get(mid,include_deleted=True)
        if sent:
            raw=await asyncio.to_thread(library.convert_upload,path)
            return Response(raw,media_type='image/jpeg' if raw.startswith(b'\xff\xd8') else 'image/png')
        return FileResponse(path,media_type={'PNG':'image/png','JPEG':'image/jpeg','GIF':'image/gif','WEBP':'image/webp'}[item['format']])

    @app.post(prefix+'/{mid}/describe')
    async def describe_meme(mid: str, body: DescribeMemeBody, runtime=Depends(scoped_runtime)):
        from .meme_describe import describe
        return await describe(runtime,app.state.manager.memes,mid,body.provider_id,body.model)

    @app.patch(prefix+'/{mid}')
    async def edit(mid:str,c:MemeEdit,runtime=Depends(scoped_runtime)):
        library=app.state.manager.memes
        return library.update(mid,c.model_dump(exclude_none=True))

    @app.delete(prefix+'/{mid}')
    async def delete(mid:str,runtime=Depends(scoped_runtime)):
        app.state.manager.memes.delete(mid)
        return {'ok':True}
