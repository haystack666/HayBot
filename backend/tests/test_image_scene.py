import json
from unittest.mock import AsyncMock
import pytest
from test_schedule import configured,schedule_bot,NOW,DAY
from app.store import Store
from app.image_scene import resolve_scene,schedule_context

@pytest.mark.asyncio
async def test_current_scene_fills_fields_but_keeps_explicit_action(tmp_path):
    store=Store(tmp_path);c=configured(store);bot,_=schedule_bot(store,[NOW])
    await bot.schedule.ensure();sid=bot.schedule.scope_id
    scene={k:{'value':v,'source':s} for k,v,s in [('location','图书馆','schedule'),('outfit','白色卫衣、牛仔裤','schedule'),('action','敷面膜自拍','user'),('appearance','低马尾、淡妆','schedule')]};scene['time_reference']='recent'
    bot.generate=AsyncMock(return_value={'message':{'content':json.dumps(scene,ensure_ascii=False)}})
    try:
        result=await resolve_scene(bot,c,'发张刚刚敷面膜时的自拍','敷面膜自拍','user:owner:owner',sid,False)
        assert '图书馆' in result and '敷面膜自拍' in result
        assert '对应时间' in bot.generate.call_args.args[1][0]['content']
        assert schedule_context(bot,c,sid,True,'自拍') is None
        assert schedule_context(bot,c,sid,False,'上次海边连衣裙自拍') is None
        before=bot.generate.await_count
        past=await resolve_scene(bot,c,'上次海边连衣裙自拍','海边连衣裙','user:owner:owner',sid,False)
        assert '图书馆' not in past and bot.generate.await_count==before
    finally:
        await bot.client.aclose();store.close()
