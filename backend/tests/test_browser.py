import asyncio
import json
import threading
from contextlib import contextmanager

import httpx
import pytest
import websockets
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app


PASSWORD = 'browser-test-password-long'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', PASSWORD)
    monkeypatch.delenv('BROWSER_RUNTIME_URL', raising=False)
    monkeypatch.delenv('BROWSER_RUNTIME_TOKEN', raising=False)
    with TestClient(create_app(tmp_path)) as c:
        yield c


def login(c):
    assert c.post('/api/login', json={'password': PASSWORD}).status_code == 200


def mock_gateway(c, handler):
    gateway = c.app.state.browser.gateway
    c.portal.call(gateway.client.aclose)
    gateway.url = 'http://host.docker.internal:17322'
    gateway.token = 'private-host-sentinel' * 3
    gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return gateway


def test_browser_requires_management_auth_and_existing_bot(client):
    c = client
    assert c.get('/api/bots/default/browser').status_code == 401
    login(c)
    assert c.get('/api/bots/default/browser').json() == {'configured': False, 'session': None}
    assert c.post('/api/bots/default/browser/start', headers={'origin': 'http://evil.test'}).status_code == 403
    assert c.get('/api/bots/missing/browser').status_code == 404
    assert c.post('/api/bots/default/browser/start').status_code == 503
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect('/api/bots/default/browser/live', headers={'origin': 'http://evil.test'}):
            pass
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect('/api/bots/missing/browser/live', headers={'origin': 'http://testserver'}):
            pass


def test_browser_environment_uses_private_host_and_never_exposes_token(client):
    login(client)
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.headers['host'], request.headers['authorization']))
        return httpx.Response(200, json={'state': 'needs_install', 'checks': [], 'installUrl': 'https://www.google.cn/chrome/'})

    gateway = mock_gateway(client, handler)
    result = client.post('/api/bots/default/browser/environment')
    assert result.status_code == 200 and result.json()['state'] == 'needs_install'
    assert seen == [('POST', '/api/environment', '127.0.0.1:17322', 'Bearer ' + gateway.token)]
    assert gateway.token not in result.text
    client.portal.call(gateway.client.aclose)
    gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={'detail': gateway.token})))
    result = client.get('/api/bots/default/browser/environment')
    assert result.status_code == 503 and gateway.token not in result.text


def test_browser_rejects_cross_bot_controls_and_malformed_identity(client):
    c = client
    login(c)
    other = c.post('/api/bots', json={'name': 'Other'}).json()['id']
    service = c.app.state.browser
    service.viewers['viewer-a'] = {'bot_id': 'default', 'auth': c.cookies.get('hay_session'), 'lease': 'lease-a', 'active': True}
    seen = []
    mock_gateway(c, lambda r: (seen.append(r), httpx.Response(200, json={'state': 'ready'}))[1])
    try:
        for route, body in [('control/claim', {'connectionId': 'viewer-a'}),
                            ('control/action', {'connectionId': 'viewer-a', 'lease': 'lease-a', 'kind': 'text', 'text': 'secret'}),
                            ('login/finish', {'connectionId': 'viewer-a', 'lease': 'lease-a'})]:
            assert c.post(f'/api/bots/{other}/browser/{route}', json=body).status_code == 409
        assert c.post('/api/bots/default/browser/control/action', json={'connectionId': {}, 'lease': []}).status_code == 422
        assert c.post('/api/bots/default/browser/control/action', json={'connectionId': 'viewer-a', 'lease': []}).status_code == 409
        assert c.post('/api/bots/default/browser/control/action', json={'connectionId': 'viewer-a', 'lease': 'old'}).status_code == 409
        assert c.post('/api/bots/default/browser/control/action', json={'connectionId': 'viewer-a', 'lease': '失效权限'}).status_code == 409
        assert not seen
    finally:
        service.viewers.clear()


def test_browser_settings_are_authorized_strict_and_scoped_to_catalog_bot(client):
    c = client
    assert c.post('/api/bots/default/browser/settings', json={'headless': False}).status_code == 401
    login(c)
    seen = []

    def handler(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={'state': 'stopped', 'options': {'headless': True}})

    mock_gateway(c, handler)
    assert c.post('/api/bots/default/browser/settings', json={'headless': False}).status_code == 400
    assert c.post('/api/bots/default/browser/settings', json={'headless': 'false'}).status_code == 422
    assert c.post('/api/bots/default/browser/settings', json={'headless': False, 'args': []}).status_code == 422
    assert c.post('/api/bots/default/browser/settings', json={'headless': False}, headers={'origin': 'http://evil.test'}).status_code == 403
    assert c.post('/api/bots/missing/browser/settings', json={'headless': False}).status_code == 404
    assert not seen
    result = c.post('/api/bots/default/browser/settings', json={'headless': True})
    assert result.status_code == 200
    assert seen == [('/api/sessions/bot-default/settings', {'headless': True, 'acknowledgeHeadlessRisk': False})]


@contextmanager
def host_socket():
    started, finished, stop = threading.Event(), threading.Event(), threading.Event()
    shared, seen = {}, []

    async def run():
        async def handler(ws):
            seen.append((ws.request.path, ws.request.headers['Host'], ws.request.headers['Authorization'], ws.request.headers.get('Origin')))
            await ws.send(json.dumps({'type': 'state', 'connectionId': 'online-viewer', 'state': {'state': 'ready', 'generation': 2, 'tabs': []}}))
            try:
                await ws.wait_closed()
            finally:
                finished.set()

        async with websockets.serve(handler, '127.0.0.1', 0) as server:
            shared['port'] = server.sockets[0].getsockname()[1]
            started.set()
            while not stop.is_set():
                await asyncio.sleep(.01)

    thread = threading.Thread(target=lambda: asyncio.run(run()), daemon=True)
    thread.start()
    assert started.wait(5)
    try:
        yield shared['port'], seen, finished
    finally:
        stop.set()
        thread.join(5)


def test_browser_live_relay_claim_logout_and_host_disconnect(client):
    c = client
    login(c)
    seen_http = []

    def handler(request):
        seen_http.append(request.url.path)
        if request.url.path.endswith('/claim'):
            return httpx.Response(200, json={'lease': 'fresh-lease', 'generation': 3})
        return httpx.Response(200, json={'id': 'bot-default', 'state': 'owner_control', 'generation': 3, 'tabs': []})

    gateway = mock_gateway(c, handler)
    with host_socket() as (port, seen, finished):
        gateway.url = f'http://127.0.0.1:{port}'
        path = '/api/bots/default/browser/live'
        with c.websocket_connect(path, headers={'origin': 'http://testserver'}) as ws:
            first = ws.receive_json()
            assert first['connectionId'] == 'online-viewer'
            payload = {'connectionId': 'online-viewer'}
            claim = c.post('/api/bots/default/browser/control/claim', json=payload)
            assert claim.status_code == 200
            payload.update(lease=claim.json()['lease'])
            assert c.post('/api/bots/default/browser/login/begin', json=payload).status_code == 200
            assert c.post('/api/bots/default/browser/control/action', json={**payload, 'kind': 'text', 'text': '你好'}).status_code == 200
            stale_cookie = c.cookies.get('hay_session')
            assert c.post('/api/logout').status_code == 200
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
            assert finished.wait(3)
            assert c.post('/api/bots/default/browser/control/action', json=payload, headers={'cookie': 'hay_session=' + stale_cookie}).status_code == 401
        login(c)
        assert c.post('/api/bots/default/browser/control/claim', json={'connectionId': 'online-viewer'}).status_code == 409
        assert seen == [('/api/sessions/bot-default/live', f'127.0.0.1:{port}', 'Bearer ' + gateway.token, None)]
        assert seen_http == ['/api/sessions/bot-default/claim', '/api/sessions/bot-default/login/begin', '/api/sessions/bot-default/action']


def test_browser_archive_stops_only_its_session(client):
    c = client
    login(c)
    other = c.post('/api/bots', json={'name': 'Archive browser'}).json()['id']
    seen = []
    mock_gateway(c, lambda r: (seen.append(r.url.path), httpx.Response(200, json={'state': 'stopped'}))[1])
    assert c.post(f'/api/bots/{other}/archive').status_code == 200
    assert seen == [f'/api/sessions/bot-{other}/stop']
    assert c.get(f'/api/bots/{other}/browser').status_code == 404
    assert c.get('/api/bots/default/browser').status_code == 200
