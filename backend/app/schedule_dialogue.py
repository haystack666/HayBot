"""Validated dialogue proposals and an atomic, bot-local schedule change journal."""
import copy
from contextlib import nullcontext
import json
import re
import uuid

from pydantic import ConfigDict, Field, ValidationError
from .config import StrictModel
from .schedule import Activity, DayEvent, DayPlan, ScheduleError, ScheduleChanged, minute


class DialogueUpdate(StrictModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=240)
    activities: list[Activity] = Field(default_factory=list, max_length=12)
    events: list[DayEvent] = Field(default_factory=list, max_length=12)
    cancel_events: list[str] = Field(default_factory=list, max_length=24)
    summary: str | None = Field(default=None, min_length=1, max_length=160)
    outfit: str | None = Field(default=None, min_length=1, max_length=160)
    appearance: str | None = Field(default=None, min_length=1, max_length=120)


class DialogueReply(StrictModel):
    reply: str = Field(min_length=1, max_length=12000)
    schedule_update: DialogueUpdate | None = None


def time_text(value):
    return f'{value // 60:02d}:{value % 60:02d}'


class DialogueSchedule:
    def __init__(self, day):
        self.day, self.store = day, day.store
        self.store.db.executescript('''
            CREATE TABLE IF NOT EXISTS schedule_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, app_id TEXT NOT NULL,
                day TEXT NOT NULL, timezone TEXT NOT NULL, generation_id TEXT NOT NULL,
                from_revision TEXT NOT NULL, to_revision TEXT NOT NULL,
                at REAL NOT NULL, reason TEXT NOT NULL, kind TEXT NOT NULL,
                target TEXT NOT NULL, sender_id TEXT NOT NULL, message_id TEXT NOT NULL, diff TEXT NOT NULL,
                UNIQUE(app_id, kind, target, message_id)
            );
            CREATE INDEX IF NOT EXISTS schedule_changes_day ON schedule_changes(app_id,day,id);
        ''')
        columns = {row['name'] for row in self.store.db.execute('PRAGMA table_info(schedule_changes)')}
        with self.store.db:
            if 'scope_id' not in columns:
                self.store.db.execute("ALTER TABLE schedule_changes ADD COLUMN scope_id TEXT NOT NULL DEFAULT ''")
            if 'trigger_message_id' not in columns:
                self.store.db.execute("ALTER TABLE schedule_changes ADD COLUMN trigger_message_id TEXT NOT NULL DEFAULT ''")

        from .schedule_semantic import SemanticSchedule
        self.semantic = SemanticSchedule(day)

    def instruction(self):
        config = self.store.load()
        plan = self.day.saved(config)
        if not config.schedule.enabled or not plan:
            return ''
        now = self.day.local(config)
        current = now.hour * 60 + now.minute
        future = [{key: item[key] for key in ('start', 'end', 'activity', 'location')}
                  for item in plan['activities'] if minute(item['end'], True) > current][:24]
        return ('\n【可协商的生活安排】以下是计划而非已发生的经历：'
                + json.dumps(future, ensure_ascii=False)
                + ('\n已确认的跨日约定（仍是计划，不代表已经发生）：'+json.dumps(self.semantic.continuity(),ensure_ascii=False) if self.semantic.continuity() else '')
                + f'\n当前时间 {now.strftime("%H:%M")}。用户不必报出具体时刻，可以自然邀请、留宿、改变活动或地点。'
                '结合最近双方对话自然回应，明确自己的答应、拒绝或犹豫；一旦已答应或发生，不要再沿用冲突的原安排。'
                '别把未来计划说成已经发生，不必向用户索要精确时间来配合后台。'
                '日程由后台独立同步，不需要在正文附带日程修改JSON。若有表情包输出协议，遵守其传输格式。\n')

    def decode(self, raw):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.IGNORECASE)
        try:
            value = json.loads(text)
        except ValueError:
            if text.startswith('{') and '"reply"' in text:
                raise ScheduleError('对话日程输出不完整，未修改安排') from None
            return raw, None
        if not isinstance(value, dict) or 'reply' not in value:
            return raw, None
        try:
            envelope = DialogueReply.model_validate(value)
        except ValidationError:
            raise ScheduleError('对话日程调整格式无效，未修改安排') from None
        if not envelope.reply.strip():
            raise ScheduleError('模型没有返回回复正文')
        return envelope.reply.strip(), envelope.schedule_update

    def prepare(self, update):
        if update is None:
            return None
        config = self.store.load()
        original = self.day.saved(config)
        if not config.schedule.enabled or not original:
            raise ScheduleChanged('日程已变化，本次对话调整未应用')
        current = self.day.local(config)
        now = current.hour * 60 + current.minute
        result = copy.deepcopy(original)
        patches = []
        for activity in update.activities:
            start, end = minute(activity.start), minute(activity.end, True)
            if end <= now or end <= start:
                raise ScheduleError('对话调整不能修改已经结束的活动')
            patches.append({**activity.model_dump(), 'start': time_text(max(now, start))})
        patches.sort(key=lambda item: item['start'])
        for left, right in zip(patches, patches[1:]):
            if minute(left['end'], True) > minute(right['start']):
                raise ScheduleError('对话调整的活动时间不能重叠')
        before = []
        removed = []
        for patch in patches:
            start, end = minute(patch['start']), minute(patch['end'], True)
            items = []
            for item in result['activities']:
                item_start, item_end = minute(item['start']), minute(item['end'], True)
                if item_end <= start or item_start >= end:
                    items.append(item)
                    continue
                before.append({**item, 'start': time_text(max(start, item_start)), 'end': time_text(min(end, item_end))})
                if item_start < start:
                    items.append({**item, 'end': patch['start']})
                if item_end > end:
                    items.append({**item, 'start': patch['end']})
                if item['activity'] != patch['activity'] or item['location'] != patch['location']:
                    for event in result['events']:
                        at = minute(event['time'])
                        if at > now and max(start, item_start) <= at < min(end, item_end) and event not in removed:
                            removed.append(event)
            items.append(patch)
            result['activities'] = sorted(items, key=lambda item: item['start'])
        for value in update.cancel_events:
            if minute(value) <= now:
                raise ScheduleError('对话调整不能删除已经发生的事件')
            removed += [event for event in result['events'] if event['time'] == value and event not in removed]
        additions = []
        for event in update.events:
            if minute(event.time) < now:
                raise ScheduleError('对话调整不能编造过去发生的事件')
            value = event.model_dump()
            if value not in result['events'] and value not in additions:
                additions.append(value)
        result['events'] = sorted([event for event in result['events'] if event not in removed] + additions, key=lambda event: event['time'])
        for field in ('summary', 'outfit', 'appearance'):
            value = getattr(update, field)
            if value is not None:
                result[field] = value
        fields = ('summary', 'outfit', 'appearance', 'activities', 'events')
        try:
            validated = DayPlan.model_validate({field: result[field] for field in fields}).model_dump()
        except (ValueError, TypeError):
            raise ScheduleError('对话调整后的日程不完整，未修改安排') from None
        if validated == {field: original[field] for field in fields}:
            return None
        result.update(validated, revision=uuid.uuid4().hex, updated_at=self.day.clock())
        result.setdefault('generation_id', original['revision'])
        ranges = sorted([*original.get('dialogue_ranges', []),
                         *[{'start': item['start'], 'end': item['end']} for item in patches]], key=lambda item: item['start'])
        marked = []
        for item in ranges:
            if marked and minute(item['start']) <= minute(marked[-1]['end'], True):
                marked[-1]['end'] = max(marked[-1]['end'], item['end'])
            else:
                marked.append(dict(item))
        result['dialogue_ranges'] = marked
        diff = {'activities_before': before, 'activities_after': patches,
                'events_removed': removed, 'events_added': additions}
        for field in ('summary', 'outfit', 'appearance'):
            if original[field] != result[field]:
                diff[field + '_before'], diff[field + '_after'] = original[field], result[field]
        return {'stamp': self.day.stamp(), 'plan': result, 'reason': update.reason,
                'from_revision': original['revision'], 'diff': diff}

    def apply(self, prepared, source, transaction=True):
        if prepared is None:
            return False
        config = self.store.load()
        identity = (config.account_id, source['kind'], source['target'], source['message_id'])
        if self.store.db.execute('SELECT 1 FROM schedule_changes WHERE app_id=? AND kind=? AND target=? AND message_id=? AND scope_id=?', (*identity, self.day.scope_id)).fetchone():
            return False
        if not self.day.matches(prepared['stamp']):
            raise ScheduleChanged('日程已变化，本次对话调整未应用')
        plan = prepared['plan']
        day, fingerprint = self.day.identity(config)
        with self.store.db if transaction else nullcontext():
            self.store.db.execute('UPDATE daily_schedules SET value=? WHERE app_id=? AND scope_id=? AND day=? AND timezone=? AND fingerprint=?',
                (json.dumps(plan, ensure_ascii=False), config.account_id, self.day.scope_id, day, config.schedule.timezone, fingerprint))
            self.store.db.execute('''INSERT INTO schedule_changes
                (app_id,day,timezone,generation_id,from_revision,to_revision,at,reason,kind,target,sender_id,message_id,diff,scope_id,trigger_message_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (config.account_id, day, config.schedule.timezone, plan['generation_id'], prepared['from_revision'],
                 plan['revision'], self.day.clock(), prepared['reason'], source['kind'], source['target'],
                 source['sender_id'], source['message_id'], json.dumps(prepared['diff'], ensure_ascii=False), self.day.scope_id,
                 source.get('trigger_message_id', source['message_id'])))
        (self.store.log if transaction else self.store._log)('info', '当日日程已根据对话调整')
        return True

    def records(self, day=None, before=None, limit=20):
        config = self.store.load()
        day = day or self.day.local(config).date().isoformat()
        rows = self.store.db.execute('''SELECT c.*, substr(m.content,1,500) AS source_content,
            m.sender_name, m.conversation_id FROM schedule_changes c
            LEFT JOIN chat_messages m ON m.event_key='in:'||c.app_id||':'||c.target||':'||COALESCE(NULLIF(c.trigger_message_id,''),c.message_id)
            WHERE c.app_id=? AND c.scope_id=? AND c.day=? AND (? IS NULL OR c.id<?) ORDER BY c.id DESC LIMIT ?''',
            (config.account_id, self.day.scope_id, day, before, before, limit + 1)).fetchall()
        plan = self.day.saved(config)
        generation = plan.get('generation_id', plan['revision']) if plan else None
        items = []
        for row in rows[:limit]:
            value = dict(row)
            value['diff'] = json.loads(value['diff'])
            value['current_generation'] = value['generation_id'] == generation
            value['source_content'] = value['source_content'] or ''
            value['sender_name'] = value['sender_name'] or ('群成员 · ' if value['kind'] == 'group' else '用户 · ') + value['sender_id'][-6:]
            items.append(value)
        return {'items': items, 'next_before': items[-1]['id'] if len(rows) > limit else None,
                'total': self.store.db.execute('SELECT COUNT(*) FROM schedule_changes WHERE app_id=? AND scope_id=? AND day=?', (config.account_id, self.day.scope_id, day)).fetchone()[0]}
