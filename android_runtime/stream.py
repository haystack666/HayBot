"""Bounded, per-device human video/control sessions; never fed to model context."""
import asyncio,hashlib,json,struct,time,uuid
from pathlib import Path
from .engine import RuntimeFailure
from .stream_protocol import validate_input,frame_info,MAX_FRAME
SERVER_SHA='8588238c9a5a00aa542906b6ec7e6d5541d9ffb9b5d0f6e1bc0e365e2303079e'

def new_scid():
    # scrcpy parses scid as a signed Java int, so keep it below 0x80000000.
    return format(uuid.uuid4().int&0x7fffffff,'08x')

class LiveManager:
    def __init__(self,engine):self.engine=engine;self.sessions={};self.prepare_lock=asyncio.Lock();self.prepared=None
    async def prepare(self):
        async with self.prepare_lock:
            files=Path(__file__).parent;server=files/'assets/scrcpy-server-v3.3.4'
            if hashlib.sha256(server.read_bytes()).hexdigest()!=SERVER_SHA:raise RuntimeFailure('scrcpy 服务器校验失败')
            digest=hashlib.sha256((files/'stream_guest.py').read_bytes()+(files/'stream_protocol.py').read_bytes()).hexdigest()[:16]
            remote='/tmp/haybot-live-'+digest
            if self.prepared==remote:
                try:await self.engine.command('test','-f',remote+'/bridge.py','-a','-f',remote+'/server.jar','-a','-f',remote+'/stream_protocol.py')
                except RuntimeFailure:self.prepared=None
            if self.prepared!=remote:
                await self.engine.command('mkdir','-p',remote)
                for local,name in [(server,'server.jar'),(files/'stream_guest.py','bridge.py'),(files/'stream_protocol.py','stream_protocol.py')]:await self.engine.command.copy(local,remote+'/'+name)
                self.prepared=remote
            return remote
    async def open(self,bot_id,device_id):
        self.engine.get(bot_id,device_id)
        await self.reap_detached()
        if sum(s.device_id==device_id for s in self.sessions.values())>=2:raise RuntimeFailure('每台手机最多同时打开两个实时画面')
        remote=await self.prepare()
        async with self.engine.lock(device_id):
            self.engine.get(bot_id,device_id)
            if sum(s.device_id==device_id for s in self.sessions.values())>=2:raise RuntimeFailure('每台手机最多同时打开两个实时画面')
            serial=await self.engine.serial(device_id)
            session=LiveSession(self,bot_id,device_id)
            self.sessions[session.id]=session
            try:
                scid=new_scid()
                session.proc=await self.engine.command.spawn('python3',remote+'/bridge.py',serial,remote+'/server.jar',scid)
                if session.closed:raise RuntimeFailure('实时连接已关闭，未启动视频')
                session.reader=asyncio.create_task(session.pump())
                session.stderr=asyncio.create_task(session.collect_stderr())
                return session
            except BaseException:
                await session.reap()
                self.sessions.pop(session.id,None);raise
            finally:session.ready.set()
    async def close_device(self,device_id,controls_only=False):
        targets=[s for s in list(self.sessions.values()) if s.device_id==device_id and (not controls_only or self.engine.manual_owners.get(device_id)==s.id)]
        await asyncio.gather(*(s.close() for s in targets),return_exceptions=True)
        # An open() may still be spawning the guest bridge; wait until it either
        # adopts the process or reaps it, so callers never leave a late process.
        await asyncio.gather(*(asyncio.wait_for(s.ready.wait(),15) for s in targets),return_exceptions=True)
    async def reap_detached(self):
        # A client that disconnects between spawn and accept must not hold a slot.
        stale=[s for s in list(self.sessions.values()) if not s.attached and time.time()-s.created>20]
        if stale:await asyncio.gather(*(s.close() for s in stale),return_exceptions=True)
    async def close(self):
        await asyncio.gather(*(s.close() for s in list(self.sessions.values())),return_exceptions=True)

class LiveSession:
    def __init__(self,manager,bot_id,device_id):
        self.manager=manager;self.engine=manager.engine;self.bot_id=bot_id;self.device_id=device_id;self.id=uuid.uuid4().hex
        self.proc=None;self.reader=None;self.stderr=None;self.closed=False;self.ready=asyncio.Event();self.queue=asyncio.Queue(maxsize=8);self.pending={};self.seq=0;self.config=None;self.failure=None
        self.attached=False;self.created=time.time()
        self.error_output=''
    async def collect_stderr(self):
        try:self.error_output=(await self.proc.stderr.read(2048)).decode('utf8','replace').strip()
        except Exception:pass
    async def pump(self):
        try:
            while True:
                head=await self.proc.stdout.readexactly(5);kind=head[:1];size=struct.unpack('>I',head[1:])[0]
                if not 0<size<=MAX_FRAME+12:raise RuntimeFailure('视频消息大小无效')
                data=await self.proc.stdout.readexactly(size)
                if kind==b'A':
                    ack=json.loads(data);f=self.pending.pop(ack['seq'],None)
                    if f and not f.done():f.set_result(True)
                    continue
                if kind==b'C':self.config=json.loads(data)
                elif kind==b'V':frame_info(data)
                else:raise RuntimeFailure('视频消息无效')
                try:self.queue.put_nowait((kind,data))
                except asyncio.QueueFull:raise RuntimeFailure('网络过慢，实时画面已停止；请重新连接')
        except (Exception,asyncio.CancelledError) as exc:
            self.failure=type(exc).__name__ if not isinstance(exc,RuntimeFailure) else str(exc)
            hint=self.error_output[:200]
            for f in self.pending.values():
                if not f.done():f.set_exception(RuntimeFailure('实时控制已断开，未重试输入'))
            self.pending.clear()
            while not self.queue.empty():self.queue.get_nowait()
            self.queue.put_nowait((b'E',('视频连接已结束，请重新连接或使用截图模式'+('；'+hint if hint else '')).encode()))
    async def claim(self):
        async with self.engine.lock(self.device_id):
            self.engine.get(self.bot_id,self.device_id)
            if self.closed or self.engine.leases.get(self.device_id):raise RuntimeFailure('请先人工接管并停止 Bot 手机任务')
            owner=self.engine.manual_owners.get(self.device_id)
            if owner and owner!=self.id:raise RuntimeFailure('另一实时窗口正在操作手机')
            self.engine.manual_owners[self.device_id]=self.id
    async def input(self,value):
        value=validate_input(value)
        async with self.engine.lock(self.device_id):
            self.engine.get(self.bot_id,self.device_id)
            if self.closed or self.engine.manual_owners.get(self.device_id)!=self.id or self.engine.leases.get(self.device_id):raise RuntimeFailure('未接管实时操作，输入未执行')
            if value['type']=='pointer' and (not self.config or (value['width'],value['height']) not in [(self.config['width'],self.config['height']),(self.config['height'],self.config['width'])]):raise RuntimeFailure('画面尺寸已变化，请重新连接')
            self.seq+=1;f=asyncio.get_running_loop().create_future();self.pending[self.seq]=f
            self.proc.stdin.write((json.dumps({'seq':self.seq,'input':value},ensure_ascii=False)+'\n').encode())
            try:
                await self.proc.stdin.drain();await asyncio.wait_for(f,3)
            except asyncio.TimeoutError:raise RuntimeFailure('实时控制响应超时，输入未重试')
            finally:self.pending.pop(self.seq,None)
    async def close(self):
        if self.closed:return
        self.closed=True
        if self.engine.manual_owners.get(self.device_id)==self.id:self.engine.manual_owners.pop(self.device_id,None)
        self.manager.sessions.pop(self.id,None)
        for task in (self.reader,self.stderr):
            if task:task.cancel()
        await asyncio.gather(*(t for t in (self.reader,self.stderr) if t),return_exceptions=True)
        await self.reap()

    async def reap(self):
        proc=self.proc
        if not proc:return
        if proc.returncode is None:
            try:
                proc.stdin.write(b'{"stop":true}\n');await proc.stdin.drain()
            except Exception:pass
            try:await asyncio.wait_for(proc.wait(),8)
            except Exception:
                if proc.returncode is None:proc.kill();await proc.wait()
        if proc.stdin:
            try:proc.stdin.close();await proc.stdin.wait_closed()
            except Exception:pass
