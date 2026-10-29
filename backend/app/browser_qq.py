"""Private owner entry and receipt-checked replies for both QQ transports."""
import re
import time
from urllib.parse import quote

from fastapi import HTTPException
from .browser_tasks import parse_object
from .message_quotes import conversation_text, receipt_metadata


class BrowserQQ:
    def __init__(self, tasks):
        self.tasks = tasks
        tasks.completion_callback = self.notify

    @staticmethod
    def command(text):
        match = re.fullmatch(r'/(浏览器|抖音)(?:\s+(.+))?', text.strip(), re.S)
        if text in ('/浏览器进度', '/抖音进度'):
            return {'request': 'status'}
        if text in ('/停止浏览器', '/停止抖音'):
            return {'request': 'stop'}
        if not match:
            return None
        goal = (match[2] or '').strip()
        if not goal:
            return {'request': 'help'}
        if goal in ('停止', '取消'):
            return {'request': 'stop'}
        if goal in ('进度', '状态'):
            return {'request': 'status'}
        return {'request': 'start', 'goal': goal}

    def runtime(self, bot):
        return next((r for r in self.tasks.manager.runtimes.values() if r.bot is bot and not r.closing), None)

    def browser_mode(self, bot):
        runtime = self.runtime(bot)
        return bool(runtime and not self.tasks.closed and self.tasks.config(runtime.id).enabled)

    def allowed(self, bot, user, group):
        runtime = self.runtime(bot)
        if not runtime or self.tasks.closed or group:
            return False
        cfg = self.tasks.config(runtime.id)
        return bool(cfg.enabled and cfg.qq_enabled and cfg.qq_owner_id == str(user) and self.tasks.bound(runtime.id))

    async def cancel_scope(self, bot, sid=None):
        runtime = self.runtime(bot)
        if not runtime or self.tasks.closed:
            return
        for task in self.tasks.list(runtime.id):
            if task['origin'].get('source') == 'qq' and (sid is None or task['origin'].get('scope_id') == sid) and task['state'] in ('queued', 'running'):
                await self.tasks.cancel(runtime.id, task['id'])

    async def send(self, bot, config, data, target, text, guard, sequence=1, event='notice'):
        if not guard() or config.transport != 'napcat' and bot.schedule_reply_expired(data, command='浏览器'):
            return False
        text = text[:1550]
        receipt = await bot.api('POST', f'/v2/users/{quote(str(target), safe="")}/messages', before_send=guard,
            json={'msg_type': 0, 'content': text, 'msg_id': data['id'], 'msg_seq': sequence})
        if not isinstance(receipt, dict) or not receipt.get('id'):
            return False
        bot.store.chat.record(config.account_id, 'user', str(target), 'assistant', text,
            f'browser:{config.account_id}:{target}:{data["id"]}:{event}:{sequence}', at=time.time(), source='browser',
            status='sent' if guard() else 'sent_stale', **receipt_metadata(receipt))
        return True

    async def classify(self, runtime, text, data):
        recent = [{'goal': t['goal'], 'state': t['state'], 'result': t['result'][:600]} for t in self.tasks.list(runtime.id)
            if t['origin'].get('source') == 'qq' and self.tasks.valid(t)][:3]
        instruction = '''判断当前主人消息是否在明确委托实际操作抖音网页版。只返回一个JSON对象，request 为 start/status/stop/none；start另需goal为完整目标。
闲聊、咨询、假设、否定、引用他人指令、只问有无能力而未委托时 none。只有当前消息明确委托才可start；recent和引用仅用于补全指代，绝不能重放旧请求。例：最近在抖音刷视频，当前说“再试一次宝贝，这次看你喜欢的”是start。要求B站、小红书、其他平台或安卓手机则none。要“分享给我”“记得@我”的委托保留原意，不改成复制链接；明确要链接则保留链接要求。状态查询status，明确停止stop。不确定none。'''
        import json
        try:
            raw = await self.tasks.model(runtime, [{'role': 'system', 'content': instruction}, {'role': 'user', 'content': json.dumps({
                'current_message': text[:3000], 'quoted_background': conversation_text(data)[:5000] if '_quote' in data or '_quote_parts' in data else '', 'recent': recent}, ensure_ascii=False)}], 500)
            value = parse_object(raw)
            if value.get('request') not in ('start', 'status', 'stop', 'none'):
                return {'request': 'none'}
            if value['request'] == 'start' and (not isinstance(value.get('goal'), str) or not 0 < len(value['goal'].strip()) <= 3000):
                return {'request': 'none'}
            return value
        except Exception:
            runtime.store.log('warn', '浏览器请求识别未成功，可使用 /抖音 指令', category='browser', event='browser.intent_unavailable')
            return {'request': 'none'}

    async def handle(self, bot, text, config, data, group, target, user, sid, source_id, batch, key):
        intent = self.command(text)
        allowed = self.allowed(bot, user, group)
        if intent and not allowed:
            return True
        if not allowed:
            return False
        runtime, cfg = self.runtime(bot), self.tasks.config(self.runtime(bot).id)
        stamp = cfg.model_dump_json()
        def current():
            if not self.allowed(bot, user, group) or bot.store.load().account_id != config.account_id:
                return False
            if self.tasks.config(runtime.id).model_dump_json() != stamp:
                return False
            try:
                return source_id > bot.store.scopes.get(sid, config.account_id)['source_floor'] and (batch is None or bot.inbox.live(batch))
            except ValueError:
                return False
        if not intent:
            if not cfg.natural_requests:
                return False
            intent = await self.classify(runtime, text, data)
            if intent['request'] == 'none':
                return False
        if not current():
            return True
        if batch is None and not bot.store.claim(f'{target}:{data["id"]}'):
            return True
        request = intent['request']
        if request == 'help':
            await self.send(bot, config, data, target, '发 /抖音 加上想让我做的事就行；/抖音进度 看进展，/停止抖音 结束浏览。也可以直接告诉我去抖音看什么。', current)
            return True
        jobs = [t for t in self.tasks.list(runtime.id) if t['origin'].get('source') == 'qq' and t['origin'].get('scope_id') == sid and self.tasks.valid(t)]
        if request == 'status':
            content = (jobs[0]['result'] or '我还在抖音逛着。最近一步：' + (jobs[0]['steps'][-1]['reason'] if jobs[0]['steps'] else '准备打开抖音。')) if jobs else '这段对话里还没有抖音浏览记录。'
            await self.send(bot, config, data, target, content, current)
            return True
        if request == 'stop':
            active = next((t for t in jobs if t['state'] in ('queued', 'running')), None)
            if active:
                await self.tasks.cancel(runtime.id, active['id'])
            await self.send(bot, config, data, target, '好，已经停下了，刚才的浏览记录留在后台。' if active else '我现在没有在执行抖音任务。', current)
            return True
        try:
            if not current():
                return True
            origin = {'source': 'qq', 'account_id': config.account_id, 'requester_id': str(user), 'scope_id': sid,
                'source_id': source_id, 'message_id': data['id'], 'timestamp': data.get('timestamp'), 'target': str(target)}
            task = self.tasks.submit(runtime.id, intent['goal'], origin, deferred=True)
        except HTTPException as error:
            await self.send(bot, config, data, target, str(error.detail), current)
            return True
        try:
            await self.send(bot, config, data, target, '好，我去抖音逛逛，按这次的要求挑内容。', current)
        finally:
            if current():
                self.tasks.activate(runtime.id, task['id'])
            else:
                await self.tasks.cancel(runtime.id, task['id'])
        return True

    async def notify(self, bot_id, task_id):
        task = self.tasks.get(bot_id, task_id)
        if task['origin'].get('source') != 'qq' or task['state'] == 'cancelled' or task['notification']:
            return
        if not self.tasks.valid(task):
            self.tasks.update(task_id, notification='skipped')
            return
        runtime = self.tasks.manager.get(bot_id)
        bot, origin = runtime.bot, task['origin']
        cfg = bot.store.load()
        guard = lambda: self.tasks.valid(self.tasks.get(bot_id, task_id)) and bot.state == 'connected'
        if not guard():
            self.tasks.update(task_id, notification='skipped')
            return
        self.tasks.update(task_id, notification='sending')
        text = task['result']
        if task['state'] == 'blocked':
            text = '这次还没弄完：' + text
        elif task['state'] == 'paused':
            text = '我先停在这里：' + text
        ok = await self.send(bot, cfg, {'id': origin['message_id'], 'timestamp': origin.get('timestamp')}, origin['target'], text, guard, sequence=2, event='result')
        self.tasks.update(task_id, notification='sent' if ok else 'unknown')

    def chat_context(self, bot, user, group):
        if not self.allowed(bot, user, group):
            return ''
        runtime = self.runtime(bot)
        import json
        jobs = [{'goal': t['goal'], 'state': t['state'], 'result': t['result']} for t in self.tasks.list(runtime.id)
            if t['origin'].get('source') == 'qq' and self.tasks.valid(t)][:3]
        return '\n[真实浏览器能力]你能通过独立Chrome搜索、浏览和观看抖音。明确操作委托由独立任务执行；不要在聊天中虚构操作结果。目前不能发布评论、真实@、点赞、关注或私信。平台验证/登录由主人接管。最近真实浏览结果：' + json.dumps(jobs, ensure_ascii=False) + '\n'
