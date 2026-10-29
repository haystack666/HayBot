// Only manage windows belonging to this Bot's context. The native window may
// restore itself when Chrome creates a tab, even without Page.bringToFront.
export class BrowserWindows {
  constructor(context) {
    this.context = context
    this.clients = new WeakMap()
    this.states = new Map()
  }
  async inspect(page) {
    let client = this.clients.get(page)
    if (!client) {
      client = this.context.newCDPSession(page)
      this.clients.set(page, client)
    }
    client = await client
    return { client, ...await client.send('Browser.getWindowForTarget') }
  }
  async capture() {
    const states = new Map()
    await Promise.all(this.context.pages().map(async page => {
      try {
        const { windowId, bounds } = await this.inspect(page)
        states.set(windowId, bounds.windowState)
      } catch { /* A page can close while its window is being inspected. */ }
    }))
    this.states = states
  }
  async restorePage(page) {
    try {
      const { client, windowId, bounds } = await this.inspect(page)
      let previous = this.states.get(windowId)
      if (previous === undefined) {
        // A target=_blank link may open a separate window. Inherit only the
        // opener's captured state, never an unrelated Bot/window's preference.
        const opener = await page.opener()
        if (opener && !opener.isClosed()) previous = this.states.get((await this.inspect(opener)).windowId)
      }
      if (previous === 'minimized' && bounds.windowState !== 'minimized') {
        await client.send('Browser.setWindowBounds', { windowId, bounds: { windowState: 'minimized' } })
      }
    } catch { /* Closed pages and unsupported native window controls are harmless. */ }
  }
  async restore() {
    await Promise.all(this.context.pages().map(page => this.restorePage(page)))
  }
}
