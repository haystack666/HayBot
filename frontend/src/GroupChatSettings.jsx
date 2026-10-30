import { Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { Panel, Field } from './components/console'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

const modes = { mentions: '仅 @ 回复', natural: '自然参与', quiet: '安静旁听', off: '不参与' }
const activities = { reserved: '克制', balanced: '适中', active: '积极' }
const states = { reply: '决定参与', silent: '继续旁听', cancelled: '取消发送', sent: '已送达', failed: '未发送' }

export default function GroupChatSettings({ config, active, busy, update, api, view = 'group', guardLeave }) {
  const c = config.group_chat
  const account = config.transport === 'napcat' ? `napcat:${config.napcat.self_id}` : config.qq.app_id
  const [data, setData] = useState(null), [error, setError] = useState('')
  useEffect(() => {
    let live = true
    setData(null)
    const load = () => api('/group-chats').then(result => { if (live) { setData(result); setError('') } }).catch(e => { if (live) setError(e.message) })
    load()
    const timer = setInterval(load, 5000)
    return () => { live = false; clearInterval(timer) }
  }, [api, account])
  const disabled = active || !!busy
  const set = (key, value) => update('group_chat', key, value)
  const owner = c?.owners?.find(item => item.account_id === account)?.sender_id || ''
  const setOwner = value => set('owners', [...(c.owners || []).filter(item => item.account_id !== account), ...(value.trim() ? [{ account_id: account, sender_id: value.trim() }] : [])])
  const override = (target, patch) => {
    const old = c.overrides.find(item => item.account_id === account && item.target_id === target)
    const others = c.overrides.filter(item => item.account_id !== account || item.target_id !== target)
    set('overrides', patch === null ? others : [...others, { account_id: account, target_id: target, mode: c.mode, activity: c.activity, ...old, ...patch }])
  }
  if (!c) return null
  return <>
    {view === 'group' && <p className="page-context">群聊自动回复总开关：{config.qq.group_reply ? '已开启' : '已关闭'} · <Link className="subtle-link" relative="path" to="../qq" onClick={e=>{if(!guardLeave())e.preventDefault()}}>前往 QQ 连接修改</Link></p>}
    <Panel title={view === 'owner' ? '身份与 Owner 关系' : '群聊参与方式'} subtitle={view === 'owner' ? '明确角色身份与可公开的关系事实，群聊人格不会覆盖 Owner 的私聊风格。' : '先理解本群对话，再决定是否接话。不需要回复时保持沉默。'}>
      <fieldset disabled={disabled} className="form-grid border-0 m-0 p-0">
        <div className="contents" hidden={view !== 'group'}><Field label="默认模式" id="group-mode" hint="适用于未单独配置的群；群聊自动回复总开关仍然有效。"><select id="group-mode" className="provider-select" value={c.mode} onChange={e => set('mode', e.target.value)}>{Object.entries(modes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
        <Field label="参与积极程度" id="group-activity" hint="影响开口意愿，不要求凑回复次数。"><select id="group-activity" className="provider-select" value={c.activity} onChange={e => set('activity', e.target.value)}>{Object.entries(activities).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
        </div><Field label="角色名字" id="group-character-name" hint="固定的角色身份，Owner 和普通群友都使用。公开人格不会覆盖此名字；留空时使用平台账号昵称。"><Input id="group-character-name" maxLength={80} value={c.character_name || ''} onChange={e => set('character_name', e.target.value)} /></Field>
        <Field label={config.transport === 'napcat' ? '群聊 Owner QQ 号' : '群聊 Owner 成员 OpenID'} id="group-owner" hint="仅与当前账号下平台提供的真实发送者 ID 精确匹配。Owner 使用回复策略中的原角色人格；官方渠道须填写群事件中的成员 OpenID，不猜测与 QQ 号或私聊 OpenID 的对应关系。"><Input id="group-owner" maxLength={128} value={owner} onChange={e => setOwner(e.target.value)} /></Field>
        <Field label="与 Owner 的公开关系" id="group-owner-relationship" full hint="填写允许向群友说明的关系事实，例如「Owner 是我的男朋友，我是他的女朋友」。被问起时如实回答；公开人格不能否认这段关系，也不会把群友当成 Owner。留空时不猜测关系细节。"><Textarea id="group-owner-relationship" rows={2} maxLength={1500} value={c.owner_relationship || ''} onChange={e => set('owner_relationship', e.target.value)} /></Field>
        <div className="contents" hidden={view !== 'group'}><Field label="群聊公开人格" id="group-persona" full hint="仅对普通群友生效，Owner 继续使用回复策略中的原角色人格。这里填写公开交流风格；所有群聊回应都不读取私聊记录，保持角色名字及已填写的 Owner 关系一致。"><Textarea id="group-persona" rows={5} maxLength={6000} value={c.public_persona} onChange={e => set('public_persona', e.target.value)} /></Field>
        <Field label="角色公开兴趣" id="group-interests" full hint="由你填写，例如插画、游戏音乐、生活摄影。留空时不从人格自动推导兴趣；出现关键词也不会强制回复。"><Textarea id="group-interests" rows={3} maxLength={3000} value={c.interests} onChange={e => set('interests', e.target.value)} /></Field>
        <Field label="主动接话最短间隔（秒）" id="group-cooldown" hint="按整个群计算；被直接 @ 的消息沿用普通回复冷却。"><Input id="group-cooldown" type="number" min="0" max="600" value={c.cooldown_seconds} onChange={e => set('cooldown_seconds', e.target.value)} /></Field>
        <Field label="每群每小时主动回复上限" id="group-hourly" hint="1–300；防止刷屏，不作为参与目标。直接 @ 的消息不受此上限限制。"><Input id="group-hourly" type="number" min="1" max="300" value={c.max_replies_per_hour} onChange={e => set('max_replies_per_hour', e.target.value)} /></Field>
</div>      </fieldset>
      <p className="push-hint">自然参与会接收并保存普通群消息，按整个群合并连续发言。群聊无法触发浏览器操作；操作权限仅限授权 Owner 私聊。{config.transport === 'qq_official' && 'QQ 官方 Bot 还需要在开放平台开启「接收所有消息」。仅收到 @ 事件时，仍可回复 @，无法旁听未推送的消息。'}</p>
    </Panel>
    {view === 'group' && <><Panel title="各群参与设置" subtitle="仅展示当前接入账号已收到消息的群。修改后使用页面底部的保存按钮。">
      {error && <p className="error-message">{error}</p>}
      {data && data.account_id === account && data.groups.map(group => {
        const item = c.overrides.find(item => item.account_id === account && item.target_id === group.target_id)
        return <div className="toggle-row" key={group.target_id}><div><b>{group.title}</b><p>{group.target_id}</p></div><div className="flex flex-wrap gap-2">
          <select className="provider-select" aria-label={`${group.title}参与方式`} disabled={disabled} value={item?.mode || 'inherit'} onChange={e => override(group.target_id, e.target.value === 'inherit' ? null : { mode: e.target.value })}><option value="inherit">沿用默认</option>{Object.entries(modes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
          {item && <select className="provider-select" aria-label={`${group.title}积极程度`} disabled={disabled} value={item.activity} onChange={e => override(group.target_id, { activity: e.target.value })}>{Object.entries(activities).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>}
        </div></div>
      })}
      {data?.account_id === account && !data.groups.length && <p className="push-hint">尚未收到群聊消息；收到后可按群设置。</p>}
    </Panel>
    <Panel title="最近参与判断" subtitle="记录开口、沉默和取消发送的原因，每 5 秒刷新。">
      {data?.account_id === account && data.decisions.map(item => <div className="toggle-row" key={item.id}><div><b>{states[item.state] || item.state} · 群 {item.target}</b><p>{item.reason}</p></div><small>{new Date(item.at * 1000).toLocaleTimeString('zh-CN')}</small></div>)}
      {!data?.decisions?.length && <p className="push-hint">暂无参与判断。启用自然参与或安静旁听后开始记录。</p>}
    </Panel></>}
    {view === 'owner' && <Panel title="私聊绑定" subtitle="官方私聊 OpenID 与群成员 OpenID 按用途分别设置，不自动匹配。"><div className="page-quicklinks"><Link className="subtle-link" relative="path" to="../diary?view=settings" onClick={e=>{if(!guardLeave())e.preventDefault()}}>日记 Owner 绑定 →</Link><Link className="subtle-link" relative="path" to="../proactive" onClick={e=>{if(!guardLeave())e.preventDefault()}}>主动消息接收者 →</Link></div></Panel>}
  </>
}
