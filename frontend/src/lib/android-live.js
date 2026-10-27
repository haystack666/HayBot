export function parseLiveFrame(raw) {
  if (!(raw instanceof ArrayBuffer) || raw.byteLength < 12) throw new Error('视频帧头不完整')
  const view = new DataView(raw), flags = view.getBigUint64(0), size = view.getUint32(8)
  if (!size || size > 4 * 1024 * 1024 || size + 12 !== raw.byteLength) throw new Error('视频帧长度无效')
  const pts = flags & ((1n << 62n) - 1n)
  if (pts > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error('视频时间戳无效')
  return { config: !!(flags & (1n << 63n)), keyframe: !!(flags & (1n << 62n)), pts: Number(pts), payload: new Uint8Array(raw, 12) }
}
export function livePoint(x, y, rect, width, height) {
  if (!(rect.width > 0 && rect.height > 0 && width > 0 && height > 0)) return null
  const scale = Math.min(rect.width / width, rect.height / height)
  const left = rect.left + (rect.width - width * scale) / 2
  const top = rect.top + (rect.height - height * scale) / 2
  if (x < left || y < top || x >= left + width * scale || y >= top + height * scale) return null
  return {
    x: Math.max(0, Math.min(width - 1, Math.floor((x - left) / scale))),
    y: Math.max(0, Math.min(height - 1, Math.floor((y - top) / scale))),
    width,
    height,
  }
}

export function splitAnnexB(bytes) {
  const starts = []
  for (let i = 0; i + 2 < bytes.length; i++) {
    if (bytes[i] !== 0 || bytes[i + 1] !== 0) continue
    if (bytes[i + 2] === 1) { starts.push([i, 3]); i += 2 }
    else if (i + 3 < bytes.length && bytes[i + 2] === 0 && bytes[i + 3] === 1) { starts.push([i, 4]); i += 3 }
  }
  return starts.map(([position, length], index) => bytes.slice(position + length, index + 1 < starts.length ? starts[index + 1][0] : bytes.length)).filter(nalu => nalu.length)
}

export function avcDecoderConfig(nalus) {
  const sps = nalus.find(nalu => (nalu[0] & 0x1f) === 7), pps = nalus.find(nalu => (nalu[0] & 0x1f) === 8)
  if (!sps || sps.length < 4 || !pps) return null
  const description = new Uint8Array(11 + sps.length + pps.length)
  description.set([1, sps[1], sps[2], sps[3], 0xff, 0xe1, sps.length >> 8, sps.length & 255])
  description.set(sps, 8)
  description[8 + sps.length] = 1
  description[9 + sps.length] = pps.length >> 8
  description[10 + sps.length] = pps.length & 255
  description.set(pps, 11 + sps.length)
  return { codec: 'avc1.' + [sps[1], sps[2], sps[3]].map(value => value.toString(16).padStart(2, '0')).join(''), description }
}

export function avcAccessUnit(nalus) {
  const slices = nalus.filter(nalu => nalu.length && ((nalu[0] & 0x1f) === 1 || (nalu[0] & 0x1f) === 5))
  if (!slices.length) return null
  const data = new Uint8Array(slices.reduce((total, nalu) => total + 4 + nalu.length, 0))
  let offset = 0
  for (const nalu of slices) {
    data[offset] = nalu.length >>> 24; data[offset + 1] = (nalu.length >>> 16) & 255; data[offset + 2] = (nalu.length >>> 8) & 255; data[offset + 3] = nalu.length & 255
    data.set(nalu, offset + 4); offset += 4 + nalu.length
  }
  return data
}
