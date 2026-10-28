import { Dialog } from 'radix-ui'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Panel, Notice } from './components/console'
const names = { installed: '已安装', existing: '已保留', downloading: '下载中', installing: '安装中', queued: '排队中', needs_install: '等待安装', needs_gms: '需配套系统', failed: '安装失败', interrupted: '安装中断', not_checked: '尚未检查' }
export default function AndroidApps({ api, device, runtime, activeTask, action, working }) {
  const [apps, setApps] = useState([]), [desktop, setDesktop] = useState(null), [error, setError] = useState(''), [loaded,setLoaded] = useState(false), [confirmGms, setConfirmGms] = useState(false)
  useEffect(() => {
    if (!device) return
    let live = true
    const refresh = () => api(`/android/devices/${device.id}/apps`).then(v => { if (live) { setApps(v.apps); setDesktop(v.desktop); setLoaded(true); setError('') } }).catch(e => { if (live) setError(e.message) })
    refresh(); const timer = setInterval(refresh, 8000)
    return () => { live = false; clearInterval(timer) }
  }, [api, device?.id])
  const provisioning = apps.some(app => ['queued','downloading','installing'].includes(app.state)) || ['queued','installing'].includes(desktop?.state)
  const unavailable = !!working || !!activeTask || device?.owner_login || device?.state !== 'running' || provisioning
  return <Panel title="手机初始化与应用">
    {error && <Notice alert>{error}</Notice>}
    {!loaded && !error && <div className="empty" role="status">正在读取初始化与应用状态…</div>}
    {loaded && !apps.length && <div className="empty">还没有初始化记录。</div>}
    <div className="phone-app-list">{apps.map(app => <details key={app.id} className="phone-app-row">
      <summary><b>{app.name}</b><Badge variant="outline" data-state={app.state}>{names[app.state] || app.state}</Badge><span>管理</span></summary><div className="phone-app-detail">
      <p className="push-hint">{app.detail}</p>
      {app.metadata?.version && <p className="push-hint">版本 {app.metadata.version}</p>}
      <div className="action-row">
        {app.id === 'playstore' && app.state === 'needs_gms' && runtime?.google_play_ready && <Button size="sm" variant="outline" disabled={unavailable} onClick={() => setConfirmGms(true)}>安装 Google 套件</Button>}
        {app.id === 'playstore' && app.state === 'needs_gms' && !runtime?.google_play_ready && <p className="push-hint">请先在宿主构建兼容的 Google 系统镜像。</p>}
        {['installed','existing'].includes(app.state) && <Button size="sm" variant="outline" disabled={unavailable} onClick={() => action('launch', () => api(`/android/devices/${device.id}/manual`, 'POST', { kind: 'launch', app: app.id }), '已打开应用')}>在手机中打开</Button>}
        {app.id === 'via' && <Button size="sm" variant="outline" disabled={unavailable || ['installed','existing'].includes(app.state)} onClick={() => action('install', () => api(`/android/devices/${device.id}/apps/via/install`, 'POST'), 'Via 安装已提交，状态会自动更新')}>安装 Via</Button>}
        {app.page && <a className="text-sm underline" href={app.page} target="_blank" rel="noreferrer">{app.id === 'playstore' ? '查看 Google 配套要求' : '查看安装来源'}</a>}
      </div>
    </div></details>)}{loaded && <details className="phone-app-row"><summary><b>桌面布局</b><Badge variant="outline" data-state={desktop?.state}>{desktop?.state === 'installed' ? '已整理' : names[desktop?.state] || '尚未整理'}</Badge><span>管理</span></summary><div className="phone-app-detail"><p className="push-hint">{desktop?.detail || '移除桌面上的其他图标、小组件与搜索栏，只保留 Via。'}</p><Button size="sm" variant="outline" disabled={unavailable || !apps.some(app => app.id === 'via' && ['installed','existing'].includes(app.state))} onClick={() => action('desktop', () => api(`/android/devices/${device.id}/desktop`, 'POST'), '桌面整理已提交，完成后可在手机画面中查看')}>整理桌面，仅保留 Via</Button></div></details>}</div>
    <Dialog.Root open={confirmGms} onOpenChange={setConfirmGms}><Dialog.Portal><Dialog.Overlay className="sheet-overlay" /><Dialog.Content className="provider-dialog"><Dialog.Title>安装 Google 套件？</Dialog.Title><Dialog.Description>这会重启手机并使用本地已构建的兼容镜像，包含 Google 服务框架、Play 服务和 Play 商店。手机数据和账号保留，Google 账号由 owner 自行登录。</Dialog.Description><div className="dialog-actions"><Button variant="outline" onClick={() => setConfirmGms(false)}>返回</Button><Button disabled={!!working} onClick={() => action('google-play', async () => { await api(`/android/devices/${device.id}/google-play`, 'POST', { enabled: true, confirm: device.id }); setConfirmGms(false) }, 'Google 套件安装已提交，手机会重新开机')}>确认安装并重启</Button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </Panel>
}
