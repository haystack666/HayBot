"""Small protocol-specific retrieval adapters; no persistent remote state."""
import math
from urllib.parse import quote, urlsplit

from .providers import headers


def base_endpoint(provider, prefix, operation):
    base = provider.base_url.rstrip('/')
    path = urlsplit(base).path.rstrip('/')
    if not path:
        base += prefix
    return base + '/' + operation


def native_endpoint(provider, suffix):
    base = provider.base_url.rstrip('/')
    if base.endswith(suffix):
        return base
    if '/services/' in urlsplit(base).path:
        raise ValueError('服务地址的接口路径与当前用途不一致')
    return base + ('' if urlsplit(base).path.rstrip('/').endswith('/api/v1') else '/api/v1') + suffix


def tokens(data):
    usage = data.get('usage') or {}
    value = data.get('prompt_eval_count', usage.get('prompt_tokens', usage.get('total_tokens', 0))) if isinstance(usage, dict) else 0
    return value if type(value) is int and value >= 0 else 0


def vectors_valid(vectors, count, dimensions=None):
    if not isinstance(vectors, list) or len(vectors) != count:
        raise ValueError('嵌入接口返回的向量数量不正确')
    normalized, size = [], dimensions
    for vector in vectors:
        if not isinstance(vector, list) or not 1 <= len(vector) <= 65536:
            raise ValueError('嵌入接口返回的向量格式无效')
        size = size or len(vector)
        if len(vector) != size or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector):
            raise ValueError('嵌入向量维度或数值无效')
        norm = math.hypot(*vector)
        if not math.isfinite(norm) or norm == 0:
            raise ValueError('嵌入接口返回了无效的零向量')
        normalized.append([x / norm for x in vector])
    return normalized


def indexed_vectors(collection, count, index_key):
    if not isinstance(collection, list) or len(collection) != count:
        raise ValueError('嵌入接口返回的向量数量不正确')
    # One input plus one vector has exactly one mapping; some compatible gateways
    # omit or renumber its index. Batch order must still be explicit and unique.
    if count == 1 and isinstance(collection[0], dict):
        return [collection[0].get('embedding')]
    result, seen = [None] * count, set()
    for item in collection:
        if not isinstance(item, dict):
            raise ValueError('嵌入接口返回格式无效')
        index = item.get(index_key)
        if type(index) is not int or not 0 <= index < count or index in seen:
            raise ValueError('嵌入接口返回的向量顺序无效')
        result[index] = item.get('embedding')
        seen.add(index)
    return result


def single_index_anomaly(collection, count, key):
    return (count == 1 and isinstance(collection, list) and len(collection) == 1
            and isinstance(collection[0], dict)
            and (type(collection[0].get(key)) is not int or collection[0][key] != 0))


async def embed(request, provider, model, texts, purpose='document', timeout=20):
    if provider.purpose != 'embedding' or not texts or len(texts) > 100 or purpose not in ('query', 'document'):
        raise ValueError('嵌入模型或请求用途无效')
    if any(not isinstance(text, str) or not text.strip() or len(text) > 16000 for text in texts):
        raise ValueError('嵌入文本为空或过长')
    kind, auth, dimensions = provider.type, headers(provider), provider.embedding_dimensions
    if kind == 'gemini_embedding':
        auth = {'x-goog-api-key': provider.api_key} if provider.api_key else {}
        model_id = model.removeprefix('models/')
        url = base_endpoint(provider, '/v1beta', 'models/' + quote(model_id, safe='') + ':batchEmbedContents')
        requests = [{'model': 'models/' + model_id, 'content': {'parts': [{'text': text}]},
                     'taskType': 'RETRIEVAL_QUERY' if purpose == 'query' else 'RETRIEVAL_DOCUMENT',
                     **({'outputDimensionality': dimensions} if dimensions else {})} for text in texts]
        body = {'requests': requests}
    elif kind == 'dashscope_embedding':
        url = native_endpoint(provider, '/services/embeddings/text-embedding/text-embedding')
        body = {'model': model, 'input': {'texts': texts}, 'parameters': {'text_type': purpose,
                **({'dimension': dimensions} if dimensions else {})}}
    elif kind == 'ollama_embedding' and provider.ollama_api != 'openai' and not (provider.ollama_api == 'auto' and provider.base_url.endswith('/v1')):
        base = provider.base_url.removesuffix('/api')
        url = base + '/api/embed'
        body = {'model': model, 'input': texts, 'truncate': False, **({'dimensions': dimensions} if dimensions else {})}
    else:
        url = base_endpoint(provider, '/v1', 'embeddings')
        body = {'model': model, 'input': texts, 'encoding_format': 'float', **({'dimensions': dimensions} if dimensions else {})}
    data = await request('POST', url, headers=auth, json=body, timeout=timeout)
    index_normalized = False
    if kind == 'gemini_embedding':
        collection = data.get('embeddings')
        vectors = [item.get('values') if isinstance(item, dict) else None for item in collection] if isinstance(collection, list) else None
    elif kind == 'dashscope_embedding':
        collection = (data.get('output') or {}).get('embeddings')
        index_normalized = single_index_anomaly(collection, len(texts), 'text_index')
        vectors = indexed_vectors(collection, len(texts), 'text_index')
    elif 'embeddings' in data and kind == 'ollama_embedding':
        vectors = data['embeddings']
    else:
        collection = data.get('data')
        index_normalized = single_index_anomaly(collection, len(texts), 'index')
        vectors = indexed_vectors(collection, len(texts), 'index')
    return {'vectors': vectors_valid(vectors, len(texts), dimensions), 'input_tokens': tokens(data), 'index_normalized': index_normalized}


async def rerank(request, provider, model, query, documents, top_n, timeout=20):
    if provider.purpose != 'rerank' or not documents or len(documents) > 100:
        raise ValueError('重排模型或候选文档无效')
    if provider.type == 'dashscope_rerank':
        url = native_endpoint(provider, '/services/rerank/text-rerank/text-rerank')
        body = {'model': model, 'input': {'query': query, 'documents': documents},
                'parameters': {'top_n': min(top_n, len(documents)), 'return_documents': False}}
    else:
        url = base_endpoint(provider, '/v1', 'rerank')
        body = {'model': model, 'query': query, 'documents': documents, 'top_n': min(top_n, len(documents)), 'return_documents': False}
    data = await request('POST', url, headers=headers(provider), json=body, timeout=timeout)
    result = (data.get('output') or {}).get('results') if provider.type == 'dashscope_rerank' else data.get('results')
    if not isinstance(result, list) or not result or len(result) > len(documents):
        raise ValueError('重排接口返回格式无效')
    seen, ranked = set(), []
    for item in result:
        index, score = item.get('index'), item.get('relevance_score')
        if type(index) is not int or not 0 <= index < len(documents) or index in seen or type(score) not in (int, float) or not math.isfinite(score):
            raise ValueError('重排接口返回的索引或分数无效')
        seen.add(index)
        ranked.append({'index': index, 'relevance_score': float(score)})
    return {'results': sorted(ranked, key=lambda item: item['relevance_score'], reverse=True)[:top_n], 'input_tokens': tokens(data)}
