import test from 'node:test'
import assert from 'node:assert/strict'
import { readLogFilters, logQuery, mergeLogPages } from '../src/lib/logs.js'

test('filter query preserves literal keywords and finite time windows', () => {
  const filters = readLogFilters(new URLSearchParams('level=error&category=model&q=a%26b&range=1h'))
  const query = new URLSearchParams(logQuery(filters, 10000000))
  assert.equal(query.get('q'), 'a&b')
  assert.equal(query.get('level'), 'error')
  assert.equal(query.get('start'), '6400')
  assert.equal(readLogFilters(new URLSearchParams('level=unknown&range=bad')).level, '')
})

test('polling merges records without losing loaded older pages', () => {
  const previous = [{ id: 5, message: 'five' }, { id: 4 }, { id: 1 }]
  const merged = mergeLogPages(previous, [{ id: 6 }, { id: 5, message: 'updated' }])
  assert.deepEqual(merged.map(item => item.id), [6, 5, 4, 1])
  assert.equal(merged[1].message, 'updated')
})
