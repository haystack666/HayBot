import struct
import pytest
from android_runtime.stream_protocol import control_packet, frame_info, validate_input


def test_scrcpy_touch_packet_and_bounds():
    packet=control_packet({'type':'pointer','action':'down','x':10,'y':20,'width':720,'height':1280})
    assert len(packet)==32
    assert struct.unpack('>BBqiiHHHii',packet)[:5]==(2,0,-2,10,20)
    with pytest.raises(ValueError):validate_input({'type':'pointer','action':'move','x':720,'y':0,'width':720,'height':1280})
    with pytest.raises(ValueError):validate_input({'type':'text','text':'a'*2001})
    with pytest.raises(ValueError):validate_input({'type':'shell','text':'id'})


def test_video_frames_are_bounded_and_timestamps_preserved():
    raw=struct.pack('>QI',1<<63,4)+b'\0\0\0\1'
    assert frame_info(raw)=={'config':True,'keyframe':False,'pts':0,'size':4}
    with pytest.raises(ValueError):frame_info(struct.pack('>QI',0,5_000_000))
    with pytest.raises(ValueError):frame_info(struct.pack('>QI',0,4)+b'a')


def test_scid_is_an_eight_digit_java_int():
    from android_runtime.stream import new_scid
    for _ in range(50):
        value=new_scid()
        assert len(value)==8 and all(c in '0123456789abcdef' for c in value)
        assert 0<=int(value,16)<=0x7fffffff

@pytest.mark.asyncio
async def test_bridge_is_recopied_after_guest_reboot_clears_tmp():
    from types import SimpleNamespace
    from android_runtime.stream import LiveManager
    from android_runtime.engine import RuntimeFailure
    class Files:
        present=True
        copied=0
        async def __call__(self,*args):
            if args[0]=='test' and not self.present:raise RuntimeFailure('missing')
        async def copy(self,*args):self.copied+=1;self.present=True
    files=Files();manager=LiveManager(SimpleNamespace(command=files))
    await manager.prepare();assert files.copied==3
    files.present=False
    await manager.prepare();assert files.copied==6


def test_text_uses_utf8_clipboard_paste_without_clipboard_reads():
    packet=control_packet({'type':'text','text':'你好'})
    assert packet[0]==9 and packet[9]==1
    assert packet[14:].decode()=='你好'
    assert control_packet({'type':'key','key':'home','action':'up'})==struct.pack('>BBiii',0,1,3,0,0)

@pytest.mark.asyncio
async def test_owner_stream_excludes_ai_and_survives_login_until_explicit_finish(tmp_path):
    from android_runtime.engine import AndroidEngine,DeviceCreate,RuntimeFailure
    from android_runtime.stream import LiveSession
    from test_engine import Guest
    e=AndroidEngine(tmp_path,Guest());d=await e.create('a',DeviceCreate(name='phone'))
    s=LiveSession(e.streams(),'a',d['id']);e.streams().sessions[s.id]=s
    with pytest.raises(RuntimeFailure):await e.streams().open('other',d['id'])
    await s.claim()
    with pytest.raises(RuntimeFailure):await e.claim('a',d['id'])
    await e.login('a',d['id'],True)
    assert e.manual_owners[d['id']]==s.id
    await e.login('a',d['id'],False)
    assert not e.manual_owners and not e.streams().sessions
    assert await e.claim('a',d['id'])
    e.close()

@pytest.mark.asyncio
async def test_close_during_spawn_waits_and_reaps_late_process(tmp_path):
    import asyncio
    from android_runtime.engine import AndroidEngine,DeviceCreate,RuntimeFailure
    from test_engine import Guest
    entered=asyncio.Event();resume=asyncio.Event()
    class Pipe:
        def __init__(self,p):self.p=p
        def write(self,data):self.p.returncode=0
        async def drain(self):pass
        def close(self):pass
        async def wait_closed(self):pass
    class Reader:
        async def readexactly(self,n):await asyncio.Event().wait()
        async def read(self,n):await asyncio.Event().wait()
    class Proc:
        returncode=None
        def __init__(self):self.stdin=Pipe(self);self.stdout=Reader();self.stderr=Reader()
        async def wait(self):return self.returncode
        def kill(self):self.returncode=-9
    proc=Proc()
    class Delayed(Guest):
        async def spawn(self,*args):entered.set();await resume.wait();return proc
    e=AndroidEngine(tmp_path,Delayed());d=await e.create('a',DeviceCreate(name='p'));manager=e.streams()
    async def prepare():return '/tmp/test-live'
    async def serial(_):return '127.0.0.1:12345'
    manager.prepare=prepare;e.serial=serial
    opening=asyncio.create_task(manager.open('a',d['id']));await entered.wait()
    closing=asyncio.create_task(manager.close_device(d['id']));await asyncio.sleep(0);resume.set()
    returned=None
    try:
        try:returned=await opening
        except RuntimeFailure:pass
        await closing
        assert returned is None and proc.returncode is not None and not manager.sessions
    finally:
        proc.kill()
        if returned:
            for task in (returned.reader,returned.stderr):
                if task:task.cancel()
            await asyncio.gather(*(t for t in (returned.reader,returned.stderr) if t),return_exceptions=True)
        e.close()
