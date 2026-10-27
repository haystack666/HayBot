// scrcpy messages contain complete access units. The trailing delimiter makes
// JMuxer consume the final NAL now instead of retaining it until the next frame.
const delimiter = new Uint8Array([0, 0, 0, 1, 9, 0xf0])
// JMuxer drops its init segment if feed() runs before MediaSource sourceopen.
export class BufferedMseSink {
  constructor(Muxer, options) {
    this.ready = false; this.closed = false; this.queue = []; this.bytes = 0
    this.muxer = new Muxer({ ...options, onReady: () => {
      if (this.closed) return
      this.ready = true
      for (const frame of this.queue) this.muxer.feed(frame)
      this.queue = []; this.bytes = 0
      options.onReady?.()
    } })
  }
  feed(frame) {
    if (this.closed) return
    if (this.ready) { this.muxer.feed(frame); return }
    this.bytes += frame.video.byteLength
    if (this.bytes > 8 * 1024 * 1024 || this.queue.length >= 120) throw new Error('视频启动缓冲已满')
    this.queue.push(frame)
  }
  destroy() { this.closed = true; this.queue = []; this.bytes = 0; this.muxer.destroy() }
}
export class LiveVideoFeed {
  constructor(create) { this.create = create; this.config = null; this.muxer = null; this.pts = null }
  push(frame) {
    if (frame.config) {
      if (this.config && this.config.length === frame.payload.length && this.config.every((v, i) => v === frame.payload[i])) return
      this.destroy(); this.config = frame.payload.slice(); return
    }
    if (!this.config || (!this.muxer && !frame.keyframe)) return
    const fresh = !this.muxer
    if (fresh) this.muxer = this.create()
    const data = new Uint8Array((fresh ? this.config.length : 0) + frame.payload.length + delimiter.length)
    let offset = 0
    if (fresh) { data.set(this.config); offset = this.config.length }
    data.set(frame.payload, offset); data.set(delimiter, offset + frame.payload.length)
    const duration = this.pts === null ? 33 : Math.max(1, Math.min(1000, (frame.pts - this.pts) / 1000))
    this.pts = frame.pts
    this.muxer.feed({ video: data, duration })
  }
  destroy() { this.muxer?.destroy(); this.muxer = null; this.pts = null }
}
