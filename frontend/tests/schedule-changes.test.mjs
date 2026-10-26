import test from 'node:test'
import assert from 'node:assert/strict'
import { mergeScheduleChanges } from '../src/lib/schedule-changes.js'

const page = (high, low, generation='a', day='2026-10-24') => Array.from({length:high-low+1}, (_,index) => ({id:high-index, day, generation_id:generation, current_generation:true}))

test('polling retains displaced records after older pages have loaded', () => {
  let records = mergeScheduleChanges([], page(41,22), '2026-10-24', 'a')
  records = mergeScheduleChanges(records, page(21,2), '2026-10-24', 'a')
  records = mergeScheduleChanges(records, page(42,23), '2026-10-24', 'a')
  assert.deepEqual(records.map(item=>item.id), Array.from({length:41},(_,index)=>42-index))
})

test('a reset updates generation badges on every cached audit record', () => {
  const cached = mergeScheduleChanges([], page(41,2), '2026-10-24', 'a')
  const records = mergeScheduleChanges(cached, page(41,22), '2026-10-24', 'b')
  assert.equal(records.length,40)
  assert.ok(records.every(item=>item.current_generation===false))
})

test('crossing midnight excludes the previous day from cached results', () => {
  const records = mergeScheduleChanges(page(20,1), page(21,21,'b','2026-10-25'), '2026-10-25', 'b')
  assert.deepEqual(records.map(item=>item.id),[21])
  assert.equal(records[0].current_generation,true)
})
