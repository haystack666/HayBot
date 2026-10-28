import pytest
from fastapi.testclient import TestClient
from android_runtime.service import create_app
from android_runtime.engine import AndroidEngine
from test_engine import Guest


def test_host_api_auth_origin_scoping_and_destroy_confirmation(tmp_path):
    engine = AndroidEngine(tmp_path, Guest())
    with TestClient(create_app(engine=engine, token='secret-token-32-characters-long-test')) as c:
        assert c.get('/health').status_code == 401
        headers = {'Authorization': 'Bearer secret-token-32-characters-long-test'}
        assert c.get('/health', headers={**headers, 'Origin': 'http://evil.test'}).status_code == 403
        d = c.post('/bots/a/devices', headers=headers, json={'name': 'phone'}).json()
        assert c.get('/bots/b/devices', headers=headers).json()['devices'] == []
        assert c.post('/bots/b/devices/' + d['id'] + '/start', headers=headers).status_code == 409
        assert c.delete('/bots/a/devices/' + d['id'] + '?destroy_data=true', headers=headers).status_code == 422
        assert c.post('/bots/a/devices/' + d['id'] + '/action', headers=headers, json={'kind': 'shell', 'text': 'id'}).status_code == 422
    engine.close()


def test_rename_is_persistent_scoped_and_does_not_interrupt_device(tmp_path):
    guest = Guest(); engine = AndroidEngine(tmp_path, guest)
    headers = {'Authorization': 'Bearer secret-token-32-characters-long-test'}
    with TestClient(create_app(engine=engine, token='secret-token-32-characters-long-test')) as c:
        device = c.post('/bots/a/devices', headers=headers, json={'name': 'phone'}).json()
        url = '/bots/a/devices/' + device['id']
        engine.state(device['id'], 'running')
        engine.leases[device['id']] = 'active-task'
        assert c.patch(url, json={'name': 'forbidden'}).status_code == 401
        assert c.patch('/bots/b/devices/' + device['id'], headers=headers, json={'name': 'forbidden'}).status_code == 409
        for name in ('', '   ', 'x' * 61, 'bad\nname', 'bad\x00name'):
            assert c.patch(url, headers=headers, json={'name': name}).status_code == 422
        assert c.patch(url, headers=headers, json={'name': 'phone', 'width': 1080}).status_code == 422
        result = c.patch(url, headers=headers, json={'name': '  诗语的手机  '})
        assert result.status_code == 200
        assert result.json()['name'] == result.json()['config']['name'] == '诗语的手机'
        assert result.json()['state'] == 'running'
        assert engine.leases[device['id']] == 'active-task'
        assert guest.calls == []
        assert c.get('/bots/a/devices', headers=headers).json()['devices'][0]['name'] == '诗语的手机'
    engine.close()
    reopened = AndroidEngine(tmp_path, guest)
    try:
        assert reopened.get('a', device['id'])['name'] == '诗语的手机'
        assert reopened.get('a', device['id'])['config']['name'] == '诗语的手机'
        assert reopened.list('b') == []
    finally:
        reopened.close()
