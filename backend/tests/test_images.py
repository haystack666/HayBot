import base64
import io
import json

import httpx
import pytest
from PIL import Image

from app.bot import Bot
from app.config import Settings
from app.images import ImageMessageError, cdn_url, download_image, prepare_image
from app.store import Store


def image_bytes(format='PNG'):
    output = io.BytesIO()
    image = Image.new('RGB', (80, 60), 'red')
    if format == 'GIF':
        image.save(output, format, save_all=True,
                   append_images=[Image.new('RGB', (80, 60), color) for color in ('green', 'blue')],
                   duration=100, loop=0)
    else:
        image.save(output, format)
    return output.getvalue()


def event(kind='C2C_MESSAGE_CREATE', text='', attachment=None):
    return {'t': kind, 'd': {
        'id': 'image-message', 'content': text,
        'author': {'user_openid': 'member1', 'member_openid': 'member1'},
        'group_openid': 'group1',
        'attachments': [attachment or {'content_type': 'image/png', 'url': '//gchat.qpic.cn/test.png'}],
    }}


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,target', [('C2C_MESSAGE_CREATE', '/v2/users/member1/messages'),
                                        ('GROUP_AT_MESSAGE_CREATE', '/v2/groups/group1/messages')])
async def test_image_only_reply_routing_dedup_and_no_binary_history(tmp_path, kind, target):
    store = Store(tmp_path)
    config = Settings()
    config.qq.group_reply = True
    config.rules.cooldown = 0
    store.save(config)
    calls = []

    def transport(request):
        calls.append(request)
        if request.url.host == 'gchat.qpic.cn':
            assert request.url.scheme == 'https'
            assert 'Authorization' not in request.headers
            return httpx.Response(200, content=image_bytes())
        if request.url.path == '/api/show':
            return httpx.Response(200, json={'capabilities': ['completion', 'vision']})
        if request.url.path == '/api/chat':
            body = json.loads(request.content)
            user = body['messages'][-1]
            assert user['content']
            assert '请看看' not in user['content']
            assert '没有附加文字' in user['content']
            assert '不要固定先点评图片，再聊天' in body['messages'][0]['content']
            decoded = Image.open(io.BytesIO(base64.b64decode(user['images'][0])))
            assert decoded.format == 'JPEG' and decoded.size == (80, 60)
            return httpx.Response(200, json={'message': {'content': '红色图片'}, 'prompt_eval_count': 100, 'eval_count': 7})
        if request.url.path.endswith('/getAppAccessToken'):
            return httpx.Response(200, json={'access_token': 'test-token', 'expires_in': 7200})
        return httpx.Response(200, json={'id': 'reply-id'})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        bot = Bot(store, client)
        payload = event(kind, '<@123>' if kind.startswith('GROUP') else '')
        await bot.handle(payload)
        await bot.handle(payload)
        assert calls[-1].url.path == target
        assert json.loads(calls[-1].content)['msg_id'] == 'image-message'
        assert bot.stats == dict(received=1, sent=1, errors=0, input_tokens=100, output_tokens=7, total_tokens=107)
        key = 'group:group1:member1' if kind.startswith('GROUP') else 'user:member1:member1'
        history = store.history(key, 6)
        assert '图片' in history[0]['content']
        assert 'images' not in history[0]
        assert len(json.dumps(history)) < 1000
    store.close()


@pytest.mark.asyncio
async def test_gif_caption_and_text_followup(tmp_path):
    store = Store(tmp_path)
    config = Settings()
    config.rules.cooldown = 0
    store.save(config)
    chats = []

    def transport(request):
        if request.url.host == 'gchat.qpic.cn':
            return httpx.Response(200, content=image_bytes('GIF'))
        if request.url.path == '/api/show':
            return httpx.Response(200, json={'capabilities': ['vision']})
        if request.url.path == '/api/chat':
            chats.append(json.loads(request.content))
            return httpx.Response(200, json={'message': {'content': '红绿蓝三个画面'}})
        if request.url.path.endswith('/getAppAccessToken'):
            return httpx.Response(200, json={'access_token': 'test-token', 'expires_in': 7200})
        return httpx.Response(200, json={'id': 'reply-id'})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        bot = Bot(store, client)
        await bot.handle(event(text='说说这个表情包'))
        message = chats[0]['messages'][-1]
        assert message['content'].startswith('说说这个表情包')
        assert '从左到右' in message['content']
        assert '不向对方复述' in message['content']
        assert '按实际请求准确回答' in chats[0]['messages'][0]['content']
        decoded = Image.open(io.BytesIO(base64.b64decode(message['images'][0])))
        assert decoded.size == (240, 82)
        assert decoded.getpixel((40, 50))[0] > 200
        assert decoded.getpixel((200, 50))[2] > 200
        followup = event(text='再说一次')
        followup['d'].update(id='followup', attachments=[])
        await bot.handle(followup)
        assert '红绿蓝三个画面' == chats[1]['messages'][-2]['content']
        assert all('images' not in item for item in chats[1]['messages'])
        assert '[本轮图片聊天方式]' not in chats[1]['messages'][0]['content']
        assert bot.stats['sent'] == 2
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure,expected', [
    ('nonvision', '不支持看图'), ('corrupt', '图片无法读取'), ('too_large', '超过 10 MB'),
    ('private_url', '不属于 QQ 图片服务'), ('redirect', '不属于 QQ 图片服务'),
    ('download_failed', '下载失败'), ('inference_failed', '图片识别失败'), ('too_many', '最多识别 3 张'),
])
async def test_image_failures_are_explained_and_not_replayed(tmp_path, failure, expected):
    store = Store(tmp_path)
    calls = []

    def transport(request):
        calls.append(request)
        if request.url.path == '/api/show':
            return httpx.Response(200, json={'capabilities': [] if failure == 'nonvision' else ['vision']})
        if request.url.host == 'gchat.qpic.cn':
            if failure == 'redirect':
                return httpx.Response(302, headers={'location': 'http://127.0.0.1/private?secret=do-not-log'})
            if failure == 'download_failed':
                return httpx.Response(403)
            return httpx.Response(200, content=b'not an image' if failure == 'corrupt' else image_bytes())
        if request.url.path == '/api/chat':
            assert failure == 'inference_failed'
            return httpx.Response(500, json={'error': 'private-upstream-response'})
        if request.url.path.endswith('/getAppAccessToken'):
            return httpx.Response(200, json={'access_token': 'test-token', 'expires_in': 7200})
        return httpx.Response(200, json={'id': 'notice-id'})

    payload = event()
    if failure == 'private_url':
        payload['d']['attachments'][0]['url'] = 'http://127.0.0.1/private?secret=do-not-log'
    elif failure == 'too_large':
        payload['d']['attachments'][0]['size'] = 11 * 1024 * 1024
    elif failure == 'too_many':
        payload['d']['attachments'] *= 4
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        bot = Bot(store, client)
        await bot.handle(payload)
        await bot.handle(payload)
        assert bot.stats['received'] == bot.stats['sent'] == bot.stats['errors'] == 1
        assert expected in json.loads(calls[-1].content)['content']
        assert not bot.pending
        assert not store.history('user:member1:member1', 6)
        assert 'do-not-log' not in json.dumps(store.logs())
        assert all(r.url.host != '127.0.0.1' for r in calls)
        assert len([r for r in calls if r.url.path == '/api/chat']) == (failure == 'inference_failed')
    store.close()


@pytest.mark.asyncio
async def test_stream_download_size_and_timeout(monkeypatch):
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'x' * (64 * 1024)
    monkeypatch.setattr('app.images.MAX_DOWNLOAD', 1024)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Stream()))) as client:
        with pytest.raises(ImageMessageError, match='超过 10 MB'):
            await download_image(client, {'url': 'https://gchat.qpic.cn/huge'})
    def timeout(request):
        raise httpx.ReadTimeout('private download URL', request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(ImageMessageError, match='下载失败'):
            await download_image(client, {'url': 'https://gchat.qpic.cn/slow'})


def test_image_pixel_limit_and_host_validation(monkeypatch):
    monkeypatch.setattr('app.images.MAX_PIXELS', 1000)
    with pytest.raises(ImageMessageError, match='分辨率过大'):
        prepare_image(image_bytes())
    for url in ('https://gchat.qpic.cn.evil.test/a', 'https://qq.com@127.0.0.1/a',
                'file:///etc/passwd', 'https://gchat.qpic.cn:8080/a'):
        with pytest.raises(ImageMessageError):
            cdn_url(url)


@pytest.mark.asyncio
@pytest.mark.parametrize('text',['[QQ表情:14]','[表情包:嘻嘻]'])
async def test_native_qq_expressions_get_chat_guidance_without_image_download(tmp_path,text):
    store=Store(tmp_path);config=Settings();config.rules.cooldown=0;store.save(config)
    prompts=[]
    def transport(request):
        assert request.url.host!='gchat.qpic.cn'
        if request.url.path=='/api/chat':
            body=json.loads(request.content);prompts.append(body['messages'])
            return httpx.Response(200,json={'message':{'content':'还笑，快说嘛。'}})
        if request.url.path.endswith('/getAppAccessToken'):
            return httpx.Response(200,json={'access_token':'test-token','expires_in':7200})
        return httpx.Response(200,json={'id':'reply-id'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        bot=Bot(store,client);payload=event(text=text);payload['d']['attachments']=[]
        await bot.handle(payload)
    assert prompts[0][-1]['content']==text
    assert '不要固定先点评图片，再聊天' in prompts[0][0]['content']
    assert '不据此猜测具体表情' in prompts[0][0]['content']
    assert all('images' not in message for message in prompts[0])
    assert bot.stats['sent']==1 and bot.stats['errors']==0
    store.close()
