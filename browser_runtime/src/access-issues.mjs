// A site error is evidence of blocked access, not proof of an IP/account ban.
export function xiaohongshuAccessIssue(address, text = '') {
  let url
  try { url = new URL(address) } catch { return null }
  if (url.hostname !== 'xiaohongshu.com' && !url.hostname.endsWith('.xiaohongshu.com')) return null
  if (url.searchParams.get('error_code') !== '300012' && !/(?:错误(?:码|代码)?|代码|error(?:[ _-]?code)?|code)\s*[:：]?\s*300012\b|(?:^|\n)\s*300012\s*(?:\n|$)/i.test(text.slice(0, 4000))) return null
  return { site: 'xiaohongshu', code: '300012', message: '当前疑似网络出口被小红书拦截，请停止自动重试，并用普通 Chrome 检查同一网络。' }
}
