from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect
from app.main import create_app

def test_live_video_csp_allows_local_mse_blob(tmp_path,monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD','test-password-long-enough')
    with TestClient(create_app(tmp_path)) as client:
        policy=client.get('/api/health').headers['content-security-policy']
        assert "media-src 'self' blob:" in policy


def test_live_socket_rejects_missing_cookie_foreign_origin_and_wrong_bot(tmp_path,monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD','test-password-long-enough')
    with TestClient(create_app(tmp_path)) as client:
        path='/api/bots/default/android/devices/'+'0'*32+'/live'
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(path,headers={'origin':'http://testserver'}):pass
        assert error.value.code==1008
        client.post('/api/login',json={'password':'test-password-long-enough'})
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(path,headers={'origin':'http://evil.test'}):pass
        assert error.value.code==1008
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(path.replace('/default/','/missing/'),headers={'origin':'http://testserver'}):pass
        assert error.value.code==1008

def test_live_relay_is_session_bound_and_logout_closes_upstream(tmp_path,monkeypatch):
    import asyncio,json,threading
    import websockets
    started=threading.Event();finished=threading.Event();shared={};seen=[]
    async def server():
        async def handler(ws):
            seen.append((ws.request.path,ws.request.headers.get('Authorization'),ws.request.headers.get('Origin')))
            try:
                await ws.send(json.dumps({'type':'config','codec':'h264','width':720,'height':1280}))
                async for raw in ws:
                    if json.loads(raw).get('type')=='claim':await ws.send('{"type":"control","owned":true}')
            finally:finished.set()
        async with websockets.serve(handler,'127.0.0.1',0) as listener:
            shared['port']=listener.sockets[0].getsockname()[1];shared['loop']=asyncio.get_running_loop();shared['stop']=asyncio.Event();started.set();await shared['stop'].wait()
    thread=threading.Thread(target=lambda:asyncio.run(server()),daemon=True);thread.start();assert started.wait(5)
    monkeypatch.setenv('ADMIN_PASSWORD','test-password-long-enough')
    try:
        with TestClient(create_app(tmp_path)) as c:
            service=c.app.state.android;service.gateway.configured=True;service.gateway.url='http://127.0.0.1:'+str(shared['port']);service.gateway.token='test-host-token'*3
            c.post('/api/login',json={'password':'test-password-long-enough'})
            with c.websocket_connect('/api/bots/default/android/devices/'+'0'*32+'/live',headers={'origin':'http://testserver'}) as ws:
                assert ws.receive_json()['codec']=='h264'
                ws.send_json({'type':'claim'});assert ws.receive_json()['owned'] is True
                c.post('/api/logout')
                with pytest.raises(WebSocketDisconnect) as error:ws.receive_json()
                assert error.value.code==1008
            assert finished.wait(5)
            assert seen==[('/bots/default/devices/'+'0'*32+'/live','Bearer '+service.gateway.token,None)]
    finally:
        shared['loop'].call_soon_threadsafe(shared['stop'].set);thread.join(5)
