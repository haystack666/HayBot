from unittest.mock import AsyncMock
import pytest
from test_image_generation import setup_generation,picture
from test_reply_segments import event

@pytest.mark.asyncio
async def test_wait_precedes_generation_and_uses_separate_message_sequence(tmp_path,monkeypatch):
    store,bot,providers=setup_generation(tmp_path);order=[]
    monkeypatch.setattr('app.image_conversation.acknowledgement',AsyncMock(return_value='等我一下，给你准备张适合屏保的。'))
    async def generate(*a,**k):order.append('generate');return picture()
    monkeypatch.setattr('app.image_generation.generate_image',generate)
    monkeypatch.setattr('app.image_conversation.caption',AsyncMock(return_value=__import__('app.image_conversation',fromlist=['ImageCaption']).ImageCaption(requirements_met=True,visual_description='蓝色画面',reply='给你啦。')))
    async def api(method,path,**kwargs):
        if path.endswith('/files'):return {'file_info':'media'}
        b=kwargs['json'];order.append((b['msg_type'],b['msg_seq']));return {'id':'ok'}
    bot.api.side_effect=api
    request=event();request['d']['content']='/画图 海边自拍'
    try:
        await bot.handle(request)
        assert order==[(0,1),'generate',(7,2),(0,3)]
        assert store.db.execute("SELECT count(*) FROM chat_messages WHERE source='image_wait'").fetchone()[0]==1
    finally:
        await bot.client.aclose();providers.close();store.close()


@pytest.fixture(autouse=True)
def isolated_composition_compiler(monkeypatch):
    # These tests isolate delivery/intent behavior; compiler contracts have their own suite.
    monkeypatch.setattr('app.image_constraints.compile_constraints',AsyncMock(return_value=''))
    monkeypatch.setattr('app.image_conversation.failure_reply',AsyncMock(return_value='这张先不给你啦，没弄好。'))
