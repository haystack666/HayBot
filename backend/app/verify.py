"""Container acceptance check. Uses real Ollama; never sends a synthetic QQ message."""
import asyncio
import os
import tempfile
import httpx
from .bot import Bot
from .store import Store
from .providers import ProviderStore


async def main():
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000', timeout=120, trust_env=False) as http:
        assert (await http.get('/api/health')).status_code == 200
        assert (await http.get('/api/settings')).status_code == 401
        response = await http.post('/api/login', json={'password': os.environ['ADMIN_PASSWORD']})
        response.raise_for_status()
        response = await http.get('/api/settings')
        response.raise_for_status()
        public = response.json()
        assert public['qq']['secret_set'] and 'secret' not in public['qq']
        print('PASS: API authentication and secret redaction', flush=True)
        response = await http.post('/api/ollama/test', json=public['ollama'])
        response.raise_for_status()
        assert public['ollama']['model'] in response.json()['models']
        print('PASS: Ollama available with configured model', flush=True)

        # 真实模型推理经过生产 Bot.handle；只替换最终 QQ HTTP 发送，避免伪造外部用户。
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            config = store.load()
            config.ollama = config.ollama.model_validate(public['ollama'])
            store.save(config)
            providers = ProviderStore(os.getenv('DATA_DIR', '/data'))
            bot = Bot(store, providers=providers)
            sent = []

            async def capture(method, path, **kwargs):
                sent.append({'path': path, 'body': kwargs['json']})
                return {'id': 'acceptance-test'}

            bot.api = capture
            await bot.handle({'t': 'C2C_MESSAGE_CREATE', 'd': {
                'id': 'acceptance-message', 'content': '请只用一句简短中文确认你可以正常回答。',
                'author': {'user_openid': 'acceptance-user'}
            }})
            assert len(sent) == 1, store.logs()
            assert sent[0]['path'] == '/v2/users/acceptance-user/messages'
            assert sent[0]['body']['content']
            assert sent[0]['body']['msg_id'] == 'acceptance-message'
            print('PASS: real model -> reply pipeline -> captured QQ payload', flush=True)
            print('Model response: ' + sent[0]['body']['content'], flush=True)
            await bot.client.aclose()
            providers.close()
            store.close()

        response = await http.post('/api/qq/test')
        response.raise_for_status()
        print('PASS: QQ official credential and gateway API', flush=True)
        response = await http.post('/api/bot/start')
        response.raise_for_status()
        for _ in range(30):
            status = (await http.get('/api/status')).json()
            if status['state'] == 'connected':
                print('PASS: QQ official WebSocket READY; bot left running', flush=True)
                return
            await asyncio.sleep(1)
        raise RuntimeError('QQ did not become connected within 30 seconds')


if __name__ == '__main__':
    asyncio.run(main())
