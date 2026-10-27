import asyncio
import hmac
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from .config import Settings, OllamaConfig
from .registry import BotManager, BotRuntime
from .providers import ProviderConfig, ProviderHTTPError, list_models, generate, read_response
from .qq_connect import QQConnect


def create_app(data_dir=None, static_dir=None):
    @asynccontextmanager
    async def lifespan(app):
        password = os.getenv('ADMIN_PASSWORD', '')
        if len(password) < 12:
            raise RuntimeError('ADMIN_PASSWORD 必须设置且至少 12 位')
        app.state.password = password
        app.state.manager = BotManager(data_dir or os.getenv('DATA_DIR', '/data'))
        from .android import AndroidTasks
        app.state.android = AndroidTasks(app.state.manager, app.state.manager.registry.root)
        app.state.manager.android_service = app.state.android
        from .android_qq import AndroidQQ
        app.state.manager.android_qq = AndroidQQ(app.state.android)
        for runtime in app.state.manager.runtimes.values():
            runtime.bot.android = app.state.manager.android_qq
        app.state.qq_connect = QQConnect(app.state.manager)
        app.state.session = secrets.token_urlsafe(48)
        app.state.auth_version = time.time()
        app.state.login_attempts = []
        try:
            yield
        finally:
            await app.state.android.close()
            await app.state.qq_connect.close()
            await app.state.manager.close()

    app = FastAPI(title='HayBot', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def security(request: Request, call_next):
        max_body = 10 * 1024 * 1024 if request.url.path.endswith(('/memes/upload','/qzone/images')) else 131072
        if request.headers.get('content-length', '').isdigit() and int(request.headers['content-length']) > max_body:
            return JSONResponse({'detail': '请求内容过大'}, status_code=413)
        if request.url.path.startswith('/api/'):
            origin = request.headers.get('origin')
            allowed = os.getenv('PUBLIC_ORIGIN') or f'{request.url.scheme}://{request.headers.get("host", "")}'
            if origin and origin != allowed:
                return JSONResponse({'detail': '请求来源不允许'}, status_code=403)
            if request.url.path not in ('/api/login', '/api/health'):
                cookie = request.cookies.get('hay_session', '')
                if not hmac.compare_digest(cookie, app.state.session):
                    return JSONResponse({'detail': '请先登录'}, status_code=401)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        detail = '配置格式错误，请检查字段范围和服务地址'
        proactive_errors = {
            'daily_limit': '每日消息上限必须为非负整数，0 表示不限次数',
            'cooldown_minutes': '冷却时间必须为 0–1440 分钟（最长 24 小时）',
            'idle_min_minutes': '搭话最短间隔必须为 5–1440 分钟（最长 24 小时）',
            'idle_max_minutes': '搭话最长间隔必须为 5–1440 分钟（最长 24 小时）',
            'unanswered_limit': '连续未回应暂停次数必须为 1–20 次',
            'active_start': '活跃时段开始时间请使用 HH:MM 格式',
            'active_end': '活跃时段结束时间请使用 HH:MM 格式',
        }
        # Only return predefined messages; validation inputs may contain credentials.
        for error in exc.errors():
            location = error['loc']
            if location[:2] == ('body', 'schedule'):
                detail = '日程配置无效：请填写生活设定（最多 6000 字），时区使用 Asia/Shanghai 等有效名称'
                break
            if location[:2] != ('body', 'proactive'):
                continue
            if len(location) == 3 and location[2] in proactive_errors:
                detail = proactive_errors[location[2]]
                break
            if str(error.get('ctx', {}).get('error', '')) == '搭话间隔上限不能小于下限':
                detail = '搭话最长间隔不能小于最短间隔'
                break
        return JSONResponse({'detail': detail}, status_code=422)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=400)

    @app.exception_handler(httpx.HTTPError)
    async def network_error(request, exc):
        return JSONResponse({'detail': '连接失败或超时，请检查服务地址、网络和服务状态'}, status_code=502)

    class Login(BaseModel):
        password: str = Field(max_length=300)

    @app.post('/api/login')
    async def login(body: Login, response: Response):
        now = time.time()
        app.state.login_attempts = [t for t in app.state.login_attempts if now - t < 60]
        if len(app.state.login_attempts) >= 10:
            raise HTTPException(429, '尝试过于频繁，请一分钟后重试')
        if not hmac.compare_digest(body.password.encode(), app.state.password.encode()):
            app.state.login_attempts.append(now)
            raise HTTPException(401, '管理密码不正确')
        response.set_cookie('hay_session', app.state.session, httponly=True, samesite='strict', secure=os.getenv('COOKIE_SECURE') == 'true', max_age=86400)
        return {'ok': True}

    @app.post('/api/logout')
    async def logout(response: Response):
        app.state.session = secrets.token_urlsafe(48)
        await app.state.qq_connect.cancel_all()
        response.delete_cookie('hay_session')
        return {'ok': True}

    @app.get('/api/health')
    async def health():
        return {'status': 'ok'}

    async def scoped_runtime(bot_id: str = 'default'):
        runtime = app.state.manager.get(bot_id)
        task = asyncio.current_task()
        runtime.requests.add(task)
        try:
            yield runtime
        finally:
            runtime.requests.discard(task)

    class BotName(BaseModel):
        model_config = {'extra': 'forbid'}
        name: str = Field(min_length=1, max_length=40)

        @field_validator('name')
        @classmethod
        def trim_name(cls, value):
            value = value.strip()
            if not value:
                raise ValueError('机器人名称不能为空')
            return value

    @app.get('/api/bots')
    async def bots(include_archived: bool = False):
        return {'bots': app.state.manager.summaries(include_archived)}

    def public_provider(provider_id):
        manager = app.state.manager
        return {**manager.providers.public(provider_id), 'used_by': [
            {'id': p['id'], 'name': p['name'], 'archived': bool(p['archived']), 'state': p['state']}
            for p in manager.provider_references(provider_id)]}

    @app.get('/api/providers')
    async def providers():
        return {'providers': [public_provider(pid) for pid in app.state.manager.providers.ids()]}

    @app.post('/api/providers', status_code=201)
    async def create_provider(body: ProviderConfig):
        return public_provider(await app.state.manager.save_provider(body))

    async def provider_request(method, url, **kwargs):
        async with httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False) as client:
            if urlsplit(url).path.endswith(('/api/chat', '/api/generate')):
                async with app.state.manager.inference_lock:
                    response = await client.request(method, url, **kwargs)
            else:
                response = await client.request(method, url, **kwargs)
            return read_response(response)

    @app.post('/api/providers/test')
    async def test_provider(body: ProviderConfig, provider_id: str = ''):
        provider = app.state.manager.providers.prepare(body, provider_id)
        if provider.purpose != 'chat':
            return {'models': [], 'models_supported': False, 'message': '请填写实际模型名称，使用「模型调用测试」验证嵌入或重排接口'}
        try:
            models = await list_models(provider_request, provider)
            return {'models': models, 'models_supported': True, 'message': f'连接成功，发现 {len(models)} 个模型'}
        except ProviderHTTPError as error:
            if provider.type == 'ollama' or error.status not in (404, 405, 501):
                raise
            return {'models': [], 'models_supported': False, 'message': '此地址不提供模型列表，请手动填写模型，并使用生成测试验证连接'}

    class GenerationProbe(ProviderConfig):
        model: str = Field(min_length=1, max_length=200)
        temperature: float = Field(default=0.7, ge=0, le=2)
        timeout: int = Field(default=120, ge=5, le=600)
        max_tokens: int = Field(default=1024, ge=128, le=32768)

    @app.post('/api/providers/test-generation')
    async def test_generation(body: GenerationProbe, provider_id: str = ''):
        provider = app.state.manager.providers.prepare(ProviderConfig.model_validate(body.model_dump(exclude={'model', 'temperature', 'timeout', 'max_tokens'})), provider_id)
        if provider.purpose != 'chat':
            from .retrieval import embed, rerank
            if provider.purpose == 'embedding':
                result = await embed(provider_request, provider, body.model, ['用户喜欢喝茶', '喜欢饮茶'], 'document', body.timeout)
                return {'content': f'嵌入测试成功：返回 {len(result["vectors"])} 条向量，每条 {len(result["vectors"][0])} 维',
                        'dimensions': len(result['vectors'][0]), 'input_tokens': result['input_tokens'], 'output_tokens': 0}
            result = await rerank(provider_request, provider, body.model, '喜欢喝茶', ['用户喜欢喝茶', '用户正在修自行车'], 2, body.timeout)
            return {'content': '重排测试成功', 'results': result['results'], 'input_tokens': result['input_tokens'], 'output_tokens': 0}
        if provider.type == 'anthropic' and provider.anthropic_version == '2023-06-01' and provider.send_temperature and body.temperature > 1:
            raise ValueError('Anthropic 温度范围为 0–1')
        selection = OllamaConfig(model=body.model, temperature=body.temperature, timeout=body.timeout)
        result = await generate(provider_request, provider, selection, [
            {'role': 'system', 'content': '你是连接测试助手，只输出一句简短中文。'},
            {'role': 'user', 'content': '请回复：连接正常。'}], body.max_tokens, thinking=provider.chat_thinking if provider.type == 'ollama' else None)
        content = result['message']['content'].strip()
        if not content:
            raise ValueError('服务未返回文本回答，请检查模型、协议和输出 Token 限制')
        return {'content': content[:500], 'input_tokens': result.get('prompt_eval_count', 0), 'output_tokens': result.get('eval_count', 0)}

    @app.put('/api/providers/{provider_id}')
    async def update_provider(provider_id: str, body: ProviderConfig):
        return public_provider(await app.state.manager.save_provider(body, provider_id))

    @app.delete('/api/providers/{provider_id}')
    async def delete_provider(provider_id: str):
        await app.state.manager.delete_provider(provider_id)
        return {'ok': True}

    @app.post('/api/bots', status_code=201)
    async def create_bot(body: BotName):
        return await app.state.manager.create(body.name)

    @app.patch('/api/bots/{bot_id}')
    async def rename_bot(bot_id: str, body: BotName):
        async with app.state.manager.catalog_lock:
            app.state.manager.registry.rename(bot_id, body.name)
        return app.state.manager.registry.get(bot_id)

    @app.post('/api/bots/{bot_id}/archive')
    async def archive_bot(bot_id: str):
        await app.state.manager.archive(bot_id)
        return {'ok': True}

    @app.post('/api/bots/{bot_id}/restore')
    async def restore_bot(bot_id: str):
        await app.state.manager.restore(bot_id)
        return {'ok': True}

    class DeleteBot(BaseModel):
        model_config = {'extra': 'forbid'}
        name: str = Field(min_length=1, max_length=40)

    class QRComplete(BaseModel):
        model_config = {'extra': 'forbid'}
        name: str = Field(default='', max_length=40)
        replace_existing: bool = False

        @field_validator('name')
        @classmethod
        def clean_name(cls, value):
            return value.strip()

    @app.post('/api/qq/qr', status_code=201)
    async def start_qr():
        owner = app.state.session
        return await app.state.qq_connect.start(owner, still_valid=lambda: secrets.compare_digest(owner, app.state.session))

    @app.get('/api/qq/qr/{session_id}')
    async def poll_qr(session_id: str):
        service = app.state.qq_connect
        return service.snapshot(service.get(session_id, app.state.session))

    @app.post('/api/qq/qr/{session_id}/complete')
    async def complete_qr(session_id: str, body: QRComplete):
        return await app.state.qq_connect.complete(session_id, app.state.session, body.name, body.replace_existing)

    @app.delete('/api/qq/qr/{session_id}')
    async def cancel_qr(session_id: str):
        await app.state.qq_connect.cancel(session_id, app.state.session)
        return {'ok': True}

    @app.delete('/api/bots/{bot_id}')
    async def delete_bot(bot_id: str, body: DeleteBot):
        await app.state.manager.delete(bot_id, body.name)
        return {'ok': True}

    @app.get('/api/bots/{bot_id}/conversations')
    async def conversations(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                            runtime: BotRuntime = Depends(scoped_runtime)):
        return runtime.store.chat.conversations(runtime.store.load().account_id, limit, offset)

    @app.get('/api/bots/{bot_id}/conversations/{conversation_id}/messages')
    async def chat_messages(conversation_id: str, limit: int = Query(100, ge=1, le=200),
                            before: int | None = Query(None, ge=1), after: int | None = Query(None, ge=1),
                            runtime: BotRuntime = Depends(scoped_runtime)):
        if before is not None and after is not None:
            raise ValueError('不能同时指定向前和向后翻页')
        result = runtime.store.chat.messages(runtime.store.load().account_id, conversation_id, limit, before, after)
        if result is None:
            raise HTTPException(404, '当前机器人中不存在此会话')
        return result

    def public_settings(runtime):
        config = runtime.store.load().model_dump()
        config['qq']['secret_set'] = bool(config['qq'].pop('secret'))
        config['napcat']['token_set']=bool(config['napcat'].pop('token'))
        config['napcat'].pop('clear_token',None)
        return config

    @app.get('/api/settings')
    @app.get('/api/bots/{bot_id}/settings')
    async def settings(runtime: BotRuntime = Depends(scoped_runtime)):
        return public_settings(runtime)

    @app.put('/api/settings')
    @app.put('/api/bots/{bot_id}/settings')
    async def save_settings(c: Settings, runtime: BotRuntime = Depends(scoped_runtime)):
        async with runtime.control_lock, app.state.manager.config_lock:
            if runtime.bot.state != 'stopped':
                raise HTTPException(409, '请先停止当前机器人再保存配置')
            if runtime.bot.schedule.lock.locked() or runtime.bot.memory.busy:
                raise HTTPException(409, '日程正在生成，请等待完成后再保存配置')
            app.state.manager.assert_unique_app_id(c.account_id, runtime.id)
            old = runtime.store.load()
            if not c.ollama.provider_id:
                c.ollama.provider_id = app.state.manager.providers.legacy(c.ollama.url, c.ollama.model)
            provider = app.state.manager.providers.get(c.ollama.provider_id)
            if provider.purpose != 'chat':
                raise ValueError('回复模型必须使用对话供应商')
            for section in (c.memory,c.memes):
                for purpose in ('embedding', 'rerank'):
                    selection = getattr(section, purpose)
                    if selection.provider_id and app.state.manager.providers.get(selection.provider_id).purpose != purpose:
                        raise ValueError('检索模型的供应商用途不匹配')
            c.ollama.url = provider.base_url
            if provider.type == 'anthropic' and provider.anthropic_version == '2023-06-01' and provider.send_temperature and c.ollama.temperature > 1:
                raise ValueError('Anthropic 温度范围为 0–1')
            if not c.qq.secret:
                c.qq.secret = old.qq.secret if c.qq.app_id == old.qq.app_id else ''
            if c.napcat.clear_token:
                c.napcat.token=''
            elif not c.napcat.token and (c.napcat.ws_url,c.napcat.self_id)==(old.napcat.ws_url,old.napcat.self_id):
                c.napcat.token=old.napcat.token
            c.napcat.clear_token=False
            if c.proactive.recipient_id and not runtime.store.contact(c.account_id, c.proactive.recipient_id):
                raise ValueError('主动消息接收者必须是当前机器人的已互动单聊用户')
            if c.proactive.enabled and not c.proactive.recipient_id:
                raise ValueError('请先选择主动消息接收者')
            runtime.store.save(c)
            if c.proactive != old.proactive and c.proactive.recipient_id:
                runtime.store.set_idle_time(c.account_id, c.proactive.recipient_id, 0)
            runtime.bot.token = ''
            display_fields = {'debounce_enabled', 'debounce_seconds', 'debounce_max_wait', 'debounce_max_messages', 'split_enabled', 'split_length', 'split_max_parts', 'split_delay'}
            if c.rules.model_dump(exclude=display_fields) != old.rules.model_dump(exclude=display_fields) or c.ollama != old.ollama or c.account_id != old.account_id or c.schedule != old.schedule or c.memory != old.memory:
                runtime.store.clear_history()
            runtime.store.log('info', '配置已保存')
            return public_settings(runtime)

    @app.get('/api/status')
    @app.get('/api/bots/{bot_id}/status')
    async def status(runtime: BotRuntime = Depends(scoped_runtime)):
        return {'state': runtime.bot.state, 'stats': runtime.bot.stats,
                'start_error': runtime.start_error, 'inbox': runtime.bot.inbox.snapshot(),
                'jobs': len(runtime.bot.jobs) + int(runtime.proactive.busy) + int(runtime.bot.schedule.lock.locked()) + int(runtime.bot.memory.busy),
                'uptime': int(time.time() - runtime.started), 'logs': runtime.store.logs()}

    def selected_schedule(runtime, scope_id):
        if not scope_id:
            raise ValueError('请先选择需要查看日程的用户')
        return runtime.bot.schedule.for_scope(scope_id)

    @app.get('/api/schedule')
    @app.get('/api/bots/{bot_id}/schedule')
    async def schedule_status(scope_id: str = '', runtime: BotRuntime = Depends(scoped_runtime)):
        if not scope_id:
            snapshot = runtime.bot.schedule.snapshot()
            snapshot.update(schedule=None, changes=[], change_count=0, changes_next_before=None, error='', retry_at=None, selection_required=True)
            return snapshot
        return selected_schedule(runtime, scope_id).snapshot()

    @app.get('/api/schedule/changes')
    @app.get('/api/bots/{bot_id}/schedule/changes')
    async def schedule_changes(scope_id: str = '', day: date | None = None, before: int | None = Query(default=None, ge=1),
                               limit: int = Query(default=20, ge=1, le=100),
                               runtime: BotRuntime = Depends(scoped_runtime)):
        return selected_schedule(runtime, scope_id).dialogue.records(day.isoformat() if day else None, before, limit)

    @app.post('/api/schedule/generate')
    @app.post('/api/bots/{bot_id}/schedule/generate')
    async def generate_schedule(scope_id: str = '', runtime: BotRuntime = Depends(scoped_runtime)):
        day = selected_schedule(runtime, scope_id)
        await day.ensure()
        return day.snapshot()

    @app.post('/api/schedule/reset')
    @app.post('/api/bots/{bot_id}/schedule/reset')
    async def reset_schedule(scope_id: str = '', runtime: BotRuntime = Depends(scoped_runtime)):
        day = selected_schedule(runtime, scope_id)
        await day.ensure(force=True)
        return day.snapshot()

    from .memory_api import install as install_memory_routes
    install_memory_routes(app, scoped_runtime)
    from .logs_api import install as install_log_routes
    install_log_routes(app, scoped_runtime)

    class Recipient(BaseModel):
        recipient_id: str = Field(min_length=1, max_length=128)

    class Preview(BaseModel):
        instruction: str = Field(default='自然地关心一下近况，避免重复问候。', min_length=1, max_length=500)

    class Reminder(BaseModel):
        at: datetime
        content: str = Field(min_length=1, max_length=500)

    @app.get('/api/proactive')
    @app.get('/api/bots/{bot_id}/proactive')
    async def proactive_status(runtime: BotRuntime = Depends(scoped_runtime)):
        return runtime.proactive.snapshot()

    @app.post('/api/proactive/preview')
    @app.post('/api/bots/{bot_id}/proactive/preview')
    async def preview_proactive(body: Preview, runtime: BotRuntime = Depends(scoped_runtime)):
        return {'content': await runtime.proactive.preview(body.instruction)}

    @app.post('/api/proactive/test')
    @app.post('/api/bots/{bot_id}/proactive/test')
    async def test_proactive(body: Recipient, runtime: BotRuntime = Depends(scoped_runtime)):
        return await runtime.proactive.test(body.recipient_id)

    @app.post('/api/proactive/reminders')
    @app.post('/api/bots/{bot_id}/proactive/reminders')
    async def add_reminder(body: Reminder, runtime: BotRuntime = Depends(scoped_runtime)):
        config = runtime.store.load()
        recipient = config.proactive.recipient_id
        if not runtime.store.contact(config.account_id, recipient):
            raise ValueError('请先保存单聊接收者')
        if body.at.tzinfo is None:
            raise ValueError('提醒时间必须包含时区')
        at, now = body.at.timestamp(), time.time()
        if not now + 10 <= at <= now + 365 * 86400:
            raise ValueError('请选择至少 10 秒后、一年内的提醒时间')
        if not body.content.strip():
            raise ValueError('提醒内容不能为空')
        count = runtime.store.db.execute("SELECT COUNT(*) FROM proactive_reminders WHERE app_id=? AND status='pending'", (config.account_id,)).fetchone()[0]
        if count >= 50:
            raise ValueError('最多保留 50 条待发送提醒')
        runtime.store.add_reminder(uuid.uuid4().hex, config.account_id, recipient, at, body.content.strip(), now)
        return runtime.proactive.snapshot()

    @app.delete('/api/proactive/reminders/{reminder_id}')
    @app.delete('/api/bots/{bot_id}/proactive/reminders/{reminder_id}')
    async def cancel_reminder(reminder_id: str, runtime: BotRuntime = Depends(scoped_runtime)):
        if not runtime.store.cancel_reminder(runtime.store.load().account_id, reminder_id):
            raise ValueError('提醒不存在或已不处于等待状态')
        return runtime.proactive.snapshot()

    @app.post('/api/ollama/test')
    @app.post('/api/bots/{bot_id}/ollama/test')
    @app.post('/api/bots/{bot_id}/models/test')
    async def test_ollama(c: OllamaConfig, runtime: BotRuntime = Depends(scoped_runtime)):
        try:
            return {'models': await runtime.bot.models(c), 'models_supported': True}
        except ProviderHTTPError as error:
            if runtime.bot.provider(c).type == 'ollama' or error.status not in (404, 405, 501):
                raise
            return {'models': [], 'models_supported': False}

    @app.post('/api/qq/test')
    @app.post('/api/bots/{bot_id}/qq/test')
    async def test_qq(runtime: BotRuntime = Depends(scoped_runtime)):
        config = runtime.store.load()
        if config.transport=='napcat':
            from .napcat import NapCatTransport
            from types import SimpleNamespace
            # A probe never starts event consumption or marks the real runtime connected.
            probe=NapCatTransport(SimpleNamespace(store=runtime.store),receive_events=False)
            try:
                await probe.start()
                return {'message':'NapCat 连接成功，QQ 登录身份已验证；启动机器人后开始接收消息','self_id':config.napcat.self_id}
            finally:await probe.close()
        if not config.qq.app_id or not config.qq.secret:
            raise ValueError('请先保存 QQ 凭证')
        await runtime.bot.api('GET', '/gateway')
        return {'message': 'QQ 凭证有效，网关获取成功；事件权限需启动后验证'}

    @app.post('/api/bot/start')
    @app.post('/api/bots/{bot_id}/start')
    async def start(runtime: BotRuntime = Depends(scoped_runtime)):
        async with runtime.control_lock:
            runtime.start_error = ''
            await runtime.bot.start()
            runtime.store.set_enabled(True)
        return {'ok': True}

    @app.post('/api/bot/stop')
    @app.post('/api/bots/{bot_id}/stop')
    async def stop(runtime: BotRuntime = Depends(scoped_runtime)):
        async with runtime.control_lock:
            runtime.store.set_enabled(False)
            runtime.start_error = ''
            await runtime.bot.stop()
            runtime.store.log('info', '机器人已停止')
        return {'ok': True}

    @app.delete('/api/history')
    @app.delete('/api/bots/{bot_id}/history')
    async def clear_history(runtime: BotRuntime = Depends(scoped_runtime)):
        async with runtime.control_lock:
            if runtime.bot.state != 'stopped':
                raise HTTPException(409, '请先停止当前机器人再清空上下文')
            runtime.store.clear_history()
            runtime.store.log('info', '对话上下文已清空')
        return {'ok': True}

    from .meme_routes import register_meme_routes
    register_meme_routes(app, scoped_runtime)
    from .qzone_routes import register_qzone_routes
    register_qzone_routes(app,scoped_runtime)

    from .android_routes import register_android_routes
    register_android_routes(app, scoped_runtime)
    from .android_live import register_android_live
    register_android_live(app)

    root = Path(static_dir or os.getenv('STATIC_DIR', '/app/static'))
    if (root / 'assets').exists():
        app.mount('/assets', StaticFiles(directory=root / 'assets'), name='assets')

    @app.get('/theme.js')
    async def theme_script():
        if not (root / 'theme.js').exists():
            raise HTTPException(404, '主题脚本不存在')
        return FileResponse(root / 'theme.js', media_type='text/javascript', headers={'Cache-Control': 'no-cache'})

    @app.get('/')
    @app.get('/bots')
    @app.get('/bots/{bot_id}/{page}')
    @app.get('/overview')
    @app.get('/qq')
    @app.get('/ollama')
    @app.get('/providers')
    @app.get('/rules')
    @app.get('/proactive')
    @app.get('/logs')
    @app.get('/chats')
    @app.get('/schedule')
    @app.get('/memory')
    @app.get('/memes')
    @app.get('/android')
    @app.get('/qzone')
    async def index():
        if not (root / 'index.html').exists():
            raise HTTPException(503, '前端尚未构建')
        return FileResponse(root / 'index.html', headers={'Cache-Control': 'no-cache'})

    return app


app = create_app()
