import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { promises as fs } from 'node:fs'
import { randomBytes, randomUUID, timingSafeEqual } from 'node:crypto'
import { WebSocketServer, WebSocket } from 'ws'
import { BrowserEngine } from './engine.mjs'
import { RuntimeError } from './environment.mjs'

const publicRoot = fileURLToPath(new URL('../public/', import.meta.url))
function equal(a, b) { const x = Buffer.from(a || ''), y = Buffer.from(b || ''); return x.length === y.length && timingSafeEqual(x, y) }
async function body(request) {
  const parts = []; let size = 0
  for await (const part of request) {
    size += part.length
    if (size > 32768) throw new RuntimeError('body_too_large', '请求过大', 413)
    parts.push(part)
  }
  try {
    const value = JSON.parse(Buffer.concat(parts).toString('utf8') || '{}')
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('not an object')
    return value
  } catch { throw new RuntimeError('invalid_json', '请求格式错误', 400) }
}

export async function createRuntimeServer({ directory, token, engine = new BrowserEngine(directory), port = 17322 } = {}) {
  if (typeof token !== 'string' || token.length < 32) throw new Error('A runtime token of at least 32 characters is required')
  const cookie = randomBytes(32).toString('hex'), sockets = new WebSocketServer({ noServer: true, maxPayload: 4096 })
  const clients = new Map()
  const authorized = request => equal(request.headers.authorization, `Bearer ${token}`) || equal((request.headers.cookie || '').split(';').map(value => value.trim()).find(value => value.startsWith('hay_browser='))?.slice(12), cookie)
  let origin
  const validHost = request => request.headers.host === new URL(origin).host
  const validOrigin = request => !request.headers.origin || request.headers.origin === origin
  function json(response, status, value, headers = {}) { response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', ...headers }); response.end(JSON.stringify(value)) }
  const server = http.createServer(async (request, response) => {
    response.setHeader('Cache-Control', 'no-store')
    response.setHeader('X-Content-Type-Options', 'nosniff')
    response.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
    response.setHeader('Referrer-Policy', 'no-referrer')
    try {
      if (!validHost(request) || !validOrigin(request)) throw new RuntimeError('forbidden_origin', '请通过本地运行时页面访问', 403)
      const url = new URL(request.url, origin), method = request.method
      if (url.pathname === '/api/connect' && method === 'POST') {
        if (!equal(request.headers.authorization, `Bearer ${token}`)) throw new RuntimeError('unauthorized', '访问码不正确', 401)
        return json(response, 200, { ok: true }, { 'Set-Cookie': `hay_browser=${cookie}; HttpOnly; SameSite=Strict; Path=/api` })
      }
      if (url.pathname.startsWith('/api/')) {
        if (!authorized(request)) throw new RuntimeError('unauthorized', '请先连接宿主运行时', 401)
        if (url.pathname === '/api/health' && method === 'GET') return json(response, 200, { ok: true, prototype: true })
        if (url.pathname === '/api/environment' && ['GET', 'POST'].includes(method)) {
          const report = await engine.prepare({ force: method === 'POST' }); return json(response, 200, engine.environment.public(report))
        }
        const match = /^\/api\/sessions\/([a-zA-Z0-9_-]{1,64})(?:\/(start|stop|claim|release|action|observe))?$/.exec(url.pathname)
        if (!match) throw new RuntimeError('not_found', '接口不存在', 404)
        const [, id, operation] = match
        if (!operation && method === 'GET') return json(response, 200, engine.state(id))
        if (operation === 'observe' && method === 'GET') return json(response, 200, await engine.observe(id))
        if (method !== 'POST') throw new RuntimeError('method_not_allowed', '请求方法无效', 405)
        const input = await body(request)
        if (operation === 'claim' && ![...clients].some(([ws, client]) => client.id === id && client.connectionId === input.connectionId && ws.readyState === WebSocket.OPEN)) throw new RuntimeError('viewer_disconnected', '请先连接当前浏览器画面再接管')
        const result = operation === 'start' ? await engine.start(id)
          : operation === 'stop' ? await engine.stop(id)
            : operation === 'claim' ? engine.claim(id, input.connectionId)
              : operation === 'release' ? engine.release(id, input.lease)
                : operation === 'action' ? await engine.action(id, input) : null
        if (!result) throw new RuntimeError('not_found', '接口不存在', 404)
        return json(response, 200, result)
      }
      const files = { '/': ['index.html', 'text/html'], '/app.js': ['app.js', 'text/javascript'], '/input.js': ['input.js', 'text/javascript'], '/style.css': ['style.css', 'text/css'], '/fixture': ['fixture.html', 'text/html'], '/fixture.js': ['fixture.js', 'text/javascript'] }
      const file = files[url.pathname]
      if (method !== 'GET' || !file) throw new RuntimeError('not_found', '页面不存在', 404)
      response.writeHead(200, { 'Content-Type': `${file[1]}; charset=utf-8` }); response.end(await fs.readFile(path.join(publicRoot, file[0])))
    } catch (error) {
      if (response.headersSent) return response.end()
      json(response, error instanceof RuntimeError ? error.status : 500, { code: error instanceof RuntimeError ? error.code : 'operation_failed', detail: error instanceof RuntimeError ? error.message : '操作未完成，请检查浏览器当前状态；已执行动作不会自动重试' })
    }
  })
  server.on('upgrade', (request, socket, head) => {
    const match = /^\/api\/sessions\/([a-zA-Z0-9_-]{1,64})\/live$/.exec(request.url)
    if (!match || !authorized(request) || !validHost(request) || !validOrigin(request)) { socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n'); return }
    let session
    try { session = engine.get(match[1]) } catch { socket.end('HTTP/1.1 409 Conflict\r\nConnection: close\r\n\r\n'); return }
    sockets.handleUpgrade(request, socket, head, ws => {
      const id = match[1], connectionId = randomUUID(); clients.set(ws, { id, session, connectionId }); engine.watch(id, 1)
      ws.isAlive = true; ws.on('pong', () => { ws.isAlive = true })
      ws.send(JSON.stringify({ type: 'state', state: engine.state(id), connectionId }))
      // All mutations use authenticated HTTP; frames are never replayed as input.
      ws.on('message', () => ws.close(1008, '只接收画面'))
      ws.on('error', () => {})
      ws.on('close', () => {
        clients.delete(ws); session.observers = Math.max(0, session.observers - 1)
        if (session.controller === connectionId && session.context && session.lease) engine.release(id, session.lease)
        engine.refreshStream(session)
      })
    })
  })
  const sendState = state => {
    for (const [ws, client] of clients) if (client.id === state.id && ws.readyState === WebSocket.OPEN) {
      if (ws.bufferedAmount > 2 * 1024 * 1024) { ws.close(1013, '接收过慢，请重新连接'); continue }
      ws.send(JSON.stringify({ type: 'state', state }))
      if (state.state === 'stopped') ws.close(1000, '浏览器已停止')
    }
  }
  const sendFrame = frame => {
    let payload
    for (const [ws, client] of clients) if (client.id === frame.id && ws.readyState === WebSocket.OPEN && ws.bufferedAmount < 1024 * 1024) {
      payload ||= JSON.stringify({ ...frame, type: 'frame', data: frame.data.toString('base64') })
      ws.send(payload)
    }
  }
  const sendError = message => { for (const [ws, client] of clients) if (client.id === message.id && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'stream_error', detail: message.detail })) }
  engine.on('state', sendState); engine.on('frame', sendFrame); engine.on('streamError', sendError)
  const heartbeat = setInterval(() => {
    for (const ws of clients.keys()) { if (!ws.isAlive) ws.terminate(); else { ws.isAlive = false; ws.ping() } }
  }, 15000); heartbeat.unref()
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve) })
  origin = `http://127.0.0.1:${server.address().port}`
  return { origin, engine, server, close: async () => {
    clearInterval(heartbeat); for (const ws of clients.keys()) ws.terminate()
    await engine.close(); await new Promise(resolve => sockets.close(resolve)); server.closeAllConnections()
    await new Promise(resolve => server.close(resolve))
    engine.off('state', sendState); engine.off('frame', sendFrame); engine.off('streamError', sendError)
  } }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const directory = path.resolve(process.env.HAYBOT_BROWSER_DATA || path.join(fileURLToPath(new URL('../../', import.meta.url)), '.browser-runtime'))
  await fs.mkdir(directory, { recursive: true, mode: 0o700 })
  const tokenFile = path.join(directory, 'token')
  let token
  try { token = (await fs.readFile(tokenFile, 'utf8')).trim() }
  catch (error) {
    if (error.code !== 'ENOENT') throw error
    token = randomBytes(32).toString('hex'); await fs.writeFile(tokenFile, token, { mode: 0o600, flag: 'wx' })
  }
  const runtime = await createRuntimeServer({ directory, token, port: Number(process.env.HAYBOT_BROWSER_PORT || 17322) })
  console.log(`浏览器运行时原型：${runtime.origin}\n本地访问码文件：${tokenFile}`)
  let stopping = false
  const stop = async () => { if (stopping) return; stopping = true; await runtime.close(); process.exit(0) }
  process.on('SIGINT', stop); process.on('SIGTERM', stop)
}
