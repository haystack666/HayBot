import { Radio, LoaderCircle, ExternalLink } from 'lucide-react'
import { Panel, Field } from './components/console'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Link } from 'react-router-dom'

export default function ConnectionPage({ config, active, busy, dirty, update, setTransport, action, api, notify, guardLeave }) {
  const napcat=config.transport==='napcat'
  return <div className="page-stack">
    <Panel title="QQ 接入方式">
      <Field label="接入类型" id="connection-type"><select className="provider-select" id="connection-type" value={config.transport||'qq_official'} disabled={active||!!busy} onChange={e=>setTransport(e.target.value)}><option value="qq_official">QQ 官方机器人</option><option value="napcat">外部 NapCat</option></select></Field>
      <p className="push-hint">切换接入方式或账号会清空近期对话上下文，需要重新选择主动消息接收者；已有聊天档案、长期记忆和日程保留，并按账号分别隔离。</p>
    </Panel>
    {napcat?<Panel title="外部 NapCat 连接" subtitle="连接你已经运行并登录 QQ 的 NapCat，HayBot 不托管扫码登录。">
      <fieldset disabled={active||!!busy} className="form-grid border-0 m-0 p-0">
        <Field label="登录 QQ 号" id="napcat-self-id" hint="必须与 NapCat 当前登录账号一致，连接时会自动核对。"><Input id="napcat-self-id" inputMode="numeric" maxLength={20} value={config.napcat.self_id} onChange={e=>update('napcat','self_id',e.target.value)} placeholder="例如：123456789" /></Field>
        <Field label="WebSocket 服务地址" id="napcat-ws-url" hint="填写 NapCat 的 WebSocket 服务端地址，不是 6099 WebUI 管理地址。"><Input id="napcat-ws-url" maxLength={2048} value={config.napcat.ws_url} onChange={e=>update('napcat','ws_url',e.target.value)} placeholder="ws://192.168.31.100:3001" /></Field>
        <Field label="连接 Token" id="napcat-token" full hint={config.napcat.token_set?'已加密保存，留空保持；更换连接地址或 QQ 号后需重新填写。':'与 NapCat WebSocket 服务端配置的 Token 一致；不要填写 WebUI 的登录 Token。'}><Input id="napcat-token" type="password" autoComplete="new-password" maxLength={4096} value={config.napcat.token||''} disabled={config.napcat.clear_token} onChange={e=>update('napcat','token',e.target.value)} placeholder={config.napcat.token_set?'•••••••• 已安全保存':'填写 WebSocket 连接 Token'} /></Field>
        {config.napcat.token_set&&<label className="napcat-clear-token"><input type="checkbox" checked={!!config.napcat.clear_token} onChange={e=>{update('napcat','token','');update('napcat','clear_token',e.target.checked)}} />清除已保存的 Token（仅限外部服务未启用鉴权时）</label>}
      </fieldset>
      <div className="action-row mt-6"><Button variant="outline" disabled={!!busy||dirty} onClick={()=>action('qq-test',async()=>{const r=await api('/qq/test','POST');notify(r.message)})}>{busy==='qq-test'?<LoaderCircle size={14} className="spin" />:<Radio size={14} />}测试 NapCat 连接</Button><a className="subtle-link" href="https://doc.napneko.icu/config/basic" target="_blank" rel="noreferrer">NapCat 配置说明<ExternalLink size={12} /></a></div>
    </Panel>:<Panel title="官方机器人凭证" subtitle="来自 QQ 开放平台，凭证加密保存在 SQLite 中。"><fieldset disabled={active||!!busy} className="form-grid border-0 m-0 p-0"><Field label="AppID" id="app-id" hint="在 QQ 开放平台机器人开发设置中获取。"><Input id="app-id" value={config.qq.app_id} onChange={e=>update('qq','app_id',e.target.value)} inputMode="numeric" /></Field><Field label="AppSecret" id="secret" hint={config.qq.secret_set?'留空保持已保存密钥，填写新值可替换。':'保存后不会返回浏览器。'}><Input id="secret" type="password" autoComplete="new-password" value={config.qq.secret} onChange={e=>update('qq','secret',e.target.value)} placeholder={config.qq.secret_set?'•••••••• 已安全保存':'填写 AppSecret'} /></Field></fieldset><div className="action-row mt-6"><Button variant="outline" disabled={!!busy||dirty} onClick={()=>action('qq-test',async()=>{const r=await api('/qq/test','POST');notify(r.message)})}>{busy==='qq-test'?<LoaderCircle size={14} className="spin" />:<Radio size={14} />}测试凭证</Button></div></Panel>}
    <Panel title="接收与回复场景" subtitle="个人记忆及日程按群成员隔离；回复时会参考本群近期收到的公开发言，并区分发送者。">
      <div className="toggle-row !pt-0"><div><b>单聊自动回复</b><p>收到用户单聊后，调用模型生成回答。</p></div><Switch aria-label="单聊自动回复" checked={config.qq.private_reply} disabled={active||!!busy} onCheckedChange={v=>update('qq','private_reply',v)} /></div>
      <div className="toggle-row"><div><b>群聊自动回复</b><p>总开关；具体参与方式在「角色与群聊」中配置。</p></div><Switch aria-label="群聊自动回复" checked={config.qq.group_reply} disabled={active||!!busy} onCheckedChange={v=>update('qq','group_reply',v)} /></div>
    </Panel>
    <Link className="subtle-link" relative="path" to="../rules?view=group" onClick={e=>{if(!guardLeave())e.preventDefault()}}>管理群聊参与、公开人格与 Owner 关系 →</Link>
    {napcat&&<details className="help-details"><summary>NapCat 连接帮助</summary><Panel title="连接步骤"><ol className="napcat-help"><li>在 NapCat 中登录目标 QQ，添加并启用「WebSocket 服务端」。</li><li>选择可访问的监听地址及端口，配置 Token，消息格式选择数组。</li><li>把服务地址、相同 Token 和登录 QQ 号填到本页，保存后点击测试连接。</li><li>配置模型并启动机器人。断线会自动重连，未确认的发送不会自动重发。</li></ol><p className="push-hint">HayBot 在 Docker 中运行时，127.0.0.1 指向容器自身。NapCat 在这台电脑上时，可使用 ws://host.docker.internal:端口；在其他设备上时，使用那台设备的局域网地址。原生表情及 GIF 通过 NapCat 发送，实际显示以 QQ 客户端为准。</p></Panel></details>}
  </div>
}
