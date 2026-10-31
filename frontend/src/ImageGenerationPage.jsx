import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { LoaderCircle, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Panel, Field } from './components/console'
import './image-generation.css'

export function ImageModelSelector({ config, providers, update, disabled }) {
  if (!config) return null
  return <fieldset className="form-grid border-0 m-0 p-0" disabled={disabled}>
    <Field label="生图供应商" id="image-provider" hint="与对话、TTS、STT 独立；先在共享供应商中添加图片生成连接。"><select id="image-provider" className="provider-select" value={config.provider_id} onChange={e=>{const p=providers.find(p=>p.id===e.target.value);update('provider_id',e.target.value);update('model',p?.default_model||'');update('enabled',false)}}><option value="">不使用</option>{providers.filter(p=>p.purpose==='image').map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
    <Field label="生图模型名称 / 接入点 ID" id="image-model" hint="OpenAI 填写支持参考图的 GPT Image 模型；火山方舟填写已开通的多图参考 Seedream 模型或接入点 ID。"><Input id="image-model" maxLength={200} disabled={!config.provider_id} value={config.model} onChange={e=>{update('model',e.target.value);if(!e.target.value.trim())update('enabled',false)}}/></Field>
  </fieldset>
}

const slots = [['front','正面'],['side','侧面'],['back','背面'],['sheet','三视图合图']]

export default function ImageGenerationPage({ config, providers, update, active, busy, dirty, api, notify }) {
  const { botId } = useParams()
  const [refs,setRefs]=useState([]),[loading,setLoading]=useState(true),[working,setWorking]=useState(''),[error,setError]=useState('')
  const [slot,setSlot]=useState('sheet')
  useEffect(()=>{if(refs.length)setSlot(current=>refs.some(r=>r.slot==='sheet')?'sheet':current==='sheet'?'front':current)},[refs])
  const refresh=()=>api('/image-generation').then(data=>{setRefs(data.references);setError('')}).catch(e=>setError(e.message)).finally(()=>setLoading(false))
  useEffect(()=>{let live=true;setLoading(true);api('/image-generation').then(data=>{if(live){setRefs(data.references);setError('')}}).catch(e=>{if(live)setError(e.message)}).finally(()=>{if(live)setLoading(false)});return()=>{live=false}},[api])
  const disabled=active||!!busy||!!working
  const complete=refs.some(r=>r.slot==='sheet')||['front','side','back'].every(slot=>refs.some(r=>r.slot===slot))
  async function upload(file){
    if(!file)return
    if(file.size>6*1024*1024){setError('单张参考图不能超过 6 MB');return}
    setWorking('upload');setError('')
    try{const bytes=new Uint8Array(await file.arrayBuffer());let text='';for(let i=0;i<bytes.length;i+=32768)text+=String.fromCharCode(...bytes.subarray(i,i+32768));const data=await api('/image-generation/references','POST',{slot,image:btoa(text)});setRefs(data.references);notify('参考图已保存。每次生成都会实际提交给所选生图供应商。')}
    catch(e){setError(e.message)}finally{setWorking('')}
  }
  async function remove(ref){
    if(!window.confirm(`删除${slots.find(([id])=>id===ref.slot)?.[1]}参考图？删除后无法撤销，需要重新上传。`))return
    setWorking(ref.id);setError('')
    try{await api(`/image-generation/references/${ref.id}`,'DELETE');await refresh();notify('参考图已删除')}
    catch(e){setError(e.message)}finally{setWorking('')}
  }
  return <div className="page-stack image-generation-page">
    <Panel title="QQ 图片创作" subtitle="自然语言提出画面要求，生成后直接向当前 QQ 会话发送图片，不只是返回链接。修改配置前请停止机器人。">
      <div className="toggle-row"><div><b>开启图片创作</b><p>默认关闭。不会在普通聊天、定时问候或主动接话中随机生图。</p></div><Switch aria-label="开启图片创作" checked={config.enabled} disabled={disabled||!config.provider_id||!config.model.trim()||!config.base_prompt.trim()} onCheckedChange={v=>update('enabled',v)}/></div>
      <ImageModelSelector {...{config,providers,update,disabled}}/>
      <p className="text-muted-foreground">没有生图供应商？<Link className="subtle-link" to="/providers" onClick={e=>{if(dirty&&!window.confirm('有未保存的配置，仍要离开吗？'))e.preventDefault()}}>前往共享供应商添加 OpenAI / 火山引擎连接 →</Link></p>
    </Panel>
    <Panel title="基础风格与角色" subtitle="以下提示词会与本次 QQ 用户的画面要求一起提交给生图模型，不会自动读取私人记忆、日记或完整聊天历史。">
      <fieldset className="image-fields" disabled={disabled}>
        <Field label="基础风格提示词（开启前必填）" id="image-base-prompt" hint="建议描述摄影 / 绘画风格、光线、镜头、色调、构图、质感和不希望出现的元素。"><textarea id="image-base-prompt" className="provider-select" rows={5} maxLength={6000} value={config.base_prompt} onChange={e=>update('base_prompt',e.target.value)} placeholder="例如：自然生活摄影，柔和日光，35mm 镜头，真实肤质，低饱和暖色，不添加文字或拼图。"/></Field>
        <Field label="角色固定外貌（可选）" id="image-character-prompt" hint="配合三视图描述发型、发色、瞳色、脸型、体型和标志性配饰；不要填个人隐私或 API Key。"><textarea id="image-character-prompt" className="provider-select" rows={3} maxLength={3000} value={config.character_prompt} onChange={e=>update('character_prompt',e.target.value)} placeholder="例如：与参考图同一角色，黑色齐肩发、棕色眼睛，保留左侧发夹。"/></Field>
        <div className="toggle-row"><div><b>要求完整角色三视图</b><p>默认开启。缺少正面 / 侧面 / 背面时不会调用付费接口；一张合图也可以。关闭后可用于风景、物品等非角色创作，已有参考图仍会随请求提交。</p></div><Switch aria-label="要求完整角色三视图" checked={config.require_reference} onCheckedChange={v=>update('require_reference',v)}/></div>
      </fieldset>
    </Panel>
    <Panel title="角色三视图" subtitle="二选一：上传正面、侧面、背面各一张，或上传一张同时包含三个视角的合图。参考图独立保存；更换 QQ 接入账号后需重新上传。">
      {error&&<p role="alert" className="provider-test-message">{error}<Button variant="ghost" size="sm" onClick={refresh} disabled={!!working}>刷新</Button></p>}
      {loading?<p>正在加载参考图…</p>:<>
        <p className="image-reference-status">{complete?'参考图已齐全':'参考图待补齐'} · {refs.length} 张 <small>系统检查视图槽位，不自动判断合图中是否真的包含三个视角。</small></p>
        {refs.length>0&&<div className="image-reference-grid">{refs.map(ref=><div className="image-reference-card" key={ref.id}><img src={`/api/bots/${encodeURIComponent(botId)}/image-generation/references/${ref.id}`} alt={`角色${slots.find(([id])=>id===ref.slot)?.[1]}参考图`}/><div><b>{slots.find(([id])=>id===ref.slot)?.[1]}</b><small>{ref.width} × {ref.height}</small><Button variant="destructive-outline" size="sm" disabled={disabled||dirty} onClick={()=>remove(ref)}><Trash2 size={13}/>删除</Button></div></div>)}</div>}
        <div className="image-reference-upload"><Field label="视图类型" id="image-reference-slot"><select id="image-reference-slot" className="provider-select" disabled={disabled||dirty} value={slot} onChange={e=>setSlot(e.target.value)}>{slots.filter(([id])=>!refs.length||(id==='sheet')===refs.some(r=>r.slot==='sheet')).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></Field><Field label="上传参考图（同视图会替换）" id="image-reference-file" hint="静态 PNG / JPEG / WebP，单张 ≤ 6 MB；会去除元数据并缩放至最长边 2048。"><Input key={refs.map(r=>r.id).join('')+slot} id="image-reference-file" type="file" accept="image/png,image/jpeg,image/webp" disabled={disabled||dirty} onChange={e=>{upload(e.target.files?.[0]);e.target.value=''}}/></Field>{working==='upload'&&<LoaderCircle size={18} className="spin"/>}</div>
        {dirty&&<p className="text-muted-foreground">请先保存或撤销页面配置，再上传或删除参考图，以确保它绑定的是已保存的 QQ 账号。</p>}
      </>}
      <div className="image-guide"><h3>怎样准备三视图？</h3><p>使用同一角色的清晰正面、侧面、背面全身图，保持相同发型、服装、比例和均匀光线，背景尽量简洁；合图请明确标注每个视角。避免遮脸、强滤镜、多人或互相冲突的外貌。只上传自己有权使用、且相关人物同意用于生成的图片。</p><p>参考图用于提高角色一致性，并非角色训练或绝对锁脸。复杂姿势、换衣、风格变化仍可能导致脸部或细节偏差，请人工检查结果。不保证精确复制，也不自动生成或验证三视图。</p></div>
    </Panel>
    <Panel title="触发与费用控制" subtitle="命令 /画图 或 /生图 直接发起；自然语言结合当前会话近期对话理解请求。每次一张，全 Bot 同时处理一个生图请求。">
      <fieldset className="image-fields" disabled={disabled}>
        <div className="toggle-row"><div><b>自然语言触发</b><p>使用当前对话模型理解请求，也可承接“换成蓝裙子，再来张侧脸”等近期图片要求；指代不清会追问。能力询问、引用示例和明确拒绝不会生图。识别和成片理解会产生对话模型用量；/画图 可跳过意图识别。</p></div><Switch aria-label="生图自然语言触发" checked={config.imperative_trigger} onCheckedChange={v=>update('imperative_trigger',v)}/></div>
        <div className="form-grid"><Field label="使用范围" id="image-scope"><select id="image-scope" className="provider-select" value={config.scope} onChange={e=>update('scope',e.target.value)}><option value="private">仅私聊</option><option value="private_and_group">私聊和群聊</option></select></Field><Field label="成片比例" id="image-aspect"><select id="image-aspect" className="provider-select" value={config.aspect} onChange={e=>update('aspect',e.target.value)}><option value="square">正方形</option><option value="portrait">竖版</option><option value="landscape">横版</option></select></Field>{[['cooldown_seconds','每位用户冷却（秒）',0,86400],['daily_limit','全 Bot 24 小时调用上限',1,500],['user_daily_limit','每位用户 24 小时调用上限',1,100],['timeout','生图超时（秒）',15,180]].map(([key,label,min,max])=><Field key={key} label={label} id={`image-${key}`}><Input id={`image-${key}`} type="number" min={min} max={max} step={1} value={config[key]} onChange={e=>update(key,e.target.value)}/></Field>)}</div>
      </fieldset>
      <div className="image-guide"><h3>使用前请了解</h3><p>先添加生图供应商并填写 API Key 和模型 ID → 选择此 Bot 的生图模型 → 填写基础风格、上传三视图 → 开启并保存 → 启动机器人 → 在 QQ 发“/画图 在海边散步的照片”。仅开启群聊范围还不够，QQ 群回复与群聊参与策略也必须允许回复；自动接话不会触发生图。</p><p>生成请求会把基础提示词、角色外貌、本次画面要求及已上传的参考图发送给所选第三方服务商。生成后会将实际成片交给当前支持视觉的对话模型，结合角色人格及同一会话近期对话准备回应；确认图片送达后再发文字。不支持看图或理解失败时，只作不描述画面细节的简短回应。请确认其隐私条款、开通权限、额度与当地规则；图片会发送到当前 QQ 私聊或群聊。每次调用和页面生图测试可能产生费用，失败或超时也可能计费，调用上限统计所有已提交尝试。</p><p>生图可能等待较久，受服务商审核、模型能力、网络与 QQ 回复时限约束。不下载模型返回的外部链接；只接受图片数据。超时、服务重启或 QQ 送达状态不明时不自动重试，避免重复计费与重复发送。服务不会把临时成片当作角色参考图，也不会自动发布到 QQ 空间。</p></div>
    </Panel>
  </div>
}
