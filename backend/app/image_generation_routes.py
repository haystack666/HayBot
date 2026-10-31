"""Admin-only, Bot/account-scoped character references. No arbitrary file paths."""
import asyncio
import base64
import binascii
from typing import Literal

from fastapi import Depends, HTTPException
from fastapi.responses import Response
from pydantic import Field

from .config import StrictModel
from .image_generation import MAX_REFERENCE, checked_picture


def register_image_generation_routes(app, scoped_runtime):
    prefix = '/api/bots/{bot_id}/image-generation'

    def editable(runtime):
        if runtime.bot.state != 'stopped' or runtime.bot.image_generation.lock.locked():
            raise HTTPException(409, '请先停止机器人并等待图片创作结束，再修改角色参考图')

    @app.get(prefix)
    async def snapshot(runtime=Depends(scoped_runtime)):
        service = runtime.bot.image_generation
        return {'references': service.references(), 'reference_complete': service.reference_complete(), 'busy': service.lock.locked()}

    class Reference(StrictModel):
        slot: Literal['front', 'side', 'back', 'sheet']
        image: str = Field(min_length=1, max_length=MAX_REFERENCE*4//3+4)

    @app.post(prefix+'/references')
    async def upload(body:Reference, runtime=Depends(scoped_runtime)):
        # Lock before asynchronous decoding; start/config changes must not race uploads.
        async with runtime.control_lock:
            editable(runtime)
            try: raw = base64.b64decode(body.image, validate=True)
            except binascii.Error: raise ValueError('参考图编码无效') from None
            picture = await asyncio.to_thread(checked_picture, raw, reference=True)
            return {'references': runtime.bot.image_generation.add_reference(body.slot, picture)}

    @app.get(prefix+'/references/{rid}')
    async def reference(rid:str, runtime=Depends(scoped_runtime)):
        return Response(runtime.bot.image_generation.image(rid), media_type='image/jpeg')

    @app.delete(prefix+'/references/{rid}')
    async def remove(rid:str, runtime=Depends(scoped_runtime)):
        async with runtime.control_lock:
            editable(runtime)
            runtime.bot.image_generation.remove_reference(rid)
        return {'ok': True}
