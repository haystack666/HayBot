import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.image_constraints import compile_constraints,PictureConstraints

@pytest.mark.asyncio
@pytest.mark.parametrize('text,view,framing,forbidden',[
 ('给我你的自拍','自拍相机视角','半身',['第三视角拍摄举手机']),
 ('镜子自拍，手机可以露出','镜中反射','半身',[]),
 ('别人帮拍全身背影，不要文字','第三视角背影','全身',['文字']),
 ('单人侧脸特写，别加其他人','侧面','特写',['其他人']),
])
async def test_general_constraints_preserve_current_request(text,view,framing,forbidden):
    result=PictureConstraints(viewpoint=view,framing=framing,forbidden_elements=forbidden)
    bot=SimpleNamespace(generate=AsyncMock(return_value={'message':{'content':result.model_dump_json()}}),store=SimpleNamespace(record_usage=lambda r:None))
    config=SimpleNamespace(ollama=SimpleNamespace(model_copy=lambda **k:None))
    compiled=await compile_constraints(bot,config,text,'旧画面设定')
    payload=json.loads(bot.generate.call_args.args[1][-1]['content'])
    assert payload['current_request']==text
    assert view in compiled and framing in compiled
    assert json.loads(compiled.split('\n')[-1])['forbidden_elements']==forbidden
