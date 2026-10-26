"""Authenticated bot- and user-scoped memory management routes."""
import time
import uuid
from typing import Literal

from fastapi import Depends, Query
from pydantic import Field
from .config import StrictModel
from .registry import BotRuntime


class MemoryWrite(StrictModel):
    category: Literal['fact', 'preference', 'boundary', 'relationship', 'episode', 'commitment'] = 'fact'
    content: str = Field(min_length=1, max_length=800)
    key: str = Field(default='', max_length=120)
    pinned: bool = False
    importance: int = Field(default=50, ge=0, le=100)
    expires_at: str | None = None
    due_at: str | None = None
    end_at: str | None = None
    commitment_state: Literal['pending', 'fulfilled', 'canceled'] = 'pending'


def install(app, scoped_runtime):
    def selected(runtime, scope_id):
        if not scope_id:
            raise ValueError('请先选择当前 Bot 的用户')
        return runtime.store.scopes.get(scope_id)

    @app.get('/api/bots/{bot_id}/users')
    async def users(runtime: BotRuntime = Depends(scoped_runtime)):
        return {'items': runtime.store.scopes.list()}

    @app.get('/api/bots/{bot_id}/memory')
    async def memories(scope_id: str = '', offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                       runtime: BotRuntime = Depends(scoped_runtime)):
        selected(runtime, scope_id)
        return runtime.bot.memory.snapshot(scope_id, offset, limit)

    @app.post('/api/bots/{bot_id}/memory', status_code=201)
    async def create_memory(body: MemoryWrite, scope_id: str = '', runtime: BotRuntime = Depends(scoped_runtime)):
        selected(runtime, scope_id)
        item = runtime.bot.memory.data.put(scope_id, body.category, body.key or 'admin:' + uuid.uuid4().hex, body.content, [],
            explicit=True, pinned=body.pinned, importance=body.importance, expires_at=body.expires_at,
            due_at=body.due_at, end_at=body.end_at, commitment_state=body.commitment_state)
        await runtime.bot.schedule.for_scope(scope_id).sync_commitments()
        runtime.bot.memory.wakeup.set()
        return item

    @app.put('/api/bots/{bot_id}/memory/{memory_id}')
    async def update_memory(memory_id: int, body: MemoryWrite, scope_id: str = '', runtime: BotRuntime = Depends(scoped_runtime)):
        selected(runtime, scope_id)
        old = runtime.bot.memory.data.get(scope_id, memory_id)
        if old['status'] != 'active' or old['category'] != body.category or body.key and body.key != old['key']:
            raise ValueError('记忆类型或标识已变化，请刷新后重试')
        item = runtime.bot.memory.data.put(scope_id, old['category'], old['key'], body.content, old['source_ids'],
            explicit=True, pinned=body.pinned, importance=body.importance, expires_at=body.expires_at,
            due_at=body.due_at, end_at=body.end_at, commitment_state=body.commitment_state)
        # Automatic correction keeps pins; an explicit management edit can unpin.
        with runtime.store.db:
            runtime.store.db.execute('UPDATE memories SET pinned=? WHERE id=? AND scope_id=?', (int(body.pinned), memory_id, scope_id))
        await runtime.bot.schedule.for_scope(scope_id).sync_commitments()
        runtime.bot.memory.wakeup.set()
        return runtime.bot.memory.data.get(scope_id, memory_id)

    @app.delete('/api/bots/{bot_id}/memory/{memory_id}')
    async def delete_memory(memory_id: int, scope_id: str = '', runtime: BotRuntime = Depends(scoped_runtime)):
        selected(runtime, scope_id)
        runtime.bot.memory.data.forget(scope_id, memory_id)
        await runtime.bot.schedule.for_scope(scope_id).sync_commitments()
        return {'ok': True}

    @app.get('/api/bots/{bot_id}/memory/{memory_id}/sources')
    async def memory_sources(memory_id: int, scope_id: str = '', runtime: BotRuntime = Depends(scoped_runtime)):
        selected(runtime, scope_id)
        item = runtime.bot.memory.data.get(scope_id, memory_id)
        return {'items': [source for mid in item['source_ids'] if (source := runtime.store.scopes.source(scope_id, mid))]}

    @app.post('/api/bots/{bot_id}/memory/rebuild')
    async def rebuild_memory(scope_id: str = '', runtime: BotRuntime = Depends(scoped_runtime)):
        selected(runtime, scope_id)
        runtime.bot.memory.rebuild(scope_id)
        return {'ok': True}

    @app.post('/api/bots/{bot_id}/memory/organize')
    async def organize_memory(scope_id: str = '', runtime: BotRuntime = Depends(scoped_runtime)):
        owner = selected(runtime, scope_id)
        if not runtime.store.load().memory.enabled:
            raise ValueError('请先配置并启用记忆功能')
        rows = runtime.store.db.execute('''SELECT m.id FROM chat_messages m JOIN chat_conversations c ON c.id=m.conversation_id
            WHERE c.app_id=? AND c.kind=? AND c.target_id=? AND m.id>? AND m.historical=0
            AND m.source IN ('incoming','reply') ORDER BY m.id DESC LIMIT 120''',
            (owner['app_id'], owner['kind'], owner['target'], owner['source_floor'])).fetchall()
        sources = [row['id'] for row in reversed(rows) if runtime.store.scopes.source(scope_id, row['id'])]
        if not sources:
            raise ValueError('没有可整理的新聊天，已遗忘屏障之前的消息不会重新提取')
        for start in range(0, len(sources), 24):
            runtime.bot.memory.enqueue(scope_id, 'manual:' + uuid.uuid4().hex, sources[start:start+24], immediate=True)
        return {'ok': True, 'source_count': len(sources)}

    @app.post('/api/bots/{bot_id}/memory/retry')
    async def retry_memory(scope_id: str = '', runtime: BotRuntime = Depends(scoped_runtime)):
        owner = selected(runtime, scope_id)
        with runtime.store.db:
            runtime.store.db.execute("UPDATE memory_jobs SET status='pending',attempts=0,retry_at=0,epoch=?,error='' WHERE scope_id=? AND status='failed'", (owner['epoch'], scope_id))
            runtime.store.db.execute('DELETE FROM memory_index WHERE scope_id=?', (scope_id,))
        runtime.bot.memory.wakeup.set()
        return {'ok': True}
