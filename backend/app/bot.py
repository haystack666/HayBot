import asyncio
import contextlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit
import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException
from .images import ImageMessageError, image_attachments, load_images
from .ollama import CONTEXT_WINDOW, ContextLimitError, chat_response
from .providers import ProviderConfig, ProviderHTTPError, endpoint, headers, list_models, generate, read_response, ollama_native
from .schedule import ScheduleService, ScheduleError, ScheduleChanged
from .schedule_stream import schedule_response
from .event_logs import exception_details
from .memory_store import StaleMemory


class Bot:
    def __init__(self, store, client=None, inference_lock=None, providers=None, memes=None):
        self.store = store
        self.providers = providers
        if providers is not None:
            self.store.events.secret_resolver = lambda catalog=providers: [catalog.get(pid).api_key for pid in catalog.ids()]
        self.client = client or httpx.AsyncClient(timeout=15, trust_env=False)
        self.task = None
        self.jobs = set()
        self.pending = set()
        self.tasks_by_key = {}
        self.last = {}
        self.state = 'stopped'
        self.session = None
        self.seq = None
        self.token = ''
        self.expires = 0
        self.token_lock = asyncio.Lock()
        self.image_lock = asyncio.Lock()
        self.inference_lock = inference_lock or asyncio.Lock()
        self.schedule = ScheduleService(store, self)
        from .memory import MemoryService
        self.memory = MemoryService(store, self)
        from .reset_command import ResetCommands
        self.reset = ResetCommands(self)
        from .inbox import ConversationInbox
        self.inbox = ConversationInbox(self)
        from .meme_service import MemeService
        self.memes = MemeService(self, memes)
        from .napcat import NapCatTransport
        self.napcat = NapCatTransport(self)
        self.command_slots = asyncio.Semaphore(4)

    @property
    def stats(self):
        return self.store.stats()

    async def request(self, method, url, **kwargs):
        if urlsplit(url).path.endswith(('/api/chat', '/api/generate')):
            # Share model inference capacity across bots; QQ heartbeats remain independent.
            async with self.inference_lock:
                res = await self.client.request(method, url, **kwargs)
        else:
            res = await self.client.request(method, url, **kwargs)
        return read_response(res)

    async def access_token(self):
        async with self.token_lock:
            if self.token and time.time() < self.expires - 60:
                return self.token
            c = self.store.load().qq
            data = await self.request('POST', 'https://api.bot.qq.com/app/getAppAccessToken', json={'appId': c.app_id, 'clientSecret': c.secret})
            if not data.get('access_token') or not data.get('expires_in'):
                raise ValueError('QQ 访问凭证响应不完整')
            self.token = data['access_token']
            self.expires = time.time() + float(data['expires_in'])
            return self.token

    async def api(self, method, path, before_send=None, **kwargs):
        if self.store.load().transport=='napcat':
            match=re.fullmatch(r'/v2/(users|groups)/([0-9]+)/messages',path)
            if method=='POST' and match and kwargs.get('json',{}).get('msg_type')==0:
                return await self.napcat.send_text(match[1]=='groups',match[2],kwargs['json'].get('content',''),before_send)
            raise ValueError('此操作仅适用于 QQ 官方机器人')
        token = await self.access_token()
        if before_send is not None and not before_send():
            raise ScheduleChanged('日程已变化，已跳过基于旧安排生成的回复')
        return await self.request(method, f'https://api.sgroup.qq.com{path}', headers={'Authorization': f'QQBot {token}'}, **kwargs)

    async def models(self, settings=None):
        c = settings or self.store.load().ollama
        return await list_models(self.request, self.provider(c))

    def provider(self, selection):
        if selection.provider_id:
            if self.providers is None:
                raise ValueError('模型供应商未加载')
            return self.providers.get(selection.provider_id)
        return ProviderConfig(base_url=selection.url)

    async def generate(self, selection, messages, max_tokens, *, stream=False, thinking=None):
        provider = self.provider(selection)
        context = self.store.events.current.get()
        started = time.monotonic()
        with self.store.events.context(trace_id=context.get('trace_id') or uuid.uuid4().hex):
            detail = {'model': selection.model, 'provider': provider.name or provider.type,
                      'provider_type': provider.type, 'request_url': provider.base_url,
                      'stage': context.get('stage', 'chat')}
            self.store.log('info', '开始调用模型', category='model', event='model.started', details=detail)
            try:
                result = await self._generate(selection, messages, max_tokens, stream=stream, thinking=thinking)
                inputs = result.get('prompt_eval_count', 0)
                outputs = result.get('eval_count', 0)
                inputs = inputs if type(inputs) is int and inputs >= 0 else 0
                outputs = outputs if type(outputs) is int and outputs >= 0 else 0
                self.store.log('info', '模型调用完成', category='model', event='model.completed',
                    details={**detail, 'duration_ms': round((time.monotonic()-started)*1000),
                             'input_tokens': inputs, 'output_tokens': outputs, 'total_tokens': inputs+outputs})
                return result
            except asyncio.CancelledError:
                self.store.log('debug', '模型调用已取消', category='model', event='model.canceled',
                               details={**detail, 'duration_ms': round((time.monotonic()-started)*1000)})
                raise
            except Exception as error:
                self.store.log('error', '模型调用失败', category='model', event='model.failed',
                    details={**detail, **exception_details(error), 'duration_ms': round((time.monotonic()-started)*1000)})
                raise

    async def _generate(self, selection, messages, max_tokens, *, stream=False, thinking=None):
        provider = self.provider(selection)
        if stream and provider.type == 'ollama':
            async def request(method, url, **kwargs):
                return await schedule_response(self.client, method, url, **kwargs)
            async with self.inference_lock:
                return await generate(request, provider, selection, messages, max_tokens, thinking=thinking)
        if provider.type == 'ollama' and not ollama_native(provider):
            async with self.inference_lock:
                return await generate(self.request, provider, selection, messages, max_tokens, thinking=thinking)
        return await generate(self.request, provider, selection, messages, max_tokens, thinking=thinking)

    async def start(self):
        if self.task and not self.task.done():
            return
        c = self.store.load()
        if c.transport=='qq_official' and (not c.qq.app_id or not c.qq.secret):
            raise ValueError('请先填写并保存 QQ AppID 和 AppSecret')
        if c.transport=='napcat' and (not c.napcat.ws_url or not c.napcat.self_id):
            raise ValueError('请先保存外部 NapCat 地址和登录 QQ 号')
        if not c.qq.private_reply and not c.qq.group_reply:
            raise ValueError('请至少启用一种回复场景')
        if not c.ollama.model:
            raise ValueError('请先选择并保存模型')
        provider = self.provider(c.ollama)
        self.state = 'connecting'
        try:
            try:
                models = await self.models()
            except ProviderHTTPError as error:
                if provider.type == 'ollama' or error.status not in (404, 405, 501):
                    raise
                models = None
            if provider.type == 'ollama' and c.ollama.model not in (models or []):
                raise ValueError('Ollama 中未找到所选模型，请先下载模型')
            if ollama_native(provider):
                self.store.log('info', '正在预热模型，首次启动可能需要数分钟')
                await self.request('POST', endpoint(provider, 'generate'), headers=headers(provider), timeout=300, json={
                    'model': c.ollama.model, 'prompt': '', 'stream': False, 'keep_alive': -1,
                    'options': {'num_ctx': CONTEXT_WINDOW},
                })
        except BaseException:
            self.state = 'stopped'
            raise
        if c.transport=='napcat':
            try:await self.napcat.start()
            except BaseException:
                self.state='stopped';raise
            self.state='connected'
            self.task=asyncio.create_task(self.napcat.run())
            return
        try:
            gateway = await self.api('GET', '/gateway')
        except BaseException:
            self.state = 'stopped'
            raise
        if not gateway.get('url', '').startswith('wss://'):
            self.state = 'stopped'
            raise ValueError('QQ 网关地址无效')
        self.state = 'connecting'
        self.task = asyncio.create_task(self.run())
        self.store.log('info', '机器人已启动，正在连接 QQ 官方网关')

    async def stop(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        await self.inbox.stop()
        await self.napcat.close()
        jobs = list(self.jobs)
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        self.reset.confirmations.clear()
        self.tasks_by_key.clear()
        self.task = None
        self.state = 'stopped'
        self.session = None
        self.seq = None

    async def heartbeat(self, ws, interval):
        self.ack = True
        while True:
            await asyncio.sleep(interval)
            if not self.ack:
                await ws.close()
                return
            self.ack = False
            await ws.send(json.dumps({'op': 1, 'd': self.seq}))

    async def run(self):
        retries = 0
        try:
            while True:
                heartbeat = None
                try:
                    gateway = await self.api('GET', '/gateway')
                    token = await self.access_token()
                    async with connect(gateway['url'], ping_interval=None, open_timeout=15, max_size=2**20) as ws:
                        self.state = 'connecting'
                        ready = False
                        while True:
                            raw = await asyncio.wait_for(ws.recv(), timeout=120 if ready else 20)
                            p = json.loads(raw)
                            if p.get('s') is not None:
                                self.seq = p['s']
                            op, d = p.get('op'), p.get('d')
                            if op == 10:
                                interval = float(d['heartbeat_interval']) / 1000
                                if interval < 1:
                                    raise ValueError('网关心跳周期无效')
                                if heartbeat:
                                    heartbeat.cancel()
                                    await asyncio.gather(heartbeat, return_exceptions=True)
                                heartbeat = asyncio.create_task(self.heartbeat(ws, interval))
                                auth = {'token': f'QQBot {token}'}
                                if self.session:
                                    auth.update(session_id=self.session, seq=self.seq)
                                else:
                                    auth.update(intents=1 << 25, shard=[0, 1], properties={})
                                await ws.send(json.dumps({'op': 6 if self.session else 2, 'd': auth}))
                            elif op == 11:
                                self.ack = True
                            elif op == 1:
                                await ws.send(json.dumps({'op': 1, 'd': self.seq}))
                            elif op in (7, 9):
                                if op == 9:
                                    self.session, self.seq = None, None
                                break
                            elif op == 0:
                                if p.get('t') in ('READY', 'RESUMED'):
                                    if p['t'] == 'READY':
                                        self.session = d['session_id']
                                    self.state = 'connected'
                                    ready = True
                                    self.inbox.start()
                                    retries = 0
                                    self.store.log('info', 'QQ 官方 WebSocket 已连接', category='qq', event='qq.connected', details={'state': 'connected'})
                                elif ready:
                                    await self.receive(p)
                except ConnectionClosed as e:
                    code = e.rcvd.code if e.rcvd else None
                    if code in (4004, 4010, 4011, 4013, 4014):
                        self.store.log('error', f'QQ 拒绝连接（{code}），请检查凭证和事件权限')
                        self.store.set_enabled(False)
                        return
                    if code in (4006, 4007, 4009):
                        self.session, self.seq = None, None
                except (httpx.HTTPError, WebSocketException, ValueError, KeyError, TypeError, asyncio.TimeoutError, OSError):
                    self.store.log('warn', 'QQ 网关连接失败，请检查网络、凭证和机器人状态')
                finally:
                    if heartbeat:
                        heartbeat.cancel()
                        await asyncio.gather(heartbeat, return_exceptions=True)
                self.state = 'reconnecting'
                delay = min(60, 2 ** min(retries + 1, 6))
                retries += 1
                self.store.log('warn', f'连接中断，{delay} 秒后重试', category='qq', event='qq.reconnecting', details={'retry_in': delay, 'attempt': retries, 'state': 'reconnecting'})
                await asyncio.sleep(delay)
        finally:
            self.state = 'stopped'

    def capture_incoming(self, payload, config=None):
        config = config or self.store.load()
        kind, data = payload.get('t'), payload.get('d', {})
        if kind not in ('C2C_MESSAGE_CREATE', 'GROUP_AT_MESSAGE_CREATE'):
            return
        author = data.get('author', {})
        if author.get('bot'):
            return
        sender = author.get('user_openid') or author.get('member_openid') or author.get('id')
        target = data.get('group_openid') if kind == 'GROUP_AT_MESSAGE_CREATE' else sender
        content = (data.get('content') or '').strip()
        attachments = image_attachments(data)
        if not sender or not target or not data.get('id') or len(content) > 12000 or (not content and not attachments):
            return
        at = time.time()
        if data.get('timestamp'):
            try:
                timestamp = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
                at = timestamp.replace(tzinfo=timezone.utc).timestamp() if timestamp.tzinfo is None else timestamp.timestamp()
            except (ValueError, TypeError, AttributeError, OverflowError):
                pass
        name = author.get('username') or author.get('nickname') or ''
        name = name.strip()[:80] if isinstance(name, str) else ''
        self.store.chat.record(config.account_id, 'group' if kind == 'GROUP_AT_MESSAGE_CREATE' else 'user', target,
                               'user', content, f'in:{config.account_id}:{target}:{data["id"]}',
                               sender_id=sender, sender_name=name, attachment_count=len(attachments),
                               at=at, source='incoming', status='received')

    @staticmethod
    def message_text(data):
        return re.sub(r'<@!?\d+>', '', data.get('content') or '').strip()

    def is_command(self, text):
        return (self.reset.action(text) is not None or text in ('/查看日程', '/重置日程', '/查看记忆')
                or text.startswith('/记住') or text.startswith('/忘记'))

    async def receive(self, payload):
        c = self.store.load()
        self.capture_incoming(payload, c)
        kind, data = payload.get('t'), payload.get('d', {})
        if kind not in ('C2C_MESSAGE_CREATE', 'GROUP_AT_MESSAGE_CREATE') or data.get('author', {}).get('bot'):
            return
        group = kind == 'GROUP_AT_MESSAGE_CREATE'
        if not (c.qq.group_reply if group else c.qq.private_reply):
            return
        author = data.get('author', {})
        user = author.get('user_openid') or author.get('member_openid') or author.get('id')
        target = data.get('group_openid') if group else user
        text = self.message_text(data)
        if not user or not target or not data.get('id') or len(text) > 12000 or not (text or image_attachments(data)):
            return
        owner = self.store.scopes.ensure(c.account_id, 'group' if group else 'user', target, user,
                                         author.get('username') or author.get('nickname') or '')
        source = self.store.db.execute('SELECT * FROM chat_messages WHERE event_key=?', (f'in:{c.account_id}:{target}:{data["id"]}',)).fetchone()
        if not source or source['id'] <= owner['source_floor']:
            return
        if self.is_command(text):
            async def command():
                async with self.command_slots:
                    await self.handle(payload)
            task = asyncio.create_task(command())
            self.jobs.add(task)
            task.add_done_callback(self.jobs.discard)
            return task
        accepted = self.inbox.enqueue(payload, owner, source)
        if accepted and not group:
            self.store.remember_contact(c.account_id, user, time.time(), data['id'])

    async def handle(self, payload, *, batch=None):
        key = None
        claimed = False
        images_requested = False
        log_token = None
        log_started = time.monotonic()
        try:
            c = self.store.load()
            if batch is None:
                self.capture_incoming(payload, c)
            kind, d = payload.get('t'), payload.get('d', {})
            group = kind == 'GROUP_AT_MESSAGE_CREATE'
            if kind not in ('C2C_MESSAGE_CREATE', 'GROUP_AT_MESSAGE_CREATE'):
                return
            if not (c.qq.group_reply if group else c.qq.private_reply) or d.get('author', {}).get('bot'):
                return
            author = d.get('author', {})
            user = author.get('user_openid') or author.get('member_openid') or author.get('id')
            target = d.get('group_openid') if group else user
            text = re.sub(r'<@!?\d+>', '', d.get('content') or '').strip()
            attachments = image_attachments(d)
            if not target or not user or not d.get('id') or (not text and not attachments) or len(text) > 12000:
                return
            if batch is None and not group and not self.store.db.execute('SELECT 1 FROM seen WHERE id=?', (f'{target}:{d["id"]}',)).fetchone():
                self.store.remember_contact(c.account_id, user, time.time(), d['id'])
            key = f'{"group" if group else "user"}:{target}:{user}'
            owner = self.store.scopes.ensure(c.account_id, 'group' if group else 'user', target, user,
                                             author.get('username') or author.get('nickname') or '')
            sid = owner['id']
            incoming = self.store.db.execute('SELECT id FROM chat_messages WHERE event_key=?',
                (f'in:{c.account_id}:{target}:{d["id"]}',)).fetchone()
            log_token = self.store.events.push(trace_id=batch['id'] if batch else uuid.uuid4().hex, scope_id=sid, app_id=c.account_id,
                incoming_id=incoming['id'] if incoming else None, message_id=d['id'], kind=owner['kind'],
                target=target, user_id=user, user_name=owner['label'], image_count=len(attachments), stage='chat',
                incoming_ids=batch['ids'] if batch else None, batch_count=len(batch['ids']) if batch else 1, batch_id=batch['id'] if batch else None)
            day = self.schedule.for_scope(sid)
            if batch and (batch['scope_id'] != sid or not self.inbox.live(batch)):
                return
            if batch is None and incoming and incoming['id'] <= owner['source_floor']:
                return
            reset_action = self.reset.action(text)
            if reset_action is not None:
                if self.schedule_reply_expired(d, command='重置') or not self.store.claim(f'{target}:{d["id"]}'):
                    return
                await self.reset.handle(reset_action, sid, key, c, d, group, target)
                return
            schedule_command = text in ('/查看日程', '/重置日程')
            memory_command = text == '/查看记忆' or text.startswith('/记住') or text.startswith('/忘记')
            if schedule_command or memory_command:
                if not self.store.claim(f'{target}:{d["id"]}'):
                    return
                if schedule_command:
                    await self.schedule_command(text, c, d, group, target, day)
                elif not self.schedule_reply_expired(d):
                    response = self.memory.command(sid, text, incoming['id'])
                    await day.sync_commitments()
                    await self.send_schedule_text(response, c, d, group, target, source='memory')
                return
            if key in self.pending or (batch is None and time.time() - self.last.get(key, 0) < c.rules.cooldown):
                return
            if batch is None and not self.store.claim(f'{target}:{d["id"]}'):
                return
            self.pending.add(key)
            self.tasks_by_key[key] = asyncio.current_task()
            claimed = True
            if batch:
                self.store.log('info', f'合并 {len(batch["ids"])} 条用户消息，开始回复', category='message', event='message.batch_started')
            self.store.log('info', '开始处理群消息' if group else '开始处理单聊消息', category='message', event='message.received')
            images_requested = bool(attachments)
            user_message = {'role': 'user', 'content': text}
            if attachments:
                provider = self.provider(c.ollama)
                if not provider.vision:
                    raise ImageMessageError('当前模型不支持看图，请在配置平台选择支持视觉的模型。')
                if ollama_native(provider):
                    try:
                        info = await self.request('POST', endpoint(provider, 'show'), headers=headers(provider),
                                                  timeout=10, json={'model': c.ollama.model})
                    except (ValueError, httpx.HTTPError):
                        raise ImageMessageError('暂时无法连接图片识别模型，请稍后再试。') from None
                    if 'vision' not in info.get('capabilities', []):
                        raise ImageMessageError('当前模型不支持看图，请在配置平台选择支持视觉的模型。')
                async with self.image_lock:
                    images, notes = await load_images(self.client, attachments)
                user_message['content'] = text or '请看看这些图片或表情包，结合当前对话自然回复。'
                if notes:
                    user_message['content'] += '\n' + '\n'.join(notes)
                user_message['images'] = images
            schedule_context = await day.context()
            schedule_stamp = day.stamp()
            dialogue_instruction = day.dialogue.instruction()
            memory_context = await self.memory.context(sid, text or '图片对话中的相关信息')
            memory_stamp = self.memory.stamp(sid)
            old = self.store.history(key, c.rules.rounds)
            meme_query = '\n'.join([*(m.get('content','') for m in old[-4:]), text])
            meme_candidates = await self.memes.candidates(sid, meme_query)
            if (not day.matches(schedule_stamp) or not self.memory.matches(sid,memory_stamp)
                    or batch is not None and not self.inbox.live(batch)):
                raise ScheduleChanged('对话状态已变化，已停止基于旧上下文的生成')
            meme_instruction = self.memes.instruction(meme_candidates, bool(dialogue_instruction))
            qzone = getattr(self, 'qzone', None)
            qzone_context = qzone.chat_context(sid) if qzone else ''
            messages = [{'role': 'system', 'content': c.rules.prompt + memory_context + schedule_context + qzone_context + dialogue_instruction + meme_instruction}, *old, user_message]
            try:
                answer = await self.generate(c.ollama, messages, max(2048, c.ollama.max_tokens) if dialogue_instruction or meme_instruction else c.ollama.max_tokens, thinking=self.provider(c.ollama).chat_thinking)
            except (ValueError, httpx.HTTPError):
                if attachments:
                    raise ImageMessageError('图片识别失败或超时，请稍后重试或发送较小的图片。') from None
                raise
            # 模型已经消耗的 Token 在 QQ 发送失败或回复超时的情况下也应计入用量。
            self.store.record_usage(answer)
            if not day.matches(schedule_stamp) or not self.memory.matches(sid, memory_stamp):
                raise ScheduleChanged('日程已变化，已跳过基于旧安排生成的回复')
            if qzone and qzone.chat_context(sid) != qzone_context:
                raise ScheduleChanged('空间动态或 Owner 已变化，已跳过基于旧动态生成的回复')
            content = (answer.get('message', {}).get('content') or '').strip()
            update, prepared, meme = None, None, None
            meme_fallback = False
            if dialogue_instruction or meme_instruction:
                try:
                    if meme_instruction:
                        from .meme_service import decode_reply
                        meme_fallback = self.memes.needs_choice(content, meme_candidates)
                        content, update, meme = decode_reply(content, meme_candidates)
                        if not meme_fallback:
                            self.store.log('info','主回复已选中表情包' if meme else '主回复选择本轮不发表情包',category='model',event='meme.selected' if meme else 'meme.selection_skipped',details={'reason':'inline_choice' if meme else 'model_declined','count':int(bool(meme))})
                        if update is not None and not dialogue_instruction:
                            update = None
                    else:
                        content, update = day.dialogue.decode(content)
                    prepared = day.dialogue.prepare(update)
                except (ScheduleError, ValueError):
                    content = '这次回复没整理好，请再说一下。' if meme_instruction else '这次安排还没改成功，请再说一下具体时间和要做的事。'
                    update, prepared = None, None
                    meme = None
                    meme_fallback = False
                    self.store.log('warn', '模型返回的对话日程调整无效，已保留原安排')
            content = content[:c.rules.max_length]
            if not content:
                raise ValueError('模型没有返回回答正文')
            # 统一保守地在五分钟以内回复，避免模型推理或补发事件超时。
            if d.get('timestamp'):
                try:
                    ts = datetime.fromisoformat(d['timestamp'].replace('Z', '+00:00'))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if time.time() - ts.timestamp() > 240:
                        self.store.log('warn', '消息已超过处理时限，已跳过回复')
                        return
                except (ValueError, TypeError):
                    pass
            history_text = text
            if attachments:
                history_text = f'{text}\n[用户发送了 {len(attachments)} 张图片或表情包，原图仅供当轮识别。]'.strip()
            from .reply_delivery import ReplyDelivery
            delivery = ReplyDelivery(self, c, d, group, target, user, sid, key, day, schedule_stamp, memory_stamp, old, history_text, batch=batch)
            receipt = await delivery.send(content, prepared, update, meme=meme, meme_candidates=meme_candidates if meme_fallback else None)
            schedule_stamp = delivery.schedule_stamp
            if not isinstance(receipt, dict) or not receipt.get('id'):
                self.store.log('warn', 'QQ 未确认回复送达，未保存回复与记忆')
                return
            if day.matches(schedule_stamp) and self.memory.matches(sid, memory_stamp):
                self.store.save_history(key, [*old, {'role': 'user', 'content': history_text}, {'role': 'assistant', 'content': content + delivery.meme_context}], c.rules.rounds)
            if self.memory.matches(sid, memory_stamp):
                await day.dialogue.semantic.observe(old, history_text, '\n\n'.join(delivery.confirmed),
                    {'kind': 'group' if group else 'user', 'target': target, 'sender_id': user, 'message_id': d['id']},
                    schedule_stamp, memory_stamp)
                schedule_stamp = day.stamp()
            if self.memory.matches(sid, memory_stamp):
                sources = [*(batch['ids'] if batch else [incoming['id']] if incoming else []), *delivery.source_ids]
                self.memory.enqueue(sid, f'reply:{c.account_id}:{target}:{d["id"]}', sources)
            if self.memory.matches(sid, memory_stamp):
                self.last[key] = time.time()
            if len(self.last) > 500:
                self.last.pop(next(iter(self.last)))
            self.store.log('info', f'{"群聊" if group else "单聊"}{"图片回复" if attachments else "回复"}已发送',
                category='message', event='message.sent', details={'duration_ms': round((time.monotonic()-log_started)*1000), 'sent_message_id': receipt['id']})
            return True
        except (ScheduleChanged, StaleMemory) as error:
            self.store.log('warn', str(error))
        except ImageMessageError as e:
            self.store.record_result('errors', f'回复失败：{e}', category='message', event='message.image_failed', details=exception_details(e))
            if claimed:
                try:
                    if batch is not None and not self.inbox.mark_sending(batch):
                        return
                    path = 'groups' if group else 'users'
                    notice = await self.api('POST', f'/v2/{path}/{quote(target, safe="")}/messages',
                                   before_send=(lambda: self.inbox.live(batch)) if batch else None,
                                   json={'msg_type': 0, 'content': str(e), 'msg_id': d['id'], 'msg_seq': 1})
                    if not isinstance(notice, dict) or not notice.get('id'):
                        self.store.log('warn', 'QQ 未确认图片提示送达')
                        return
                    self.store.chat.record(c.account_id, 'group' if group else 'user', target, 'assistant', str(e),
                                           f'reply:{c.account_id}:{target}:{d["id"]}', at=time.time(), source='image_notice')
                    self.last[key] = time.time()
                    if len(self.last) > 500:
                        self.last.pop(next(iter(self.last)))
                    self.store.record_result('sent', f'{"群聊" if group else "单聊"}图片处理提示已发送')
                    return True
                except Exception:
                    self.store.log('warn', '图片处理提示发送失败')
        except asyncio.CancelledError:
            raise
        except Exception as e:
            detail = str(e) if isinstance(e, ValueError) else '图片识别超时或服务异常' if images_requested else '网络或服务异常'
            self.store.record_result('errors', f'回复失败：{detail}', category='message', event='message.failed', details={**exception_details(e), 'duration_ms': round((time.monotonic()-log_started)*1000)})
        finally:
            if claimed and self.tasks_by_key.get(key) is asyncio.current_task():
                self.tasks_by_key.pop(key, None)
                self.pending.discard(key)
                self.inbox.wakeup.set()
            if log_token is not None:
                self.store.events.reset(log_token)

    async def schedule_command(self, text, config, data, group, target, day=None):
        day = day or self.schedule
        if self.schedule_reply_expired(data):
            return
        sequence = 1
        if text == '/重置日程' and config.schedule.enabled and not day.lock.locked():
            await self.send_schedule_text('正在重新生成今天的日程，可能需要几分钟。成功后新安排立即生效，发送 /查看日程 可查看结果。',
                                          config, data, group, target, sequence)
            sequence += 1
        try:
            if text == '/查看日程' and day.lock.locked() and not day.saved(config):
                raise ScheduleError('当日日程正在生成中，请稍后发送 /查看日程 查看结果')
            plan = await day.ensure(force=text == '/重置日程')
            content = ('当日日程已重置，新安排已生效。发送 /查看日程 查看完整安排。'
                       if text == '/重置日程' else day.format(plan))
        except ScheduleError as error:
            content = str(error)
        if self.schedule_reply_expired(data):
            return
        await self.send_schedule_text(content, config, data, group, target, sequence)

    def schedule_reply_expired(self, data, command='日程'):
        if data.get('timestamp'):
            try:
                timestamp = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                if time.time() - timestamp.timestamp() > 240:
                    self.store.log('warn', f'{command}指令已超过回复时限，请重新发送指令')
                    return True
            except (ValueError, TypeError):
                pass
        return False

    async def send_schedule_text(self, content, config, data, group, target, first_sequence=1, source='schedule'):
        path = 'groups' if group else 'users'
        # Bounded plan fields keep the complete display within four QQ replies.
        chunks = [content[index:index + 1600] for index in range(0, len(content), 1600)]
        if len(chunks) > 4:
            raise ValueError('日程显示内容过长，请在网页查看完整日程')
        for sequence, chunk in enumerate(chunks, first_sequence):
            await self.api('POST', f'/v2/{path}/{quote(target, safe="")}/messages', json={
                'msg_type': 0, 'content': chunk, 'msg_id': data['id'], 'msg_seq': sequence})
            self.store.chat.record(config.account_id, 'group' if group else 'user', target, 'assistant', chunk,
                f'{source}:{config.account_id}:{target}:{data["id"]}:{sequence}', at=time.time(), source=source)
            self.store.record_result('sent', '日程指令回复已发送')
