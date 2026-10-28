const $ = id => document.getElementById(id)
const embedded = new URL(location.href).searchParams.has('iframe')
if (embedded) document.querySelector('iframe').remove()
$('message').value = localStorage.getItem('message') || ''
$('save').onclick = () => { localStorage.setItem('message', $('message').value); document.cookie = 'fixture=retained; SameSite=Strict; Path=/; Max-Age=86400'; $('result').textContent = '已保存：' + $('message').value }
$('feed').replaceChildren(...Array.from({ length: 8 }, (_, index) => { const p = document.createElement('p'); p.textContent = `合成内容 ${index + 1} · 用于检查滚动后页面观察与画面是否一致`; p.style.padding = '24px'; return p }))
const canvas = $('animation'), context = canvas.getContext('2d')
let tick = 0
setInterval(() => { tick++; $('clock').textContent = '画面更新 ' + tick; context.fillStyle = '#151515'; context.fillRect(0, 0, 600, 180); context.fillStyle = '#fff'; context.beginPath(); context.arc(30 + tick * 8 % 540, 90, 22, 0, Math.PI * 2); context.fill() }, 100)
$('video').srcObject = canvas.captureStream(10)
$('video').play().catch(() => {})
