import test from 'node:test'
import assert from 'node:assert/strict'
import { scopePath, providerPayload } from '../src/lib/memory-config.js'

test('scope path preserves pagination and replaces stale owners', () => {
  const path = scopePath('/schedule/changes?day=2026-10-24&scope_id=old&before=15', 'current user')
  const parsed = new URL(path, 'http://local')
  assert.equal(parsed.searchParams.get('scope_id'), 'current user')
  assert.equal(parsed.searchParams.get('before'), '15')
  assert.equal(parsed.searchParams.get('day'), '2026-10-24')
  assert.throws(() => scopePath('/memory', ''), /选择用户/)
})

test('empty dimensions remain unset while invalid values fail before saving', () => {
  assert.equal(providerPayload({ embedding_dimensions: '' }).embedding_dimensions, null)
  assert.equal(providerPayload({ embedding_dimensions: '1024' }).embedding_dimensions, 1024)
  assert.throws(() => providerPayload({ embedding_dimensions: '0' }), /维度/)
  assert.throws(() => providerPayload({ embedding_dimensions: '1.5' }), /维度/)
})
