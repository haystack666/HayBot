import os from 'node:os'
import path from 'node:path'
import { promises as fs } from 'node:fs'
import { execFile as execFileCallback } from 'node:child_process'
import { promisify } from 'node:util'
import { randomUUID } from 'node:crypto'

const execFile = promisify(execFileCallback)
export const CHROME_INSTALL_URL = 'https://www.google.cn/chrome/'
export class RuntimeError extends Error {
  constructor(code, message, status = 409) { super(message); this.code = code; this.status = status }
}

export function chromeCandidates(platform = process.platform, env = process.env, home = os.homedir()) {
  if (platform === 'darwin') return ['/Applications/Google Chrome.app', path.join(home, 'Applications/Google Chrome.app')]
  if (platform === 'win32') return [env.PROGRAMFILES, env['PROGRAMFILES(X86)'], env.LOCALAPPDATA].filter(Boolean).map(root => path.join(root, 'Google/Chrome/Application/chrome.exe'))
  if (platform === 'linux') return ['/opt/google/chrome/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/google-chrome']
  return []
}

export async function findChrome({ platform = process.platform, arch = process.arch, candidates = chromeCandidates(platform), stat = fs.stat, run = execFile } = {}) {
  let found = false
  let detail = 'Chrome 身份、签名或安装状态验证失败'
  for (const candidate of candidates) {
    try { await stat(candidate) } catch { continue }
    found = true
    if (platform !== 'darwin') return { state: 'needs_repair', detail: '当前原型尚未验证此系统的 Chrome 身份与启动流程', executable: null }
    let stage = 'identity'
    try {
      const plist = path.join(candidate, 'Contents/Info.plist')
      const read = async key => (await run('/usr/bin/plutil', ['-extract', key, 'raw', '-o', '-', plist], { timeout: 10000 })).stdout.trim()
      const identifier = await read('CFBundleIdentifier'), version = await read('CFBundleShortVersionString')
      if (identifier !== 'com.google.Chrome' || !/^\d+\.\d+\.\d+\.\d+$/.test(version)) { detail = 'Chrome 产品身份或版本信息无效'; continue }
      // Verify the signed bundle and Google identity. --strict also rejects harmless
      // Finder resource metadata on otherwise valid installed applications.
      stage = 'signature'
      await run('/usr/bin/codesign', ['--verify', '-R=anchor apple generic and identifier "com.google.Chrome" and certificate leaf[subject.OU] = "EQHXZ8M8AV"', candidate], { timeout: 30000 })
      const signature = await run('/usr/bin/codesign', ['--display', '--verbose=4', candidate], { timeout: 10000 })
      if (!/^TeamIdentifier=EQHXZ8M8AV$/m.test(signature.stderr)) { detail = 'Chrome 签名不是受信任的 Google 发布身份'; continue }
      const executable = path.join(candidate, 'Contents/MacOS/Google Chrome')
      // /usr/bin/lipo is an Xcode shim and can require an unrelated SDK license.
      // Read the signed executable's Mach-O architecture with the system file tool.
      stage = 'architecture'
      const description = (await run('/usr/bin/file', ['-b', executable], { timeout: 10000, env: { ...process.env, LC_ALL: 'C', LANG: 'C' } })).stdout
      const architectures = [...new Set([...description.matchAll(/Mach-O 64-bit executable (arm64|x86_64)\b/g)].map(match => match[1]))]
      const required = arch === 'arm64' ? 'arm64' : arch === 'x64' ? 'x86_64' : null
      if (!required || !architectures.includes(required)) { detail = 'Chrome 可执行文件架构与宿主不兼容或无法识别'; continue }
      return { state: 'passed', detail: `Google Chrome ${version}`, version, executable, architectures }
    } catch {
      // Do not expose raw subprocess errors; keep tool failures distinct from invalid Chrome.
      detail = stage === 'architecture' ? 'Chrome 架构检测工具执行失败，未判定 Chrome 损坏，请重新检测'
        : stage === 'signature' ? 'Chrome Google 签名校验未通过或签名工具执行失败'
          : 'Chrome 产品身份读取失败，请检查安装状态'
    }
  }
  return { state: found ? 'needs_repair' : 'needs_install', detail: found ? detail : '未检测到 Google Chrome', executable: null }
}

export class Environment {
  constructor(directory, { discover = findChrome } = {}) {
    this.directory = directory; this.discover = discover; this.pending = null; this.cached = null
  }
  check({ force = false } = {}) {
    if (this.pending) return this.pending
    if (!force && this.cached && Date.now() - this.cached.checkedAt < 30000) return Promise.resolve(this.cached)
    this.pending = this.inspect().finally(() => { this.pending = null })
    return this.pending
  }
  async inspect() {
    const checks = [{ id: 'host', label: '宿主运行时', state: 'passed', detail: `${os.hostname()} · ${os.platform()} ${os.arch()}` }]
    checks.push({ id: 'node', label: '运行依赖', state: Number(process.versions.node.split('.')[0]) >= 20 ? 'passed' : 'failed', detail: `Node ${process.versions.node}` })
    let directoryOK = false
    try {
      await fs.mkdir(this.directory, { recursive: true, mode: 0o700 })
      const probe = path.join(this.directory, `.probe-${randomUUID()}`)
      await fs.writeFile(probe, '', { flag: 'wx', mode: 0o600 }); await fs.unlink(probe); directoryOK = true
    } catch { /* Report a predefined message, never raw filesystem errors. */ }
    checks.push({ id: 'directory', label: '工作目录', state: directoryOK ? 'passed' : 'failed', detail: directoryOK ? '可读写' : '工作目录无法写入，请检查权限和磁盘空间' })
    const chrome = await this.discover()
    checks.push({ id: 'chrome', label: 'Google Chrome', state: chrome.state === 'passed' ? 'passed' : 'failed', detail: chrome.detail })
    checks.push({ id: 'launch', label: '隐藏启动验证', state: 'pending', detail: '待验证' })
    this.cached = { state: chrome.state === 'needs_install' ? 'needs_install' : checks.some(check => check.state === 'failed') ? 'needs_repair' : 'checking', checkedAt: Date.now(), checks, installUrl: CHROME_INSTALL_URL, chrome }
    return this.cached
  }
  setLaunch(result, passed) {
    result.checks = result.checks.map(check => check.id === 'launch' ? { ...check, state: passed ? 'passed' : 'failed', detail: passed ? 'Chrome 隐藏启动与连接正常' : 'Chrome 启动或连接失败，请重新检测' } : check)
    result.state = result.checks.every(check => check.state === 'passed') ? 'ready' : 'needs_repair'
    return result
  }
  public(result) { const { chrome, ...rest } = result; return rest }
}
