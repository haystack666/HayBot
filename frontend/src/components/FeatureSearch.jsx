import { useEffect, useState } from 'react'
import { Dialog } from 'radix-ui'
import { Search, X, ArrowUpRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
const entries = [
['工作概览','overview','状态 用量'],['会话记录','chats','聊天 私聊 群聊 引用'],
['浏览器工作台','browser','Chrome 环境检测 实时画面 放大 接管 主人登录 拖动 滑动'],
['身份与私聊','rules','回复策略 系统提示词'],['Owner 关系','rules?view=owner','主人 群成员身份 公开关系'],
['群聊参与','rules?view=group','群聊人格 自主回复 各群设置 判断记录'],['公开评论风格','rules?view=public','公开评论人格'],
['回复设置','rules?view=advanced','防抖 分段 冷却 上下文'],['角色记忆','memory','长期记忆 来源 约定'],
['记忆设置','memory?view=settings','整理 检索 索引'],['每日日程','schedule','时间线 穿着 生活'],
['私人日记','diary','日记本 正文 版本'],['写作习惯','diary?view=settings','自动写作 自主分享'],
['主动互动','proactive','搭话 问候'],['一次性提醒','proactive?view=reminders','定时消息'],
['QQ 空间','proactive?view=qzone','动态 草稿 定时发布'],['发送记录','proactive?view=history','主动消息 推送状态'],
['表情素材','memes','表情包 共享图库'],['表情策略','memes?view=settings','概率 冷却 语义索引'],
['QQ 连接','qq','NapCat WebSocket 官方 AppID'],['模型分配','qq?view=models','Ollama 对话 记忆 模型供应商'],
['运行日志','logs','错误 事件 链路 诊断']]
export default function FeatureSearch({ botId, guardLeave, closeMenu, keyboard = true }) {
 const [open,setOpen]=useState(false),[query,setQuery]=useState(''); const navigate=useNavigate()
 useEffect(()=>{if(!keyboard)return;const key=e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();setOpen(v=>!v)}};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key)},[keyboard])
 const all=[...(botId?entries.map(([t,p,k])=>[t,'/bots/'+botId+'/'+p,k]):[]),['机器人管理','/bots','创建 归档 切换 Bot'],['共享供应商','/providers','连接目录 API Key 模型服务']]
 const matches=all.filter(x=>x.join(' ').toLowerCase().includes(query.toLowerCase().trim()))
 function go(path){if(guardLeave&&!guardLeave())return;setOpen(false);closeMenu?.();navigate(path)}
 return <Dialog.Root open={open} onOpenChange={v=>{setOpen(v);if(!v)setQuery('')}}><Dialog.Trigger asChild><button className="feature-search-trigger"><Search size={14}/><span>查找功能</span><kbd>⌘ K</kbd></button></Dialog.Trigger><Dialog.Portal><Dialog.Overlay className="sheet-overlay"/><Dialog.Content className="feature-search-dialog"><Dialog.Title className="sr-only">查找功能</Dialog.Title><Dialog.Description className="sr-only">按页面名称或原有功能名称查找入口</Dialog.Description><div className="feature-search-input"><Search size={18}/><Input autoFocus aria-label="搜索功能" value={query} onChange={e=>setQuery(e.target.value)} placeholder="查找功能，例如初始化、群聊人格…"/><Dialog.Close asChild><Button variant="ghost" size="icon-sm" aria-label="关闭搜索"><X size={15}/></Button></Dialog.Close></div><div className="feature-search-results">{matches.map(([t,p,k])=><button key={p} onClick={()=>go(p)}><span><b>{t}</b><small>{k}</small></span><ArrowUpRight size={15}/></button>)}{!matches.length&&<div className="empty">没有找到匹配功能，试试更短的关键词。</div>}</div></Dialog.Content></Dialog.Portal></Dialog.Root>
}
