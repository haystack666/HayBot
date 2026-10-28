import { usePageTabs, Section } from './components/PageTabs'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Dialog } from 'radix-ui'
import { CalendarClock, ImagePlus, LoaderCircle, RefreshCw, Send, Sparkles, Trash2, X } from 'lucide-react'
import { Panel, Field } from './components/console'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'

const audiences={64:'仅自己可见',4:'好友可见',1:'所有人可见',16:'指定好友可见',128:'指定好友不可见'}
const states={draft:'草稿',scheduled:'等待定时',queued:'排队中',generating:'生成中',sending:'发布中',sent:'已发布',failed:'未发送',unknown:'发布结果未知',canceled:'已取消',deleting:'删除中',deleted:'已删除',delete_unknown:'删除结果未知'}
const showTime=t=>t?new Date(t*1000).toLocaleString('zh-CN',{hour12:false}):'—'
const targetList=s=>s.split(/[\s,，;；]+/).map(x=>x.trim()).filter(Boolean)
const blank={content:'',images:[],visibility:64,targets:[],scheduled_at:null}

function Audience({ value, set, prefix }) {
  return <><Field label="可见范围" id={`${prefix}-visibility`}><select className="provider-select" id={`${prefix}-visibility`} value={value.visibility} onChange={e=>set({...value,visibility:Number(e.target.value)})}>{Object.entries(audiences).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></Field>{[16,128].includes(Number(value.visibility))&&<Field label="QQ 号列表" id={`${prefix}-targets`} hint="使用逗号或空格分隔。"><Input id={`${prefix}-targets`} required value={value.targetsText??value.targets.join(', ')} onChange={e=>set({...value,targetsText:e.target.value,targets:targetList(e.target.value)})} /></Field>}</>
}

export default function QzonePage({ api, notify, dirty }) {
  const {botId}=useParams()
  const tabs=usePageTabs([['records','动态记录'],['compose','写动态'],['settings','空间设置']], 'spaceView')
  const [snapshot,setSnapshot]=useState(null),[policy,setPolicy]=useState(null),[saved,setSaved]=useState(null)
  const [posts,setPosts]=useState({items:[],total:0}),[offset,setOffset]=useState(0),[error,setError]=useState(''),[working,setWorking]=useState('')
  const [draft,setDraft]=useState(structuredClone(blank)),[editing,setEditing]=useState(null),[instruction,setInstruction]=useState('')
  const [when,setWhen]=useState(''),[confirm,setConfirm]=useState(null)
  const upload=useRef(null),live=useRef(true)
  const refresh=useCallback(async()=>{
    const [s,p]=await Promise.all([api('/qzone'),api(`/qzone/posts?offset=${offset}`)])
    if(live.current){setSnapshot(s);setPosts(p)}
    return s
  },[api,offset])
  useEffect(()=>{live.current=true;refresh().then(s=>{if(live.current){setPolicy(s.config);setSaved(s.config)}}).catch(e=>setError(e.message));return()=>{live.current=false}},[api])
  useEffect(()=>{const load=()=>refresh().catch(e=>{if(live.current)setError(e.message)});load();const timer=setInterval(load,3000);return()=>clearInterval(timer)},[refresh])
  const imageUrl=id=>`/api/bots/${encodeURIComponent(botId)}/qzone/images/${id}`
  async function action(name,task,success){setWorking(name);setError('');try{await task();await refresh();if(success)notify(success)}catch(e){setError(e.message);notify(e.message,true)}finally{setWorking('')}}
  function payload(){
    const result={...draft,scheduled_at:when?new Date(when).getTime()/1000:null};delete result.targetsText
    if(!result.content.trim())throw new Error('请先填写动态正文')
    if(result.scheduled_at!=null&&(!Number.isFinite(result.scheduled_at)||result.scheduled_at<=Date.now()/1000))throw new Error('请选择未来的发布时间')
    return result
  }
  async function saveDraft(publish=false){
    await action('save',async()=>{
      const value=payload();if(publish)value.scheduled_at=null
      const p=editing?await api(`/qzone/posts/${editing}`,'PUT',value):await api('/qzone/posts','POST',value)
      setEditing(p.id)
      if(publish)setConfirm({kind:'publish',post:p});else notify(value.scheduled_at?'已保存定时发布':'草稿已保存')
    })
  }
  function edit(p){tabs.select('compose');setDraft({content:p.content,images:p.images,visibility:p.visibility,targets:p.targets});setEditing(p.id)
    if(p.scheduled_at){const d=new Date(p.scheduled_at*1000);setWhen(new Date(d-d.getTimezoneOffset()*60000).toISOString().slice(0,16))}else setWhen('')
    document.getElementById('qzone-content')?.scrollIntoView({block:'center',behavior:'smooth'})
  }
  async function uploadImages(event){
    const files=[...event.target.files];event.target.value=''
    if(draft.images.length+files.length>9){notify('最多添加9张配图',true);return}
    if(files.some(f=>f.size>10*1024*1024)){notify('单张配图不能超过10MB',true);return}
    await action('upload',async()=>{
      const ids=[]
      for(const file of files){const r=await fetch(`/api/bots/${encodeURIComponent(botId)}/qzone/images?name=${encodeURIComponent(file.name.slice(0,120))}`,{method:'POST',body:file,headers:{'Content-Type':file.type||'application/octet-stream'}});const data=await r.json();if(!r.ok)throw new Error(data.detail||'配图上传失败');ids.push(data.id)}
      setDraft(d=>({...d,images:[...d.images,...ids]}))
    })
  }
  async function savePolicy(event){event.preventDefault();await action('policy',async()=>{
    const c={...policy};delete c.targetsText
    for(const key of ['interval_min_minutes','interval_max_minutes','event_min_minutes','event_max_minutes','cooldown_minutes','daily_limit','share_probability']){if(String(c[key]).trim()===''||!Number.isFinite(Number(c[key])))throw new Error('请填写完整数字配置');c[key]=Number(c[key])}
    const result=await api('/qzone/config','PUT',c);setPolicy(result);setSaved(result)
  },'自动发布策略已保存')}
  if(!snapshot||!policy)return <div className="notice">{error||'正在读取空间配置…'}</div>
  if(!snapshot.supported)return <Panel title="QQ 空间" subtitle="此功能需要 NapCat 登录的 QQ 账号。"><p className="push-hint">当前为官方机器人接入。请切换到已有 NapCat 机器人，再管理动态。</p></Panel>
  const policyDirty=JSON.stringify(policy)!==JSON.stringify(saved)
  return <div className="page-stack">{tabs.tabs}
    {error&&<div className="notice" role="alert">{error}</div>}
    {!snapshot.connected&&<div className="notice">NapCat 尚未连接，可以编辑草稿；发布前请启动机器人。</div>}
    <Section show={tabs.value === 'compose'}><Panel title={editing?'编辑动态草稿':'写一条动态'} subtitle="发布到当前 NapCat 账号的 QQ 空间，默认仅自己可见。">
      <div className="page-stack"><Field label="动态正文" id="qzone-content"><Textarea id="qzone-content" rows={5} maxLength={2000} value={draft.content} onChange={e=>setDraft(d=>({...d,content:e.target.value}))} placeholder="分享此刻的想法…" /><small className="qzone-counter">{draft.content.length} / 2000</small></Field>
        <div className="qzone-ai"><Input aria-label="本次生成要求" maxLength={2000} value={instruction} onChange={e=>setInstruction(e.target.value)} placeholder="可选：本次生成要求，例如轻松地分享校园生活" /><Button variant="outline" disabled={!!working||dirty||policyDirty} onClick={()=>action('generate',async()=>{const r=await api('/qzone/generate','POST',{instruction});setDraft(d=>({...d,content:r.content}))},'正文已生成，请检查后发布')}>{working==='generate'?<LoaderCircle size={14} className="spin" />:<Sparkles size={14} />}AI 生成正文</Button></div>
        <p className="push-hint">绑定 Owner 后，只使用其私聊和对应日程作为生活素材，不读取其他用户；仅参考已经开始的活动和已发生的事件。正文会隐藏身份、联系方式和聊天原话，生成后可编辑。</p>
        <div className="qzone-images">{draft.images.map((id,i)=><div key={`${id}-${i}`}><img src={imageUrl(id)} alt={`配图 ${i+1}`} /><Button size="icon-sm" variant="secondary" aria-label={`移除配图 ${i+1}`} onClick={()=>setDraft(d=>({...d,images:d.images.filter((_,n)=>n!==i)}))}><X size={12} /></Button></div>)}</div>
        <input ref={upload} type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden onChange={uploadImages} />
        <div className="action-row"><Button variant="outline" size="sm" disabled={!!working||draft.images.length>=9} onClick={()=>upload.current?.click()}><ImagePlus size={14} />添加配图（{draft.images.length}/9）</Button><span className="push-hint">单张10MB，配图总计20MB；动图取首帧。</span></div>
        <div className="form-grid"><Audience value={draft} set={setDraft} prefix="qzone-draft" /><Field label="一次定时发布（可选）" id="qzone-when" hint="按当前设备时区填写；留空保存为草稿。"><Input id="qzone-when" type="datetime-local" value={when} onChange={e=>setWhen(e.target.value)} /></Field></div>
        <div className="qzone-editor-actions"><Button variant="ghost" disabled={!!working} onClick={()=>{setEditing(null);setDraft(structuredClone(blank));setWhen('')}}>新建草稿</Button><div className="action-row"><Button variant="outline" disabled={!!working||!draft.content.trim()} onClick={()=>saveDraft()}><CalendarClock size={14} />{when?'保存定时发布':'保存草稿'}</Button><Button disabled={!!working||!snapshot.connected||!draft.content.trim()} onClick={()=>saveDraft(true)}><Send size={14} />立即发布</Button></div></div>
      </div>
    </Panel>
    </Section><Section show={tabs.value === 'settings'}><Panel title="随机分享与 Owner" subtitle="由生活和对话触发分享欲，随机等待后再决定，不按固定时刻打卡。">
      <form className="page-stack" onSubmit={savePolicy}>
        <div className="toggle-row !pt-0"><div><b>启用随机自动发布</b><p>活跃时段内随机评估，允许跳过或一天不发。需要 NapCat 在线。</p></div><Switch aria-label="启用随机自动发布" checked={policy.auto_enabled} disabled={!!working} onCheckedChange={v=>setPolicy(p=>({...p,auto_enabled:v}))} /></div>
        <fieldset className="meme-policy" disabled={!!working}>
          <Field label="Owner QQ 号" id="qzone-owner-id" hint="每个 Bot 单独填写，可随时修改或清空。仅作为素材来源，不改变下面设置的可见范围。"><Input id="qzone-owner-id" inputMode="numeric" maxLength={20} required={policy.auto_enabled} value={policy.owner_id} onChange={e=>setPolicy(p=>({...p,owner_id:e.target.value}))} placeholder="填写与你对话的 Owner QQ 号" /></Field>
          <p className="push-hint">{!policy.owner_id?'未绑定 Owner，不会自动读取任何人的聊天和日程。':snapshot.owner?.available?'已找到此 Owner 的单聊范围。':'Owner 需先私聊此机器人，建立独立对话范围后才会自动分享。'}修改 Owner 会让旧的自动素材及待发任务失效。</p>
          <div className="form-grid"><Field label="活跃时段开始" id="qzone-active-start"><Input id="qzone-active-start" type="time" value={policy.active_start} onChange={e=>setPolicy(p=>({...p,active_start:e.target.value}))} /></Field><Field label="活跃时段结束" id="qzone-active-end" hint="00:00 表示午夜；开始与结束相同表示全天。"><Input id="qzone-active-end" type="time" value={policy.active_end} onChange={e=>setPolicy(p=>({...p,active_end:e.target.value}))} /></Field>
          {[['interval_min_minutes','随机评估最短间隔（分钟）',5,1440,1],['interval_max_minutes','随机评估最长间隔（分钟）',5,1440,1],['event_min_minutes','新事件最短等待（分钟）',1,1440,1],['event_max_minutes','新事件最长等待（分钟）',1,1440,1],['cooldown_minutes','两条动态最短间隔（分钟）',0,1440,1],['daily_limit','每日最多动态数',0,1000,1],['share_probability','分享倾向',0,1,.05]].map(([key,label,min,max,step])=><Field key={key} label={label} id={`qzone-${key}`} hint={key==='daily_limit'?'0 表示不限次数，上限不是每天必发数量。':key==='share_probability'?'0–1，越高越容易进入模型评估；模型仍可决定不发。':undefined}><Input id={`qzone-${key}`} type="number" required min={min} max={max} step={step} value={policy[key]} onChange={e=>setPolicy(p=>({...p,[key]:e.target.value}))} /></Field>)}
          <Field label="发布时区" id="qzone-timezone"><Input id="qzone-timezone" value={policy.timezone} onChange={e=>setPolicy(p=>({...p,timezone:e.target.value}))} /></Field><Field label="内容来源" id="qzone-mode"><select className="provider-select" id="qzone-mode" value={policy.mode} onChange={e=>setPolicy(p=>({...p,mode:e.target.value}))}><option value="generated">按 Owner 日程与聊天自然生成</option><option value="fixed">固定正文（避免重复发布）</option></select></Field><Audience value={policy} set={setPolicy} prefix="qzone-auto" /></div>
          <Field label={policy.mode==='fixed'?'固定发布正文':'默认写作要求'} id="qzone-auto-content"><Textarea id="qzone-auto-content" rows={3} maxLength={2000} value={policy.mode==='fixed'?policy.content:policy.instruction} onChange={e=>setPolicy(p=>({...p,[p.mode==='fixed'?'content':'instruction']:e.target.value}))} /></Field>
          <Field label="额外可公开素材" id="qzone-public-context" hint="可补充已发生的经历或穿搭；不要填写身份、联系方式或他人隐私。"><Textarea id="qzone-public-context" rows={3} maxLength={4000} value={policy.public_context} onChange={e=>setPolicy(p=>({...p,public_context:e.target.value}))} /></Field>
        </fieldset><p className="push-hint">{snapshot.random?.next_check?`下次随机评估约 ${showTime(snapshot.random.next_check)}，不保证发布。`:snapshot.random?.last_reason}{snapshot.random?.next_check&&snapshot.random.last_reason?` ${snapshot.random.last_reason}`:''}</p><div className={policyDirty ? "local-savebar" : "action-row justify-end"}>{policyDirty && <span>空间策略有未保存的修改</span>}<div className="action-row">{policyDirty && <Button type="button" variant="outline" disabled={!!working} onClick={()=>setPolicy(structuredClone(saved))}>撤销更改</Button>}<Button disabled={!!working||!policyDirty}>保存空间策略</Button></div></div>
      </form>
    </Panel>
    </Section><Section show={tabs.value === 'records'}><Panel title={`动态记录 · ${posts.total} 条`} subtitle="草稿、定时及发布结果保存在本机；结果未知时请先去 QQ 空间核对。" action={<Button variant="ghost" size="icon-sm" aria-label="刷新动态记录" onClick={()=>refresh().catch(e=>setError(e.message))}><RefreshCw size={14} /></Button>}>
      {!posts.items.length?<div className="empty">还没有动态记录，先写一条草稿。</div>:<div className="qzone-posts">{posts.items.map(p=><article key={p.id} className="qzone-post"><div className="qzone-post-heading"><Badge variant={p.status==='sent'?'secondary':'outline'}>{states[p.status]||p.status}</Badge><span>{audiences[p.visibility]}</span><time>{showTime(p.created)}</time></div><p className="qzone-post-content">{p.content}</p>{!!p.images.length&&<div className="qzone-record-images">{p.images.map((id,i)=><img key={`${id}-${i}`} src={imageUrl(id)} alt={`动态配图 ${i+1}`} loading="lazy" />)}</div>}{p.scheduled_at&&<p className="push-hint">定时：{showTime(p.scheduled_at)}</p>}{p.error&&<p className="provider-test-message" role="status">{p.error}</p>}{p.tid&&<p className="push-hint">说说 ID：{p.tid}</p>}<div className="action-row justify-end">{['draft','scheduled','failed'].includes(p.status)&&<><Button size="sm" variant="outline" disabled={!!working} onClick={()=>edit(p)}>编辑</Button><Button size="sm" disabled={!!working||!snapshot.connected||p.content==='正在生成动态'} onClick={()=>setConfirm({kind:'publish',post:p})}>立即发布</Button></>}{['draft','scheduled','queued','failed','sent'].includes(p.status)&&<Button size="sm" variant="destructive-outline" disabled={!!working} onClick={()=>setConfirm({kind:'delete',post:p})}><Trash2 size={13} />{p.status==='sent'?'删除说说':'取消'}</Button>}</div></article>)}</div>}
      {posts.total>30&&<div className="memory-pagination"><Button size="sm" variant="outline" disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-30))}>上一页</Button><span>{offset+1}–{Math.min(offset+30,posts.total)} / {posts.total}</span><Button size="sm" variant="outline" disabled={offset+30>=posts.total} onClick={()=>setOffset(offset+30)}>下一页</Button></div>}
    </Panel>
    </Section><Dialog.Root open={!!confirm} onOpenChange={v=>{if(!v&&!working)setConfirm(null)}}><Dialog.Portal><Dialog.Overlay className="sheet-overlay" /><Dialog.Content className="provider-dialog"><Dialog.Title>{confirm?.kind==='publish'?'发布到 QQ 空间？':confirm?.post.status==='sent'?'删除这条 QQ 空间说说？':'取消这条草稿或定时任务？'}</Dialog.Title><Dialog.Description>{confirm?.kind==='publish'?`将立即发布到当前账号，可见范围为「${audiences[confirm.post.visibility]}」，共 ${confirm.post.images.length} 张配图。`:confirm?.post.status==='sent'?'会调用 NapCat 删除该账号已发布的这条说说。':'内容会保留为已取消记录，不再自动发送。'}</Dialog.Description><p className="qzone-post-content">{confirm?.post.content}</p><div className="dialog-actions"><Button variant="outline" disabled={!!working} onClick={()=>setConfirm(null)}>返回</Button><Button variant={confirm?.kind==='delete'?'destructive':'default'} disabled={!!working} onClick={()=>action('confirm',async()=>{const c=confirm;if(c.kind==='publish')await api(`/qzone/posts/${c.post.id}/publish`,'POST');else await api(`/qzone/posts/${c.post.id}`,'DELETE');setConfirm(null);if(editing===c.post.id){setEditing(null);setDraft(structuredClone(blank));setWhen('')}},confirm?.kind==='publish'?'已加入发布队列':'操作已完成')}>{working==='confirm'&&<LoaderCircle size={14} className="spin" />}{confirm?.kind==='publish'?'确认发布':'确认操作'}</Button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>
}
