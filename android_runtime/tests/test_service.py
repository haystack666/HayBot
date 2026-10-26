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
