"""Project dated commitments onto one user's day without inventing fulfillment."""
import copy
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from .schedule import DayPlan, minute


def clock_text(value):
    return f'{value // 60:02d}:{value % 60:02d}'


def overlay(plan, start, end, replacements):
    before, result = [], []
    for item in plan['activities']:
        left, right = minute(item['start']), minute(item['end'], True)
        if right <= start or left >= end:
            result.append(item)
            continue
        before.append({**item, 'start': clock_text(max(left, start)), 'end': clock_text(min(right, end))})
        if left < start:
            result.append({**item, 'end': clock_text(start)})
        if right > end:
            result.append({**item, 'start': clock_text(end)})
    result.extend(replacements)
    plan['activities'] = sorted(result, key=lambda item: item['start'])
    return before


def window(item, day, timezone):
    tz = ZoneInfo(timezone)
    start = datetime.fromisoformat(day).replace(tzinfo=tz).timestamp()
    return max(0, int((item['due_at'] - start) / 60)), min(1440, int((item['end_at'] - start) / 60))


def project(service, plan, day, now_minute=0):
    data, sid = service.bot.memory.data, service.scope_id
    config = service.store.load()
    appointments = data.appointments(sid, day, config.schedule.timezone)
    current = {str(item['id']): item for item in appointments}
    bindings = copy.deepcopy(plan.get('commitment_bindings', {}))
    changed = False
    for mid, old in list(bindings.items()):
        item = current.get(mid)
        if item and item['revision'] == old['revision']:
            continue
        # Restore only pieces still owned by this appointment. A later dialogue edit wins.
        for before in old['before']:
            start, end = max(now_minute, minute(before['start'])), minute(before['end'], True)
            if start >= end:
                continue
            owned = [piece for piece in plan['activities'] if minute(piece['start']) < end and minute(piece['end'], True) > start
                     and piece['activity'] == old['after']['activity'] and piece['location'] == old['after']['location']]
            for piece in owned:
                left, right = max(start, minute(piece['start'])), min(end, minute(piece['end'], True))
                overlay(plan, left, right, [{**before, 'start': clock_text(left), 'end': clock_text(right)}])
        bindings.pop(mid)
        changed = True
    conflicts = []
    occupied = [(minute(value['after']['start']), minute(value['after']['end'], True), mid) for mid, value in bindings.items()]
    for item in appointments:
        mid = str(item['id'])
        if mid in bindings:
            continue
        start, end = window(item, day, config.schedule.timezone)
        start = max(start, now_minute)
        if start >= end:
            continue
        if any(start < minute(r['end'],True) and end > minute(r['start']) for r in plan.get('dialogue_ranges', [])):
            conflicts.append({'id':item['id'],'content':item['content'],'reason':'与对话中已确认的安排重叠，保留对话中的活动及所在地'})
            continue
        if any(start < right and end > left for left, right, _ in occupied):
            conflicts.append({'id': item['id'], 'content': item['content'], 'reason': '与另一条已确认约定时间重叠，请核对或改期'})
            continue
        outfit = next(piece['outfit'] for piece in plan['activities'] if minute(piece['start']) <= start < minute(piece['end'], True))
        after = {'start': clock_text(start), 'end': clock_text(end), 'activity': item['content'][:80], 'location': '约定地点（以对话为准）', 'outfit': outfit}
        before = overlay(plan, start, end, [after])
        plan['events'] = [event for event in plan['events'] if not start <= minute(event['time']) < end]
        bindings[mid] = {'revision': item['revision'], 'before': before, 'after': after}
        occupied.append((start, end, mid))
        changed = True
    if plan.get('commitment_conflicts', []) != conflicts:
        changed = True
    plan['commitment_bindings'], plan['commitment_conflicts'] = bindings, conflicts
    DayPlan.model_validate({key: plan[key] for key in DayPlan.model_fields})
    return changed


async def sync(service):
    if not service.scope_id or not service.store.load().schedule.enabled:
        return
    async with service.lock:
        config = service.store.load()
        original = service.saved(config)
        if not original:
            return
        plan = copy.deepcopy(original)
        now = service.local(config)
        if not project(service, plan, now.date().isoformat(), now.hour * 60 + now.minute):
            return
        plan.update(revision=uuid.uuid4().hex, updated_at=service.clock())
        diff = {'activities_before': [item for item in original['activities'] if item not in plan['activities']],
                'activities_after': [item for item in plan['activities'] if item not in original['activities']],
                'events_removed': [item for item in original['events'] if item not in plan['events']], 'events_added': []}
        prepared = {'stamp': service.stamp(), 'plan': plan, 'reason': '同步此用户已确认约定的新增、改期或取消',
                    'from_revision': original['revision'], 'diff': diff}
        owner = service.store.scopes.get(service.scope_id)
        newest = service.bot.memory.data.list(service.scope_id, limit=1)['items']
        source_ids = newest[0]['source_ids'] if newest else []
        trigger = next((service.store.scopes.source(service.scope_id, mid) for mid in reversed(source_ids)
                        if (service.store.scopes.source(service.scope_id, mid) or {}).get('role') == 'user'), None)
        service.dialogue.apply(prepared, {'kind': owner['kind'], 'target': owner['target'], 'sender_id': owner['sender_id'],
            'message_id': 'commitment:' + plan['revision'], 'trigger_message_id': trigger['event_key'].rsplit(':', 1)[-1] if trigger else ''})
