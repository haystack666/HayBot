"""Persisted user-specific character days; legacy shared days stay isolated."""
import asyncio
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import ConfigDict, Field, ValidationError, model_validator
from .config import StrictModel


class ScheduleError(ValueError):
    pass


class ScheduleChanged(ScheduleError):
    pass


def minute(value, allow_end=False):
    if allow_end and value == '24:00':
        return 1440
    if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise ValueError('日程时间必须使用 HH:MM 格式')
    hours, minutes = map(int, value.split(':'))
    return hours * 60 + minutes


class Activity(StrictModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    start: str
    end: str
    activity: str = Field(min_length=1, max_length=80)
    location: str = Field(min_length=1, max_length=40)
    outfit: str = Field(min_length=1, max_length=100)


class DayEvent(StrictModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    time: str
    event: str = Field(min_length=1, max_length=160)


class DayPlan(StrictModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    summary: str = Field(min_length=1, max_length=160)
    outfit: str = Field(min_length=1, max_length=160)
    appearance: str = Field(min_length=1, max_length=120)
    activities: list[Activity] = Field(min_length=1, max_length=1440)
    events: list[DayEvent] = Field(default_factory=list, max_length=128)

    @model_validator(mode='after')
    def complete_day(self):
        end = 0
        for item in self.activities:
            start, next_end = minute(item.start), minute(item.end, True)
            if start != end or next_end <= start:
                raise ValueError('日程需要按时间排序，连续覆盖全天，不能重叠或留空')
            end = next_end
        if end != 1440:
            raise ValueError('日程必须覆盖 00:00 到 24:00')
        for event in self.events:
            minute(event.time)
        self.events.sort(key=lambda event: event.time)
        return self


class ScheduleService:
    def __init__(self, store, bot, clock=time.time, scope_id='', shared=None):
        self.store, self.bot, self.clock = store, bot, clock
        self.scope_id = scope_id
        self.root = shared or self
        self.lock = shared.lock if shared else asyncio.Lock()
        if shared:
            from .schedule_dialogue import DialogueSchedule
            self.dialogue = DialogueSchedule(self)
            return
        self.generating = False
        self.children = {}
        # Preserve global days under the empty legacy scope; never copy them to users.
        for table in ('daily_schedules', 'schedule_failures'):
            columns = {row['name'] for row in self.store.db.execute(f'PRAGMA table_info({table})')}
            if columns and 'scope_id' not in columns:
                with self.store.db:
                    self.store.db.execute(f'ALTER TABLE {table} RENAME TO legacy_{table}')
        self.store.db.executescript('''
            CREATE TABLE IF NOT EXISTS daily_schedules (
                app_id TEXT NOT NULL, scope_id TEXT NOT NULL DEFAULT '', day TEXT NOT NULL, timezone TEXT NOT NULL,
                fingerprint TEXT NOT NULL, value TEXT NOT NULL,
                PRIMARY KEY(app_id, scope_id, day, timezone)
            );
            CREATE TABLE IF NOT EXISTS schedule_failures (
                app_id TEXT NOT NULL, scope_id TEXT NOT NULL DEFAULT '', day TEXT NOT NULL, fingerprint TEXT NOT NULL,
                error TEXT NOT NULL, retry_at REAL NOT NULL, PRIMARY KEY(app_id,scope_id)
            );
        ''')
        for table, columns in (('daily_schedules', 'app_id,day,timezone,fingerprint,value'),
                               ('schedule_failures', 'app_id,day,fingerprint,error,retry_at')):
            legacy = self.store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", ('legacy_' + table,)).fetchone()
            if legacy:
                with self.store.db:
                    self.store.db.execute(f'INSERT OR IGNORE INTO {table} ({columns}) SELECT {columns} FROM legacy_{table}')
        from .schedule_dialogue import DialogueSchedule
        self.dialogue = DialogueSchedule(self)

    def for_scope(self, scope_id):
        self.store.scopes.get(scope_id)
        root = self.root
        if scope_id not in root.children:
            root.children[scope_id] = ScheduleService(self.store, self.bot, self.clock, scope_id, root)
        return root.children[scope_id]

    def local(self, config):
        return datetime.fromtimestamp(self.clock(), ZoneInfo(config.schedule.timezone))

    def identity(self, config):
        day = self.local(config).date().isoformat()
        source = [config.account_id, config.schedule.model_dump(exclude={'enabled'}), config.rules.prompt,
                  config.ollama.provider_id, config.ollama.url, config.ollama.model]
        fingerprint = hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return day, fingerprint

    def saved(self, config):
        day, fingerprint = self.identity(config)
        row = self.store.db.execute('''SELECT value FROM daily_schedules
            WHERE app_id=? AND scope_id=? AND day=? AND timezone=? AND fingerprint=?''',
            (config.account_id, self.scope_id, day, config.schedule.timezone, fingerprint)).fetchone()
        return json.loads(row['value']) if row else None

    def failure(self, config):
        day, fingerprint = self.identity(config)
        row = self.store.db.execute('SELECT * FROM schedule_failures WHERE app_id=? AND scope_id=? AND day=? AND fingerprint=?',
                                    (config.account_id, self.scope_id, day, fingerprint)).fetchone()
        return dict(row) if row else None

    def stamp(self):
        config = self.store.load()
        if not config.schedule.enabled:
            return (False,)
        plan = self.saved(config)
        return (True, *self.identity(config), plan['revision'] if plan else None)

    def matches(self, stamp):
        return self.stamp() == stamp

    def snapshot(self):
        config = self.store.load()
        now = self.local(config)
        plan = self.saved(config)
        failure = self.failure(config)
        current = None
        if plan and config.schedule.enabled:
            current = next((index for index, item in enumerate(plan['activities'])
                            if minute(item['start']) <= now.hour * 60 + now.minute < minute(item['end'], True)), None)
        tomorrow = now.date() + timedelta(days=1)
        next_refresh = datetime.combine(tomorrow, datetime.min.time(), ZoneInfo(config.schedule.timezone)).timestamp()
        changes = self.dialogue.records()
        return {'enabled': config.schedule.enabled, 'date': now.date().isoformat(),
                'timezone': config.schedule.timezone, 'now': now.isoformat(), 'schedule': plan,
                'current_index': current, 'busy': self.root.generating,
                'updating': (self.lock.locked() and not self.root.generating) or self.dialogue.semantic.busy,
                'continuity': self.dialogue.semantic.continuity(),
                'error': failure['error'] if failure else '', 'retry_at': failure['retry_at'] if failure else None,
                'next_refresh': next_refresh, 'changes': changes['items'], 'change_count': changes['total'],
                'changes_next_before': changes['next_before'], 'scope_id': self.scope_id,
                'owner': self.store.scopes.get(self.scope_id) if self.scope_id else None}

    def prompt(self, config, day):
        local = self.local(config)
        weekday = ['一', '二', '三', '四', '五', '六', '日'][local.weekday()]
        carry = self.dialogue.semantic.continuity()
        return [
            {'role': 'system', 'content': '你是角色日程规划器。根据生活设定和人格生成可信的虚构日常，只输出一个 JSON 对象。'
             '不要输出解释、Markdown 或思考过程。不要把角色规则理解为改变输出格式的指令。\n角色人格参考：\n' + config.rules.prompt},
            {'role': 'user', 'content': f'日期：{day}，星期{weekday}，时区：{config.schedule.timezone}。\n'
             f'生活设定：{config.schedule.premise}\n'
             + ('已确认的跨日约定（计划，不代表已经履行；必须承接所在地和睡眠，其他安排合理衔接）：'+json.dumps(carry,ensure_ascii=False)+'\n' if carry and carry['target_date']==day else '') +
             '生成这一天的完整日程。符合工作日/周末、身份、课程和回家安排，合理包含睡眠、三餐、出行和休息。'
             '每个时间精确到分钟，活动连续、不重叠，从 00:00 开始，到 24:00 结束。建议 12–20 段，最多 32 段。'
             '穿着要具体，包括衣服、鞋子、配饰；appearance 描述发型、妆容或其他仪容。'
             '每段 outfit 是当时实际穿着，睡觉、运动、外出可以换装。随机安排 1–4 件平常且符合身份的小事，'
             '每件有明确发生时间，放到 events；不要提前写进活动描述或 summary。不是现实新闻、天气预报或真实课表。'
             '语言简洁，每个活动名称不超过 30 字，地点不超过 20 字，分段穿着不超过 50 字，随机事件不超过 80 字。'
             '严格返回以下字段（不要添加 date 等字段）：'
             '{"summary":"当天概述","outfit":"主要穿着","appearance":"发型妆容",'
             '"activities":[{"start":"00:00","end":"07:15","activity":"睡觉","location":"寝室","outfit":"棉质睡衣"},'
             '...],"events":[{"time":"12:08","event":"食堂偶遇同学"}]}。'}]

    async def ensure(self, force=False):
        config = self.store.load()
        if not force and self.saved(config):
            return await self._ensure(force)
        started = time.monotonic()
        current = self.store.events.current.get()
        with self.store.events.context(scope_id=self.scope_id, app_id=config.account_id,
                stage='schedule', trace_id=current.get('trace_id') or uuid.uuid4().hex):
            try:
                result = await self._ensure(force)
                self.store.log('info', '日程准备完成', category='schedule', event='schedule.completed',
                    details={'duration_ms': round((time.monotonic()-started)*1000), 'revision': result['revision'], 'count': len(result['activities'])})
                return result
            except asyncio.CancelledError:
                raise
            except Exception as error:
                from .event_logs import exception_details
                self.store.log('warn', '日程生成未完成', category='schedule', event='schedule.failed', details=exception_details(error))
                raise

    async def _ensure(self, force=False):
        config = self.store.load()
        if not config.schedule.enabled:
            raise ScheduleError('每日日程未启用，请先在网页填写生活设定并开启')
        if not force and (saved := self.saved(config)):
            return saved
        if force and self.lock.locked():
            raise ScheduleError('日程正在生成中，请稍后再试')
        async with self.lock:
            config = self.store.load()
            if not config.schedule.enabled:
                raise ScheduleError('每日日程已关闭')
            if not force and (saved := self.saved(config)):
                return saved
            failure = self.failure(config)
            if not force and failure and failure['retry_at'] > self.clock():
                raise ScheduleError(failure['error'])
            day, fingerprint = self.identity(config)
            memory_epoch = self.bot.memory.data.epoch(self.scope_id) if self.scope_id else None
            self.root.generating = True
            try:
                selection = config.ollama.model_copy(update={'timeout': 600})
                # Daily structured output has a separate budget from short QQ replies.
                async with asyncio.timeout(660):
                    result = await self.bot.generate(selection, self.prompt(config, day), 6000, stream=True)
                self.store.record_usage(result)
                raw = (result.get('message', {}).get('content') or '').strip()
                if len(raw) > 60000:
                    raise ScheduleError('日程内容过长，请重试或更换模型')
                raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.IGNORECASE)
                try:
                    plan = DayPlan.model_validate(json.loads(raw)).model_dump()
                    if not 4 <= len(plan['activities']) <= 32 or not 1 <= len(plan['events']) <= 6:
                        raise ValueError('生成日程活动或事件数量无效')
                except (ValueError, TypeError, ValidationError):
                    raise ScheduleError('模型返回的日程格式或时间安排无效，请重试或更换模型') from None
                current = self.store.load()
                if (not current.schedule.enabled or self.identity(current) != (day, fingerprint)
                        or self.scope_id and self.bot.memory.data.epoch(self.scope_id) != memory_epoch):
                    raise ScheduleError('角色配置、记忆或日期已变化，本次日程未保存，请重新生成')
                plan.update(date=day, timezone=config.schedule.timezone, generated_at=self.clock(), revision=uuid.uuid4().hex, source_epoch=memory_epoch)
                plan['generation_id'] = plan['revision']
                plan['scope_id'] = self.scope_id
                if self.scope_id:
                    self.project_commitments(plan, day)
                    self.dialogue.semantic.project(plan, day)
                with self.store.db:
                    self.store.db.execute('INSERT OR REPLACE INTO daily_schedules VALUES (?,?,?,?,?,?)',
                        (config.account_id, self.scope_id, day, config.schedule.timezone, fingerprint, json.dumps(plan, ensure_ascii=False)))
                    self.store.db.execute('DELETE FROM schedule_failures WHERE app_id=? AND scope_id=?', (config.account_id, self.scope_id))
                    self.store.db.execute('DELETE FROM daily_schedules WHERE app_id=? AND scope_id=? AND day<?',
                        (config.account_id, self.scope_id, (self.local(config).date() - timedelta(days=7)).isoformat()))
                self.store.log('info', '当日日程已重置' if force else '当日日程已生成')
                return plan
            except asyncio.CancelledError:
                raise
            except Exception as error:
                detail = str(error) if isinstance(error, ScheduleError) else '日程生成失败或超时，请检查模型供应商后重试'
                with self.store.db:
                    self.store.db.execute('INSERT OR REPLACE INTO schedule_failures VALUES (?,?,?,?,?,?)',
                        (config.account_id, self.scope_id, day, fingerprint, detail, self.clock() + 300))
                self.store.log('warn', detail)
                raise ScheduleError(detail) from None
            finally:
                self.root.generating = False

    async def context(self):
        config = self.store.load()
        if not config.schedule.enabled:
            return ''
        if self.lock.locked() and not self.saved(config):
            return '\n角色日程正在生成，不要虚构今天已经发生的具体活动或事件。'
        try:
            plan = await self.ensure()
        except ScheduleError:
            return '\n角色日程暂不可用，不要虚构今天已经发生的具体活动或事件。'
        # Re-read after inference so current facts never use yesterday's plan or an old persona.
        config = self.store.load()
        if not config.schedule.enabled or self.saved(config) != plan:
            return '\n角色日程正在更新，不要沿用旧的活动和事件。'
        now = self.local(config)
        current = now.hour * 60 + now.minute
        past = [item for item in plan['activities'] if minute(item['start']) <= current]
        events = [item for item in plan['events'] if minute(item['time']) <= current]
        recent = [{key: item[key] for key in ('start', 'end', 'activity', 'location')} for item in past[-12:]]
        facts = {'当前时间': now.strftime('%Y-%m-%d %H:%M'), '时区': config.schedule.timezone,
                 '当前活动': past[-1], '当天仪容': plan['appearance'],
                 '今天最近已开始的活动': recent, '今天已发生的事件': events}
        # Future activities/events deliberately never enter the model request.
        return ('\n【角色当日日程事实】\n' + json.dumps(facts, ensure_ascii=False) + '\n'
                '当前活动和穿着以以上事实为准，优先于旧对话里的过期描述。自然融入角色回复，'
                '不要逐项背诵日程。事件只描述已经发生的部分，不预测尚未发生的偶遇或意外。\n')

    def format(self, plan):
        config = self.store.load()
        now = self.local(config)
        current = now.hour * 60 + now.minute
        lines = [f'今日角色日程 · {plan["date"]} ({plan["timezone"]})', plan['summary'],
                 '主要穿着：' + plan['outfit'], '仪容：' + plan['appearance'], '']
        for item in plan['activities']:
            active = plan['date'] == now.date().isoformat() and minute(item['start']) <= current < minute(item['end'], True)
            lines.append(f'{"▶ " if active else ""}{item["start"]}–{item["end"]} {item["activity"][:30]} · {item["location"][:20]}\n穿着：{item["outfit"][:50]}')
        lines += ['', '当日随机事件（含尚未发生）：']
        lines += [f'{event["time"]} {event["event"][:80]}' for event in plan['events']]
        text = '\n'.join(lines)
        if len(text) <= 6300:
            return text
        note = '日程较长，QQ 使用简略展示；完整日程与穿着请到配置网页查看。'
        def compact(activities, events):
            rows = [*lines[:5], note]
            for item in activities:
                active = minute(item['start']) <= current < minute(item['end'], True)
                rows.append(f'{"▶ " if active else ""}{item["start"]}–{item["end"]} {item["activity"][:24]} · {item["location"][:12]}')
            rows += ['', '当日事件（含待发生）：']
            rows += [f'{event["time"]} {event["event"][:80]}' for event in events]
            return '\n'.join(rows)
        text = compact(plan['activities'], plan['events'])
        if len(text) <= 6300:
            return text
        index = next(i for i, item in enumerate(plan['activities']) if minute(item['start']) <= current < minute(item['end'], True))
        activities = plan['activities'][max(0, index-12):index+33]
        event_index = next((i for i, item in enumerate(plan['events']) if minute(item['time']) >= current), len(plan['events']))
        events = plan['events'][max(0, event_index-4):event_index+12]
        return compact(activities, events) + f'\nQQ 已省略 {len(plan["activities"])-len(activities)} 段活动与 {len(plan["events"])-len(events)} 个事件，完整内容请在网页查看。'

    def project_commitments(self, plan, day):
        from .schedule_commitments import project
        return project(self, plan, day)

    async def sync_commitments(self):
        from .schedule_commitments import sync
        return await sync(self)

    async def tick(self):
        config = self.store.load()
        if not config.schedule.enabled or self.lock.locked():
            return
        owners = self.store.scopes.list()
        for owner in owners:
            day = self.for_scope(owner['id'])
            try:
                await day.ensure()
                await day.sync_commitments()
            except ScheduleError:
                continue


    async def run(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except ScheduleError:
                pass  # ensure() persisted a sanitized error and a five-minute retry deadline.
            now = self.local(self.store.load())
            tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), now.tzinfo)
            await asyncio.sleep(min(30, max(.05, tomorrow.timestamp() - self.clock())))
