import { useEffect, useRef, useState } from 'react'
import { Dialog } from 'radix-ui'
import { Check, CircleHelp, Cpu, KeyRound, LoaderCircle, Pencil, Plus, RefreshCw, Server, Sparkles, Trash2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { Panel, Field } from './components/console'
import MemoryModelSelectors from './MemoryModelSelectors'
import { providerPayload } from './lib/memory-config'

export const providerTypes = {
  openai_embedding: { title: 'OpenAI Embedding', purpose: 'embedding', url: 'https://api.openai.com/v1', hint: '支持 OpenAI 与兼容嵌入接口，使用 /embeddings。' },
  gemini_embedding: { title: 'Gemini Embedding', purpose: 'embedding', url: 'https://generativelanguage.googleapis.com/v1beta', hint: '使用 Gemini 原生嵌入接口，自动区分入库与查询任务。' },
  ollama_embedding: { title: 'Ollama Embedding', purpose: 'embedding', url: 'http://ollama:11434', hint: '支持本地或外部 Ollama。原生使用 /api/embed，以 /v1 结尾时使用兼容嵌入接口。' },
  dashscope_embedding: { title: 'DashScope Embedding', purpose: 'embedding', url: 'https://dashscope.aliyuncs.com/api/v1', hint: '使用 DashScope 原生文本嵌入接口。地址按 API Key 所属地域与业务空间填写。' },
  dashscope_rerank: { title: 'DashScope Rerank', purpose: 'rerank', url: 'https://dashscope.aliyuncs.com/api/v1', hint: '使用 DashScope 原生文本重排接口，填写对应地域与业务空间地址。' },
  xinference_rerank: { title: 'Xinference Rerank', purpose: 'rerank', url: 'http://host.docker.internal:9997/v1', hint: '使用 /v1/rerank，模型名称填写已经部署的模型 UID。' },
  ollama: { title: 'Ollama', url: 'http://ollama:11434', hint: '本地与外部 Ollama 共用此类型。Docker 内置：http://ollama:11434；宿主机：http://host.docker.internal:11434；外部服务填写实际地址。以 /v1 结尾时自动使用兼容接口。' },
  openai_chat: { title: 'OpenAI Compatible', url: 'https://api.openai.com/v1', hint: '使用 Chat Completions 协议。填写 API 基础地址，例如 https://api.openai.com/v1；兼容服务请填写其基础地址。' },
  openai_responses: { title: 'OpenAI Responses', url: 'https://api.openai.com/v1', hint: '使用 Responses 协议。填写 API 基础地址，例如 https://api.openai.com/v1。' },
  anthropic: { title: 'Anthropic Compatible', url: 'https://api.anthropic.com/v1', hint: '使用 Messages 协议，API Key 通过 x-api-key 发送。填写基础地址，例如 https://api.anthropic.com/v1。' },
  deepseek: { title: 'DeepSeek', url: 'https://api.deepseek.com', hint: '使用 DeepSeek Chat Completions 协议。官方地址为 https://api.deepseek.com，也可配置兼容服务。' },
}
const purposes = { chat: '对话', embedding: 'Embedding 嵌入', rerank: 'Rerank 重排' }
const initial = { purpose: 'chat', embedding_dimensions: null, name: '', default_model: '', type: 'ollama', base_url: providerTypes.ollama.url, api_key: '', clear_api_key: false, vision: true, ollama_api: 'auto', chat_thinking: false, send_temperature: true, token_limit_field: 'max_tokens', anthropic_version: '2023-06-01' }
function editable(provider) { const { id, api_key_set, used_by, ...config } = provider; return { ...initial, ...config, api_key: '' } }

export default function ProvidersPage({ providers, refreshProviders, globalApi, config, update, active, busy, dirty, notify }) {
  const [editor, setEditor] = useState(null), [draft, setDraft] = useState(initial), [working, setWorking] = useState(''), [error, setError] = useState('')
  const [models, setModels] = useState([]), [connection, setConnection] = useState(''), [result, setResult] = useState(null), [modelBusy, setModelBusy] = useState(''), [deleteId, setDeleteId] = useState('')
  const selectedId = config?.ollama.provider_id || '', currentId = useRef(selectedId), live = useRef(true), testEpoch = useRef(0)
  currentId.current = selectedId
  const provider = providers.find(item => item.id === selectedId)
  const locked = editor?.used_by?.some(bot => bot.state !== 'stopped')
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])
  useEffect(() => { testEpoch.current += 1; setModels([]); setConnection(''); setResult(null); setModelBusy('') }, [selectedId, providers])
  function openEditor(item) { setEditor(item || { id: '' }); setDraft(item ? editable(item) : { ...initial }); setError(''); setDeleteId('') }
  function change(key, value) { setDraft(old => ({ ...old, [key]: value })); setError('') }
  function changeType(type) {
    setDraft(old => ({ ...old, type, purpose: providerTypes[type].purpose || 'chat', base_url: !old.base_url || old.base_url === providerTypes[old.type].url ? providerTypes[type].url : old.base_url, api_key: '', clear_api_key: false, vision: type !== 'deepseek', send_temperature: type !== 'openai_responses' }))
    setError('')
  }
  async function saveProvider(event) {
    event.preventDefault(); setWorking('save'); setError('')
    try { await globalApi(editor.id ? `/providers/${editor.id}` : '/providers', editor.id ? 'PUT' : 'POST', providerPayload(draft)); await refreshProviders(); setEditor(null); notify('供应商已保存') }
    catch (error) { setError(error.message) } finally { setWorking('') }
  }
  async function testDraft() {
    setWorking('test'); setError('')
    try {
      const payload = providerPayload(draft)
      if (draft.purpose !== 'chat' && !draft.default_model.trim()) throw new Error('请填写默认模型名称，再进行实际调用测试')
      const response = await globalApi(`/providers/${draft.purpose === 'chat' ? 'test' : 'test-generation'}${editor.id ? `?provider_id=${editor.id}` : ''}`, 'POST', draft.purpose === 'chat' ? payload : { ...payload, model: draft.default_model.trim() })
      setError(response.message || response.content)
    }
    catch (error) { setError(error.message) } finally { setWorking('') }
  }
  async function testSelected(generate = false) {
    if (!provider) return
    const id = selectedId, epoch = testEpoch.current
    setModelBusy(generate ? 'generate' : 'models'); setConnection(''); setResult(null)
    try {
      const payload = editable(provider)
      if (generate) {
        if (!config.ollama.model.trim()) throw new Error('请先选择或填写模型名称')
        if ([config.ollama.temperature, config.ollama.timeout, config.ollama.max_tokens].some(value => String(value).trim() === '')) throw new Error('请填写温度、超时和输出 Token 上限')
        const response = await globalApi(`/providers/test-generation?provider_id=${id}`, 'POST', { ...payload, model: config.ollama.model.trim(), temperature: Number(config.ollama.temperature), timeout: Number(config.ollama.timeout), max_tokens: Number(config.ollama.max_tokens) })
        if (live.current && currentId.current === id && testEpoch.current === epoch) { setResult(response); setConnection('生成测试成功') }
      } else {
        const response = await globalApi(`/providers/test?provider_id=${id}`, 'POST', payload)
        if (live.current && currentId.current === id && testEpoch.current === epoch) { setModels(response.models); setConnection(response.message) }
      }
    } catch (error) { if (live.current && currentId.current === id && testEpoch.current === epoch) setConnection(error.message) }
    finally { if (live.current && currentId.current === id && testEpoch.current === epoch) setModelBusy('') }
  }
  async function removeProvider() {
    setWorking('delete'); setError('')
    try { await globalApi(`/providers/${editor.id}`, 'DELETE'); await refreshProviders(); setEditor(null); notify('供应商已删除') }
    catch (error) { setError(error.message) } finally { setWorking('') }
  }
  return <div className="page-stack providers-page">
    {config && <Panel title="当前机器人的模型" subtitle="每个 Bot 独立选择供应商、模型与生成参数；供应商连接在下方统一管理。">
      <fieldset className="form-grid border-0 m-0 p-0" disabled={active || !!busy}>
        <Field label="模型供应商" id="bot-provider" full hint="可以添加多个同类型供应商，并用名称区分本地、外部服务或不同账号。"><select className="provider-select" id="bot-provider" value={selectedId} onChange={event => { update('ollama', 'provider_id', event.target.value); update('ollama', 'model', providers.find(item => item.id === event.target.value)?.default_model || '') }}><option value="" disabled>选择模型供应商</option>{providers.filter(item => !item.purpose || item.purpose === 'chat').map(item => <option value={item.id} key={item.id}>{item.name} · {providerTypes[item.type]?.title}</option>)}</select></Field>
        <Field label="使用模型" id="provider-model" hint="从下方模型列表选择，也可手动填写模型名称或模型别名。"><Input id="provider-model" value={config.ollama.model} onChange={event => update('ollama', 'model', event.target.value)} placeholder="选择或填写模型名称" /></Field>
        <Field label="请求超时（秒）" id="provider-timeout" hint="默认 120 秒，可设 5–600 秒（最长 10 分钟）。QQ 回复仍受消息有效期限制。"><Input id="provider-timeout" type="number" min="5" max="600" value={config.ollama.timeout} onChange={event => update('ollama', 'timeout', event.target.value)} /></Field>
        <Field label="温度" id="provider-temperature" hint={provider && !provider.send_temperature || provider?.type === 'anthropic' && provider.anthropic_version === '2026-10-21' ? '此供应商关闭温度参数，实际使用服务默认值。' : provider?.type === 'anthropic' ? '0–1，较低时回答更稳定。' : '0–2，较低时回答更稳定。'}><Input id="provider-temperature" type="number" min="0" max={provider?.type === 'anthropic' ? '1' : '2'} step="0.1" value={config.ollama.temperature} onChange={event => update('ollama', 'temperature', event.target.value)} /></Field>
        <Field label="输出 Token 上限" id="provider-max-tokens" hint="128–32768，默认 1024；推理模型可适当增大，以留出思考与正文的预算。"><Input id="provider-max-tokens" type="number" min="128" max="32768" value={config.ollama.max_tokens} onChange={event => update('ollama', 'max_tokens', event.target.value)} /></Field>
      </fieldset>
      {provider && <div className="provider-current"><Server size={16} /><span><b>{provider.name}</b><small>{provider.base_url}</small></span><Badge variant="outline">{providerTypes[provider.type]?.title}</Badge></div>}
      <div className="action-row mt-5"><Button variant="outline" disabled={!provider || !!modelBusy} onClick={() => testSelected()}>{modelBusy === 'models' ? <LoaderCircle className="spin" size={14} /> : <RefreshCw size={14} />}获取模型列表</Button><Button variant="outline" disabled={!provider || !config.ollama.model.trim() || !!modelBusy} onClick={() => testSelected(true)}>{modelBusy === 'generate' ? <LoaderCircle className="spin" size={14} /> : <Sparkles size={14} />}生成测试</Button><small className="text-muted-foreground">使用当前填写的模型参数，测试不会发送 QQ 消息。</small></div>
      {connection && <p className="provider-test-message" role="status">{connection}</p>}
      {result && <div className="provider-test-result"><p>{result.content}</p><small>本次测试：输入 {result.input_tokens} / 输出 {result.output_tokens} Token；不计入 Bot 聊天统计。</small></div>}
      {models.length > 0 && <div className="model-list mt-5">{models.map(model => <Button key={model} title={model} className="model-choice" size="sm" variant={config.ollama.model === model ? 'default' : 'outline'} disabled={active || !!busy} onClick={() => update('ollama', 'model', model)}><Cpu size={12} /><span>{model}</span></Button>)}</div>}
    </Panel>}
    {config && <Panel title="当前机器人的记忆模型" subtitle="与对话模型独立配置；可共用供应商连接，用户记忆始终隔离。"><MemoryModelSelectors config={config.memory} providers={providers} update={(key, value) => update('memory', key, value)} disabled={active || !!busy} /></Panel>}
    <Panel title="供应商连接" subtitle="所有 Bot 共用的连接目录 · API Key 加密保存，不回传原文" action={<div className="action-row"><Button variant="ghost" size="icon-sm" aria-label="刷新供应商" onClick={() => refreshProviders().catch(error => notify(error.message, true))}><RefreshCw size={14} /></Button><Button size="sm" onClick={() => openEditor()}><Plus size={14} />添加供应商</Button></div>}>
      <div className="provider-cards">{providers.map(item => <div className={`provider-card ${item.id === selectedId ? 'selected' : ''}`} key={item.id}><div className="provider-card-top"><div className="provider-card-title"><Server size={18} /><strong title={item.name}>{item.name}</strong></div><Badge variant="secondary">{providerTypes[item.type]?.title}</Badge></div><p className="provider-address" title={item.base_url}>{item.base_url}</p>{item.default_model && <p className="provider-default-model" title={item.default_model}>默认模型 · {item.default_model}</p>}<div className="provider-card-meta"><span><KeyRound size={12} />{item.api_key_set ? '已保存 API Key' : '未设置 API Key'}</span><span>{item.used_by.length} 个 Bot 使用</span></div><div className="provider-card-actions">{config && (!item.purpose || item.purpose === 'chat') && <Button size="sm" variant="outline" disabled={active || !!busy || item.id === selectedId} onClick={() => { update('ollama', 'provider_id', item.id); update('ollama', 'model', item.default_model || '') }}>{item.id === selectedId ? <Check size={13} /> : <Cpu size={13} />}{item.id === selectedId ? '当前选择' : '为此 Bot 使用'}</Button>}<Button variant="ghost" size="sm" onClick={() => openEditor(item)} aria-label={`编辑 ${item.name}`}><Pencil size={13} />编辑</Button></div></div>)}{!providers.length && <div className="empty">暂无供应商，添加一个连接开始配置。</div>}</div>
    </Panel><div className="notice"><CircleHelp size={16} /><span>Ollama 本地与外部连接可同时添加。服务地址由 Python 后台访问；其他协议也支持填写自建兼容服务地址。修改共享连接会影响使用它的 Bot，并清空模型上下文（聊天档案保留），请先停止相关机器人。模型须具备相应的文字或视觉能力。</span></div>
    <Dialog.Root open={!!editor} onOpenChange={open => { if (!open && !working) setEditor(null) }}><Dialog.Portal><Dialog.Overlay className="sheet-overlay" /><Dialog.Content className="dialog-content provider-dialog"><Dialog.Title>{editor?.id ? '编辑模型供应商' : '添加模型供应商'}</Dialog.Title><Dialog.Description>连接供所有 Bot 选择。名称留空自动生成，例如 ollama-1、ollama-2。</Dialog.Description><form onSubmit={saveProvider} className="provider-form"><Field label="自定义名称" id="provider-name"><Input id="provider-name" autoFocus maxLength={60} value={draft.name} onChange={event => change('name', event.target.value)} placeholder="留空自动命名" disabled={!!working} /></Field><Field label="默认模型（可选）" id="provider-default-model" hint="Bot 选择此供应商时自动填入；不会更改已保存的 Bot 模型。"><Input id="provider-default-model" maxLength={200} value={draft.default_model} onChange={event => change('default_model', event.target.value)} placeholder="例如：gemma4:latest" disabled={!!working} /></Field>{locked && <div className="notice">此连接正在被机器人使用，目前可修改名称、默认模型与对话 Thinking。</div>}<fieldset className="provider-fields" disabled={locked || !!working}>
      <Field label="模型用途" id="provider-purpose"><select className="provider-select" id="provider-purpose" value={draft.purpose} onChange={event => changeType(Object.keys(providerTypes).find(type => (providerTypes[type].purpose || 'chat') === event.target.value))}>{Object.entries(purposes).map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select></Field>
      <Field label="接口类型" id="provider-type"><select className="provider-select" id="provider-type" value={draft.type} onChange={event => changeType(event.target.value)}>{Object.entries(providerTypes).filter(([, info]) => (info.purpose || 'chat') === draft.purpose).map(([id, info]) => <option key={id} value={id}>{info.title}</option>)}</select></Field>
      <Field label="API 基础地址" id="provider-url" hint={providerTypes[draft.type].hint}><Input id="provider-url" value={draft.base_url} onChange={event => change('base_url', event.target.value)} placeholder={providerTypes[draft.type].url} required /></Field>
      {['ollama', 'ollama_embedding'].includes(draft.type) && <Field label="Ollama 接口模式" id="ollama-api-mode" hint="自动模式：/v1 地址使用 OpenAI 兼容接口，其他地址使用 Ollama 原生 API。"><select className="provider-select" id="ollama-api-mode" value={draft.ollama_api} onChange={event => change('ollama_api', event.target.value)}><option value="auto">自动识别</option><option value="native">Ollama 原生 API</option><option value="openai">OpenAI 兼容 API</option></select></Field>}
      <Field label="API Key" id="provider-key" hint={editor?.api_key_set ? '留空保留原 Key；更换地址或协议时留空会清除原 Key。勾选下方开关可主动清除。' : '可选。本地 Ollama 通常无需填写；外部服务按其要求填写。'}><Input id="provider-key" type="password" autoComplete="new-password" value={draft.api_key} onChange={event => setDraft(old => ({ ...old, api_key: event.target.value, clear_api_key: false }))} placeholder={editor?.api_key_set ? '•••••••• 已加密保存' : '填写 API Key（可选）'} /></Field>
      {editor?.api_key_set && <div className="toggle-row"><div><b>清除已保存的 API Key</b><p>保存后生效，不影响尚未保存的连接。</p></div><Switch aria-label="清除已保存的 API Key" checked={draft.clear_api_key} onCheckedChange={value => setDraft(old => ({ ...old, clear_api_key: value, api_key: '' }))} /></div>}
      {draft.purpose === 'embedding' && <Field label="向量维度（可选）" id="embedding-dimensions" hint="留空使用模型默认值。更换模型或维度后需要重建用户记忆索引。"><Input id="embedding-dimensions" type="number" min="1" max="65536" value={draft.embedding_dimensions ?? ''} onChange={event => change('embedding_dimensions', event.target.value)} /></Field>}
      {draft.purpose === 'chat' && <div className="toggle-row"><div><b>允许图片输入</b><p>所选模型需支持视觉；Ollama 还会检查模型能力。</p></div><Switch aria-label="允许图片输入" checked={draft.vision} onCheckedChange={value => change('vision', value)} /></div>}
      {draft.purpose === 'chat' && draft.type !== 'ollama' && <details className="provider-advanced"><summary>协议高级设置</summary><div className="toggle-row"><div><b>发送温度参数</b><p>若模型拒绝 temperature，可关闭使用服务默认值。</p></div><Switch aria-label="发送温度参数" checked={draft.send_temperature} onCheckedChange={value => change('send_temperature', value)} /></div>{draft.type === 'openai_chat' && <Field label="输出 Token 限制字段" id="token-limit-field" hint="一般兼容服务使用 max_tokens；要求新字段的模型使用 max_completion_tokens。"><select className="provider-select" id="token-limit-field" value={draft.token_limit_field} onChange={event => change('token_limit_field', event.target.value)}><option value="max_tokens">max_tokens</option><option value="max_completion_tokens">max_completion_tokens</option></select></Field>}{draft.type === 'anthropic' && <Field label="Anthropic API 版本" id="anthropic-version" hint="兼容服务通常使用 2023-06-01。2026-10-21 版本不发送温度参数。"><select className="provider-select" id="anthropic-version" value={draft.anthropic_version} onChange={event => change('anthropic_version', event.target.value)}><option value="2023-06-01">2023-06-01（兼容）</option><option value="2026-10-21">2026-10-21</option></select></Field>}</details>}
      </fieldset>{draft.type === 'ollama' && <div className="toggle-row"><div><b>对话 Thinking</b><p>仅控制普通聊天回复，默认关闭以减少等待。日程、记忆整理和主动消息保持原有行为；需模型支持。保存后从下一次对话请求生效。</p></div><Switch aria-label="对话 Thinking" checked={draft.chat_thinking} disabled={!!working} onCheckedChange={value => change('chat_thinking', value)} /></div>}{error && <p className="provider-test-message" role="status">{error}</p>}
      {editor?.id && !editor?.used_by?.length && <div className="provider-remove">{deleteId === editor.id ? <><p>删除“{editor.name}”的连接与密钥？此操作无法恢复。</p><Button type="button" variant="destructive" size="sm" disabled={!!working} onClick={removeProvider}>确认删除供应商</Button><Button type="button" variant="ghost" size="sm" disabled={!!working} onClick={() => setDeleteId('')}>取消删除</Button></> : <Button type="button" variant="ghost" size="sm" disabled={!!working} onClick={() => setDeleteId(editor.id)}><Trash2 size={13} />删除供应商</Button>}</div>}
      {editor?.used_by?.length > 0 && <p className="provider-usage">正在使用：{editor.used_by.map(bot => `${bot.name}${bot.archived ? '（已归档）' : ''}`).join('、')}。解除所有引用后可删除。</p>}
      <div className="dialog-actions"><Button type="button" variant="ghost" disabled={!!working} onClick={() => setEditor(null)}>取消</Button><Button type="button" variant="outline" disabled={!!working} onClick={testDraft}>{working === 'test' ? <LoaderCircle className="spin" size={13} /> : <RefreshCw size={13} />}{draft.purpose === 'chat' ? '测试连接' : '模型调用测试'}</Button><Button type="submit" disabled={!!working}>{working === 'save' && <LoaderCircle className="spin" size={13} />}保存供应商</Button></div>
    </form><Dialog.Close asChild><Button variant="ghost" size="icon-sm" className="dialog-close" aria-label="关闭对话框" disabled={!!working}><X size={16} /></Button></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>
}
