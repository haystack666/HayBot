import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Panel, Notice } from './components/console'
const names = { installed: '已安装', existing: '已保留', downloading: '下载中', installing: '安装中', queued: '排队中', needs_install: '等待安装', needs_gms: '需配套系统', failed: '安装失败', interrupted: '安装中断', not_checked: '尚未检查' }
export default function AndroidApps({ api, device, activeTask, action, working }) {
  const [apps, setApps] = useState([]), [error, setError] = useState('')
  useEffect(() => {
    if (!device) return
    let live = true
    const refresh = () => api(`/android/devices/${device.id}/apps`).then(v => { if (live) { setApps(v.apps); setError('') } }).catch(e => { if (live) setError(e.message) })
    refresh(); const timer = setInterval(refresh, 8000)
    return () => { live = false; clearInterval(timer) }
  }, [api, device?.id])
  return <Panel title="手机初始化与应用" subtitle="应用商店使用酷安和 Google Play；账号登录全部由 owner 完成。">
    {error && <Notice alert>{error}</Notice>}
    <div className="page-stack">{apps.map(app => <article key={app.id} className="android-task">
      <div className="action-row justify-between"><b>{app.name}</b><Badge variant="outline">{names[app.state] || app.state}</Badge></div>
      <p className="push-hint">{app.detail}</p>
      {app.metadata?.version && <p className="push-hint">版本 {app.metadata.version}</p>}
      <div className="action-row">
        {['installed','existing'].includes(app.state) && !['wallpaper','defaults'].includes(app.id) && <Button size="sm" variant="outline" disabled={!!working || !!activeTask || device?.state !== 'running'} onClick={() => action('launch', () => api(`/android/devices/${device.id}/manual`, 'POST', { kind: 'launch', app: app.id }), '已打开应用')}>在手机中打开</Button>}
        {app.page && !['playstore','coolapk'].includes(app.id) && <Button size="sm" variant="ghost" disabled={!!working || !!activeTask || device?.state !== 'running'} onClick={() => action('source', () => api(`/android/devices/${device.id}/manual`, 'POST', { kind: 'open', url: app.page }))}>手机打开下载页</Button>}
        {(app.url || ['wallpaper','defaults'].includes(app.id)) && <Button size="sm" variant="outline" disabled={!!working || !!activeTask || device?.owner_login || device?.state !== 'running' || ['installed','existing','queued','downloading','installing'].includes(app.state)} onClick={() => action('install', () => api(`/android/devices/${device.id}/apps/${app.id}/install`, 'POST'), '安装已提交，状态会自动更新')}>{app.id === 'wallpaper' ? '应用默认壁纸' : app.id === 'defaults' ? '应用中国大陆默认设置' : '安装应用'}</Button>}
        {app.page && <a className="text-sm underline" href={app.page} target="_blank" rel="noreferrer">{app.id === 'playstore' ? '查看 Google 配套要求' : '查看安装来源'}</a>}
      </div>
    </article>)}</div>
    <p className="push-hint">已安装的应用会保留原版本与数据。支持官方包的应用可直接安装；小红书、Chrome 可在手机中的应用商店安装或在宿主导入官方 APK，具体可用性以商店实际页面为准。默认壁纸仅主动应用一次。</p>
  </Panel>
}
