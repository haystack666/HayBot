const layout = document.querySelector('#live-layout'), pane = document.querySelector('#progress-pane')
const progressButton = document.querySelector('[data-action="task-detail"]')
let progressOpen = false
function toggleProgress(next) {
  progressOpen = next
  layout.classList.toggle('progress-open', next)
  pane.setAttribute('aria-hidden', String(!next))
  pane.inert = !next
  progressButton.setAttribute('aria-expanded', String(next))
  progressButton.firstChild.textContent = next ? '收起进度' : '查看进度'
  if (!next && pane.contains(document.activeElement)) progressButton.focus({preventScroll:true})
}
actions['task-detail'] = () => {
  document.querySelector('[data-page="live"]').click()
  toggleProgress(!progressOpen)
}
pane.inert = true
document.querySelector('#close-progress').addEventListener('click', () => toggleProgress(false))
document.querySelector('#slow-motion').addEventListener('click', e => {
  const slow = layout.classList.toggle('slow')
  e.currentTarget.textContent = slow ? '恢复正常动效' : '慢速演示动效'
  toggleProgress(!progressOpen)
})
function fitProgress() {
  if (innerWidth <= 850) return
  const viewerHeight = document.querySelector('#viewer').getBoundingClientRect().height
  layout.style.setProperty('--progress-height', `${Math.max(400, Math.round(viewerHeight))}px`)
}
new ResizeObserver(fitProgress).observe(document.querySelector('#viewer'))
window.addEventListener('resize', fitProgress)
fitProgress()
document.addEventListener('keydown', e => { if (e.key === 'Escape' && progressOpen && !document.querySelector('dialog[open]')) toggleProgress(false) })
document.querySelector('#demo-update').addEventListener('click', () => {
  const row = document.createElement('li'); row.className = 'just-added'
  row.innerHTML = '<span class="step-check">✓</span><div><div class="step-meta">刚刚 <span>观看完成</span></div><b>窗边午睡的小猫</b><p>实际播放推进 28 秒，已覆盖全片。准备继续看下一条推荐。</p></div>'
  document.querySelector('.progress-timeline').prepend(row)
  document.querySelector('.current-step b').textContent = '寻找下一条感兴趣的视频'
  document.querySelector('.current-step p').textContent = '继续看看推荐里有没有好看的舞台或者小动物。'
  document.querySelector('.progress-scroll').scrollTo({top:0,behavior:'smooth'})
})
