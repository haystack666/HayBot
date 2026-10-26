import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes, Link, useParams } from 'react-router-dom'
import App, { pages } from './App'
import './index.css'

function NotFound() {
  return <div className="loading-page"><div className="text-center"><h1>页面不存在</h1><p className="subtitle">请检查地址或返回机器人管理。</p><Link className="subtle-link mt-4" to="/bots">返回 HayBot</Link></div></div>
}
function BotPage() {
  const { botId, page } = useParams()
  if (page === 'ollama') return <Navigate to={`/bots/${botId}/providers`} replace />
  return pages.some(item => item.id === page) ? <App key={botId} page={page} /> : <NotFound />
}
createRoot(document.getElementById('root')).render(
  <React.StrictMode><BrowserRouter><Routes>
    <Route path="/" element={<Navigate to="/bots" replace />} />
    <Route path="/bots" element={<App key="manager" page="bots" />} />
    <Route path="/providers" element={<App key="providers" page="providers" />} />
    <Route path="/ollama" element={<Navigate to="/bots/default/providers" replace />} />
    <Route path="/bots/:botId/:page" element={<BotPage />} />
    {pages.filter(page => page.id !== 'providers').map(page => <Route key={page.id} path={`/${page.id}`} element={<Navigate to={`/bots/default/${page.id}`} replace />} />)}
    <Route path="*" element={<NotFound />} />
  </Routes></BrowserRouter></React.StrictMode>
)
