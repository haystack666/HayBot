import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.bot import Bot
from app.config import OllamaConfig, Settings
from app.main import create_app
from app.proactive import ProactiveService
from app.providers import ProviderConfig, ProviderHTTPError, ProviderStore, endpoint, generate, list_models, read_response
from app.registry import BotManager, BotRegistry
from app.store import Store

PASSWORD = 'test-password-long-enough'
KINDS = ['ollama', 'openai_chat', 'openai_responses', 'anthropic', 'deepseek']


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', PASSWORD)
    with TestClient(create_app(tmp_path)) as client:
        assert client.post('/api/login', json={'password': PASSWORD}).status_code == 200
        yield client


def body(client, bot_id='default'):
    settings = client.get(f'/api/bots/{bot_id}/settings').json()
    settings['qq'].pop('secret_set')
    return settings


def reply(kind):
    if kind == 'ollama':
        return {'message': {'content': '回答正文'}, 'prompt_eval_count': 21, 'eval_count': 9}
    if kind == 'openai_responses':
        return {'status': 'completed', 'output': [{'type': 'reasoning', 'summary': [{'text': '不应输出'}]},
                {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '回答正文'}]}],
                'usage': {'input_tokens': 21, 'output_tokens': 9}}
    if kind == 'anthropic':
        return {'content': [{'type': 'thinking', 'thinking': '不应输出'}, {'type': 'text', 'text': '回答正文'}],
                'usage': {'input_tokens': 11, 'cache_creation_input_tokens': 3, 'cache_read_input_tokens': 7, 'output_tokens': 9}}
    return {'choices': [{'message': {'content': '回答正文', 'reasoning_content': '不应输出'}}],
            'usage': {'prompt_tokens': 21, 'completion_tokens': 9}}


def test_provider_catalog_encryption_names_and_secret_semantics(tmp_path):
    catalog = ProviderStore(tmp_path)
    first = catalog.save(ProviderConfig(api_key='key-secret-sentinel'))
    second = catalog.save(ProviderConfig(base_url='https://second.test'))
    assert catalog.get(first).name == 'ollama-1' and catalog.get(second).name == 'ollama-2'
    assert catalog.public(first)['api_key_set'] and 'api_key' not in catalog.public(first)
    assert 'key-secret-sentinel' not in catalog.db.execute('SELECT value FROM providers WHERE id=?', (first,)).fetchone()['value']
    assert (tmp_path / 'providers.key').stat().st_mode & 0o777 == 0o600
    catalog.save(ProviderConfig(name='本地连接'), first)
    assert catalog.get(first).api_key == 'key-secret-sentinel'
    catalog.save(ProviderConfig(name='新地址', base_url='https://new.test'), first)
    assert catalog.get(first).api_key == ''
    catalog.save(ProviderConfig(base_url='https://new.test', api_key='replacement'), first)
    catalog.save(ProviderConfig(base_url='https://new.test', clear_api_key=True), first)
    assert not catalog.get(first).api_key
    with pytest.raises(ValueError):
        catalog.save(ProviderConfig(name='OLLAMA-2'))
    catalog.close()
    reopened = ProviderStore(tmp_path)
    assert len(reopened.ids()) == 2 and not reopened.get(first).api_key
    reopened.close()


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'http://user:password@test', 'https://test?key=secret', 'https://test/#key', 'http://test:bad'])
def test_invalid_provider_url_and_key_are_rejected(client, url):
    response = client.post('/api/providers', json={'base_url': url, 'api_key': 'secret-sentinel'})
    assert response.status_code == 422 and 'secret-sentinel' not in response.text
    response = client.post('/api/providers', json={'api_key': 'secret\nheader'})
    assert response.status_code == 422 and 'secret' not in response.text


@pytest.mark.asyncio
async def test_migration_keeps_each_bots_settings_and_archives(tmp_path):
    registry = BotRegistry(tmp_path)
    second = registry.create('外部 Bot')['id']
    registry.archive(second, True)
    for bot_id, url in [('default', 'http://inside.test:11434'), (second, 'https://outside.test/prefix')]:
        store = Store(registry.directory(bot_id)); config = Settings()
        config.qq.secret = 'unchanged-qq-secret'
        config.rules.prompt = 'unchanged-persona'
        config.ollama.url = url; config.ollama.model = 'unchanged-model'
        store.save(config); store.save_history('user:u:u', [{'role': 'user', 'content': 'keep'}], 2)
        store.record_usage({'prompt_eval_count': 10}); store.close()
    registry.close()
    manager = BotManager(tmp_path)
    assert len(manager.providers.ids()) == 2
    original_ids = manager.providers.ids()
    for profile in manager.registry.list(True):
        store = Store(manager.registry.directory(profile['id'])); c = store.load()
        assert c.qq.secret == 'unchanged-qq-secret' and c.rules.prompt == 'unchanged-persona'
        assert c.ollama.model == 'unchanged-model' and c.ollama.provider_id in original_ids
        assert manager.providers.get(c.ollama.provider_id).base_url == c.ollama.url
        assert store.history('user:u:u', 2) and store.stats()['input_tokens'] == 10
        store.close()
    await manager.close()
    manager = BotManager(tmp_path)
    assert manager.providers.ids() == original_ids
    assert manager.registry.get(second)['archived']
    await manager.close()


def test_provider_api_references_archive_and_removal(client, tmp_path):
    providers = client.get('/api/providers').json()['providers']; original = providers[0]['id']
    assert providers[0]['used_by'][0]['id'] == 'default'
    result = client.post('/api/providers', json={'type': 'openai_responses', 'base_url': 'https://models.test/v1', 'api_key': 'private-provider-key'})
    assert result.status_code == 201 and result.json()['name'] == 'responses-1'
    added = result.json()['id']
    assert 'private-provider-key' not in result.text and 'private-provider-key' not in client.get('/api/providers').text
    settings = body(client); settings['ollama'].update(provider_id=added, model='model-a')
    assert client.put('/api/settings', json=settings).status_code == 200
    assert client.get('/api/bots').json()['bots'][0]['provider_name'] == 'responses-1'
    assert client.delete(f'/api/providers/{added}').status_code == 409
    assert client.post('/api/bots/default/archive').status_code == 200
    assert client.delete(f'/api/providers/{added}').status_code == 409
    assert client.post('/api/bots/default/restore').status_code == 200
    settings = body(client); settings['ollama']['provider_id'] = original
    assert client.put('/api/settings', json=settings).status_code == 200
    assert client.delete(f'/api/providers/{added}').status_code == 200
    assert client.put(f'/api/providers/{added}', json={'base_url': 'http://missing.test'}).status_code == 404
    settings['ollama']['provider_id'] = 'a' * 32
    assert client.put('/api/settings', json=settings).status_code == 404
    client.post('/api/logout')
    assert client.get('/api/providers').status_code == 401
    assert client.post('/api/providers', json={}).status_code == 401


def test_provider_edit_guard_during_generation_and_start(client):
    manager = client.app.state.manager; runtime = client.portal.call(manager.get, 'default')
    pid = client.portal.call(lambda: runtime.store.load().ollama.provider_id)
    original = client.portal.call(manager.providers.public, pid)
    def payload(name='renamed'):
        return {k: v for k, v in {**original, 'name': name}.items() if k not in ('id', 'api_key_set')}
    runtime.bot.state = 'connecting'
    assert client.put(f'/api/providers/{pid}', json=payload()).status_code == 200
    assert client.put(f'/api/providers/{pid}', json={**payload(), 'base_url': 'https://changed.test'}).status_code == 409
    runtime.bot.state = 'stopped'; runtime.proactive.busy = True
    assert client.put(f'/api/providers/{pid}', json={**payload(), 'api_key': 'new-key'}).status_code == 409
    runtime.proactive.busy = False
    client.portal.call(runtime.store.save_history, 'user:x:x', [{'role': 'user', 'content': 'old-model-context'}], 2)
    client.portal.call(runtime.store.chat.record, '', 'user', 'x', 'user', 'archive-kept', 'keep')
    assert client.put(f'/api/providers/{pid}', json={**payload(), 'base_url': 'https://changed.test'}).status_code == 200
    assert not client.portal.call(runtime.store.history, 'user:x:x', 2)
    assert client.portal.call(lambda: runtime.store.db.execute('SELECT count(*) FROM chat_messages').fetchone()[0]) == 1


@pytest.mark.parametrize('kind,base,path', [('ollama','https://test/proxy/api','/proxy/api/chat'),
    ('openai_chat','https://test','/v1/chat/completions'), ('openai_responses','https://test/custom/v1','/custom/v1/responses'),
    ('anthropic','https://test','/v1/messages'), ('deepseek','https://test','/chat/completions')])
@pytest.mark.asyncio
async def test_protocol_body_auth_images_and_usage(kind, base, path):
    selection = OllamaConfig(model='selected', temperature=0.6)
    provider = ProviderConfig(type=kind, base_url=base, api_key='private-key')
    messages = [{'role': 'system', 'content': '完整人格'}, {'role': 'user', 'content': '旧问题'},
                {'role': 'assistant', 'content': '旧回答'}, {'role': 'user', 'content': '看图', 'images': ['encoded-jpeg']}]
    request = AsyncMock(return_value=reply(kind))
    result = await generate(request, provider, selection, messages, 160)
    assert result == {'message': {'content': '回答正文'}, 'prompt_eval_count': 21, 'eval_count': 9}
    call = request.await_args; payload = call.kwargs['json']
    assert call.args[1] == 'https://test' + path
    assert payload['model'] == 'selected' and payload['stream'] is False
    if kind == 'anthropic':
        assert call.kwargs['headers'] == {'x-api-key': 'private-key', 'anthropic-version': '2023-06-01'}
        assert payload['system'] == '完整人格'
        assert payload['messages'][-1]['content'][1]['source']['data'] == 'encoded-jpeg'
        assert payload['max_tokens'] == 160
    else:
        assert call.kwargs['headers'] == {'Authorization': 'Bearer private-key'}
        if kind == 'openai_responses':
            assert payload['store'] is False and 'previous_response_id' not in payload
            assert payload['input'][0]['content'] == '完整人格' and payload['max_output_tokens'] == 160
            assert payload['input'][-1]['content'][1]['image_url'] == 'data:image/jpeg;base64,encoded-jpeg'
        elif kind == 'ollama':
            assert payload['messages'][-1]['images'] == ['encoded-jpeg'] and payload['options']['num_ctx'] == 8192
        else:
            assert payload['messages'][0]['content'] == '完整人格'
            assert payload['messages'][-1]['content'][1]['image_url']['url'].endswith('encoded-jpeg')
            assert payload['max_tokens'] == 160
    assert messages[-1]['images'] == ['encoded-jpeg'] and 'private-key' not in json.dumps(payload)


@pytest.mark.asyncio
async def test_generation_options_and_anthropic_version():
    selection = OllamaConfig(model='reasoning-model')
    request = AsyncMock(return_value=reply('openai_chat'))
    await generate(request, ProviderConfig(type='openai_chat', send_temperature=False, token_limit_field='max_completion_tokens'), selection, [{'role':'user','content':'hello'}], 128)
    payload = request.await_args.kwargs['json']
    assert 'temperature' not in payload and payload['max_completion_tokens'] == 128 and 'max_tokens' not in payload
    request.return_value = reply('anthropic')
    await generate(request, ProviderConfig(type='anthropic', anthropic_version='2026-10-21'), selection, [{'role':'system','content':'persona'},{'role':'user','content':'hi'}], 128)
    assert 'temperature' not in request.await_args.kwargs['json']
    assert request.await_args.kwargs['headers']['anthropic-version'] == '2026-10-21'


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.asyncio
async def test_bot_reply_and_proactive_use_chosen_provider(tmp_path, kind):
    catalog = ProviderStore(tmp_path)
    pid = catalog.save(ProviderConfig(type=kind, base_url='https://provider.test/v1', api_key='provider-secret', ollama_api='native' if kind == 'ollama' else 'auto'))
    store = Store(tmp_path); config = Settings(); config.qq.app_id = '111'
    config.ollama.provider_id = pid; config.ollama.model = 'chosen-model'; config.rules.cooldown = 0
    store.save(config)
    calls = []
    def transport(request):
        assert request.url.host == 'provider.test'
        assert request.headers['x-api-key' if kind == 'anthropic' else 'Authorization'] == ('provider-secret' if kind == 'anthropic' else 'Bearer provider-secret')
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=reply(kind))
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        bot = Bot(store, client, providers=catalog); bot.api = AsyncMock(return_value={'id':'sent'})
        await bot.handle({'t':'C2C_MESSAGE_CREATE','d':{'id':'m1','content':'你好','author':{'user_openid':'user'}}})
        assert bot.stats['sent'] == 1 and bot.stats['input_tokens'] == 21
        assert bot.api.await_args.args[1] == '/v2/users/user/messages'
        service = ProactiveService(store, bot)
        assert await service.generate(config, 'user', '问候') == '回答正文'
        assert len(calls) == 2 and all(call['model'] == 'chosen-model' for call in calls)
        assert bot.stats['total_tokens'] == 60
        assert store.db.execute('SELECT count(*) FROM chat_messages').fetchone()[0] == 2
    store.close(); catalog.close()


@pytest.mark.parametrize('kind', ['openai_chat','openai_responses','anthropic','deepseek'])
@pytest.mark.asyncio
async def test_external_start_does_not_call_ollama_or_generate(tmp_path, kind):
    catalog = ProviderStore(tmp_path); pid = catalog.save(ProviderConfig(type=kind, base_url='https://provider.test'))
    store = Store(tmp_path); config = Settings(); config.qq.app_id='111';config.qq.secret='qq-secret';config.ollama.provider_id=pid;store.save(config)
    bot = Bot(store, providers=catalog)
    bot.models = AsyncMock(side_effect=ProviderHTTPError(404)); bot.request=AsyncMock()
    bot.api=AsyncMock(return_value={'url':'wss://qq.test'});bot.run=AsyncMock()
    await bot.start(); await bot.stop()
    assert bot.request.await_count == 0 and bot.api.await_count == 1
    bot.models.side_effect=ProviderHTTPError(401)
    with pytest.raises(ProviderHTTPError): await bot.start()
    assert bot.state == 'stopped'
    await bot.client.aclose(); store.close();catalog.close()


def test_test_endpoints_preserve_keys_and_do_not_leak_or_send_qq(client, monkeypatch):
    result = client.post('/api/providers', json={'type':'openai_responses','base_url':'https://service.test/v1','api_key':'key-sentinel'}).json()
    pid=result['id'];seen=[]
    async def request(self, method, url, **kwargs):
        assert str(url).startswith('https://service.test/v1/')
        assert kwargs['headers']['Authorization']=='Bearer key-sentinel'
        seen.append((method,url,kwargs))
        if str(url).endswith('/models'):return httpx.Response(404,json={'error':{'message':'private-key-sentinel'}})
        return httpx.Response(200,json=reply('openai_responses'))
    monkeypatch.setattr(httpx.AsyncClient,'request',request)
    payload={'type':'openai_responses','base_url':'https://service.test/v1'}
    response=client.post(f'/api/providers/test?provider_id={pid}',json=payload)
    assert response.status_code==200 and not response.json()['models_supported']
    response=client.post(f'/api/providers/test-generation?provider_id={pid}',json={**payload,'model':'chosen'})
    assert response.status_code==200 and response.json()['content']=='回答正文'
    assert client.get('/api/status').json()['stats']['total_tokens']==0
    assert len(seen)==2
    async def failed(self, method, url, **kwargs):
        return httpx.Response(401,json={'error':{'message':'key-sentinel private-prompt'}})
    monkeypatch.setattr(httpx.AsyncClient,'request',failed)
    response=client.post(f'/api/providers/test?provider_id={pid}',json=payload)
    assert response.status_code==400 and '401' in response.text and 'key-sentinel' not in response.text and 'private-prompt' not in response.text


@pytest.mark.asyncio
async def test_anthropic_model_pagination_and_duplicate_filter():
    request=AsyncMock(side_effect=[{'data':[{'id':'a'},{'id':'a'}],'has_more':True,'last_id':'a'}, {'data':[{'id':'b'}],'has_more':False}])
    models=await list_models(request,ProviderConfig(type='anthropic',base_url='https://models.test'))
    assert models==['a','b'] and request.await_args.kwargs['params']=={'after_id':'a'}


@pytest.mark.parametrize('data', [{'error':{'message':{'unexpected':'private'}}}, {'code':{'private':'secret'}}, []])
def test_malformed_error_body_is_safe(data):
    with pytest.raises(ValueError) as error:read_response(httpx.Response(400,json=data))
    assert 'private' not in str(error.value) and 'secret' not in str(error.value)


@pytest.mark.parametrize('kind', ['openai_chat', 'openai_responses', 'anthropic', 'deepseek'])
@pytest.mark.asyncio
async def test_external_context_retry_preserves_persona_and_current(kind):
    from app.ollama import ContextLimitError
    messages = [{'role': 'system', 'content': '完整人格' * 200}, {'role': 'user', 'content': 'old'},
                {'role': 'assistant', 'content': 'old reply'}, {'role': 'user', 'content': 'new', 'images': ['jpeg']}]
    request = AsyncMock(side_effect=[ContextLimitError('limit'), reply(kind)])
    result = await generate(request, ProviderConfig(type=kind), OllamaConfig(), messages, 160)
    payload = request.await_args.kwargs['json']
    assert 'old reply' not in json.dumps(payload) and 'jpeg' in json.dumps(payload)
    assert '完整人格' in str(payload) and result['message']['content'] == '回答正文'
    assert len(messages) == 4
    request = AsyncMock(side_effect=ProviderHTTPError(429))
    with pytest.raises(ProviderHTTPError):
        await generate(request, ProviderConfig(type=kind), OllamaConfig(), messages, 160)
    assert request.await_count == 1


@pytest.mark.asyncio
async def test_two_bots_use_different_external_providers_concurrently(tmp_path):
    catalog = ProviderStore(tmp_path); lock = asyncio.Lock(); entered = set(); both = asyncio.Event(); stores = []; bots = []
    async def transport(request):
        entered.add(request.url.host)
        if len(entered) == 2: both.set()
        await asyncio.wait_for(both.wait(), 2)
        index = 1 if request.url.host == 'first.test' else 2
        assert request.headers['Authorization'] == f'Bearer key-{index}'
        payload = json.loads(request.content)
        assert payload['model'] == f'model-{index}' and payload['messages'][0]['content'].split('\n\n[平台会话上下文]',1)[0] == f'persona-{index}'
        assert f'persona-{3-index}' not in str(payload)
        return httpx.Response(200, json=reply('openai_chat'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        for index, host in [(1, 'first.test'), (2, 'second.test')]:
            pid = catalog.save(ProviderConfig(type='openai_chat', base_url=f'https://{host}/v1', api_key=f'key-{index}'))
            store = Store(tmp_path / str(index)); config = Settings(); config.qq.app_id = str(index)
            config.rules.prompt = f'persona-{index}'; config.ollama.provider_id = pid; config.ollama.model = f'model-{index}'
            store.save(config); stores.append(store)
            bot = Bot(store, client, inference_lock=lock, providers=catalog); bot.api = AsyncMock(return_value={'id': 'sent'}); bots.append(bot)
        await asyncio.gather(*(bot.handle({'t':'C2C_MESSAGE_CREATE','d':{'id':'m','content':'hello','author':{'user_openid':'same-user'}}}) for bot in bots))
        assert both.is_set() and all(bot.stats['sent'] == 1 and bot.stats['total_tokens'] == 30 for bot in bots)
        for index, store in enumerate(stores, 1):
            assert store.chat.conversations(str(index))['items'] and not store.chat.conversations(str(3-index))['items']
    for store in stores: store.close()
    catalog.close()


@pytest.mark.asyncio
async def test_external_ollama_v1_uses_compatible_endpoints_and_bearer_key(tmp_path):
    catalog = ProviderStore(tmp_path)
    pid = catalog.save(ProviderConfig(type='ollama', base_url='https://external.test/v1', api_key='external-key'))
    store = Store(tmp_path / 'bot'); config = Settings(); config.ollama.provider_id=pid
    config.ollama.model='GemmaCustom:latest';config.qq.app_id='111';config.qq.secret='qq-key';store.save(config)
    calls=[]
    def transport(request):
        assert request.headers['Authorization']=='Bearer external-key'
        calls.append(request.url.path)
        if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'GemmaCustom:latest'}]})
        payload=json.loads(request.content)
        assert payload['model']=='GemmaCustom:latest' and payload['messages'][-1]['content']=='hello'
        return httpx.Response(200,json=reply('openai_chat'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        bot=Bot(store,client,providers=catalog);bot.api=AsyncMock(return_value={'url':'wss://qq.test'});bot.run=AsyncMock()
        await bot.start();await bot.stop()
        result=await bot.generate(config.ollama,[{'role':'user','content':'hello'}],128)
        assert result['message']['content']=='回答正文'
        assert calls==['/v1/models','/v1/chat/completions']
    store.close();catalog.close()


def test_referenced_provider_cannot_change_purpose(client):
    provider = client.get('/api/providers').json()['providers'][0]
    result = client.put('/api/providers/' + provider['id'], json={'type': 'openai_embedding', 'base_url': 'https://new.test/v1'})
    assert result.status_code == 409
    assert client.get('/api/providers').json()['providers'][0]['purpose'] == 'chat'
