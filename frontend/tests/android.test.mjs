import test from 'node:test'
import assert from 'node:assert/strict'
import { pointOnScreen, androidConfigPayload } from '../src/lib/android.js'
test('screen coordinate mapping handles scaling and clamps a drag outside the screen', () => {
  const rect = { left: 10, top: 20, width: 360, height: 640 }
  assert.deepEqual(pointOnScreen(190, 340, rect, 720, 1280), { x: 360, y: 640 })
  assert.deepEqual(pointOnScreen(-100, 2000, rect, 720, 1280), { x: 0, y: 1279 })
})
test('empty numeric fields stay editable but are rejected before saving', () => {
  assert.throws(() => androidConfigPayload({ max_steps: '', timeout_minutes: '5' }), /步数/)
  assert.throws(() => androidConfigPayload({ max_steps: '2', timeout_minutes: '' }), /时限/)
  assert.deepEqual(androidConfigPayload({ max_steps: '15', timeout_minutes: '5' }), { max_steps: 15, timeout_minutes: 5 })
})
test('manual stage budgets support long tasks beyond the former 60 step ceiling', () => {
 assert.deepEqual(androidConfigPayload({adaptive_budget:false,max_steps:'600',timeout_minutes:'90'}),{adaptive_budget:false,max_steps:600,timeout_minutes:90})
 assert.throws(()=>androidConfigPayload({max_steps:'10001',timeout_minutes:'90'}))
})
