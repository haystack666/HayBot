const $ = id => document.getElementById(id)
const embedded = new URL(location.href).searchParams.has('iframe')
if (embedded) document.querySelector('iframe').remove()
$('message').value = localStorage.getItem('message') || ''
$('save').onclick = () => { localStorage.setItem('message', $('message').value); document.cookie = 'fixture=retained; SameSite=Strict; Path=/; Max-Age=86400'; $('result').textContent = '已保存：' + $('message').value }
$('range').oninput = () => { $('range-result').textContent = '滑块：' + $('range').value }
$('nested-feed').replaceChildren(...Array.from({ length: 24 }, (_, index) => { const p = document.createElement('p'); p.textContent = `区域内第 ${index + 1} 行 · 横向与纵向滚动验收`; return p }))
$('nested-scroll').onscroll = () => { $('scroll-result').textContent = `纵向：${Math.round($('nested-scroll').scrollTop)} · 横向：${Math.round($('nested-scroll').scrollLeft)}` }
let drag = null
$('drag-handle').onpointerdown = event => { drag = { x: event.clientX, left: $('drag-handle').offsetLeft }; $('drag-handle').setPointerCapture(event.pointerId) }
$('drag-handle').onpointermove = event => {
  if (!drag) return
  const left = Math.max(0, Math.min($('drag-track').clientWidth - $('drag-handle').offsetWidth, drag.left + event.clientX - drag.x))
  $('drag-handle').style.left = left + 'px'; $('drag-result').textContent = '拖动距离：' + Math.round(left - 12)
}
$('drag-handle').onpointerup = $('drag-handle').onpointercancel = () => { drag = null }
$('feed').replaceChildren(...Array.from({ length: 8 }, (_, index) => { const p = document.createElement('p'); p.textContent = `合成内容 ${index + 1} · 用于检查滚动后页面观察与画面是否一致`; p.style.padding = '24px'; return p }))
const canvas = $('animation'), context = canvas.getContext('2d')
let tick = 0
setInterval(() => { tick++; $('clock').textContent = '画面更新 ' + tick; context.fillStyle = '#151515'; context.fillRect(0, 0, 600, 180); context.fillStyle = '#fff'; context.beginPath(); context.arc(30 + tick * 8 % 540, 90, 22, 0, Math.PI * 2); context.fill() }, 100)
$('video').srcObject = canvas.captureStream(10)
$('video').play().catch(() => {})
