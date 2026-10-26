import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Dialog } from 'radix-ui'
import { ImagePlus, LoaderCircle, Pencil, RefreshCw, Search, Trash2, X } from 'lucide-react'
import { Panel, Field } from './components/console'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'

const packName = value => value === 'deepseek-fanart-v1' ? 'DeepSeek 同人表情包' : value === 'custom' ? '自定义表情包' : value
const lines = value => value.split('\n').map(s => s.trim()).filter(Boolean)

export default function MemesPage({ api, providers, memory, notify, onSaved }) {
  const { botId } = useParams()
  const [config, setConfig] = useState(null), [saved, setSaved] = useState(null)
  const [library, setLibrary] = useState({ items: [], total: 0, packs: [] }), [index, setIndex] = useState(null)
  const [search, setSearch] = useState(''), [offset, setOffset] = useState(0), [working, setWorking] = useState(''), [error, setError] = useState('')
  const [editor, setEditor] = useState(null), [draft, setDraft] = useState(null), [deleting, setDeleting] = useState(null)
  const upload = useRef(null)
  const refresh = useCallback(async () => {
    const [list, status] = await Promise.all([api(`/memes?q=${encodeURIComponent(search)}&offset=${offset}`), api('/memes/index')])
    setLibrary(list); setIndex(status)
  }, [api, search, offset])
  useEffect(() => {
    let live = true
    api('/memes/config').then(c => { if (live) { setConfig(c); setSaved(c) } }).catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [api])
  useEffect(() => { let live=true; const load=()=>refresh().catch(e=>{if(live)setError(e.message)}); load(); const timer=setInterval(load,5000);return()=>{live=false;clearInterval(timer)} }, [refresh])
  const change = (key, value) => setConfig(c => ({ ...c, [key]: value }))
  const imageUrl = id => `/api/bots/${encodeURIComponent(botId)}/memes/${id}/image`
  const dirty = JSON.stringify(config) !== JSON.stringify(saved)
  async function action(name, task, success) {
    setWorking(name); setError('')
    try { await task(); await refresh(); if (success) notify(success) } catch(e) { setError(e.message); notify(e.message,true) } finally { setWorking('') }
  }
  async function save(event) {
    event.preventDefault()
    const c=structuredClone(config)
    for(const key of ['chance','cooldown_seconds','repeat_window','top_k','min_similarity','timeout']) {
      if(String(c[key]).trim()==='') { setError('请填写完整数字配置');return }
      c[key]=Number(c[key]);if(!Number.isFinite(c[key])){setError('数字配置无效');return}
    }
    await action('config',async()=>{const result=await api('/memes/config','PUT',c);setConfig(result);setSaved(result);onSaved(result)},'表情包策略已保存')
  }
  function edit(item) { setEditor(item); setDraft({ name:item.name, enabled:item.enabled, ...item.description,
    scenarios:item.description.scenarios.join('\n'),avoid_scenarios:item.description.avoid_scenarios.join('\n'),emotions:item.description.emotions.join('\n') }) }
  async function saveDescription(event) {
    event.preventDefault()
    await action('edit',async()=>{
      const {name,enabled,...d}=draft
      await api(`/memes/${editor.id}`,'PATCH',{name,enabled,description:{...d,scenarios:lines(d.scenarios),avoid_scenarios:lines(d.avoid_scenarios),emotions:lines(d.emotions),needs_review:false}})
      setEditor(null)
    },'描述已保存，请重建语义索引')
  }
  async function uploadFile(event) {
    const file=event.target.files?.[0];event.target.value='';if(!file)return
    if(file.size>10*1024*1024){notify('图片必须小于 10 MB',true);return}
    await action('upload',async()=>{
      const response=await fetch(`/api/bots/${encodeURIComponent(botId)}/memes/upload?name=${encodeURIComponent(file.name.slice(0,120))}`,{method:'POST',body:file,headers:{'Content-Type':file.type||'application/octet-stream'}})
      const item=await response.json();if(!response.ok)throw new Error(item.detail||'上传失败')
      edit(item)
    })
  }
  function modelField(purpose,label) {
    const selection=config[purpose], options=providers.filter(p=>p.purpose===purpose)
    return <div className="form-grid"><Field label={`${label} 供应商`} id={`meme-${purpose}-provider`}><select className="provider-select" id={`meme-${purpose}-provider`} value={selection.provider_id} onChange={e=>{const p=options.find(p=>p.id===e.target.value);change(purpose,{provider_id:p?.id||'',model:p?.default_model||''})}}><option value="">{purpose==='rerank'?'不使用重排':'请选择 Embedding'}</option>{options.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></Field><Field label={`${label} 模型`} id={`meme-${purpose}-model`}><Input id={`meme-${purpose}-model`} disabled={!selection.provider_id} value={selection.model} maxLength={200} onChange={e=>change(purpose,{...selection,model:e.target.value})} /></Field></div>
  }
  if(!config)return <div className="notice">{error||'正在读取表情包配置…'}</div>
  return <div className="page-stack">
    {error&&<div className="notice" role="alert">{error}</div>}
    <Panel title="表情包策略" subtitle="仅作用于当前机器人。模型会结合上下文选择合适的表情，最多发送一张。">
      <form onSubmit={save} className="page-stack">
        <div className="toggle-row !pt-0"><div><b>在聊天中发送表情包</b><p>适合时才发送，文字和图片合计最多 4 个气泡；指令和主动消息不受影响。</p></div><Switch aria-label="启用表情包" checked={config.enabled} onCheckedChange={v=>change('enabled',v)} disabled={!!working} /></div>
        <fieldset className="meme-policy" disabled={!!working||index?.busy}>
          {modelField('embedding','Embedding')}{modelField('rerank','Rerank（可选）')}
          {memory?.embedding?.provider_id&&<Button type="button" variant="outline" size="sm" onClick={()=>setConfig(c=>({...c,embedding:structuredClone(memory.embedding),rerank:structuredClone(memory.rerank)}))}>沿用当前记忆模型配置</Button>}
          <div className="form-grid mt-4">{[['chance','候选触发概率',0,1,.05,'0–1，0.35 表示约 35% 的对话会尝试选图，并非一定发送。'],['cooldown_seconds','发送冷却（秒）',0,86400,1,'同一用户两次表情包的最短间隔，0–86400 秒。'],['repeat_window','避开最近几张',0,100,1,'每个用户分别记录，0 表示允许连续重复。'],['top_k','提供给模型的候选数',1,10,1,'向量召回后供主对话模型挑选，1–10 张。'],['min_similarity','最低相似度',-1,1,.05,'低于此值不进入候选，默认 0.2。'],['timeout','检索超时（秒）',5,120,1,'超时后本轮正常发送文字。']].map(([key,label,min,max,step,hint])=><Field key={key} label={label} id={`meme-${key}`} hint={hint}><Input id={`meme-${key}`} type="number" required min={min} max={max} step={step} value={config[key]} onChange={e=>change(key,e.target.value)} /></Field>)}</div>
          <div className="meme-pack-options"><b>启用的集合</b>{library.packs.map(p=><label key={p.pack}><input type="checkbox" checked={config.packs.includes(p.pack)} onChange={e=>change('packs',e.target.checked?[...config.packs,p.pack]:config.packs.filter(v=>v!==p.pack))} />{packName(p.pack)} <span>{p.count} 张</span></label>)}</div>
        </fieldset>
        <div className="meme-actions"><span>策略可在机器人运行时保存，不清空聊天或记忆。</span><Button disabled={!dirty||!!working||index?.busy}>{working==='config'&&<LoaderCircle size={14} className="spin" />}保存表情包策略</Button></div>
      </form>
    </Panel>
    <Panel title="语义索引" subtitle="表情包使用独立索引，支持单独选择 Embedding 与 Rerank。" action={<Button size="sm" variant="outline" disabled={!!working||index?.busy||dirty||!index?.configured} onClick={()=>action('rebuild',()=>api('/memes/rebuild','POST'),'已安排构建索引')}><RefreshCw size={14} className={index?.busy?'spin':''} />{index?.busy?'构建中':'构建 / 更新索引'}</Button>}>
      <div className="meme-index"><Badge variant="secondary">{index?.indexed||0} / {index?.total||0} 张已索引</Badge><span>{!index?.configured?'请先选择并保存 Embedding 模型。':index?.busy?'可以继续聊天，索引进度每 5 秒更新。':index?.indexed<index?.total?'有图片尚未索引，点击构建即可补齐。':'索引可用。修改描述或模型后需要重新构建。'}</span></div>{index?.error&&<p className="provider-test-message" role="status">{index.error}</p>}
    </Panel>
    <Panel title={`表情包图库 · ${library.total} 张`} subtitle="图库由所有机器人共享；逐图描述、文字和场景可编辑。新增图片先补充描述再启用。" action={<><input ref={upload} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden onChange={uploadFile} /><Button size="sm" variant="outline" disabled={!!working} onClick={()=>upload.current?.click()}><ImagePlus size={14} />上传图片</Button></>}>
      <div className="meme-search"><Search size={15} /><Input aria-label="搜索表情包" value={search} onChange={e=>{setSearch(e.target.value);setOffset(0)}} placeholder="搜索画面、图中文字或适用场景" /></div>
      {!library.items.length?<div className="empty">{search?'没有匹配的表情包':'还没有表情包，可以上传图片。'}</div>:<div className="meme-grid">{library.items.map(item=><article className="meme-card" key={item.id}><button className="meme-preview" onClick={()=>edit(item)} aria-label={`编辑 ${item.name}`}><img src={imageUrl(item.id)} alt={item.description.visual} loading="lazy" /></button><div className="meme-card-body"><div className="meme-card-heading"><Badge variant={item.enabled?'secondary':'outline'}>{item.enabled?'已启用':'已停用'}</Badge>{item.description.needs_review&&<span>待核对</span>}</div><p className="meme-caption">{item.description.text||item.description.visual}</p><p className="meme-scenario">{item.description.scenarios[0]||'待补充适用场景'}</p><div className="meme-card-actions"><Button size="icon-sm" variant="ghost" aria-label={`编辑描述 ${item.name}`} onClick={()=>edit(item)}><Pencil size={14} /></Button><Button size="icon-sm" variant="ghost" aria-label={`删除 ${item.name}`} onClick={()=>setDeleting(item)}><Trash2 size={14} /></Button></div></div></article>)}</div>}
      {!!library.total&&<div className="memory-pagination"><Button size="sm" variant="outline" disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-48))}>上一页</Button><span>{offset+1}–{Math.min(offset+48,library.total)} / {library.total}</span><Button size="sm" variant="outline" disabled={offset+48>=library.total} onClick={()=>setOffset(offset+48)}>下一页</Button></div>}
      <p className="push-hint">DeepSeek 同人包来自 anka-afk/deepseek-fanart-meme-pack，描述由 DeepSeek Flash 自动生成，可能有识别误差。素材原作者权利及包内 LICENSE 保留；未取得额外商业授权。QQ 官方接入按首帧静态图片发送，NapCat 保留原始动图并按表情发送。</p>
    </Panel>
    <Dialog.Root open={!!editor} onOpenChange={open=>{if(!open&&!working)setEditor(null)}}><Dialog.Portal><Dialog.Overlay className="sheet-overlay" /><Dialog.Content className="provider-dialog meme-dialog"><Dialog.Title>逐图语义描述</Dialog.Title><Dialog.Description>图片、文字、适用场景共同用于检索。保存后更新索引即可生效。</Dialog.Description>{editor&&draft&&<form className="provider-form" onSubmit={saveDescription}><img className="meme-editor-image" src={imageUrl(editor.id)} alt={draft.visual} /><Field label="名称" id="meme-name"><Input id="meme-name" required maxLength={120} value={draft.name} onChange={e=>setDraft(d=>({...d,name:e.target.value}))} /></Field>{[['visual','画面描述',1500],['text','图中文字（无则留空）',1500],['scenarios','适用场景（每行一条）',4000],['avoid_scenarios','不适用场景（每行一条）',4000],['emotions','情绪标签（每行一个）',1000],['tone','语气',200]].map(([key,label,max])=><Field key={key} label={label} id={`meme-edit-${key}`}><Textarea id={`meme-edit-${key}`} required={key==='visual'} rows={key==='visual'?3:2} maxLength={max} value={draft[key]} onChange={e=>setDraft(d=>({...d,[key]:e.target.value}))} /></Field>)}<div className="toggle-row"><div><b>允许机器人使用此图</b><p>所有启用此集合的机器人都会受影响。</p></div><Switch aria-label="允许使用此表情包" checked={draft.enabled} onCheckedChange={v=>setDraft(d=>({...d,enabled:v}))} /></div><p className="push-hint">{editor.provenance.model?`自动描述模型：${editor.provenance.model}；置信度：${Math.round(draft.confidence*100)}%。保存即标记已人工核对。`:'自定义图片。请根据画面准确填写，避免语义误配。'}</p><div className="dialog-actions"><Button type="button" variant="outline" disabled={!!working} onClick={()=>setEditor(null)}>取消</Button><Button disabled={!!working}>保存描述</Button></div></form>}<Dialog.Close asChild><Button variant="ghost" size="icon-sm" className="dialog-close" aria-label="关闭表情包编辑"><X size={15} /></Button></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={!!deleting} onOpenChange={open=>{if(!open&&!working)setDeleting(null)}}><Dialog.Portal><Dialog.Overlay className="sheet-overlay" /><Dialog.Content className="bot-dialog"><Dialog.Title>从图库删除表情包？</Dialog.Title><Dialog.Description>所有机器人将停止使用此图。已有聊天记录中的图片仍保留。</Dialog.Description><div className="dialog-actions"><Dialog.Close asChild><Button variant="outline">取消</Button></Dialog.Close><Button variant="destructive" disabled={!!working} onClick={()=>action('delete',async()=>{await api(`/memes/${deleting.id}`,'DELETE');setDeleting(null)},'表情包已删除')}>确认删除</Button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>
}
