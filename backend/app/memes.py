"""Shared meme assets and versioned semantic indexes, separate from private memories."""
import hashlib
import io
import json
import shutil
import sqlite3
import time
import warnings
from pathlib import Path
from typing import Annotated

from fastapi import HTTPException
from PIL import Image, ImageOps
from pydantic import Field
from .config import StrictModel


class MemeDescription(StrictModel):
    visual: str = Field(default='待补充画面描述', min_length=1, max_length=1500)
    text: str = Field(default='', max_length=1500)
    scenarios: list[Annotated[str,Field(min_length=1,max_length=400)]] = Field(default_factory=list, max_length=12)
    avoid_scenarios: list[Annotated[str,Field(min_length=1,max_length=400)]] = Field(default_factory=list, max_length=12)
    emotions: list[Annotated[str,Field(min_length=1,max_length=80)]] = Field(default_factory=list, max_length=12)
    tone: str = Field(default='', max_length=200)
    needs_review: bool = True
    confidence: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)


class MemeEdit(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    description: MemeDescription | None = None


def semantic_text(item):
    d = item['description']
    return '\n'.join([d['visual'], '图中文字：' + d['text'], '适用场景：' + '；'.join(d['scenarios']),
        '不适用：' + '；'.join(d['avoid_scenarios']), '情绪：' + '、'.join(d['emotions']), '语气：' + d['tone']])[:8000]


def checked_image(raw):
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise ValueError('图片必须小于 10 MB')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=('PNG', 'JPEG', 'WEBP', 'GIF')) as im:
                if im.width * im.height > 20_000_000:
                    raise ValueError('图片分辨率过大')
                fmt, size, frames = im.format, im.size, getattr(im, 'n_frames', 1)
                im.load()
                return fmt, size, frames
    except Exception:
        raise ValueError('图片无效或过大，仅支持 PNG、JPEG、WebP 和 GIF') from None


class MemeCatalog:
    def __init__(self, root):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.assets = self.root / 'meme-assets'; self.assets.mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / 'memes.sqlite3'); self.db.row_factory = sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS memes (id TEXT PRIMARY KEY, name TEXT NOT NULL, pack TEXT NOT NULL,
                category TEXT NOT NULL, description TEXT NOT NULL, revision TEXT NOT NULL,
                format TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, frames INTEGER NOT NULL,
                enabled INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0, provenance TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS meme_vectors (fingerprint TEXT NOT NULL, meme_id TEXT NOT NULL,
                revision TEXT NOT NULL, vector TEXT NOT NULL, PRIMARY KEY(fingerprint,meme_id));
        ''')

    def unpack(self, row):
        if row is None:
            raise HTTPException(404, '表情包不存在')
        item = dict(row); item['description'] = json.loads(item['description']); item['provenance'] = json.loads(item['provenance'])
        item['enabled'], item['deleted'] = bool(item['enabled']), bool(item['deleted'])
        return item

    def get(self, mid, include_deleted=False):
        return self.unpack(self.db.execute('SELECT * FROM memes WHERE id=?' + ('' if include_deleted else ' AND deleted=0'), (mid,)).fetchone())

    def list(self, search='', offset=0, limit=50, enabled_only=False, packs=None):
        where, params = ['deleted=0'], []
        if enabled_only: where.append('enabled=1')
        if search:
            where.append('(name LIKE ? OR description LIKE ? OR category LIKE ?)'); params += ['%' + search + '%'] * 3
        if packs:
            where.append('pack IN (' + ','.join('?' for _ in packs) + ')'); params += list(packs)
        sql = ' FROM memes WHERE ' + ' AND '.join(where)
        total = self.db.execute('SELECT COUNT(*)' + sql, params).fetchone()[0]
        items = [self.unpack(r) for r in self.db.execute('SELECT *' + sql + ' ORDER BY pack,category,name,id LIMIT ? OFFSET ?', [*params, limit, offset])]
        return {'items': items, 'total': total, 'offset': offset}

    def add(self, raw, name, description=None, pack='custom', category='custom', provenance=None):
        fmt, size, frames = checked_image(raw); mid = hashlib.sha256(raw).hexdigest()
        existing = self.db.execute('SELECT * FROM memes WHERE id=?', (mid,)).fetchone()
        if existing: return self.unpack(existing)
        if self.db.execute('SELECT COUNT(*) FROM memes WHERE deleted=0').fetchone()[0] >= 5000:
            raise ValueError('图库最多容纳 5000 张图片')
        d = description or MemeDescription()
        self.assets.joinpath(mid).write_bytes(raw)
        revision = hashlib.sha256(json.dumps(d.model_dump(), sort_keys=True).encode()).hexdigest()
        with self.db:
            self.db.execute('INSERT INTO memes VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?,?)',
                (mid, name[:120], pack, category, d.model_dump_json(), revision, fmt, *size, frames,
                 int(bool(d.scenarios)), json.dumps(provenance or {}), time.time()))
        return self.get(mid)

    def update(self, mid, changes):
        item = self.get(mid); change = MemeEdit.model_validate(changes).model_dump(exclude_none=True)
        d = change.get('description', item['description']); revision = hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()
        with self.db:
            self.db.execute('UPDATE memes SET name=?,description=?,revision=?,enabled=?,updated=? WHERE id=?',
                (change.get('name', item['name']), json.dumps(d), revision, int(change.get('enabled', item['enabled'])), time.time(), mid))
            if revision != item['revision']:
                self.db.execute('DELETE FROM meme_vectors WHERE meme_id=?', (mid,))
        return self.get(mid)

    def delete(self, mid):
        self.get(mid)
        with self.db:
            self.db.execute('UPDATE memes SET deleted=1,enabled=0,updated=? WHERE id=?', (time.time(), mid))
            self.db.execute('DELETE FROM meme_vectors WHERE meme_id=?', (mid,))

    def image(self, mid):
        self.get(mid, include_deleted=True)
        path = self.assets / mid
        if not path.is_file(): raise HTTPException(404, '表情包文件缺失')
        return path

    def upload_bytes(self, mid):
        return self.convert_upload(self.image(mid))

    @staticmethod
    def convert_upload(path):
        # QQ outbound WebP/GIF compatibility varies. Normalize to a static PNG/JPEG.
        with Image.open(path) as im:
            im.seek(0); frame = ImageOps.exif_transpose(im).convert('RGBA'); frame.thumbnail((1600, 1600))
            out = io.BytesIO(); frame.save(out, 'PNG', optimize=True)
            raw = out.getvalue()
            if len(raw) > 4 * 1024 * 1024:
                bg = Image.new('RGBA', frame.size, 'white'); bg.alpha_composite(frame)
                out = io.BytesIO(); bg.convert('RGB').save(out, 'JPEG', quality=90); raw = out.getvalue()
            return raw

    def save_vectors(self, fingerprint, items, vectors):
        with self.db:
            for item, vector in zip(items, vectors, strict=True):
                current = self.get(item['id'], include_deleted=True)
                if current['deleted'] or current['revision'] != item['revision']: continue
                self.db.execute('INSERT OR REPLACE INTO meme_vectors VALUES (?,?,?,?)',
                    (fingerprint, item['id'], item['revision'], json.dumps(vector)))

    def vectors(self, fingerprint, packs=None):
        items = self.list(limit=5000, enabled_only=True, packs=packs)['items']
        indexed = {r['meme_id']: r for r in self.db.execute('SELECT * FROM meme_vectors WHERE fingerprint=?', (fingerprint,))}
        return [(item, json.loads(indexed[item['id']]['vector'])) for item in items
                if item['id'] in indexed and indexed[item['id']]['revision'] == item['revision']]

    def index_status(self, fingerprint, packs=None):
        return {'total': self.list(limit=1, enabled_only=True, packs=packs)['total'], 'indexed': len(self.vectors(fingerprint, packs))}

    def import_pack(self, source, descriptions):
        source, descriptions = Path(source).resolve(), Path(descriptions)
        rows = json.loads((source / 'source_index.json').read_text())['images']; count = 0
        # Validate the entire pack before changing the catalog.
        prepared = []
        for row in rows:
            path = (source / row['path']).resolve()
            if not path.is_relative_to(source) or not path.is_file(): raise ValueError('素材路径无效')
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != row['sha256']: raise ValueError('素材 SHA256 不匹配')
            record = json.loads((descriptions / (row['sha256'] + '.json')).read_text())
            if record['sha256'] != row['sha256']: raise ValueError('描述与素材不匹配')
            prepared.append((row, raw, record, MemeDescription.model_validate(record['description'])))
        for row, raw, record, description in prepared:
            self.add(raw, row['filename'], description, pack='deepseek-fanart-v1', category=row['category'], provenance={
                'repository': 'https://github.com/anka-afk/deepseek-fanart-meme-pack',
                'commit': '86841e222b1c26a3d4d307e7224963e8a271f9e9', 'path': row['path'],
                'model': record['model'], 'generated_at': record['generated_at'], 'usage': record.get('usage', {})})
            count += 1
        attribution = self.root / 'meme-sources' / 'deepseek-fanart-v1'; attribution.mkdir(parents=True, exist_ok=True)
        for name in ('LICENSE', 'README.md', 'source_index.json', 'manifest.json'):
            shutil.copy2(source / name, attribution / name)
        return count

    def close(self): self.db.close()
