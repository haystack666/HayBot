import { NavLink } from 'react-router-dom'
const groups = [
  ['工作台', ['overview', 'chats', 'android']],
  ['角色与生活', ['rules', 'memory', 'schedule', 'diary']],
  ['互动', ['proactive', 'memes']],
  ['配置与诊断', ['qq', 'logs']],
]
export default function BotNavigation({ botId, pages, closeMenu, mobile, guardLeave }) {
  return <nav aria-label={mobile ? '移动机器人导航' : '机器人导航'}>{groups.map(([title, children]) => <div className="nav-group" key={title}><div className="nav-section-label">{title}</div>{children.map(id => { const item = pages.find(page => page.id === id), Icon = item.icon; return <NavLink key={id} to={`/bots/${botId}/${id}`} className={({ isActive }) => `nav-button ${isActive ? 'active' : ''}`} title={item.title} onClick={event => { if (guardLeave && !guardLeave()) event.preventDefault(); else closeMenu?.() }}><Icon size={16} /><span className="nav-text">{item.title}</span></NavLink> })}</div>)}</nav>
}
