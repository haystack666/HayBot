"""Paginated metadata from the fixed Aigengtu public gallery index."""
import asyncio
import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

URL = 'https://aigengtu.com/gallery-index.json'


class MemeGallery:
    def __init__(self):
        self.cached = None
        self.expires = 0
        self.lock = asyncio.Lock()

    @staticmethod
    def image_url(value):
        if not isinstance(value, str):
            return ''
        parsed = urlsplit(value)
        return value if parsed.scheme == 'https' and parsed.netloc == 'img.aigengtu.com' else ''

    async def load(self):
        async with self.lock:
            if self.cached is not None and time.monotonic() < self.expires:
                return self.cached
            try:
                async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                    async with client.stream('GET', URL) as response:
                        response.raise_for_status()
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > 10 * 1024 * 1024:
                                raise ValueError('index too large')
                import json
                data = json.loads(raw)
                if not isinstance(data.get('gallery'), dict):
                    raise ValueError('invalid gallery')
                items, categories = [], []
                for key, group in data['gallery'].items():
                    name = group.get('name') or key
                    count = 0
                    for source in group.get('images', []):
                        preview = self.image_url(source.get('preview'))
                        original = self.image_url(source.get('original'))
                        if not preview or not original:
                            continue
                        story = source.get('story') or {}
                        items.append({'category': key, 'category_name': name,
                            'name': source.get('name') or source.get('alt') or name,
                            'alt': source.get('alt') or source.get('name') or name,
                            'preview': preview, 'original': original, 'type': source.get('type') or '',
                            'description': story.get('zh') or '', 'origin': story.get('origin') or '',
                            'contributor': story.get('contributor') or ''})
                        count += 1
                    categories.append({'id': key, 'name': name, 'count': count})
                self.cached = {'items': items, 'categories': categories, 'generated_at': data.get('generated_at')}
                self.expires = time.monotonic() + 300
                return self.cached
            except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                raise HTTPException(502, '爱梗图图库暂时无法加载，请稍后重试') from None

    async def list(self, category='', q='', offset=0, limit=48):
        data = await self.load()
        query = q.strip().casefold()
        items = [item for item in data['items'] if (not category or item['category'] == category)
                 and (not query or query in ' '.join([item['name'], item['alt'], item['description'], item['type']]).casefold())]
        return {'items': items[offset:offset + limit], 'total': len(items), 'offset': offset, 'limit': limit,
                'categories': data['categories'], 'generated_at': data['generated_at']}
