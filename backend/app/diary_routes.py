"""Diaries are managed only through the authenticated Bot administration API."""
from fastapi import Depends, HTTPException, Query
from .diary_store import DiaryConfig, DiaryWrite


def register_diary_routes(app, scoped_runtime):
    prefix='/api/bots/{bot_id}/diary'

    @app.get(prefix)
    async def snapshot(runtime=Depends(scoped_runtime)):
        d=runtime.bot.diary;c=runtime.store.load();policy,revision,_=d.data.config(c.account_id)
        return {'config':policy.model_dump(),'revision':revision,'busy':d.lock.locked(),
                'today':d.local(policy).date().isoformat(),'account_id':c.account_id,
                'contacts':runtime.store.contacts(c.account_id)}

    @app.put(prefix+'/config')
    async def config(body:DiaryConfig,runtime=Depends(scoped_runtime)):
        d=runtime.bot.diary
        d.data.save_config(runtime.store.load().account_id,body)
        return body.model_dump()

    @app.get(prefix+'/entries')
    async def entries(offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100),runtime=Depends(scoped_runtime)):
        return runtime.bot.diary.data.list(runtime.store.load().account_id,offset,limit)

    @app.post(prefix+'/write')
    async def write(body:DiaryWrite,runtime=Depends(scoped_runtime)):
        if runtime.bot.diary.lock.locked():
            raise HTTPException(409,'正在写日记，请稍后再试')
        if not runtime.store.load().account_id:
            raise ValueError('请先配置机器人接入账号')
        return await runtime.bot.diary.write(body.day)

    @app.get(prefix+'/entries/{entry_id}')
    async def entry(entry_id:str,runtime=Depends(scoped_runtime)):
        return runtime.bot.diary.data.get(runtime.store.load().account_id,entry_id)

    @app.get(prefix+'/entries/{entry_id}/versions')
    async def versions(entry_id:str,runtime=Depends(scoped_runtime)):
        return {'items':runtime.bot.diary.data.versions(runtime.store.load().account_id,entry_id)}

    @app.delete(prefix+'/entries/{entry_id}')
    async def remove(entry_id:str,runtime=Depends(scoped_runtime)):
        runtime.bot.diary.data.delete(runtime.store.load().account_id,entry_id)
        return {'ok':True}
