CONTEXT_WINDOW = 8192


class ContextLimitError(ValueError):
    pass


async def chat_response(request, config, messages, num_predict, *, thinking=None):
    working = list(messages)
    while True:
        try:
            return await request('POST', config.url + '/api/chat', timeout=config.timeout, json={
                'model': config.model, 'stream': False, 'messages': working,
                **({'think': thinking} if thinking is not None else {'think': False} if config.model.lower().startswith(('qwen3:', 'gemma4', 'hf.co/hauhaucs/gemma-4-')) else {}),
                'options': {'temperature': config.temperature, 'num_predict': num_predict, 'num_ctx': CONTEXT_WINDOW},
            })
        except ContextLimitError:
            if len(working) <= 2:
                raise
            # 只在服务明确拒绝超长上下文时移除最早的历史轮次；始终保留完整人格与本条消息。
            working = [working[0], *working[min(3, len(working) - 1):]]
