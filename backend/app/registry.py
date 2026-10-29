"""Bot catalog and isolated runtimes. Existing single-bot data stays in place."""
import asyncio
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

from fastapi import HTTPException
from .bot import Bot
from .config import Settings
from .proactive import ProactiveService
from .store import Store
from .providers import ProviderStore
from .memes import MemeCatalog


class BotRegistry:
    def __init__(self, directory):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / 'bots.sqlite3')
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS bots (
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL, archived INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS registry_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        if not self.db.execute("SELECT 1 FROM registry_meta WHERE key='initialized'").fetchone():
            if not self.db.execute('SELECT 1 FROM bots LIMIT 1').fetchone():
                legacy = self.root / 'hayqqbot.sqlite3'
                if legacy.exists():
                    backups = self.root / 'backups'
                    backups.mkdir(exist_ok=True)
                    source = sqlite3.connect(legacy)
                    target = sqlite3.connect(backups / f'before-multibot-{time.time_ns()}.sqlite3')
                    try:
                        source.backup(target)
                    finally:
                        source.close(); target.close()
                with self.db:
                    now = time.time()
                    self.db.execute('INSERT INTO bots VALUES (?,?,?,?,0)', ('default', '默认机器人', now, now))
            with self.db:
                self.db.execute("INSERT INTO registry_meta VALUES ('initialized','1')")

    def list(self, include_archived=False):
        sql = 'SELECT * FROM bots' + ('' if include_archived else ' WHERE archived=0') + ' ORDER BY created,id'
        return [dict(row) for row in self.db.execute(sql)]

    def get(self, bot_id):
        row = self.db.execute('SELECT * FROM bots WHERE id=?', (bot_id,)).fetchone()
        if not row:
            raise HTTPException(404, '机器人不存在')
        return dict(row)

    def directory(self, bot_id):
        self.get(bot_id)
        if bot_id == 'default':
            return self.root
        # IDs are generated here, never names or caller-provided paths.
        if len(bot_id) != 32 or any(c not in '0123456789abcdef' for c in bot_id):
            raise ValueError('机器人标识无效')
        return self.root / 'bots' / bot_id

    def create(self, name):
        bot_id, now = uuid.uuid4().hex, time.time()
        with self.db:
            self.db.execute('INSERT INTO bots VALUES (?,?,?,?,0)', (bot_id, name, now, now))
        return self.get(bot_id)

    def rename(self, bot_id, name):
        self.get(bot_id)
        with self.db:
            self.db.execute('UPDATE bots SET name=?,updated=? WHERE id=?', (name, time.time(), bot_id))

    def archive(self, bot_id, archived):
        self.get(bot_id)
        with self.db:
            self.db.execute('UPDATE bots SET archived=?,updated=? WHERE id=?', (int(archived), time.time(), bot_id))

    def close(self):
        self.db.close()


class BotRuntime:
    def __init__(self, directory, inference_lock, providers=None, memes=None):
        self.store = Store(directory)
        self.bot = Bot(self.store, inference_lock=inference_lock, providers=providers, memes=memes)
        self.proactive = ProactiveService(self.store, self.bot)
        from .qzone import QzoneService
        self.qzone=QzoneService(self.store,self.bot)
        self.control_lock = asyncio.Lock()
        self.tasks = []
        self.requests = set()
        self.closing = False
        self.started = time.time()
        self.start_error = ''
        self.wakeup = asyncio.Event()

    def start_background(self):
        async def restore():
            while True:
                self.wakeup.clear()
                async with self.control_lock:
                    if self.store.enabled() and self.bot.state == 'stopped':
                        try:
                            self.start_error = ''
                            await self.bot.start()
                        except Exception as error:
                            self.start_error = str(error) if isinstance(error, ValueError) else '服务连接失败或超时，请检查 QQ 凭证与模型供应商配置'
                            self.store.log('warn', '自动恢复机器人失败，将在 60 秒后重试；请检查模型与 QQ 配置')
                try:
                    await asyncio.wait_for(self.wakeup.wait(), timeout=60)
                except asyncio.TimeoutError:
                    pass
        self.tasks = [asyncio.create_task(restore()), asyncio.create_task(self.proactive.run()),
                      asyncio.create_task(self.bot.schedule.run()), asyncio.create_task(self.bot.memory.run()),
                      asyncio.create_task(self.qzone.run()),asyncio.create_task(self.bot.diary.run())]

    def request_start(self):
        self.store.set_enabled(True)
        self.start_error = ''
        self.wakeup.set()

    async def close(self):
        self.closing = True
        current = asyncio.current_task()
        tasks = [*self.tasks, *(task for task in self.requests if task is not current)]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.bot.stop()
        await self.qzone.close()
        await self.bot.memes.close()
        await self.bot.client.aclose()
        self.store.close()


class BotManager:
    def __init__(self, directory):
        self.registry = BotRegistry(directory)
        self.providers = ProviderStore(directory)
        self.memes = MemeCatalog(directory)
        # Migrate every existing bot, including archives, before starting workers.
        for profile in self.registry.list(True):
            store = Store(self.registry.directory(profile['id']))
            try:
                config = store.load()
                if not config.ollama.provider_id:
                    config.ollama.provider_id = self.providers.legacy(config.ollama.url, config.ollama.model)
                    store.save(config)
            finally:
                store.close()
        self.runtimes = {}
        self.inference_lock = asyncio.Lock()
        self.config_lock = asyncio.Lock()
        self.catalog_lock = asyncio.Lock()
        for profile in self.registry.list():
            self.attach(profile['id'])

    def attach(self, bot_id):
        runtime = BotRuntime(self.registry.directory(bot_id), self.inference_lock, self.providers, self.memes)
        runtime.id = bot_id
        runtime.bot.android = getattr(self, 'android_qq', None)
        runtime.bot.browser = getattr(self, 'browser_qq', None)
        self.runtimes[bot_id] = runtime
        runtime.store.log('info', '机器人管理服务已就绪')
        runtime.start_background()
        return runtime

    def get(self, bot_id):
        profile = self.registry.get(bot_id)
        if profile['archived']:
            raise HTTPException(404, '机器人已归档，请先在机器人管理中恢复')
        runtime = self.runtimes.get(bot_id)
        if not runtime or runtime.closing:
            raise HTTPException(409, '机器人正在停止或恢复，请稍后重试')
        return runtime

    def assert_unique_app_id(self, app_id, bot_id):
        if not app_id:
            return
        for other_id, runtime in self.runtimes.items():
            if other_id != bot_id and runtime.store.load().account_id == app_id:
                raise ValueError('此 QQ AppID 已被其他机器人使用，请使用不同的官方机器人凭证')

    def summaries(self, include_archived=False):
        result = []
        for profile in self.registry.list(include_archived):
            runtime = self.runtimes.get(profile['id'])
            if runtime:
                config, stats = runtime.store.load(), runtime.store.stats()
                state, enabled = runtime.bot.state, runtime.store.enabled()
            else:
                # Archived data is read only for this request and never starts tasks.
                store = Store(self.registry.directory(profile['id']))
                try:
                    config, stats, enabled = store.load(), store.stats(), False
                finally:
                    store.close()
                state = 'stopped'
            provider = self.providers.get(config.ollama.provider_id) if config.ollama.provider_id else None
            result.append({**profile, 'archived': bool(profile['archived']), 'app_id': config.qq.app_id if config.transport=='qq_official' else config.napcat.self_id, 'transport':config.transport,
                           'provider_id': config.ollama.provider_id, 'provider_name': provider.name if provider else '',
                           'model': config.ollama.model, 'configured': bool(config.qq.app_id and config.qq.secret) if config.transport=='qq_official' else bool(config.napcat.self_id and config.napcat.ws_url),
                           'proactive_enabled': config.proactive.enabled, 'state': state, 'enabled': enabled, 'stats': stats})
        return result

    async def create(self, name):
        async with self.catalog_lock:
            profile = self.registry.create(name)
            store = Store(self.registry.directory(profile['id']))
            try:
                config = Settings()
                config.ollama.provider_id = self.providers.legacy(config.ollama.url, config.ollama.model)
                store.save(config)
                store.set_enabled(False)
            finally:
                store.close()
            self.attach(profile['id'])
            return profile

    async def archive(self, bot_id):
        async with self.catalog_lock:
            runtime = self.get(bot_id)
            tasks = getattr(self, 'browser_tasks', None)
            if tasks:
                await tasks.stop_dm_monitor(bot_id)
                await tasks.cancel_bot(bot_id)
            browser = getattr(self, 'browser_service', None)
            if browser:
                await browser.stop_bot(bot_id)
            android = getattr(self, 'android_service', None)
            if android and not await android.cancel_bot(bot_id):
                raise HTTPException(409, '安卓任务授权撤销未确认，请先在安卓页面人工接管，再归档')
            # Disable persisted auto-recovery before cancelling any in-flight work.
            runtime.store.set_enabled(False)
            self.registry.archive(bot_id, True)
            await runtime.close()
            self.runtimes.pop(bot_id)

    async def restore(self, bot_id):
        async with self.catalog_lock:
            profile = self.registry.get(bot_id)
            if not profile['archived']:
                raise ValueError('机器人尚未归档')
            async with self.config_lock:
                store = Store(self.registry.directory(bot_id))
                try:
                    self.assert_unique_app_id(store.load().account_id, bot_id)
                    store.set_enabled(False)
                finally:
                    store.close()
                self.registry.archive(bot_id, False)
                self.attach(bot_id)

    async def delete(self, bot_id, confirmation):
        async with self.catalog_lock:
            profile = self.registry.get(bot_id)
            if not profile['archived'] or bot_id in self.runtimes:
                raise HTTPException(409, '请先归档机器人，再永久删除')
            if confirmation != profile['name']:
                raise ValueError('请输入完整的机器人名称确认删除')
            directory = self.registry.directory(bot_id)
            if bot_id == 'default':
                # The legacy bot shares its parent with the catalog and other bots.
                # Never remove /data itself, its backups, or the bots subdirectory.
                for filename in ('hayqqbot.sqlite3', 'hayqqbot.sqlite3-wal', 'hayqqbot.sqlite3-shm', 'secret.key'):
                    (directory / filename).unlink(missing_ok=True)
            elif directory.exists():
                shutil.rmtree(directory)
            with self.registry.db:
                self.registry.db.execute('DELETE FROM bots WHERE id=?', (bot_id,))

    async def close(self):
        await asyncio.gather(*(runtime.close() for runtime in self.runtimes.values()))
        self.registry.close()
        self.providers.close()
        self.memes.close()

    def provider_references(self, provider_id):
        references = []
        for profile in self.registry.list(True):
            runtime = self.runtimes.get(profile['id'])
            store = runtime.store if runtime else Store(self.registry.directory(profile['id']))
            try:
                config = store.load()
                android = getattr(self, 'android_service', None)
                android_reference = android and profile['id'] in android.references(provider_id)
                if android_reference or provider_id in (config.ollama.provider_id, config.memory.embedding.provider_id, config.memory.rerank.provider_id,
                                   config.memes.embedding.provider_id,config.memes.rerank.provider_id):
                    references.append({**profile, 'state': runtime.bot.state if runtime else 'stopped',
                                       'busy': bool(android and android.busy(profile['id']) or runtime and (runtime.proactive.busy or runtime.bot.jobs or runtime.bot.schedule.lock.locked() or runtime.bot.diary.lock.locked()
                                                                or getattr(runtime.bot, 'memory', None) and runtime.bot.memory.busy
                                                                or runtime.bot.memes.lock.locked()))})
            finally:
                if not runtime:
                    store.close()
        return references

    def existing_app(self, app_id):
        profiles = sorted(self.registry.list(True), key=lambda p: p['archived'])
        for profile in profiles:
            runtime = self.runtimes.get(profile['id'])
            store = runtime.store if runtime else Store(self.registry.directory(profile['id']))
            try:
                if store.load().account_id == app_id:
                    return profile
            finally:
                if not runtime:
                    store.close()

    async def bind_credentials(self, app_id, secret, name, replace_existing=False, still_valid=lambda: True):
        async with self.catalog_lock:
            existing = self.existing_app(app_id)
            if existing:
                if existing['archived']:
                    raise HTTPException(409, '此机器人已归档，请先在机器人管理中恢复，再扫码更新凭证')
                if not replace_existing:
                    raise HTTPException(409, '此 AppID 已存在，请确认更新现有机器人的凭证')
                runtime = self.get(existing['id'])
                async with runtime.control_lock, self.config_lock:
                    if not still_valid():
                        raise HTTPException(409, '扫码授权已失效，请重新扫码')
                    if runtime.bot.state != 'stopped' or runtime.proactive.busy or runtime.bot.jobs or runtime.bot.schedule.lock.locked():
                        raise HTTPException(409, '请先停止现有机器人并等待处理完成，再更新凭证')
                    config = runtime.store.load()
                    if config.qq.app_id != app_id:
                        raise HTTPException(409, '机器人配置已变化，请重新扫码')
                    config.qq.secret = secret
                    runtime.store.save(config)
                    runtime.bot.token = ''
                    runtime.store.log('info', '已通过 QQ 官方扫码更新机器人凭证')
                return existing
            if replace_existing:
                raise HTTPException(409, '未找到可更新的机器人，请选择添加新机器人')
            async with self.config_lock:
                if not still_valid():
                    raise HTTPException(409, '扫码授权已失效，请重新扫码')
                self.assert_unique_app_id(app_id, '')
                config = Settings()
                config.qq.app_id, config.qq.secret = app_id, secret
                config.ollama.provider_id = self.providers.legacy(config.ollama.url, config.ollama.model)
                profile = self.registry.create(name or f'QQ 机器人 · {app_id}'[:40])
                store = Store(self.registry.directory(profile['id']))
                try:
                    store.save(config)
                    store.set_enabled(False)
                finally:
                    store.close()
                self.attach(profile['id'])
                return profile

    async def save_provider(self, config, provider_id=''):
        async with self.catalog_lock, self.config_lock:
            old = self.providers.get(provider_id) if provider_id else None
            prepared = self.providers.prepare(config, provider_id)
            changed = old and old.model_dump(exclude={'name', 'default_model', 'chat_thinking'}) != prepared.model_dump(exclude={'name', 'default_model', 'chat_thinking'})
            references = self.provider_references(provider_id) if provider_id else []
            if old and old.purpose != prepared.purpose and references:
                raise HTTPException(409, '此供应商仍被机器人引用，不能改变用途；请新建供应商或先解除引用')
            if changed and any(p['state'] != 'stopped' or p['busy'] for p in references):
                raise HTTPException(409, '请先停止使用此供应商的机器人，再修改连接、密钥或协议参数')
            result = self.providers.save(config, provider_id)
            if changed:
                for profile in references:
                    runtime = self.runtimes.get(profile['id'])
                    store = runtime.store if runtime else Store(self.registry.directory(profile['id']))
                    try:
                        store.clear_history()
                    finally:
                        if not runtime:
                            store.close()
            return result

    async def delete_provider(self, provider_id):
        async with self.catalog_lock, self.config_lock:
            self.providers.get(provider_id)
            if self.provider_references(provider_id):
                raise HTTPException(409, '此供应商仍被机器人使用（含已归档机器人），请先为它们切换供应商')
            self.providers.delete(provider_id)
