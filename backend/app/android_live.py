"""Same-origin, session-bound relay to private host video/control WebSocket."""
import asyncio,hmac,os,re
from urllib.parse import quote,urlsplit,urlunsplit
from fastapi import WebSocket
import websockets
MAX_MESSAGE=4*1024*1024+12


def register_android_live(app):
    @app.websocket('/api/bots/{bot_id}/android/devices/{device_id}/live')
    async def live(ws:WebSocket,bot_id:str,device_id:str):
        session=ws.cookies.get('hay_session','');workers=[];runtime=None;current=asyncio.current_task()
        allowed=os.getenv('PUBLIC_ORIGIN') or ('https' if ws.url.scheme=='wss' else 'http')+'://'+ws.headers.get('host','')
        if not session or not hmac.compare_digest(session,app.state.session) or ws.headers.get('origin')!=allowed or not re.fullmatch('[0-9a-f]{32}',device_id):
            await ws.close(code=1008);return
        try:runtime=app.state.manager.get(bot_id)
        except Exception:await ws.close(code=1008);return
        gateway=app.state.android.gateway
        if not gateway.configured:await ws.close(code=1013,reason='安卓运行时未配置');return
        def valid():return hmac.compare_digest(session,app.state.session) and not runtime.closing
        runtime.requests.add(current)
        try:
            parsed=urlsplit(gateway.url)
            path=parsed.path.rstrip('/')+'/bots/'+quote(bot_id,safe='')+'/devices/'+device_id+'/live'
            url=urlunsplit(('wss' if parsed.scheme=='https' else 'ws',parsed.netloc,path,'',''))
            async with websockets.connect(url,additional_headers={'Authorization':'Bearer '+gateway.token},open_timeout=25,max_size=MAX_MESSAGE,max_queue=8,proxy=None,ping_interval=15,ping_timeout=15) as upstream:
                if not valid():return
                await ws.accept()
                async def outbound():
                    async for message in upstream:
                        if not valid():return
                        if isinstance(message,bytes):await ws.send_bytes(message)
                        else:await ws.send_text(message)
                async def inbound():
                    while valid():
                        message=await ws.receive_text()
                        if len(message)>12000:raise ValueError('控制消息过大')
                        if not valid():return
                        await upstream.send(message)
                async def watch_auth():
                    while valid():await asyncio.sleep(.5)
                workers=[asyncio.create_task(outbound()),asyncio.create_task(inbound()),asyncio.create_task(watch_auth())]
                done,_=await asyncio.wait(workers,return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if not task.cancelled() and task.exception():raise task.exception()
        except (Exception,asyncio.CancelledError):pass
        finally:
            for worker in workers:worker.cancel()
            await asyncio.gather(*workers,return_exceptions=True)
            if runtime:runtime.requests.discard(current)
            try:await ws.close(code=1000 if valid() else 1008)
            except Exception:pass
