import { useEffect, useState } from 'react'
import { Brain, ChevronRight, FileText, MessageSquare, Radio } from 'lucide-react'
import { NavLink, useParams } from 'react-router-dom'

const groups = [
  { id: 'connections', title: '接入设置', icon: Radio, pages: ['qq', 'providers', 'android'] },
  { id: 'character', title: '角色与对话', icon: Brain, pages: ['rules', 'memory', 'schedule', 'memes'] },
  { id: 'interaction', title: '主动互动', icon: MessageSquare, pages: ['proactive', 'qzone'] },
  { id: 'records', title: '记录与诊断', icon: FileText, pages: ['chats', 'logs'] },
]
const storageKey = 'haybot.navigation.groups'
function readGroups() {
  try { const saved = JSON.parse(localStorage.getItem(storageKey)); return Object.fromEntries(groups.map(group => [group.id, saved?.[group.id] === true])) }
  catch { return {} }
}

export default function BotNavigation({ botId, pages, closeMenu, mobile }) {
  const { page } = useParams()
  const activeGroup = groups.find(group => group.pages.includes(page))?.id
  const [expanded, setExpanded] = useState(() => ({ ...readGroups(), ...(activeGroup ? { [activeGroup]: true } : {}) }))
  useEffect(() => {
    if (activeGroup) setExpanded(previous => ({ ...previous, [activeGroup]: true }))
  }, [activeGroup, botId, page])
  useEffect(() => {
    try { localStorage.setItem(storageKey, JSON.stringify(expanded)) } catch { /* Navigation works when browser storage is unavailable. */ }
  }, [expanded])
  function link(item) {
    const Icon = item.icon
    return <NavLink key={item.id} to={`/bots/${botId}/${item.id}`} className={({ isActive }) => `nav-button ${isActive ? 'active' : ''}`} onClick={closeMenu} aria-label={item.title} title={item.title}><Icon size={17} /><span className="nav-text">{item.title}</span></NavLink>
  }
  return <nav aria-label={mobile ? '移动机器人配置' : '机器人配置'}>
    {link(pages.find(item => item.id === 'overview'))}
    {groups.map(({ id, title, icon: Icon, pages: children }) => {
      const open = !!expanded[id], controlId = `${mobile ? 'mobile' : 'desktop'}-nav-${id}`
      return <div className="nav-group" key={id}>
        <button type="button" className={`nav-button nav-group-toggle ${activeGroup === id ? 'contains-active' : ''}`} aria-label={title} title={title} aria-expanded={open} aria-controls={controlId} onClick={() => setExpanded(previous => ({ ...previous, [id]: !previous[id] }))}><Icon size={17} /><span className="nav-text">{title}</span><ChevronRight size={14} className={`nav-group-chevron ${open ? 'expanded' : ''}`} aria-hidden="true" /></button>
        <div id={controlId} className="nav-submenu" hidden={!open}>{children.map(child => link(pages.find(item => item.id === child)))}</div>
      </div>
    })}
  </nav>
}
