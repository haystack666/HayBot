"""A provider's Thinking preference applies only to conversational replies."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from app.bot import Bot
from app.config import OllamaConfig
from app.providers import ProviderConfig, ProviderStore, generate
from app.store import Store
from test_providers import client


@pytest.mark.asyncio
@pytest.mark.parametrize('native', [True, False])
@pytest.mark.parametrize('thinking', [True, False])
async def test_dialogue_adapter_sends_explicit_thinking_for_custom_model(native, thinking):
    bodies = []
    async def request(method, url, **kwargs):
        bodies.append(kwargs['json'])
        return {'message': {'content': 'ok'}} if native else {'choices': [{'message': {'content': 'ok'}}]}
    provider = ProviderConfig(type='ollama', base_url='https://model.test' if native else 'https://model.test/v1')
    await generate(request, provider, OllamaConfig(model='Qwen3635BUncensoredQ8KP:latest'), [{'role': 'user', 'content': 'hi'}], 128, thinking=thinking)
    assert bodies[0].get('think') is thinking if native else bodies[0].get('reasoning_effort') == ('medium' if thinking else 'none')


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['deepseek', 'openai_chat', 'openai_responses', 'anthropic'])
async def test_ollama_thinking_control_does_not_change_other_protocols(kind):
    async def request(method, url, **kwargs):
        assert 'think' not in kwargs['json'] and 'reasoning_effort' not in kwargs['json']
        if kind == 'openai_responses': return {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'ok'}]}]}
        if kind == 'anthropic': return {'content': [{'type': 'text', 'text': 'ok'}]}
        return {'choices': [{'message': {'content': 'ok'}}]}
    await generate(request, ProviderConfig(type=kind, base_url='https://model.test/v1'), OllamaConfig(model='Qwen3635BUncensoredQ8KP:latest'), [{'role':'user','content':'hi'}], 128, thinking=False)


@pytest.mark.asyncio
@pytest.mark.parametrize('native', [True, False])
@pytest.mark.parametrize('thinking', [True, False])
async def test_real_handle_uses_provider_switch_but_auxiliary_generation_is_unchanged(tmp_path, native, thinking):
    store = Store(tmp_path); providers = ProviderStore(tmp_path)
    config = store.load(); config.qq.app_id = '111'; config.rules.cooldown = 0; config.ollama.model = 'Qwen3635BUncensoredQ8KP:latest'
    config.ollama.provider_id = providers.save(ProviderConfig(type='ollama', base_url='http://model.test' if native else 'http://model.test/v1', chat_thinking=thinking))
    store.save(config); bodies = []
    def transport(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={'message': {'content': 'ok'}} if native else {'choices': [{'message': {'content': 'ok'}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        bot = Bot(store, client, providers=providers); bot.api = AsyncMock(return_value={'id': 'accepted'})
        await bot.handle({'t':'C2C_MESSAGE_CREATE','d':{'id':'m1','content':'hi','author':{'user_openid':'alice'}}})
        assert bot.api.await_count == 1
        assert bodies[0].get('think') is thinking if native else bodies[0].get('reasoning_effort') == ('medium' if thinking else 'none')
        # Memory extraction/proactive generation and schedule streaming omit the dialogue override.
        for stream in (False, True):
            await bot.generate(config.ollama, [{'role':'user','content':'auxiliary'}], 128, stream=stream)
            assert 'think' not in bodies[-1] and 'reasoning_effort' not in bodies[-1]
    store.close(); providers.close()


def test_provider_switch_roundtrips_live_without_resetting_context(client):
    manager = client.app.state.manager; runtime = client.portal.call(manager.get, 'default')
    pid = client.portal.call(lambda: runtime.store.load().ollama.provider_id)
    original = client.get('/api/providers').json()['providers'][0]
    assert original['chat_thinking'] is False
    payload = {k:v for k,v in original.items() if k not in ('id','api_key_set','used_by')}
    client.portal.call(runtime.store.save_history, 'user:alice:alice', [{'role':'user','content':'keep history'}], 2)
    runtime.bot.state = 'connected'
    for enabled in (True, False):
        result = client.put(f'/api/providers/{pid}', json={**payload, 'chat_thinking':enabled})
        assert result.status_code == 200 and result.json()['chat_thinking'] is enabled
        assert client.portal.call(runtime.store.history, 'user:alice:alice', 2)
    runtime.bot.state = 'stopped'


def test_timeout_default_bounds_and_saved_values():
    assert OllamaConfig().timeout == 120
    assert OllamaConfig(timeout=600).timeout == 600
    assert OllamaConfig(timeout=90).timeout == 90
    for value in (4, 601):
        with pytest.raises(ValidationError): OllamaConfig(timeout=value)


def test_settings_and_generation_probe_accept_ten_minutes(client, monkeypatch):
    settings = client.get('/api/bots/default/settings').json(); settings['qq'].pop('secret_set')
    settings['ollama']['timeout'] = 600
    assert client.put('/api/bots/default/settings', json=settings).status_code == 200
    settings['ollama']['timeout'] = 601
    assert client.put('/api/bots/default/settings', json=settings).status_code == 422
    import app.main
    mock = AsyncMock(return_value={'message':{'content':'ok'}}); monkeypatch.setattr(app.main, 'generate', mock)
    result = client.post('/api/providers/test-generation', json={'type':'ollama','model':'custom','timeout':600})
    assert result.status_code == 200
    assert mock.await_args.args[2].timeout == 600
    assert client.post('/api/providers/test-generation', json={'type':'ollama','model':'custom','timeout':601}).status_code == 422
