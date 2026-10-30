"""External NapCat forward-WebSocket adapter. No QQ login or generic protocol hosting."""
import asyncio
import base64
import contextlib
import json
import re
import time
import uuid
from datetime import datetime,timezone

from websockets.asyncio.client import connect
from .message_quotes import quoted_body
from .group_chat import is_group


class NapCatError(ValueError):
    pass


def number(value, signed=False):
    value=str(value)
    return value if re.fullmatch(r'-?[0-9]{1,20}' if signed else r'[1-9][0-9]{0,19}',value) else None


def normalize_event(event,config):
    if not isinstance(event,dict) or event.get('post_type')!='message' or str(event.get('self_id'))!=config.napcat.self_id:
        return None
    group=event.get('message_type')=='group'
    if event.get('message_type') not in ('private','group'):return None
    user=number(event.get('user_id'));mid=number(event.get('message_id'),True)
    target=number(event.get('group_id')) if group else user
    if not user or not target or mid is None or mid=='0' or user==config.napcat.self_id:return None
    segments=event.get('message')
    if not isinstance(segments,list) or len(segments)>200:return None
    texts=[];images=[];mentions=[];mentioned=False;reply_id=None
    for segment in segments:
        if not isinstance(segment,dict) or not isinstance(segment.get('data'),dict):continue
        kind,data=segment.get('type'),segment['data']
        if kind=='reply' and reply_id is None:
            reply_id=number(data.get('id'),True)
            if reply_id=='0':reply_id=None
        elif kind=='at':
            mentioned |= str(data.get('qq'))==config.napcat.self_id
            uid=number(data.get('qq')) or ('all' if data.get('qq')=='all' else None)
            if uid and len(mentions)<20 and not any(m['id']==uid for m in mentions):
                mentions.append({'id':uid,'bot':uid==config.napcat.self_id})
        elif kind=='text' and isinstance(data.get('text'),str):texts.append(data['text'])
        elif kind=='image' and len(images)<3:
            url=data.get('url')
            # Never interpret remote filesystem paths, arbitrary URLs, or embedded base64.
            if isinstance(url,str) and len(url)<8192:
                from .images import cdn_url,ImageMessageError
                try:url=cdn_url(url)
                except ImageMessageError: url=None
            else:url=None
            if url:
                images.append({'content_type':'image/png','url':url,'filename':'napcat-image.png'})
            else:texts.append('[收到图片，但 NapCat 未提供可读取的 QQ 图片地址]')
        elif kind=='record':
            from .images import cdn_url,ImageMessageError
            try:url=cdn_url(data.get('url'))
            except ImageMessageError:url=None
            if url and len(images)<3:images.append({'content_type':'audio/qq','url':url,'filename':'voice.silk'})
            else:texts.append('[收到语音，但没有可读取的 QQ 音频地址]')
        elif kind=='face':texts.append('[QQ表情:'+str(data.get('id',''))[:30]+']')
        elif kind=='mface':texts.append('[表情包:'+str(data.get('summary',''))[:100]+']')
    mode=config.group_chat.policy(config.account_id,target)['mode'] if group else 'mentions'
    if group and mode=='mentions' and config.napcat.group_require_at and not mentioned:return None
    text=''.join(texts).strip()
    if len(text)>12000 or not text and not images and reply_id is None and not mentions:return None
    stamp=event.get('time')
    if type(stamp) not in (int,float) or not 0<stamp<time.time()+300:stamp=time.time()
    sender=event.get('sender') or {}
    name=(sender.get('card') or sender.get('nickname') or '') if isinstance(sender,dict) else ''
    role=sender.get('role') if isinstance(sender,dict) else None
    return {'t':('GROUP_AT_MESSAGE_CREATE' if mentioned else 'GROUP_MESSAGE_CREATE') if group else 'C2C_MESSAGE_CREATE','d':{
        'id':mid,'content':text,'timestamp':datetime.fromtimestamp(stamp,timezone.utc).isoformat(),
        'author':{'member_openid' if group else 'user_openid':user,'nickname':str(name)[:80],
                  **({'member_role':role} if group and role in ('owner','admin','member') else {})},
        'mentions':mentions,
        **({'group_openid':target} if group else {}),'attachments':images,
        **({'_quote':{'id':reply_id,'available':False}} if reply_id is not None else {})}}


class NapCatTransport:
    def __init__(self,bot,receive_events=True):
        self.bot=bot;self.ws=None;self.reader=None;self.worker=None;self.pending={}
        self.events=asyncio.Queue(maxsize=128);self.send_lock=asyncio.Lock();self.ready=False
        self.nickname='';self.last_drop=0
        self.receive_events=receive_events
        self.session=None

    async def call(self,action,params,timeout=15,before_send=None):
        if not self.ws:raise NapCatError('NapCat 未连接')
        if len(self.pending)>=64:raise NapCatError('NapCat 请求过多，请稍后重试')
        echo=uuid.uuid4().hex;future=asyncio.get_running_loop().create_future();self.pending[echo]=future
        try:
            async with asyncio.timeout(timeout):
                async with self.send_lock:
                    if before_send is not None and not before_send():raise NapCatError('对话状态已变化，停止发送')
                    await self.ws.send(json.dumps({'action':action,'params':params,'echo':echo},ensure_ascii=False))
                result=await future
            if result.get('status')!='ok' or result.get('retcode')!=0:
                code=result.get('retcode');code=code if type(code) is int else 'unknown'
                raise NapCatError(f'NapCat 拒绝请求（错误码 {code}）')
            return result.get('data')
        except asyncio.CancelledError:raise
        except NapCatError:raise
        except TimeoutError:raise NapCatError('NapCat 请求超时，发送结果可能未知，不自动重发') from None
        except Exception:raise NapCatError('NapCat 连接中断，发送结果可能未知，不自动重发') from None
        finally:
            self.pending.pop(echo,None)
            if not future.done():future.cancel()

    async def read(self,ws):
        try:
            async for raw in ws:
                try:event=json.loads(raw)
                except (ValueError,TypeError):continue
                if not isinstance(event,dict):continue
                echo=event.get('echo')
                if isinstance(echo,str) and echo in self.pending:
                    f=self.pending[echo]
                    if not f.done():f.set_result(event)
                    continue
                if not self.ready:continue
                if event.get('self_id') is not None and str(event['self_id'])!=self.bot.store.load().napcat.self_id:
                    self.ready=False
                    await ws.close();return
                if event.get('post_type')=='meta_event' and event.get('meta_event_type')=='heartbeat':
                    status=event.get('status') or {}
                    if isinstance(status,dict) and status.get('online') is False:
                        await ws.close();return
                if self.receive_events and event.get('post_type')=='message':
                    try:self.events.put_nowait(event)
                    except asyncio.QueueFull:
                        if time.monotonic()-self.last_drop>30:
                            self.bot.store.log('warn','NapCat 接收队列已满，部分事件未处理',category='qq',event='napcat.queue_full');self.last_drop=time.monotonic()
        finally:
            self.ready=False
            for f in list(self.pending.values()):
                if not f.done():f.set_exception(NapCatError('NapCat 连接中断，未确认的发送不会自动重试'))

    async def consume(self):
        while True:
            event=await self.events.get()
            try:
                config=self.bot.store.load()
                payload=normalize_event(event,config)
                if payload:
                    await self.resolve_quote(payload)
                    current=self.bot.store.load()
                    if (current.account_id,current.napcat.ws_url)==(config.account_id,config.napcat.ws_url):
                        await self.bot.receive(payload)
            except asyncio.CancelledError:raise
            except Exception:
                self.bot.store.log('warn','NapCat 消息格式无效或处理失败',category='message',event='napcat.event_failed')
            finally:self.events.task_done()

    async def resolve_quote(self,payload):
        data=payload['d'];reference=data.get('_quote')
        if not reference:return
        config=self.bot.store.load();group=is_group(payload['t'])
        target=data.get('group_openid') if group else data['author']['user_openid']
        local=self.bot.store.chat.find_platform(config.account_id,'group' if group else 'user',target,reference['id'])
        if local:
            data['_quote']={**reference,'available':True,**self.bot.store.chat.quote_body(local)}
            return
        try:
            result=await self.call('get_msg',{'message_id':int(reference['id'])},timeout=5)
        except asyncio.CancelledError:raise
        except Exception:
            self.bot.store.log('debug','引用原文暂时无法读取，保留本次新消息继续回复',category='message',event='message.quote_unavailable')
            return
        if (self.bot.store.load().account_id!=config.account_id or not isinstance(result,dict)
                or str(result.get('message_id'))!=reference['id']):return
        sender=result.get('sender');sender=sender if isinstance(sender,dict) else {}
        sender_id=str(sender.get('user_id') or result.get('user_id') or '')
        # A reply ID must never pull a message from a different private chat or group.
        if group:
            if result.get('message_type')!='group' or str(result.get('group_id'))!=target:return
        elif result.get('message_type')!='private' or sender_id!=target:return
        segments=result.get('message')
        if not isinstance(segments,list):return
        texts=[];attachments=[]
        for segment in segments[:200]:
            if not isinstance(segment,dict) or not isinstance(segment.get('data'),dict):continue
            kind,part=segment.get('type'),segment['data']
            if kind=='text' and isinstance(part.get('text'),str):texts.append(part['text'][:4000])
            elif kind=='at':texts.append('[提及QQ:'+str(part.get('qq',''))[:20]+']')
            elif kind=='face':texts.append('[QQ表情:'+str(part.get('id',''))[:30]+']')
            elif kind=='mface':texts.append('[表情包:'+str(part.get('summary',''))[:100]+']')
            elif kind in ('image','video','record','file','forward'):
                attachments.append({'content_type':{'image':'image','video':'video','record':'voice','file':'file','forward':'合并转发'}[kind]})
        body=quoted_body({'content':''.join(texts),'attachments':attachments,
            'author':{'id':sender_id,'nickname':sender.get('card') or sender.get('nickname'),
                      'bot':sender_id==config.napcat.self_id}})
        if body:data['_quote']={**reference,'available':True,**body}

    async def start(self):
        c=self.bot.store.load().napcat
        if not c.ws_url or not c.self_id:raise NapCatError('请先填写并保存外部 NapCat 地址和登录 QQ 号')
        try:
            self.ws=await connect(c.ws_url,additional_headers={'Authorization':'Bearer '+c.token} if c.token else {},
                open_timeout=10,ping_interval=20,ping_timeout=20,max_size=2*1024*1024,max_queue=16)
            self.reader=asyncio.create_task(self.read(self.ws))
            login=await self.call('get_login_info',{})
            if not isinstance(login,dict) or str(login.get('user_id'))!=c.self_id:
                raise NapCatError('NapCat 登录 QQ 号与配置不一致，请核对后重试')
            status=await self.call('get_status',{})
            if not isinstance(status,dict) or status.get('online') is not True:
                raise NapCatError('NapCat 已连接，但 QQ 尚未登录或不在线')
            self.nickname=str(login.get('nickname',''))[:80];self.ready=True
            self.session=(self.bot.store.load().account_id,c.ws_url)
            if self.receive_events:self.worker=asyncio.create_task(self.consume())
        except BaseException as error:
            await self.close()
            if isinstance(error,(asyncio.CancelledError,NapCatError)):raise
            raise NapCatError('无法连接 NapCat，请检查地址、Token、网络及 WebSocket 服务配置') from None

    async def run(self):
        retry=0
        try:
            while True:
                self.bot.state='connected';self.bot.inbox.start();self.bot.group_chat.start()
                self.bot.store.log('info','已连接外部 NapCat，QQ 登录身份已验证',category='qq',event='napcat.connected')
                try:await self.reader
                except asyncio.CancelledError:raise
                except Exception:pass
                await self.close();self.bot.state='reconnecting'
                while True:
                    delay=min(30,2**min(retry,5));retry+=1
                    self.bot.store.log('warn',f'NapCat 连接中断，{delay} 秒后重连',category='qq',event='napcat.reconnecting',details={'retry_in':delay})
                    await asyncio.sleep(delay)
                    try:await self.start();retry=0;break
                    except asyncio.CancelledError:raise
                    except Exception:continue
        finally:
            await self.close();self.bot.state='stopped'

    async def close(self):
        self.ready=False
        if self.ws:
            with contextlib.suppress(Exception):await self.ws.close()
        tasks=[t for t in (self.reader,self.worker) if t and t is not asyncio.current_task()]
        for t in tasks:t.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        self.ws=self.reader=self.worker=None
        while not self.events.empty():self.events.get_nowait();self.events.task_done()

    async def send(self,group,target,message,before_send=None):
        if not number(target):raise NapCatError('QQ 接收者标识无效')
        def guard():
            config=self.bot.store.load()
            return (self.ready and config.transport=='napcat' and self.session==(config.account_id,config.napcat.ws_url)
                and (before_send is None or before_send()))
        if not guard():raise NapCatError('NapCat 未就绪或登录身份已变化，停止发送')
        result=await self.call('send_group_msg' if group else 'send_private_msg',
            {'group_id' if group else 'user_id':int(target),'message':message},timeout=30,before_send=guard)
        mid=number(result.get('message_id'),True) if isinstance(result,dict) else None
        if mid is None or mid=='0':raise NapCatError('NapCat 未确认消息送达，不自动重发')
        return {'id':mid}

    async def send_text(self,group,target,text,before_send=None):
        return await self.send(group,target,[{'type':'text','data':{'text':text}}],before_send)

    async def send_image(self,group,target,data,before_send=None):
        if not data or len(data)>10*1024*1024:raise NapCatError('表情包大小超出限制')
        return await self.send(group,target,[{'type':'image','data':{'file':'base64://'+base64.b64encode(data).decode(),
            'sub_type':1,'summary':'[表情包]'}}],before_send)

    async def send_picture(self,group,target,data,before_send=None):
        if not data or len(data)>10*1024*1024:raise NapCatError('图片大小超出限制')
        return await self.send(group,target,[{'type':'image','data':{'file':'base64://'+base64.b64encode(data).decode(),'summary':'[图片]'}}],before_send)

    async def send_voice(self,group,target,data,before_send=None):
        if not data or len(data)>6*1024*1024:raise NapCatError('语音大小超出限制')
        return await self.send(group,target,[{'type':'record','data':{'file':'base64://'+base64.b64encode(data).decode()}}],before_send)
