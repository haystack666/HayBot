import { Field, Notice } from './components/console'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
export default function AndroidCompanion({ value, onChange, disabled }) {
  const c = value || { video_enabled: true, frame_interval_seconds: 3, batch_frames: 6, public_persona: '', platforms: {} }
  const update = patch => onChange({ ...c, ...patch })
  const platform = (id, patch) => update({ platforms: { ...c.platforms, [id]: { comments: false, mentions: false, owner_id: '', owner_name: '', cooldown_minutes: 30, daily_limit: 5, ...c.platforms?.[id], ...patch } } })
  return <div className="page-stack">
    <label className="setting-toggle"><div><b>多帧视频观察</b><p>按时间采样画面与字幕，没有音频时不推测对白。</p></div><Switch checked={c.video_enabled} disabled={disabled} onCheckedChange={v => update({ video_enabled: v })} /></label>
    <div className="form-grid">{[['frame_interval_seconds','采样间隔（秒）',1,10],['batch_frames','每批画面数',3,8]].map(([key,label,min,max]) => <Field key={key} label={label} id={`companion-${key}`}><Input id={`companion-${key}`} type="number" min={min} max={max} required value={c[key]} disabled={disabled} onChange={e => update({ [key]: e.target.value })} /></Field>)}</div>
    <Field label="主人的兴趣偏好" id="android-owner-interests" hint="填写喜欢、不感兴趣和尽量避开的内容；用于挑选适合分享或 @ 你的内容。"><Textarea id="android-owner-interests" maxLength={2000} value={c.owner_interests || ''} disabled={disabled} onChange={e => update({ owner_interests: e.target.value })} /></Field>
    <Field label="角色自己的兴趣" id="android-character-interests"><Textarea id="android-character-interests" maxLength={2000} value={c.character_interests || ''} disabled={disabled} onChange={e => update({ character_interest_mode: 'custom', character_interests: e.target.value })} /></Field>
    <Field label="内容筛选要求" id="android-content-constraints" hint="例如：跳过带货、标题党和搬运；优先实际演示。"><Textarea id="android-content-constraints" maxLength={2000} value={c.content_constraints || ''} disabled={disabled} onChange={e => update({ content_constraints: e.target.value })} /></Field>
    <Field label="视频缓冲等待（秒）" id="android-buffer-wait" hint="后台持续观察播放恢复，默认等 120 秒；期间不因两次短等待就换片。"><Input id="android-buffer-wait" type="number" min={30} max={600} value={c.buffering_wait_seconds ?? 120} disabled={disabled} onChange={e => update({ buffering_wait_seconds: e.target.value })} /></Field>
    <Field label="公开评论风格" id="android-public-persona" hint="仅用于公开评论，不会读取私人聊天人格、记忆或日程；原有配置保留。"><Textarea id="android-public-persona" maxLength={1000} rows={3} value={c.public_persona} disabled={disabled} placeholder="例如：简短自然，结合具体画面，不写套话。" onChange={e => update({ public_persona: e.target.value })} /></Field>
    {['douyin','bilibili'].map((id,index) => {
      const p = { comments: false, mentions: false, owner_id: '', owner_name: '', cooldown_minutes: 30, daily_limit: 5, ...c.platforms?.[id] }
      return <details className="android-task" key={id}><summary>{['抖音','bilibili'][index]} · {p.comments ? '允许自主评论' : '未开启评论'}</summary><div className="page-stack pt-4">
        <label className="setting-toggle"><span>允许自主评论，无需逐条确认</span><Switch checked={p.comments} disabled={disabled} onCheckedChange={v => platform(id, { comments: v })} /></label>
        <label className="setting-toggle"><span>看到有意思的内容可以 @ owner</span><Switch checked={p.mentions} disabled={disabled || !p.comments} onCheckedChange={v => platform(id, { mentions: v })} /></label>
        <Field label="Bot 登录的平台账号 ID" id={`${id}-posting-account-id`} hint="填写手机里实际发表评论的账号 ID；多个 Bot 使用同一账号时填写相同值，用于跨 Bot 去重。留空兼容原有账号分组。"><Input id={`${id}-posting-account-id`} maxLength={128} value={p.posting_account_id || ''} disabled={disabled} onChange={e => platform(id, { posting_account_id: e.target.value })} /></Field>
        <Field label="owner 平台账号 ID" id={`${id}-owner-id`} hint="用于核对 @ 候选账号；填该平台真实公开账号 ID。"><Input id={`${id}-owner-id`} maxLength={128} value={p.owner_id} disabled={disabled} onChange={e => platform(id, { owner_id: e.target.value })} /></Field>
        <Field label="owner 昵称" id={`${id}-owner-name`}><Input id={`${id}-owner-name`} maxLength={80} value={p.owner_name} disabled={disabled} onChange={e => platform(id, { owner_name: e.target.value })} /></Field>
        <div className="form-grid">{[['cooldown_minutes','评论冷却（分钟）',0,1440],['daily_limit','每日评论上限',1,100]].map(([key,label,min,max]) => <Field key={key} label={label} id={`${id}-${key}`}><Input id={`${id}-${key}`} type="number" min={min} max={max} required value={p[key]} disabled={disabled} onChange={e => platform(id, { [key]: e.target.value })} /></Field>)}</div>
      </div></details>
    })}
    <Notice>仅在已授权的手机任务中互动，不会自行无限刷视频。发布结果不明时不会重复发送。@ 需要实际选中可核对的账号；登录和验证由 owner 完成。</Notice>
  </div>
}
