export function scopePath(path, scopeId) {
  if (!scopeId) throw new Error('请先选择用户')
  const [base, search = ''] = path.split('?')
  const params = new URLSearchParams(search)
  params.set('scope_id', scopeId)
  return `${base}?${params}`
}

export function providerPayload(draft) {
  const value = draft.embedding_dimensions
  const dimensions = value == null || String(value).trim() === '' ? null : Number(value)
  if (dimensions !== null && (!Number.isInteger(dimensions) || dimensions < 1 || dimensions > 65536)) throw new Error('向量维度必须为 1–65536 的整数，或留空使用模型默认值')
  return { ...draft, embedding_dimensions: dimensions }
}
