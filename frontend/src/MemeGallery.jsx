import { useEffect, useState } from 'react'
import { Dialog } from 'radix-ui'
import { ExternalLink, LoaderCircle, RefreshCw, Search, X } from 'lucide-react'
import { Panel, Field } from './components/console'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'

const PAGE_SIZE = 48
export function GalleryThanks() {
  return <p className="push-hint">感谢 <a className="subtle-link" href="https://aigengtu.com" target="_blank" rel="noreferrer">爱梗图（aigengtu.com）</a> 提供图库内容与分类整理，也感谢素材创作者及贡献者。</p>
}

export default function MemeGallery({ api }) {
  const [data, setData] = useState({ items: [], categories: [], total: 0 })
  const [category, setCategory] = useState(''), [search, setSearch] = useState(''), [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0), [loading, setLoading] = useState(true), [error, setError] = useState('')
  const [retry, setRetry] = useState(0), [selected, setSelected] = useState(null)
  useEffect(() => { const timer = setTimeout(() => { setQuery(search); setOffset(0) }, 300); return () => clearTimeout(timer) }, [search])
  useEffect(() => {
    let live = true
    setLoading(true); setError('')
    api(`/memes/gallery?category=${encodeURIComponent(category)}&q=${encodeURIComponent(query)}&offset=${offset}&limit=${PAGE_SIZE}`)
      .then(result => { if (live) setData(result) })
      .catch(e => { if (live) setError(e.message) })
      .finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [api, category, query, offset, retry])
  return <Panel title={`爱梗图图库${loading ? '' : ` · ${data.total} 张`}`} subtitle="按爱梗图原始分类浏览，点击图片查看大图与说明。" action={<Button variant="outline" size="sm" disabled={loading} onClick={() => setRetry(v => v + 1)}><RefreshCw size={14} />刷新</Button>}>
    <div className="form-grid mb-5"><Field label="分类" id="meme-gallery-category"><select id="meme-gallery-category" className="provider-select" value={category} onChange={e => { setCategory(e.target.value); setOffset(0) }}><option value="">全部分类</option>{data.categories.map(item => <option key={item.id} value={item.id}>{item.name}（{item.count}）</option>)}</select></Field><Field label="搜索图库" id="meme-gallery-search"><div className="meme-search !mb-0"><Search size={15} /><Input id="meme-gallery-search" maxLength={120} value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索名称、内容或类型" /></div></Field></div>
    {loading ? <div className="empty" role="status"><LoaderCircle size={20} className="spin" />正在加载图库…</div> : error ? <div className="notice" role="alert">{error}<Button variant="outline" size="sm" onClick={() => setRetry(v => v + 1)}>重试</Button></div> : !data.items.length ? <div className="empty">没有匹配的图片，试试其他分类或关键词。</div> : <div className="meme-grid">{data.items.map((item, i) => <article className="meme-card" key={`${item.category}:${item.original}:${i}`}><button className="meme-preview" onClick={() => setSelected(item)} aria-label={`查看 ${item.name}`}><img src={item.preview} alt={item.alt} loading="lazy" decoding="async" referrerPolicy="no-referrer" /></button><div className="meme-card-body"><div className="meme-card-heading"><Badge variant="secondary">{item.category_name}</Badge>{item.type && <span>{item.type}</span>}</div><p className="meme-caption">{item.name}</p>{item.description && <p className="meme-scenario">{item.description}</p>}</div></article>)}</div>}
    {!loading && !error && data.total > 0 && <nav className="memory-pagination" aria-label="图库分页"><Button size="sm" variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>上一页</Button><span>第 {Math.floor(offset / PAGE_SIZE) + 1} / {Math.ceil(data.total / PAGE_SIZE)} 页 · {offset + 1}–{Math.min(offset + PAGE_SIZE, data.total)} / {data.total}</span><Button size="sm" variant="outline" disabled={offset + PAGE_SIZE >= data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>下一页</Button></nav>}
    <GalleryThanks />
    <Dialog.Root open={!!selected} onOpenChange={open => { if (!open) setSelected(null) }}><Dialog.Portal><Dialog.Overlay className="sheet-overlay" /><Dialog.Content className="provider-dialog meme-dialog"><Dialog.Title>{selected?.name}</Dialog.Title><Dialog.Description>{selected?.category_name}{selected?.type ? ` · ${selected.type}` : ''}</Dialog.Description>{selected && <><img className="meme-editor-image" src={selected.original} alt={selected.alt} referrerPolicy="no-referrer" /><p>{selected.description || selected.alt}</p>{selected.origin && <p className="push-hint">梗的来源：{selected.origin}</p>}{selected.contributor && <p className="push-hint">贡献者：{selected.contributor}</p>}<a className="subtle-link" href={selected.original} target="_blank" rel="noreferrer">打开原图<ExternalLink size={14} /></a></>}<Dialog.Close asChild><Button variant="ghost" size="icon-sm" className="dialog-close" aria-label="关闭图片预览"><X size={15} /></Button></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>
  </Panel>
}
