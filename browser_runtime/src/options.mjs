import path from 'node:path'
import { promises as fs } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { RuntimeError } from './environment.mjs'

export const DEFAULT_OPTIONS = Object.freeze({ headless: false })
const RISK_VERSION = 1

export class BrowserOptions {
  constructor(directory) { this.directory = path.join(directory, 'settings'); this.values = new Map() }
  filename(id) {
    if (typeof id !== 'string' || !/^[a-zA-Z0-9_-]{1,64}$/.test(id)) throw new RuntimeError('invalid_session', '浏览器会话标识无效', 400)
    return path.join(this.directory, id + '.json')
  }
  async get(id) {
    const filename = this.filename(id)
    if (!this.values.has(id)) {
      let value
      try { value = JSON.parse(await fs.readFile(filename, 'utf8')) }
      catch (error) {
        if (error.code !== 'ENOENT') throw new RuntimeError('invalid_settings', '浏览器启动设置无法读取，请停止浏览器后重新保存设置')
        value = DEFAULT_OPTIONS
      }
      if (typeof value?.headless !== 'boolean' || value.headless && value.headlessRiskVersion !== RISK_VERSION) throw new RuntimeError('invalid_settings', '无头模式需要重新确认风险，请停止浏览器后重新保存设置')
      // A concurrent save may have completed while the disk read was pending.
      if (!this.values.has(id)) this.values.set(id, { headless: value.headless })
    }
    return { ...this.values.get(id) }
  }
  async save(id, input) {
    const filename = this.filename(id)
    if (!input || Object.keys(input).some(key => !['headless', 'acknowledgeHeadlessRisk'].includes(key)) || typeof input.headless !== 'boolean' || input.acknowledgeHeadlessRisk !== undefined && typeof input.acknowledgeHeadlessRisk !== 'boolean') throw new RuntimeError('invalid_settings', '启动设置仅支持 headless 布尔开关和风险确认', 400)
    if (input.headless && input.acknowledgeHeadlessRisk !== true) throw new RuntimeError('headless_confirmation_required', '开启实验性无头模式前，请确认可能出现访问异常、登录验证或风控拦截；实时查看与接管仍然保留', 400)
    await fs.mkdir(this.directory, { recursive: true, mode: 0o700 })
    const temporary = filename + '.' + randomUUID()
    try {
      await fs.writeFile(temporary, JSON.stringify({ headless: input.headless, headlessRiskVersion: input.headless ? RISK_VERSION : null }), { mode: 0o600, flag: 'wx' })
      await fs.rename(temporary, filename)
    } catch { throw new RuntimeError('settings_save_failed', '浏览器启动设置保存失败，请检查磁盘后重试') }
    finally { await fs.unlink(temporary).catch(() => {}) }
    this.values.set(id, { headless: input.headless })
    return { headless: input.headless }
  }
}
