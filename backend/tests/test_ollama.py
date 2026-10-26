from unittest.mock import AsyncMock

import httpx
import pytest

from app.bot import Bot
from app.config import OllamaConfig
from app.config import Settings
from app.ollama import ContextLimitError, chat_response
from app.store import Store


@pytest.mark.asyncio
async def test_context_overflow_drops_old_history_preserves_persona_and_current():
    messages = [{'role': 'system', 'content': '完整人格' * 1000},
                {'role': 'user', 'content': '旧问题'}, {'role': 'assistant', 'content': '旧回答'},
                {'role': 'user', 'content': '新问题', 'images': ['encoded-image']}]
    request = AsyncMock(side_effect=[ContextLimitError('over limit'), {'message': {'content': '正常回答'}}])
    result = await chat_response(request, OllamaConfig(), messages, 160)
    assert result['message']['content'] == '正常回答'
    assert request.await_count == 2
    second = request.await_args_list[1].kwargs['json']
    assert second['options']['num_ctx'] == 8192
    assert second['messages'] == [messages[0], messages[-1]]
    assert len(messages) == 4


@pytest.mark.asyncio
async def test_oversized_persona_or_current_is_not_silently_removed():
    request = AsyncMock(side_effect=ContextLimitError('超长'))
    with pytest.raises(ContextLimitError):
        await chat_response(request, OllamaConfig(), [{'role': 'system', 'content': '完整人格'},
                                                     {'role': 'user', 'content': '当前消息'}], 160)
    assert request.await_count == 1


@pytest.mark.asyncio
async def test_only_explicit_context_overflow_is_retried(tmp_path):
    store = Store(tmp_path)
    def response(request):
        return httpx.Response(400, json={'error': 'request (9000 tokens) exceeds the available context size (8192 tokens)'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        bot = Bot(store, client)
        with pytest.raises(ContextLimitError):
            await bot.request('POST', 'http://ollama/api/chat')
    request = AsyncMock(side_effect=ValueError('其他接口错误'))
    with pytest.raises(ValueError):
        await chat_response(request, OllamaConfig(), [{'role': 'system', 'content': '人格'},
                                                     {'role': 'user', 'content': '历史'},
                                                     {'role': 'assistant', 'content': '回答'},
                                                     {'role': 'user', 'content': '问题'}], 160)
    assert request.await_count == 1
    store.close()


@pytest.mark.asyncio
async def test_start_preloads_model_before_connecting_to_qq(tmp_path):
    store = Store(tmp_path)
    config = Settings()
    config.qq.app_id = '123456'
    config.qq.secret = 'test-secret'
    store.save(config)
    bot = Bot(store)
    bot.models = AsyncMock(return_value=[config.ollama.model])
    bot.request = AsyncMock(return_value={})
    async def gateway(*args, **kwargs):
        assert bot.request.await_count == 1
        assert bot.request.await_args.kwargs['json']['options']['num_ctx'] == 8192
        assert bot.request.await_args.kwargs['timeout'] == 300
        return {'url': 'wss://gateway.test'}
    bot.api = AsyncMock(side_effect=gateway)
    bot.run = AsyncMock()
    await bot.start()
    await bot.stop()
    await bot.client.aclose()
    store.close()
