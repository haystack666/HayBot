import math
import pytest

from app.providers import ProviderConfig


def test_auxiliary_provider_types_have_distinct_purposes():
    assert ProviderConfig(type='openai_embedding').purpose == 'embedding'
    assert ProviderConfig(type='dashscope_rerank').purpose == 'rerank'
    assert ProviderConfig().purpose == 'chat'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,path,response', [
    ('openai_embedding', '/v1/embeddings', {'data': [{'index': 1, 'embedding': [0., 2.]}, {'index': 0, 'embedding': [1., 0.]}], 'usage': {'prompt_tokens': 8}}),
    ('ollama_embedding', '/api/embed', {'embeddings': [[1., 0.], [0., 2.]], 'prompt_eval_count': 8}),
    ('gemini_embedding', '/v1beta/models/embedding-test:batchEmbedContents', {'embeddings': [{'values': [1., 0.]}, {'values': [0., 2.]}]}),
    ('dashscope_embedding', '/api/v1/services/embeddings/text-embedding/text-embedding', {'output': {'embeddings': [{'text_index': 1, 'embedding': [0., 2.]}, {'text_index': 0, 'embedding': [1., 0.]}]}, 'usage': {'total_tokens': 8}}),
])
async def test_embedding_adapters_preserve_input_order_and_retrieval_type(kind, path, response):
    from app.retrieval import embed
    calls = []
    async def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return response
    provider = ProviderConfig(type=kind, base_url='https://model.test', api_key='test-key')
    result = await embed(request, provider, 'embedding-test', ['hello', 'world'], 'query')
    assert result['vectors'] == [[1., 0.], [0., 1.]]
    method, url, kwargs = calls[0]
    assert method == 'POST' and url == 'https://model.test' + path
    assert kwargs['headers'].get('x-goog-api-key') == 'test-key' if kind == 'gemini_embedding' else kwargs['headers']['Authorization'] == 'Bearer test-key'
    if kind == 'gemini_embedding':
        assert kwargs['json']['requests'][0]['taskType'] == 'RETRIEVAL_QUERY'
    if kind == 'dashscope_embedding':
        assert kwargs['json']['parameters']['text_type'] == 'query'
    assert 'test-key' not in str(kwargs['json'])


@pytest.mark.asyncio
@pytest.mark.parametrize('vectors', [[], [[0, 0]], [[math.nan, 1]], [[1, 0], [1]], [[True, 1]], [[math.inf, 1]]])
async def test_invalid_embedding_results_are_rejected(vectors):
    from app.retrieval import embed
    async def request(*args, **kwargs):
        return {'embeddings': vectors}
    with pytest.raises(ValueError):
        await embed(request, ProviderConfig(type='ollama_embedding'), 'embed', ['text'], 'document')


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['dashscope_rerank', 'xinference_rerank'])
async def test_rerank_reorders_real_document_indices(kind):
    from app.retrieval import rerank
    async def request(method, url, **kwargs):
        assert kwargs['headers']['Authorization'] == 'Bearer private'
        if kind == 'dashscope_rerank':
            assert url.endswith('/api/v1/services/rerank/text-rerank/text-rerank')
            assert kwargs['json']['input'] == {'query': 'tea', 'documents': ['coffee', 'tea']}
            return {'output': {'results': [{'index': 1, 'relevance_score': .9}, {'index': 0, 'relevance_score': .1}]}, 'usage': {'total_tokens': 9}}
        assert url.endswith('/v1/rerank')
        assert kwargs['json']['model'] == 'deployed-uid'
        return {'results': [{'index': 1, 'relevance_score': .9}, {'index': 0, 'relevance_score': .1}]}
    result = await rerank(request, ProviderConfig(type=kind, base_url='https://rerank.test', api_key='private'), 'deployed-uid', 'tea', ['coffee', 'tea'], 2)
    assert [item['index'] for item in result['results']] == [1, 0]


@pytest.mark.asyncio
@pytest.mark.parametrize('results', [[{'index': 8, 'relevance_score': .3}], [{'index': 0, 'relevance_score': math.nan}], [{'index': 0, 'relevance_score': .5}, {'index': 0, 'relevance_score': .3}]])
async def test_invalid_rerank_indices_and_scores_fail_closed(results):
    from app.retrieval import rerank
    async def request(*args, **kwargs):
        return {'results': results}
    with pytest.raises(ValueError):
        await rerank(request, ProviderConfig(type='xinference_rerank'), 'uid', 'question', ['one', 'two'], 2)


@pytest.mark.asyncio
async def test_ollama_compatible_embeddings_and_gemini_proxy_prefixes():
    from app.retrieval import embed
    async def request(method, url, **kwargs):
        if 'ollama' in url:
            assert url == 'https://ollama.test/proxy/v1/embeddings'
            return {'data': [{'index': 0, 'embedding': [1., 0.]}]}
        assert url == 'https://google.test/proxy/v1beta/models/embedding:batchEmbedContents'
        assert kwargs['json']['requests'][0]['taskType'] == 'RETRIEVAL_DOCUMENT'
        return {'embeddings': [{'values': [1., 0.]}]}
    assert (await embed(request, ProviderConfig(type='ollama_embedding', base_url='https://ollama.test/proxy/v1'), 'model', ['one']))['vectors'] == [[1., 0.]]
    assert (await embed(request, ProviderConfig(type='gemini_embedding', base_url='https://google.test/proxy/v1beta'), 'models/embedding', ['one']))['vectors'] == [[1., 0.]]


def test_auxiliary_generation_probes_use_actual_protocol_and_hide_keys(tmp_path, monkeypatch):
    import httpx
    from fastapi.testclient import TestClient
    from app.main import create_app
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-password-long-enough')
    async def request(self, method, url, **kwargs):
        if 'embeddings' in str(url):
            assert kwargs['headers']['Authorization'] == 'Bearer secret-sentinel'
            return httpx.Response(200, json={'data': [{'index': 0, 'embedding': [1., 0.]}, {'index': 1, 'embedding': [0., 1.]}]})
        assert str(url).endswith('/v1/rerank')
        return httpx.Response(200, json={'results': [{'index': 0, 'relevance_score': .9}]})
    monkeypatch.setattr(httpx.AsyncClient, 'request', request)
    with TestClient(create_app(tmp_path)) as client:
        client.post('/api/login', json={'password': 'test-password-long-enough'})
        for kind in ('openai_embedding', 'xinference_rerank'):
            result = client.post('/api/providers/test-generation', json={'type': kind, 'base_url': 'https://test/v1', 'api_key': 'secret-sentinel', 'model': 'embed-or-uid'})
            assert result.status_code == 200 and '成功' in result.json()['content']
            assert 'secret-sentinel' not in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize('index', [None, '0', 1, 9])
async def test_single_embedding_has_unambiguous_mapping_despite_provider_index(index):
    from app.retrieval import embed
    async def request(*args,**kwargs):
        item={'embedding':[3.,4.]}
        if index is not None:item['text_index']=index
        return {'output':{'embeddings':[item]}}
    result=await embed(request,ProviderConfig(type='dashscope_embedding',base_url='https://embed.test'),'embed',['合成测试'])
    assert result['vectors']==[[.6,.8]]
    assert result['index_normalized'] is True


@pytest.mark.asyncio
async def test_batch_embedding_never_guesses_ambiguous_order():
    from app.retrieval import embed
    for indices in ([0,0],[None,None],[1,2]):
        async def request(*args,**kwargs):return {'output':{'embeddings':[{'text_index':i,'embedding':[1.,0.]} for i in indices]}}
        with pytest.raises(ValueError):await embed(request,ProviderConfig(type='dashscope_embedding',base_url='https://embed.test'),'embed',['一','二'])
