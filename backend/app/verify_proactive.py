"""Real Ollama generation with an isolated database and captured QQ sends."""
import asyncio
import json
import os
import tempfile
import time
from unittest.mock import AsyncMock

import httpx

from .bot import Bot
from .config import Settings
from .proactive import ProactiveService
from .store import Store
from .providers import ProviderStore


class CaptureTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.real = httpx.AsyncHTTPTransport()
        self.sent = []
        self.generations = 0

    async def handle_async_request(self, request):
        if request.url.host == 'api.sgroup.qq.com':
            self.sent.append(json.loads(request.content))
            return httpx.Response(200, json={'id': 'captured-proactive-reply'})
        if request.url.path == '/api/chat':
            self.generations += 1
        return await self.real.handle_async_request(request)

    async def aclose(self):
        await self.real.aclose()


async def main():
    async with httpx.AsyncClient(base_url=os.getenv('VERIFY_APP_URL', 'http://127.0.0.1:8000'), trust_env=False, timeout=30) as client:
        response = await client.post('/api/login', json={'password': os.environ['ADMIN_PASSWORD']})
        response.raise_for_status()
        response = await client.get('/api/settings')
        response.raise_for_status()
        public = response.json()
    config = Settings()
    config.qq.app_id = public['qq']['app_id']
    config.ollama = config.ollama.model_validate(public['ollama'])
    config.rules = config.rules.model_validate(public['rules'])
    config.proactive.enabled = True
    config.proactive.recipient_id = 'local-proactive-acceptance'
    config.proactive.active_start = config.proactive.active_end = '00:00'
    config.proactive.greetings = []
    with tempfile.TemporaryDirectory() as directory:
        store = Store(directory)
        store.save(config)
        recipient = config.proactive.recipient_id
        store.remember_contact(config.qq.app_id, recipient, time.time() - 7200, 'test-incoming')
        store.set_capability(config.qq.app_id, recipient, 'supported', '仅限隔离测试', time.time())
        transport = CaptureTransport()
        async with httpx.AsyncClient(transport=transport, trust_env=False, timeout=15) as client:
            providers = ProviderStore(os.getenv('DATA_DIR', '/data'))
            bot = Bot(store, client, providers=providers)
            bot.state = 'connected'
            bot.access_token = AsyncMock(return_value='captured-test-token')
            service = ProactiveService(store, bot)
            start = time.monotonic()
            await service.execute('real-model-probe', config, recipient, 'idle', '用一句简短中文自然地关心一下近况。')
            assert len(transport.sent) == 1 and store.stats()['errors'] == 0, store.logs()
            assert set(transport.sent[0]) == {'msg_type', 'content'}
            assert transport.sent[0]['content']
            assert store.stats()['input_tokens'] > 0 and store.stats()['output_tokens'] > 0
            await service.execute('real-model-probe', config, recipient, 'idle', '不应重复生成')
            assert transport.generations == 1 and len(transport.sent) == 1
            providers.close()
            print('PASS: real proactive generation (%.1fs): %s' % (time.monotonic() - start, transport.sent[0]['content']), flush=True)
            now = time.time()
            store.add_reminder('local-reminder', config.qq.app_id, recipient, now, '本地提醒验收', now)
            await service.execute('reminder:local-reminder', config, recipient, 'reminder', '提醒：本地提醒验收', generated=False, reminder_id='local-reminder')
            assert len(transport.sent) == 2 and transport.generations == 1
            assert store.stats()['sent'] == 2
            print('PASS: fixed reminder uses no model generation; independent sends omit msg_id; duplicate task suppressed.', flush=True)
            print('Isolated test counters:', store.stats(), flush=True)
        store.close()
    print('PASS: no external QQ messages sent by this acceptance test.', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
