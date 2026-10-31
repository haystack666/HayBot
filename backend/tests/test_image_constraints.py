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

@pytest.mark.asyncio
async def test_constraint_failure_never_calls_paid_image_generation(tmp_path,monkeypatch):
    from test_image_generation import setup_generation
    from test_reply_segments import event
    store,bot,providers=setup_generation(tmp_path)
    monkeypatch.setattr('app.image_constraints.compile_constraints',AsyncMock(side_effect=ValueError('invalid schema')))
    image=AsyncMock();monkeypatch.setattr('app.image_generation.generate_image',image)
    request=event();request['d']['content']='/画图 自拍'
    try:
        await bot.handle(request)
        image.assert_not_awaited()
        assert store.db.execute("SELECT count(*) FROM logs WHERE event='image_generation.constraints_failed'").fetchone()[0]==1
        assert store.db.execute("SELECT count(*) FROM chat_messages WHERE source='generated_image'").fetchone()[0]==0
    finally:
        await bot.client.aclose();providers.close();store.close()


@pytest.mark.asyncio
async def test_nonconforming_actual_picture_is_not_sent(tmp_path,monkeypatch):
    from test_image_generation import setup_generation,picture
    from test_reply_segments import event
    from app.image_conversation import ImageCaption
    store,bot,providers=setup_generation(tmp_path)
    monkeypatch.setattr('app.image_constraints.compile_constraints',AsyncMock(return_value='自拍相机视角，不允许第三视角举手机'))
    monkeypatch.setattr('app.image_conversation.acknowledgement',AsyncMock(return_value='等我一下。'))
    monkeypatch.setattr('app.image_generation.generate_image',AsyncMock(return_value=picture()))
    monkeypatch.setattr('app.image_conversation.caption',AsyncMock(return_value=ImageCaption(requirements_met=False,violations=['实际是第三视角举手机'],visual_description='角色举着手机',reply='给你啦')))
    request=event();request['d']['content']='/画图 自拍'
    try:
        await bot.handle(request)
        assert all(c.kwargs['json']['msg_type']==0 for c in bot.api.await_args_list)
        assert store.db.execute("SELECT count(*) FROM chat_messages WHERE source='generated_image'").fetchone()[0]==0
    finally:
        await bot.client.aclose();providers.close();store.close()

@pytest.mark.asyncio
async def test_malformed_constraint_json_is_repaired_without_image_call():
    from app.image_constraints import compile_constraints,PictureConstraints
    from types import SimpleNamespace
    model=AsyncMock(side_effect=[{'message':{'content':'{"viewpoint":"unfinished'}},
        {'message':{'content':PictureConstraints(viewpoint='自拍相机视角').model_dump_json()}}])
    bot=SimpleNamespace(generate=model,store=SimpleNamespace(record_usage=lambda r:None,log=lambda *a,**k:None))
    c=SimpleNamespace(ollama=SimpleNamespace(model_copy=lambda **k:None))
    assert '自拍相机' in await compile_constraints(bot,c,'自拍','自拍')
    assert model.await_count==2 and model.call_args_list[0].args[2]==4000
