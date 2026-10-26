"""Real vision acceptance checks; downloads and QQ sends stay inside the test."""
import asyncio
import io
import os
import tempfile
import time

import httpx
from PIL import Image, ImageDraw

from .bot import Bot
from .config import Settings
from .store import Store
from .providers import ProviderStore


def fixtures():
    static = Image.new('RGB', (480, 240), 'white')
    drawing = ImageDraw.Draw(static)
    drawing.ellipse((40, 40, 200, 200), fill='red')
    drawing.rectangle((280, 40, 440, 200), fill='blue')
    png = io.BytesIO()
    static.save(png, 'PNG')
    gif = io.BytesIO()
    frames = [Image.new('RGB', (180, 180), color) for color in ('red', 'green', 'blue')]
    frames[0].save(gif, 'GIF', save_all=True, append_images=frames[1:], duration=200, loop=0)
    return {'/verify-static.png': png.getvalue(), '/verify-animation.gif': gif.getvalue()}


class AcceptanceTransport(httpx.AsyncBaseTransport):
    def __init__(self, media):
        self.media = media
        self.real = httpx.AsyncHTTPTransport()
        self.downloads = 0

    async def handle_async_request(self, request):
        if request.url.host == 'gchat.qpic.cn' and request.url.path in self.media:
            self.downloads += 1
            return httpx.Response(200, content=self.media[request.url.path])
        return await self.real.handle_async_request(request)

    async def aclose(self):
        await self.real.aclose()


async def main():
    app_url = os.getenv('VERIFY_APP_URL', 'http://127.0.0.1:8000')
    async with httpx.AsyncClient(base_url=app_url, trust_env=False, timeout=30) as client:
        response = await client.post('/api/login', json={'password': os.environ['ADMIN_PASSWORD']})
        response.raise_for_status()
        response = await client.get('/api/settings')
        response.raise_for_status()
        public = response.json()
    config = Settings()
    config.ollama = config.ollama.model_validate(public['ollama'])
    config.rules = config.rules.model_validate(public['rules'])
    config.rules.cooldown = 0
    cases = [
        ('static-caption', '/verify-static.png', '请用一句中文描述图片中的颜色和形状。', ('红', '蓝', '圆', '方')),
        ('static-only', '/verify-static.png', '', ('红', '蓝')),
        ('gif', '/verify-animation.gif', '请用一句中文按顺序列出图片中三个画面的主要颜色。', ('红', '绿', '蓝')),
    ]
    print('Real vision model:', config.ollama.model, flush=True)
    for label, path, text, expected in cases:
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.save(config)
            transport = AcceptanceTransport(fixtures())
            async with httpx.AsyncClient(transport=transport, trust_env=False, timeout=15) as client:
                providers = ProviderStore(os.getenv('DATA_DIR', '/data'))
                bot = Bot(store, client, providers=providers)
                captured = []

                async def capture(method, route, **kwargs):
                    captured.append({'route': route, 'body': kwargs['json']})
                    return {'id': 'captured-test-reply'}

                bot.api = capture
                payload = {'t': 'C2C_MESSAGE_CREATE', 'd': {
                    'id': 'vision-acceptance-' + label,
                    'content': text,
                    'author': {'user_openid': 'local-vision-acceptance'},
                    'attachments': [{'content_type': 'image/gif' if label == 'gif' else 'image/png',
                                     'url': 'https://gchat.qpic.cn' + path}],
                }}
                started = time.monotonic()
                await bot.handle(payload)
                assert bot.stats['sent'] == 1 and bot.stats['errors'] == 0, store.logs()
                answer = captured[0]['body']['content']
                assert all(word in answer for word in expected), f'{label}: {answer}'
                assert captured[0]['route'] == '/v2/users/local-vision-acceptance/messages'
                assert bot.stats['input_tokens'] > 0 and bot.stats['output_tokens'] > 0
                await bot.handle(payload)
                assert len(captured) == 1 and transport.downloads == 1
                assert all('images' not in message for message in store.history('user:local-vision-acceptance:local-vision-acceptance', 6))
                print('PASS %s (%.1fs): %s' % (label, time.monotonic() - started, answer), flush=True)
                print('Actual isolated test usage:', bot.stats, flush=True)
            providers.close()
            store.close()
    print('PASS: image-only, image-with-caption, GIF, reply routing, dedup and token recording. No QQ test messages sent.', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
