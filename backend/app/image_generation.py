"""Single-image, reference-aware adapters and receipt-confirmed QQ delivery.

Contracts: developers.openai.com/api/docs/guides/image-generation and
www.volcengine.com/docs/82379/1541523. Request base64 output from both vendors;
never follow a model-supplied download URL or silently drop character references.
"""
import asyncio
import base64
import binascii
import hashlib
import io
import json
import re
import time
import uuid
import warnings
from urllib.parse import quote

import httpx
from PIL import Image, ImageOps

from .message_quotes import receipt_metadata
from .providers import ProviderHTTPError, endpoint, headers
from .schedule import ScheduleChanged

MAX_REFERENCE = 6 * 1024 * 1024
MAX_IMAGE = 10 * 1024 * 1024
MAX_RESPONSE = 18 * 1024 * 1024
SLOTS = {'front': '正面', 'side': '侧面', 'back': '背面', 'sheet': '三视图合图'}


class ImageGenerationError(ValueError):
    pass


def image_request(text, imperative=True):
    """Recognize an explicit current request, not quotes, capabilities or history."""
    text = text.strip()
    if re.search(r'(?:不用画了|别画了|不要画了|取消(?:画图|生图|生成)|停止(?:画图|生图|生成))', text):
        return None
    if re.match(r'^/(?:画图|生图)(?:\s|$)', text):
        return re.sub(r'^/(?:画图|生图)\s*', '', text).strip()
    if not imperative or not text or len(text) > 4000:
        return None
    # A quotation/question about the feature is not permission to spend money.
    if re.search(r'[“”‘’「」『』\'"`]|(?:什么是|什么意思|怎么(?:用|配置|接入)|如何(?:配置|接入)|能不能|能否|会不会|支持|教程|API|接口)', text, re.I):
        return None
    if re.search(r'(?:不要|不用|别|不想|禁止|取消|停止).{0,16}(?:画|图|自拍|照片|image|draw)|(?:don.t|do not|no need).{0,20}(?:draw|generate|image)', text, re.I):
        return None
    requested = re.search(
        r'(?:请|帮我|给我|替我|为我|麻烦|来|想要|想看).{0,16}(?:画(?:一|个|张|幅|出|下)|绘制|生成.{0,10}(?:图|照片|自拍)|(?:发|拍|来).{0,8}(?:自拍|照片|画像|图))'
        r'|^(?:画(?:一|个|张|幅)|绘制|生成.{0,80}(?:图|照片)|发(?:一|个|张).{0,8}自拍)'
        r'|\b(?:draw|generate|create)\b.{0,45}\b(?:image|picture|photo|portrait|illustration)\b', text, re.I)
    return text if requested else None


def checked_picture(raw, *, reference=False):
    """Decode once, bound pixels, strip metadata and normalize to a QQ-safe JPEG."""
    if not raw or len(raw) > (MAX_REFERENCE if reference else MAX_IMAGE):
        raise ImageGenerationError('参考图不能超过 6 MB' if reference else '生成图片为空或超过 10 MB')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=['PNG', 'JPEG', 'WEBP']) as source:
                if source.width * source.height > 25_000_000 or source.width < 32 or source.height < 32 or getattr(source, 'n_frames', 1) != 1:
                    raise ValueError
                image = ImageOps.exif_transpose(source).convert('RGBA')
                background = Image.new('RGB', image.size, 'white')
                background.paste(image, mask=image.getchannel('A'))
                background.thumbnail((2048, 2048) if reference else (4096, 4096))
                output = io.BytesIO()
                background.save(output, 'JPEG', quality=92, optimize=True)
                result = output.getvalue()
                if len(result) > MAX_IMAGE: raise ValueError
                return result, background.width, background.height
    except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageGenerationError('图片格式无效；请使用静态 PNG、JPEG 或 WebP，尺寸至少 32×32 且不超过 2500 万像素') from None


async def generate_image(client, provider, model, prompt, references=(), *, aspect='square', timeout=150):
    if provider.type not in ('openai_image', 'volcengine_image') or provider.purpose != 'image':
        raise ImageGenerationError('请选择 OpenAI 或火山引擎的图片生成供应商')
    if not model.strip() or not prompt.strip() or len(prompt) > 12000 or len(references) > 3:
        raise ImageGenerationError('生图模型、提示词或参考图数量无效')
    if not provider.api_key:
        raise ImageGenerationError('请先为生图供应商配置 API Key')
    if aspect not in ('square', 'portrait', 'landscape'):
        raise ImageGenerationError('图片比例无效')
    operation = 'images/generations'
    kwargs = {}
    if provider.type == 'openai_image':
        size = {'square': '1024x1024', 'portrait': '1024x1536', 'landscape': '1536x1024'}[aspect]
        body = dict(model=model, prompt=prompt, n=1, size=size)
        if references:
            operation = 'images/edits'
            kwargs = {'data': {k: str(v) for k, v in body.items()},
                      'files': [('image[]', (f'reference-{i+1}.jpg', ref, 'image/jpeg')) for i, ref in enumerate(references)]}
        else: kwargs = {'json': body}
    else:
        size = {'square': '2048x2048', 'portrait': '1440x2560', 'landscape': '2560x1440'}[aspect]
        body = dict(model=model, prompt=prompt, size=size, response_format='b64_json', watermark=True)
        if references: body['image'] = ['data:image/jpeg;base64,' + base64.b64encode(ref).decode() for ref in references]
        kwargs = {'json': body}
    try:
        # No implicit retry. A timeout may still have incurred a provider charge.
        async with asyncio.timeout(timeout):
            async with client.stream('POST', endpoint(provider, operation), headers=headers(provider),
                                     timeout=timeout, follow_redirects=False, **kwargs) as response:
                if not response.is_success: raise ProviderHTTPError(response.status_code)
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE: raise ImageGenerationError('生图响应过大，已停止接收，不会自动重试')
            result = json.loads(raw)
            data = result.get('data') if isinstance(result, dict) else None
            if result.get('error') or not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
                raise ImageGenerationError('生图服务未返回单张图片，可能受到内容限制；请检查模型能力与额度')
            encoded = data[0].get('b64_json')
            if not isinstance(encoded, str) or not encoded or len(encoded) > MAX_IMAGE * 4 // 3 + 4:
                raise ImageGenerationError('生图服务未返回有效的 Base64 图片；本功能不下载外部链接，请检查模型兼容性')
            image = base64.b64decode(encoded, validate=True)
            return (await asyncio.to_thread(checked_picture, image))[0]
    except ProviderHTTPError as error:
        raise ImageGenerationError(str(error)) from None
    except (httpx.TimeoutException, TimeoutError):
        raise ImageGenerationError('生图等待超时，服务商可能已计费；不会自动重试，请稍后再决定是否重新请求') from None
    except httpx.HTTPError:
        raise ImageGenerationError('生图网络请求失败，结果待核对；不会自动重试，请检查供应商连接') from None
    except (json.JSONDecodeError, binascii.Error, TypeError, AttributeError):
        raise ImageGenerationError('生图响应格式无效，请检查模型是否支持 Images API 和 Base64 输出') from None


class ImageGenerationService:
    def __init__(self, bot):
        self.bot, self.store = bot, bot.store
        self.lock = asyncio.Lock()
        self.store.db.executescript('''
            CREATE TABLE IF NOT EXISTS image_references (
                id TEXT PRIMARY KEY, app_id TEXT NOT NULL, slot TEXT NOT NULL,
                data BLOB NOT NULL, digest TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
                UNIQUE(app_id,slot));
            CREATE TABLE IF NOT EXISTS image_generation_jobs (
                id TEXT PRIMARY KEY, app_id TEXT NOT NULL, scope_id TEXT NOT NULL, event_key TEXT NOT NULL,
                created REAL NOT NULL, status TEXT NOT NULL, model TEXT NOT NULL,
                UNIQUE(app_id,event_key));
            CREATE INDEX IF NOT EXISTS image_jobs_quota ON image_generation_jobs(app_id,created,scope_id);
            CREATE TABLE IF NOT EXISTS image_generation_sources (
                app_id TEXT NOT NULL, source_id INTEGER NOT NULL, job_id TEXT NOT NULL,
                PRIMARY KEY(app_id,source_id));
            UPDATE image_generation_jobs SET status='unknown' WHERE status IN ('reserved','generated','sending');
        ''')

    def references(self, account=None, *, data=False):
        account = self.store.load().account_id if account is None else account
        rows = self.store.db.execute('SELECT * FROM image_references WHERE app_id=? ORDER BY CASE slot WHEN \'sheet\' THEN 0 WHEN \'front\' THEN 1 WHEN \'side\' THEN 2 ELSE 3 END', (account,)).fetchall()
        return [{k: r[k] for k in ('id', 'slot', 'digest', 'width', 'height', *(['data'] if data else []))} for r in rows]

    def reference_complete(self, account=None):
        slots = {r['slot'] for r in self.references(account)}
        return 'sheet' in slots or {'front', 'side', 'back'} <= slots

    def add_reference(self, slot, picture):
        if slot not in SLOTS: raise ImageGenerationError('请选择正面、侧面、背面或三视图合图')
        raw, width, height = picture
        account = self.store.load().account_id
        if not account: raise ImageGenerationError('请先保存 QQ 接入账号，再上传角色参考图')
        current = self.references(account)
        if any((r['slot'] == 'sheet') != (slot == 'sheet') for r in current):
            raise ImageGenerationError('三视图合图与三张独立视图二选一；请先删除另一种形式的参考图')
        rid = uuid.uuid4().hex
        with self.store.db:
            self.store.db.execute('DELETE FROM image_references WHERE app_id=? AND slot=?', (account, slot))
            self.store.db.execute('INSERT INTO image_references VALUES (?,?,?,?,?,?,?)',
                (rid, account, slot, raw, hashlib.sha256(raw).hexdigest(), width, height))
        return self.references(account)

    def image(self, rid):
        row = self.store.db.execute('SELECT data FROM image_references WHERE app_id=? AND id=?', (self.store.load().account_id, rid)).fetchone()
        if not row: raise ImageGenerationError('当前机器人账号中不存在此参考图')
        return row['data']

    def remove_reference(self, rid):
        with self.store.db:
            cursor = self.store.db.execute('DELETE FROM image_references WHERE app_id=? AND id=?', (self.store.load().account_id, rid))
            if not cursor.rowcount: raise ImageGenerationError('当前机器人账号中不存在此参考图')

    def stamp(self):
        c = self.store.load()
        p = self.bot.providers.get(c.image_generation.provider_id) if c.image_generation.provider_id and self.bot.providers else None
        return hashlib.sha256(json.dumps([c.account_id, c.transport, c.image_generation.model_dump(),
            p.model_dump(exclude={'name', 'default_model'}) if p else None, self.references()], sort_keys=True).encode()).hexdigest()

    def reserve(self, config, sid, event_key, source_ids=()):
        now = time.time()
        if self.store.db.execute('SELECT 1 FROM image_generation_jobs WHERE app_id=? AND event_key=?', (config.account_id,event_key)).fetchone():
            return None
        # A recovered inbox batch gets a new batch ID and can absorb newer messages.
        # Deduplicate by immutable archive sources, never by that transient batch ID.
        if any(self.store.db.execute('SELECT 1 FROM image_generation_sources WHERE app_id=? AND source_id=?',
                (config.account_id,mid)).fetchone() for mid in source_ids):
            return None
        rows = self.store.db.execute('''SELECT j.scope_id,j.created,s.sender_id FROM image_generation_jobs j
            JOIN user_scopes s ON s.id=j.scope_id WHERE j.app_id=? AND j.created>?''', (config.account_id, now-86400)).fetchall()
        sender = self.store.scopes.get(sid)['sender_id']
        own = [r for r in rows if r['sender_id'] == sender]
        if len(rows) >= config.image_generation.daily_limit or len(own) >= config.image_generation.user_daily_limit:
            raise ImageGenerationError('图片创作已达到过去 24 小时的调用上限，请稍后再试')
        if own and now - max(r['created'] for r in own) < config.image_generation.cooldown_seconds:
            raise ImageGenerationError('图片创作正在冷却，请稍等一会儿再请求')
        jid = uuid.uuid4().hex
        with self.store.db:
            cursor = self.store.db.execute('INSERT OR IGNORE INTO image_generation_jobs VALUES (?,?,?,?,?,?,?)',
                (jid, config.account_id, sid, event_key, now, 'reserved', config.image_generation.model))
            if cursor.rowcount:
                self.store.db.executemany('INSERT INTO image_generation_sources VALUES (?,?,?)',
                    [(config.account_id,mid,jid) for mid in source_ids])
        return jid if cursor.rowcount else None

    def status(self, jid, value):
        with self.store.db: self.store.db.execute('UPDATE image_generation_jobs SET status=? WHERE id=?', (value, jid))

    async def resolve_request(self, text, config, data, group, sid, key):
        from .image_conversation import ImageIntent, classify
        explicit=re.match(r'^/(?:画图|生图)(?:\s|$)',text.strip())
        if explicit:
            prompt=image_request(text,False)
            return ImageIntent(action='generate',prompt=prompt) if prompt else (ImageIntent(action='clarify',clarification='想画什么样的画面呀？') if prompt=='' else None)
        c=config.image_generation
        if not c.enabled or not c.imperative_trigger or (group and c.scope=='private') or not text.strip() or len(text)>4000 or text.lstrip().startswith('/'):
            return None
        stamp=self.stamp();scope=self.store.scopes.get(sid);barrier=(scope['epoch'],scope['source_floor'])
        try:
            decision=await classify(self.bot,config,text,key)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.store.log('warn','图片意图识别未完成，仅保留明确的当前生图请求',category='model',event='image_generation.intent_failed')
            fallback=image_request(text,True)
            decision=ImageIntent(action='generate',prompt=fallback) if fallback else ImageIntent(action='none')
        current=self.store.load();latest=self.store.scopes.get(sid)
        if current.account_id!=config.account_id or self.stamp()!=stamp or (latest['epoch'],latest['source_floor'])!=barrier:
            raise ScheduleChanged('图片请求上下文或授权已变化，停止处理')
        self.store.log('info','图片意图识别完成',category='model',event='image_generation.intent',details={'reason':decision.action})
        return None if decision.action=='none' else decision

    async def reply_text(self, text, config, data, group, target, guard, sequence=2, source='image_reply'):
        if not guard():return None
        receipt=await self.bot.api('POST',f'/v2/{"groups" if group else "users"}/{quote(target,safe="")}/messages',
            before_send=guard,json={'msg_type':0,'content':text,'msg_id':data['id'],'msg_seq':sequence})
        if not isinstance(receipt,dict) or not receipt.get('id'):return None
        self.store.chat.record(config.account_id,'group' if group else 'user',target,'assistant',text,
            f'{source}:{config.account_id}:{target}:{data["id"]}:{sequence}',at=time.time(),source=source,
            status='sent' if guard() else 'sent_stale',reply_to=f'in:{config.account_id}:{target}:{data["id"]}',**receipt_metadata(receipt))
        self.store.record_result('sent','图片对话回复已确认发送',category='message',event='image_generation.reply_sent')
        return receipt

    async def clarify(self, text, config, data, group, target, sid, key, batch):
        scope=self.store.scopes.get(sid);barrier=(scope['epoch'],scope['source_floor']);stamp=self.stamp()
        def guard():
            latest=self.store.scopes.get(sid)
            return (self.store.load().account_id==config.account_id and self.stamp()==stamp and (latest['epoch'],latest['source_floor'])==barrier
                and (batch is None or self.bot.inbox.live(batch)) and not self.bot.schedule_reply_expired(data,command='图片'))
        receipt=await self.reply_text(text,config,data,group,target,guard,sequence=1,source='image_clarify')
        if receipt and guard():
            old=self.store.history(key,config.rules.rounds)
            self.store.save_history(key,[*old,{'role':'user','content':self.bot.message_text(data)},{'role':'assistant','content':text}],config.rules.rounds)
        return True

    async def handle(self, prompt, config, data, group, target, user, sid, key, batch):
        owner = self.store.scopes.get(sid)
        epoch, floor = owner['epoch'], owner['source_floor']
        stamp = self.stamp()
        memory_stamp = self.bot.memory.stamp(sid)
        def guard():
            try:
                live_config = self.store.load()
                latest = self.store.scopes.get(sid)
                return ((live_config.account_id, live_config.transport, live_config.image_generation) ==
                        (config.account_id, config.transport, config.image_generation)
                    and self.stamp() == stamp and (latest['epoch'], latest['source_floor']) == (epoch, floor)
                    and self.bot.memory.matches(sid, memory_stamp)
                    and (batch is None or self.bot.inbox.live(batch))
                    and not self.bot.schedule_reply_expired(data, command='画图'))
            except ValueError: return False
        def mark_sending():
            return guard() and (batch is None or self.bot.inbox.mark_sending(batch))
        async def notice(text):
            if mark_sending():
                await self.bot.send_schedule_text(text, config, data, group, target, first_sequence=3, source='image_notice', guard=guard)
        jid = None
        sending = False
        image_confirmed = False
        try:
            c = config.image_generation
            if not c.enabled: raise ImageGenerationError('当前机器人尚未开启图片创作，请先在管理页面配置生图模型、基础提示词和角色三视图')
            if group and c.scope == 'private': raise ImageGenerationError('当前图片创作仅在私聊中开启，请私聊请求画图')
            if not prompt: raise ImageGenerationError('请在 /画图 后描述画面，例如：/画图 穿白色连衣裙，在海边拍一张照片')
            if len(prompt) > 4000: raise ImageGenerationError('画面要求请控制在 4000 字以内')
            if c.require_reference and not self.reference_complete():
                raise ImageGenerationError('角色三视图尚未齐全，请先上传正面、侧面、背面三张图，或一张包含三个视角的合图')
            if self.lock.locked(): raise ImageGenerationError('当前机器人正在创作另一张图片，请稍后再试')
            async with self.lock:
                if not guard(): return True
                refs = self.references(data=True)
                p = self.bot.providers.get(c.provider_id) if self.bot.providers else None
                if p is None or p.purpose != 'image': raise ImageGenerationError('图片生成供应商不可用，请检查模型分配')
                if not p.api_key: raise ImageGenerationError('请先为生图供应商配置 API Key')
                source = self.store.db.execute('SELECT id FROM chat_messages WHERE event_key=?', (f'in:{config.account_id}:{target}:{data["id"]}',)).fetchone()
                sources = batch['ids'] if batch else [source['id']] if source else []
                jid = self.reserve(config, sid, f'{sid}:{data["id"]}', sources)
                if not jid: return True
                self.store.log('info', '开始图片创作，固定生成一张，不自动重试', category='model', event='image_generation.started',
                    details={'job_id': jid, 'model': c.model, 'provider_type': p.type, 'reference_count': len(refs)})
                from .image_scene import resolve_scene
                try:
                    prompt=await resolve_scene(self.bot,config,self.bot.conversation_text(data) or prompt,prompt,key,sid,group)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.store.log('warn','图片场景补全未完成，保留用户要求，不猜测日程',category='model',event='image_generation.scene_failed')
                if not guard():
                    self.status(jid,'cancelled');return True
                from .image_constraints import compile_constraints
                original_request=self.bot.conversation_text(data) or prompt
                try:
                    composition=await compile_constraints(self.bot,config,original_request,prompt)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    from .event_logs import exception_details
                    self.store.log('warn','构图约束提炼失败，停止本轮生图，不降级继续生成',category='model',event='image_generation.constraints_failed',details=exception_details(error))
                    raise ImageGenerationError('这次画面的视角和构图要求没有整理完整，我先不画，免得又发错图给你。') from None
                prompt += composition+'\n【用户本轮原话，明确要求优先】\n'+original_request
                if not guard():
                    self.status(jid,'cancelled');return True
                prompt_text = ('基础风格与拍摄要求：\n' + c.base_prompt.strip() + '\n角色固定外貌：\n' + c.character_prompt.strip()
                    + ('\n附图是同一个角色的' + '、'.join(SLOTS[r['slot']] for r in refs) + '。保持同一角色的脸型、发型、发色和身体特征；根据本次要求改变场景与动作。只生成一张最终成片，不要生成三视图拼图。' if refs else '')
                    + '\n本次用户画面要求：\n' + prompt)
                from .image_conversation import acknowledgement
                waiting='等我一下呀。'
                try:
                    waiting=await acknowledgement(self.bot,config,self.bot.conversation_text(data) or prompt,prompt,key,group,data)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.store.log('warn','图片等待回应生成未完成，使用简短等待提示',category='model',event='image_generation.ack_fallback')
                if not guard():
                    self.status(jid,'cancelled');return True
                try:
                    await self.reply_text(waiting,config,data,group,target,guard,sequence=1,source='image_wait')
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.store.log('warn','等待回应未确认，不重试，继续图片创作',category='message',event='image_generation.ack_unknown')
                if not guard():
                    self.status(jid,'cancelled');return True
                image = await generate_image(self.bot.client, p, c.model, prompt_text, [r['data'] for r in refs], aspect=c.aspect, timeout=c.timeout)
                self.status(jid, 'generated')
                if not guard():
                    self.status(jid, 'cancelled'); return True
                from .image_conversation import caption
                user_request=self.bot.conversation_text(data) or prompt
                visual_description=''
                response='图片发给你啦，看看喜不喜欢。'
                try:
                    grounded=await caption(self.bot,config,image,user_request,prompt,key,group,data,sid)
                    if not grounded.requirements_met or grounded.violations:
                        raise ImageGenerationError('这张图的构图没符合你的要求，我先不把错图发给你。不会自动重新生成。')
                    visual_description,response=grounded.visual_description,grounded.reply
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    from .event_logs import exception_details
                    self.store.log('warn','成片核验未通过，停止发送图片',category='model',event='image_generation.caption_failed',details=exception_details(error))
                    if isinstance(error,ImageGenerationError):raise
                    raise ImageGenerationError('这张图还没能确认符合你的要求，我先不发送，避免再发错图。不会自动重新生成。') from None
                if not guard():
                    self.status(jid,'cancelled');return True
                if config.transport == 'napcat':
                    if not mark_sending(): self.status(jid, 'cancelled'); return True
                    sending = True; self.status(jid, 'sending')
                    receipt = await self.bot.napcat.send_picture(group, target, image, before_send=guard)
                else:
                    path = f'/v2/{"groups" if group else "users"}/{quote(target, safe="")}'
                    uploaded = await self.bot.api('POST', path+'/files', before_send=guard, timeout=30,
                        json={'file_type': 1, 'file_data': base64.b64encode(image).decode(), 'srv_send_msg': False})
                    info = uploaded.get('file_info') if isinstance(uploaded, dict) else None
                    if not isinstance(info, str) or not info: raise ImageGenerationError('图片已生成，但 QQ 未确认上传成功；不会自动重新生成')
                    if not mark_sending(): self.status(jid, 'cancelled'); return True
                    sending = True; self.status(jid, 'sending')
                    receipt = await self.bot.api('POST', path+'/messages', before_send=guard,
                        json={'msg_type': 7, 'content': ' ', 'media': {'file_info': info}, 'msg_id': data['id'], 'msg_seq': 2})
                if not isinstance(receipt, dict) or not receipt.get('id'):
                    self.status(jid, 'unknown')
                    self.store.log('warn', 'QQ 未确认生成图片送达，不自动补发', category='message', event='image_generation.receipt_unknown')
                    return True
                self.status(jid, 'sent')
                image_confirmed = True
                current = guard()
                description = '[已发送本轮生成的图片'+('；画面：'+visual_description if visual_description else '；画面细节尚未确认')+']'
                self.store.chat.record(config.account_id, 'group' if group else 'user', target, 'assistant', description,
                    f'reply:{config.account_id}:{target}:{data["id"]}', attachment_count=1, at=time.time(), source='generated_image',
                    status='sent' if current else 'sent_stale', reply_to=f'in:{config.account_id}:{target}:{data["id"]}', **receipt_metadata(receipt))
                if current:
                    old = self.store.history(key, config.rules.rounds)
                    self.store.save_history(key, [*old, {'role': 'user', 'content': user_request}, {'role': 'assistant', 'content': description}], config.rules.rounds)
                    self.bot.last[key] = time.time()
                self.store.record_result('sent', '生成图片已确认发送到 QQ', category='message', event='image_generation.sent', details={'job_id': jid})
                if current:
                    try:
                        reply_receipt=await self.reply_text(response,config,data,group,target,guard,sequence=3)
                        if reply_receipt and guard():
                            history=self.store.history(key,config.rules.rounds)
                            if history and history[-1]['role']=='assistant':
                                history[-1]['content']+='\n'+response
                                self.store.save_history(key,history,config.rules.rounds)
                        elif guard():
                            self.store.log('warn','图片已送达，后续回应回执未确认，不重发图片或文字',category='message',event='image_generation.reply_unknown',details={'job_id':jid})
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        self.store.log('warn','图片已送达，后续回应发送失败，不重发图片',category='message',event='image_generation.reply_failed',details={'job_id':jid})
        except (asyncio.CancelledError, ScheduleChanged):
            if jid: self.status(jid, 'sent' if image_confirmed else 'unknown' if sending else 'cancelled')
            raise
        except Exception as error:
            if jid: self.status(jid, 'sent' if image_confirmed else 'unknown' if sending else 'failed')
            text = str(error) if isinstance(error, ImageGenerationError) else '图片创作或 QQ 上传失败，未自动重试；请检查连接和额度'
            self.store.log('warn', text, category='message', event='image_generation.receipt_unknown' if sending else 'image_generation.failed', details={'job_id': jid})
            if not sending: await notice(text)
        return True
