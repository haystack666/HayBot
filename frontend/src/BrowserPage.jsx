import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Panel, Notice } from './components/console'
import BrowserViewer from './BrowserViewer'
import './browser.css'

export default function BrowserPage({ api, botId, notify }) {
  const [configured, setConfigured] = useState(null), [environment, setEnvironment] = useState(null), [checking, setChecking] = useState(false), [details, setDetails] = useState(false), [error, setError] = useState('')
  const check = useCallback(async (force = false) => {
    setChecking(true); setError('')
    try {
      const status = await api('/browser')
      setConfigured(status.configured)
      if (status.configured) {
        const report = await api('/browser/environment', force ? 'POST' : 'GET', force ? {} : undefined)
        setEnvironment(report); setDetails(report.state !== 'ready')
      } else { setEnvironment(null) }
    } catch (error) { setEnvironment(null); setError(error.message) }
    finally { setChecking(false) }
  }, [api])
  useEffect(() => { check() }, [check])
  const labels = { ready: '环境就绪', needs_install: '待安装 Chrome', needs_repair: '环境待修复', checking: '检测中' }
  return <div className="page-stack browser-page">
    <Panel title="运行环境" action={<div className="action-row"><span className="browser-env-state" role="status">{checking ? '检测中…' : labels[environment?.state] || (error ? '未连接' : configured === false ? '未配置' : '待检测')}</span><Button size="sm" variant="outline" disabled={checking} onClick={() => check(true)}><RefreshCw size={14}/>重新检测</Button></div>}>
      {error && <Notice alert>{error}</Notice>}
      {configured === false && <Notice>请在后台配置宿主浏览器运行时的地址和访问码，然后重新检测。</Notice>}
      {environment && <>
        <div className="action-row">{environment.state === 'needs_install' && <Button asChild size="sm"><a href="https://www.google.cn/chrome/" target="_blank" rel="noreferrer">安装 Google Chrome</a></Button>}<Button size="sm" variant="ghost" aria-expanded={details} onClick={() => setDetails(v => !v)}>{details ? '收起检测项' : '查看检测项'}</Button></div>
        {details && <dl className="browser-checks">{environment.checks.map(item => <div key={item.id}><dt>{item.label}</dt><dd>{item.detail}</dd><span data-state={item.state}>{item.state === 'passed' ? '通过' : item.state === 'failed' ? '未通过' : '待检查'}</span></div>)}</dl>}
      </>}
    </Panel>
    {configured && <BrowserViewer key={botId} {...{api, botId, notify}} ready={environment?.state === 'ready' && !checking}/>}
  </div>
}
