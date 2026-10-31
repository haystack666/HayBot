"""Receive long Ollama schedules incrementally through native and /v1 proxies."""
import json
from urllib.parse import urlsplit

from .providers import read_response


async def schedule_response(client, method, url, **kwargs):
    native = urlsplit(url).path.endswith('/api/chat')
    body = {**kwargs.pop('json'), 'stream': True}
    if not native:
        body['stream_options'] = {'include_usage': True}
        if str(body.get('model', '')).lower().startswith(('qwen3:', 'gemma4', 'hf.co/hauhaucs/gemma-4-')):
            # Match the native adapter's think=False for these Ollama models.
            body['reasoning_effort'] = 'none'
    async with client.stream(method, url, json=body, **kwargs) as response:
        content_type = response.headers.get('content-type', '').split(';')[0].strip()
        if not response.is_success or content_type == 'application/json':
            # Some compatible servers ignore stream=true and return ordinary JSON.
            await response.aread()
            return read_response(response)
        text, size, usage, finished = [], 0, {}, False
        finish_reason = None
        async for line in response.aiter_lines():
            line = line.strip()
            if not line or line.startswith(':') or line.startswith(('event:', 'id:', 'retry:')):
                continue
            if line.startswith('data:'):
                line = line[5:].strip()
            if line == '[DONE]':
                finished = True
                break
            try:
                frame = json.loads(line)
            except ValueError:
                raise ValueError('日程模型流格式无效') from None
            if not isinstance(frame, dict) or frame.get('error'):
                raise ValueError('日程模型流返回错误')
            if native:
                message = frame.get('message') or {}
                part = message.get('content', '') if isinstance(message, dict) else ''
                if frame.get('done'):
                    finished = True
                    finish_reason = frame.get('done_reason')
                    usage = {name: frame.get(name, 0) for name in ('prompt_eval_count', 'eval_count')}
            else:
                choices = frame.get('choices') or []
                choice = choices[0] if choices and isinstance(choices[0], dict) else {}
                delta = choice.get('delta') or {}
                part = (delta.get('content') or '') if isinstance(delta, dict) else ''
                finish_reason = choice.get('finish_reason') or finish_reason
                finished = finished or choice.get('finish_reason') is not None
                if isinstance(frame.get('usage'), dict):
                    usage = frame['usage']
            if not isinstance(part, str):
                raise ValueError('日程模型流没有返回文本')
            size += len(part)
            if size > 60000:
                raise ValueError('日程模型流内容过长')
            text.append(part)
        if not finished:
            raise ValueError('日程模型流意外中断，请重试')
        content = ''.join(text)
        if native:
            return {'message': {'content': content}, **usage, **({'done_reason':finish_reason} if finish_reason else {})}
        return {'choices': [{'message': {'content': content}, **({'finish_reason':finish_reason} if finish_reason else {})}], 'usage': usage}
