import { useEffect, useRef, useState } from 'react'
import { Dialog } from 'radix-ui'
import { CheckCircle2, CircleHelp, ExternalLink, LoaderCircle, QrCode, RefreshCw, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Field } from './components/console'

export default function QQConnectDialog({ open, onOpenChange, api, onConnected, onManual }) {
  const [binding, setBinding] = useState(null), [name, setName] = useState(''), [image, setImage] = useState(''), [error, setError] = useState(''), [working, setWorking] = useState('')
  const session = useRef(''), epoch = useRef(0), opened = useRef(open)
  opened.current = open
  async function discard(id) { if (id) { try { await api(`/qq/qr/${id}`, 'DELETE') } catch {} } }
  async function start() {
    const version = ++epoch.current
    setWorking('start'); setError(''); setBinding(null); setImage('')
    const previous = session.current; session.current = ''
    await discard(previous)
    try {
      const result = await api('/qq/qr', 'POST')
      if (version !== epoch.current || !opened.current) { discard(result.session_id); return }
      session.current = result.session_id; setBinding(result)
    } catch (error) { if (version === epoch.current && opened.current) setError(error.message) }
    finally { if (version === epoch.current && opened.current) setWorking('') }
  }
  useEffect(() => {
    if (!open) return
    setName(''); start()
    return () => { epoch.current += 1; const id = session.current; session.current = ''; discard(id) }
  }, [open, api])
  useEffect(() => {
    setImage('')
    if (!binding?.qr_url) return
    let live = true
    import('qrcode').then(module => (module.default || module).toDataURL(binding.qr_url, { width: 280, margin: 2, errorCorrectionLevel: 'M' })).then(url => { if (live) setImage(url) }).catch(() => { if (live) setError('二维码图片生成失败，可使用下方 QQ 官方授权链接') })
    return () => { live = false }
  }, [binding?.qr_url])
  useEffect(() => {
    if (!open || !binding?.session_id || !['waiting', 'authorized'].includes(binding.state)) return
    const id = binding.session_id, version = epoch.current
    let live = true, pending = false
    async function poll() {
      if (pending) return
      pending = true
      try {
        const result = await api(`/qq/qr/${id}`)
        if (live && epoch.current === version) { setBinding(result); setError('') }
      } catch (error) {
        if (live && epoch.current === version) {
          setError(error.message)
          if (error.status === 404 || error.status === 401) setBinding(old => ({ ...old, state: 'error', qr_url: '' }))
        }
      } finally { pending = false }
    }
    const timer = setInterval(poll, 2000)
    return () => { live = false; clearInterval(timer) }
  }, [open, api, binding?.session_id, binding?.state])
  async function complete() {
    if (!binding) return
    setWorking('complete'); setError('')
    try {
      const result = binding.state === 'completed' ? binding : await api(`/qq/qr/${binding.session_id}/complete`, 'POST', { name: name.trim(), replace_existing: !!binding.existing_bot })
      setBinding(result); await onConnected(result.bot_id)
    } catch (error) { setError(error.message) } finally { setWorking('') }
  }
  const existing = binding?.existing_bot
  const cannotReplace = existing && (existing.archived || existing.state !== 'stopped')
  return <Dialog.Root open={open} onOpenChange={value => { if (working !== 'complete') onOpenChange(value) }}><Dialog.Portal><Dialog.Overlay className="sheet-overlay" /><Dialog.Content className="bot-dialog qq-connect-dialog"><Dialog.Title>扫码添加 QQ 机器人</Dialog.Title><Dialog.Description>使用手机 QQ 扫码并完成官方授权，自动获取凭证；完成添加后立即启动并连接 QQ。</Dialog.Description>
    <Field label="机器人名称（可选）" id="qr-bot-name" hint="留空将按 AppID 自动命名，之后可以修改。"><Input id="qr-bot-name" maxLength={40} value={name} onChange={event => setName(event.target.value)} placeholder="例如：工作助手" disabled={!!working} /></Field>
    <div className="qq-qr-stage" aria-live="polite">{working === 'start' ? <><LoaderCircle className="spin" size={28} /><p>正在获取 QQ 官方二维码…</p></> : binding?.state === 'waiting' ? <>{image ? <img src={image} width="250" height="250" alt="QQ 官方机器人授权二维码" /> : <LoaderCircle className="spin" size={28} />}<p>{binding.message}</p><a className="subtle-link" href={binding.qr_url} target="_blank" rel="noreferrer">打开 QQ 官方授权页面<ExternalLink size={12} /></a></> : ['authorized', 'completed'].includes(binding?.state) ? <><CheckCircle2 size={30} /><strong>{binding.state === 'completed' ? '已添加，正在连接 QQ' : 'QQ 授权成功'}</strong><p>AppID · {binding.app_id}</p></> : <><QrCode size={30} /><p>{binding?.message || '暂未获得二维码，请重试'}</p></>}</div>
    {existing && <div className="notice qq-existing"><CircleHelp size={15} /><span>此 AppID 已属于“{existing.name}”，将更新该机器人的凭证，保留原配置和聊天记录，不创建重复 Bot。{existing.archived ? '请先在机器人管理中恢复该机器人。' : existing.state !== 'stopped' ? '请先在其他页面停止该机器人，再回到这里确认。' : '请确认更新。'}</span></div>}
    {error && <p className="qq-connect-error" role="alert">{error}</p>}
    <p className="qq-connect-hint">QQ 授权页可能将 HayBot 显示为“第三方机器人”。请核对官方域名 q.qq.com 后授权；凭证仅在后台解密、加密保存。二维码过期或关闭窗口后需重新扫码。</p>
    <div className="qq-connect-actions"><Button type="button" variant="ghost" disabled={!!working} onClick={onManual}>改用手动添加</Button>{!['authorized', 'completed'].includes(binding?.state) && <Button type="button" variant="outline" disabled={!!working} onClick={start}><RefreshCw size={14} />重新生成二维码</Button>}{['authorized', 'completed'].includes(binding?.state) && <Button disabled={!!working || !!cannotReplace} onClick={complete}>{working === 'complete' && <LoaderCircle size={14} className="spin" />}{binding.state === 'completed' ? '打开机器人配置' : existing ? '更新凭证并启动' : '完成添加并启动'}</Button>}</div>
    <Dialog.Close asChild><Button className="sheet-close" variant="ghost" size="icon-sm" aria-label="关闭扫码窗口" disabled={working === 'complete'}><X size={16} /></Button></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>
}
