import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from PIL import Image

from app.meme_describe import describe, frames
from app.memes import MemeCatalog
from app.store import Store


@pytest.mark.asyncio
async def test_ai_description_is_reviewable_and_does_not_save_or_enable_image(tmp_path):
    library=MemeCatalog(tmp_path/'library');store=Store(tmp_path/'bot')
    raw=io.BytesIO();Image.new('RGB',(16,16),'blue').save(raw,'PNG')
    item=library.add(raw.getvalue(),'测试图')
    c=store.load();c.ollama.model='vision-model';store.save(c)
    generated={'visual':'蓝色方块','text':'','scenarios':['表达平静'],'avoid_scenarios':['需要明确文字信息时'],
               'emotions':['平静'],'tone':'中性','confidence':.9}
    generate=AsyncMock(return_value={'message':{'content':json.dumps(generated)},'prompt_eval_count':3,'eval_count':4})
    runtime=SimpleNamespace(store=store,bot=SimpleNamespace(provider=lambda _:SimpleNamespace(purpose='chat',vision=True),generate=generate))
    try:
        result=await describe(runtime,library,item['id'])
        assert result['description']['needs_review'] is True
        assert result['description']['visual']=='蓝色方块'
        current=library.get(item['id'])
        assert current['description']==item['description'] and not current['enabled']
        content=generate.call_args.args[1][1]['content']
        assert content[1]['image_url']['url'].startswith('data:image/jpeg;base64,')
        runtime.bot.provider=lambda _:SimpleNamespace(purpose='chat',vision=False)
        with pytest.raises(HTTPException) as error:
            await describe(runtime,library,item['id'])
        assert error.value.status_code==409 and generate.await_count==1
    finally:
        store.close();library.close()


def test_gif_description_samples_actual_first_middle_and_last_frames(tmp_path):
    image=tmp_path/'animated.gif'
    Image.new('RGB',(8,8),'red').save(image,save_all=True,append_images=[Image.new('RGB',(8,8),'blue'),Image.new('RGB',(8,8),'green')])
    assert len(frames(image))==3
