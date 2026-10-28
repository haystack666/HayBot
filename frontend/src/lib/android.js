export function pointOnScreen(clientX, clientY, rect, width, height) {
  return {
    x: Math.max(0, Math.min(width - 1, Math.floor((clientX - rect.left) * width / rect.width))),
    y: Math.max(0, Math.min(height - 1, Math.floor((clientY - rect.top) * height / rect.height))),
  }
}
export function androidConfigPayload(config) {
  const result = { ...config }
  for (const [key, label, max] of [['max_steps', '阶段最多操作步数', 10000], ['timeout_minutes', '阶段任务时限', 1440]]) {
    if (String(config[key]).trim() === '' || !Number.isInteger(Number(config[key])) || Number(config[key]) < 1 || Number(config[key]) > max) throw new Error(`${label}请填写1–${max}的整数`)
    result[key] = Number(config[key])
  }
  if (config.companion) {
    const c = structuredClone(config.companion)
    const numeric = (value, label, min, max) => {
      if (String(value).trim() === '' || !Number.isInteger(Number(value)) || Number(value) < min || Number(value) > max) throw new Error(`${label}请填写${min}–${max}的整数`)
      return Number(value)
    }
    c.frame_interval_seconds = numeric(c.frame_interval_seconds, '采样间隔', 1, 10)
    c.batch_frames = numeric(c.batch_frames, '每批画面数', 3, 8)
    c.buffering_wait_seconds = numeric(c.buffering_wait_seconds ?? 120, '视频缓冲等待', 30, 600)
    for (const p of Object.values(c.platforms || {})) {
      p.cooldown_minutes = numeric(p.cooldown_minutes, '评论冷却', 0, 1440)
      p.daily_limit = numeric(p.daily_limit, '每日评论上限', 1, 100)
      if (p.mentions && (!p.comments || !p.owner_id.trim() || !p.owner_name.trim())) throw new Error('开启 @ 前请允许评论并填写 owner 账号 ID 和昵称')
    }
    result.companion = c
  }
  return result
}
