import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, Loader2, RefreshCw, X } from 'lucide-react'
import { Dialog } from 'radix-ui'
import { Button } from '@/components/ui/button'
import { Notice } from './components/console'
import BrowserViewer from './BrowserViewer'
import BrowserDouyin from './BrowserDouyin'
import './browser.css'

export default function BrowserPage({ api, botId, notify }) {
  const [environment, setEnvironment] = useState(null), [checking, setChecking] = useState(true), [open, setOpen] = useState(true), [error, setError] = useState('')
  const generation = useRef(0)
  const check = useCallback(async (force = false) => {
    const epoch = ++generation.current
    setOpen(true); setChecking(true); setError('')
    try {
      // Ask the independent environment endpoint first: status needs a running
      // session service and cannot diagnose a missing Node installation.
      const report = await api('/browser/environment', force ? 'POST' : 'GET', force ? {} : undefined)
      if (epoch !== generation.current) return
      setEnvironment(report)
    } catch (e) { if (epoch === generation.current) { setEnvironment(null); setError(e.message) } }
    finally { if (epoch === generation.current) setChecking(false) }
  }, [api])
  useEffect(() => { check(); return () => { generation.current++ } }, [check])
  useEffect(() => {
    if (checking || environment?.state !== 'ready') return
    const timer = setTimeout(() => setOpen(false), 850)
    return () => clearTimeout(timer)
  }, [checking, environment])
  const ready = environment?.state === 'ready'
  return <div className="browser-page">
    <BrowserDouyin {...{api, notify}} onCheck={() => check(true)}>
      <BrowserViewer key={botId} {...{api, botId, notify}} ready={ready} onCheck={() => check(true)}/>
    </BrowserDouyin>
    <Dialog.Root open={open} onOpenChange={setOpen}><Dialog.Portal><Dialog.Overlay className="sheet-overlay"/><Dialog.Content className="browser-environment-dialog">
      <div className="browser-dialog-heading"><div><Dialog.Title>{checking ? '正在准备浏览器' : ready ? '环境已就绪' : '运行环境需要处理'}</Dialog.Title><Dialog.Description>检查运行服务、Node.js 与 Google Chrome</Dialog.Description></div><Dialog.Close asChild><Button size="icon-sm" variant="ghost" aria-label="关闭检测窗口"><X size={16}/></Button></Dialog.Close></div>
      {checking ? <div className="browser-check-loading" role="status"><Loader2 className="browser-spin" size={18}/>正在连接宿主并检查运行环境…</div> : <dl className="browser-checks">{environment?.checks?.map((item, index) => <div key={item.id} style={{animationDelay:`${index * 70}ms`}}><span data-state={item.state}>{item.state === 'passed' ? <Check size={16}/> : item.state === 'pending' ? <Loader2 size={16}/> : <X size={16}/>}</span><dt>{item.label}</dt><dd>{item.detail}</dd></div>)}</dl>}
      {error && <Notice alert>{error}</Notice>}
      {!checking && !ready && <div className="browser-install-help">
        {environment?.state === 'needs_install' ? <><b>安装 Google Chrome</b><p>下载并按安装器提示完成安装，然后回到这里重新检测。</p><Button asChild size="sm"><a href="https://www.google.cn/chrome/" target="_blank" rel="noreferrer">前往 Chrome 中国官网</a></Button></> : <><b>先打开本机的「启动浏览器.command」</b><p>启动入口会在运行服务之前检查 Node.js。缺少或版本不兼容时，会打开官方安装页面；安装完成后回到启动窗口按回车即可重新检测。依赖就绪后自动启动服务。</p><p>Node.js 已安装但这里仍无法连接时，请查看启动窗口的错误，并检查后台的运行时连接配置。浏览器页面无法直接检测宿主是否安装 Node.js。</p><Button asChild size="sm" variant="outline"><a href="https://nodejs.org/en/download" target="_blank" rel="noreferrer">Node.js 官方下载</a></Button></>}
      </div>}
      <div className="browser-dialog-footer"><span role="status">{ready && !checking ? '检测通过，即将进入工作台' : checking ? '检测中…' : '安装或启动后重新检测'}</span><Button size="sm" variant="outline" disabled={checking} onClick={() => check(true)}><RefreshCw size={14}/>重新检测</Button></div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>
}
