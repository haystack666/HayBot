import path from 'node:path'
import { promises as fs } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { RuntimeError } from './environment.mjs'

export const DEFAULT_OPTIONS = Object.freeze({ headless: true })
const VERSION = 2

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
      if (typeof value?.headless !== 'boolean') throw new RuntimeError('invalid_settings', '浏览器启动设置无效，请停止浏览器后重新保存设置')
      // Both historical headed settings and experimental opt-ins migrate to the
      // same supported mode. Profiles, cookies and login fences are untouched.
      if (value.version !== VERSION || value.headless !== true) await this.persist(filename)
      this.values.set(id, { ...DEFAULT_OPTIONS })
    }
    return { ...DEFAULT_OPTIONS }
  }
  async persist(filename) {
    await fs.mkdir(this.directory, { recursive: true, mode: 0o700 })
    const temporary = filename + '.' + randomUUID()
    try {
      await fs.writeFile(temporary, JSON.stringify({ version: VERSION, headless: true }), { mode: 0o600, flag: 'wx' })
      await fs.rename(temporary, filename)
    } catch { throw new RuntimeError('settings_save_failed', '浏览器启动设置保存失败，请检查磁盘后重试') }
    finally { await fs.unlink(temporary).catch(() => {}) }
  }
  async save(id, input) {
    const filename = this.filename(id)
    // Accept the obsolete acknowledgement field for already-open old clients;
    // it no longer controls the mode or requires a confirmation dialog.
    if (!input || Object.keys(input).some(key => !['headless', 'acknowledgeHeadlessRisk'].includes(key)) || typeof input.headless !== 'boolean' || input.acknowledgeHeadlessRisk !== undefined && typeof input.acknowledgeHeadlessRisk !== 'boolean') throw new RuntimeError('invalid_settings', '启动设置仅支持 headless 布尔值', 400)
    if (!input.headless) throw new RuntimeError('headless_required', '当前仅支持无头模式；实时查看与接管仍可使用，请刷新管理页面', 400)
    await this.persist(filename)
    this.values.set(id, { ...DEFAULT_OPTIONS })
    return { ...DEFAULT_OPTIONS }
  }
}
