from fastapi import Depends, HTTPException, Query
from .registry import BotRuntime


def install(app, scoped_runtime):
    @app.get('/api/bots/{bot_id}/logs')
    async def logs(level: str = '', category: str = '', q: str = Query('', max_length=200),
                   start: float | None = Query(None, ge=0, le=4102444800), end: float | None = Query(None, ge=0, le=4102444800),
                   before: int | None = Query(None, ge=1), after: int | None = Query(None, ge=1),
                   limit: int = Query(50, ge=1, le=200), trace_id: str = Query('', max_length=100),
                   runtime: BotRuntime = Depends(scoped_runtime)):
        return runtime.store.events.query(level=level, category=category, query=q, start=start, end=end,
                                          before=before, after=after, limit=limit, trace_id=trace_id)

    @app.get('/api/bots/{bot_id}/logs/{event_id}')
    async def log_detail(event_id: int, runtime: BotRuntime = Depends(scoped_runtime)):
        result = runtime.store.events.detail(event_id)
        if result is None:
            raise HTTPException(404, '当前机器人中不存在此日志')
        return result
