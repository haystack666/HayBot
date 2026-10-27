"""Guest-side scrcpy socket bridge; stdio carries only bounded framed messages.
No network listener outside the guest loopback, no UI text/clipboard logging.
"""
import asyncio,json,os,signal,struct,sys
from stream_protocol import control_packet,MAX_FRAME

async def run(*args):
    p=await asyncio.create_subprocess_exec(*args,stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
    try:
        out,_=await asyncio.wait_for(p.communicate(),20)
        if p.returncode:raise RuntimeError('ADB operation failed')
        return out
    except BaseException:
        if p.returncode is None:p.kill();await p.communicate()
        raise

async def main(serial,server,scid):
    port=None;process=None;writers=[];tasks=[];stop=asyncio.Event();outlock=asyncio.Lock()
    remote='/data/local/tmp/haybot-scrcpy-'+scid+'.jar'
    async def emit(kind,data):
        async with outlock:
            sys.stdout.buffer.write(kind+struct.pack('>I',len(data))+data);sys.stdout.buffer.flush()
    try:
        await run('adb','-s',serial,'push',server,remote)
        port=(await run('adb','-s',serial,'forward','tcp:0','localabstract:scrcpy_'+scid)).decode().strip()
        if not port.isdigit():raise RuntimeError('Invalid forward')
        args=['adb','-s',serial,'shell','CLASSPATH='+remote,'app_process','/','com.genymobile.scrcpy.Server','3.3.4',
            'scid='+scid,'audio=false','control=true','tunnel_forward=true','send_device_meta=false','send_dummy_byte=true','send_codec_meta=true','send_frame_meta=true',
            'clipboard_autosync=false','max_size=1280','max_fps=30','video_bit_rate=2500000','video_codec=h264',
            'video_codec_options=repeat-previous-frame-after:long=100000,i-frame-interval=1','power_on=false','cleanup=true']
        process=await asyncio.create_subprocess_exec(*args,stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE)
        loop=asyncio.get_running_loop();reader=writer=None;deadline=loop.time()+40
        while loop.time()<deadline:
            reader,writer=await asyncio.open_connection('127.0.0.1',int(port))
            try:
                if await asyncio.wait_for(reader.readexactly(1),2)==b'\0':break
            except asyncio.TimeoutError:
                # adb forward already queued this socket; scrcpy may still be starting.
                try:
                    if await asyncio.wait_for(reader.readexactly(1),25)==b'\0':break
                except (OSError,asyncio.IncompleteReadError,asyncio.TimeoutError):pass
            except (OSError,asyncio.IncompleteReadError):pass
            writer.close();await writer.wait_closed();reader=writer=None
            await asyncio.sleep(.2)
        if not reader or not writer:
            try:detail=(await asyncio.wait_for(process.stderr.read(4096),2)).decode('utf8','replace').strip()
            except Exception:detail=''
            raise RuntimeError('Scrcpy connection failed'+(': '+detail[-200:] if detail else ''))
        writers.append(writer)
        cr,cw=await asyncio.open_connection('127.0.0.1',int(port));writers.append(cw)
        codec,w,h=struct.unpack('>III',await asyncio.wait_for(reader.readexactly(12),20))
        if codec!=0x68323634 or not(1<=w<=2560 and 1<=h<=2560):raise RuntimeError('Unsupported codec')
        await emit(b'C',json.dumps({'type':'config','codec':'h264','width':w,'height':h,'fps':30}).encode())
        async def video():
            while True:
                header=await reader.readexactly(12);size=struct.unpack('>I',header[8:])[0]
                if not 0<size<=MAX_FRAME:raise RuntimeError('Invalid frame')
                await emit(b'V',header+await reader.readexactly(size))
        async def inputs():
            source=asyncio.StreamReader(limit=16384);protocol=asyncio.StreamReaderProtocol(source)
            await asyncio.get_running_loop().connect_read_pipe(lambda:protocol,sys.stdin.buffer)
            while True:
                line=await source.readline()
                if not line:return
                msg=json.loads(line)
                if msg.get('stop'):return
                seq=msg['seq'];packet=control_packet(msg['input'])
                cw.write(packet);await cw.drain()
                await emit(b'A',json.dumps({'seq':seq}).encode())
        async def discard_control():
            # Device messages may contain clipboard contents. Never forward/store them.
            while await cr.read(4096):pass
        for signum in (signal.SIGTERM,signal.SIGHUP,signal.SIGINT):asyncio.get_running_loop().add_signal_handler(signum,stop.set)
        tasks=[asyncio.create_task(video()),asyncio.create_task(inputs()),asyncio.create_task(discard_control()),asyncio.create_task(stop.wait())]
        done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if not task.cancelled() and task.exception():raise RuntimeError('Live connection ended')
    finally:
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        for writer in writers:writer.close()
        if process and process.returncode is None:
            process.terminate()
            try:await asyncio.wait_for(process.wait(),3)
            except asyncio.TimeoutError:process.kill();await process.wait()
        if port:
            try:await run('adb','-s',serial,'forward','--remove','tcp:'+port)
            except Exception:pass
        try:await run('adb','-s',serial,'shell','rm','-f',remote)
        except Exception:pass

if __name__=='__main__':
    try:asyncio.run(main(*sys.argv[1:]))
    except Exception as exc:print('Video transport ended: '+type(exc).__name__+': '+str(exc),file=sys.stderr);sys.exit(1)
