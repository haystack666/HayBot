export function pointOnScreen(clientX, clientY, rect, width, height) {
  return {
    x: Math.max(0, Math.min(width - 1, Math.floor((clientX - rect.left) * width / rect.width))),
    y: Math.max(0, Math.min(height - 1, Math.floor((clientY - rect.top) * height / rect.height))),
  }
}
export function androidConfigPayload(config) {
  const result = { ...config }
  for (const [key, label, max] of [['max_steps', '最多操作步数', 60], ['timeout_minutes', '任务时限', 20]]) {
    if (String(config[key]).trim() === '' || !Number.isInteger(Number(config[key])) || Number(config[key]) < 1 || Number(config[key]) > max) throw new Error(`${label}请填写1–${max}的整数`)
    result[key] = Number(config[key])
  }
  return result
}
