"""Admin-authenticated, bot/account/user-scoped emotional expression controls."""
from fastapi import Depends
from pydantic import Field
from .config import StrictModel
from .registry import BotRuntime


class Pause(StrictModel):
    paused: bool


class Adjustment(StrictModel):
    valence: float | None = Field(default=None, ge=-100, le=100, allow_inf_nan=False)
    energy: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    tension: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    familiarity: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    trust: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    comfort: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)


def install(app, scoped_runtime):
    def service(runtime, scope_id):
        if not scope_id:
            raise ValueError('请先选择当前 Bot 的用户')
        runtime.store.scopes.get(scope_id)
        return runtime.bot.emotion

    @app.get('/api/bots/{bot_id}/emotion')
    async def snapshot(scope_id: str = '', runtime: BotRuntime = Depends(scoped_runtime)):
        return service(runtime, scope_id).snapshot(scope_id)

    @app.post('/api/bots/{bot_id}/emotion/pause')
    async def pause(body: Pause, scope_id: str = '', runtime: BotRuntime = Depends(scoped_runtime)):
        emotion = service(runtime, scope_id)
        emotion.pause(scope_id, body.paused)
        return emotion.snapshot(scope_id)

    @app.post('/api/bots/{bot_id}/emotion/adjust')
    async def adjust(body: Adjustment, scope_id: str = '', runtime: BotRuntime = Depends(scoped_runtime)):
        emotion = service(runtime, scope_id)
        emotion.adjust(scope_id, body.model_dump(exclude_none=True))
        return emotion.snapshot(scope_id)

    @app.post('/api/bots/{bot_id}/emotion/reset')
    async def reset(scope_id: str = '', runtime: BotRuntime = Depends(scoped_runtime)):
        emotion = service(runtime, scope_id)
        emotion.reset(scope_id)
        return emotion.snapshot(scope_id)

    @app.post('/api/bots/{bot_id}/emotion/events/{event_id}/retract')
    async def retract(event_id: int, scope_id: str = '', runtime: BotRuntime = Depends(scoped_runtime)):
        emotion = service(runtime, scope_id)
        emotion.retract(scope_id, event_id)
        return emotion.snapshot(scope_id)

    @app.get('/api/bots/{bot_id}/emotion/events/{event_id}/sources')
    async def sources(event_id: int, scope_id: str = '', runtime: BotRuntime = Depends(scoped_runtime)):
        import json
        emotion = service(runtime, scope_id)
        row = emotion.db.execute('SELECT * FROM emotion_events WHERE scope_id=? AND id=?', (scope_id, event_id)).fetchone()
        if not row:
            raise ValueError('此用户中不存在该情感事件')
        if row['status'] != 'active':
            return {'items': []}
        return {'items': [source for mid in json.loads(row['source_ids'])
                          if (source := runtime.store.scopes.source(scope_id, mid))]}
