import { useEffect, useState } from 'react'
import { Check, Monitor, Moon, Sun } from 'lucide-react'
import { DropdownMenu } from 'radix-ui'
import { Button } from '@/components/ui/button'

const modes = [{ value: 'light', label: '浅色模式', icon: Sun }, { value: 'dark', label: '深色模式', icon: Moon }, { value: 'system', label: '跟随系统', icon: Monitor }]
const readTheme = () => { try { const value = localStorage.getItem('haybot-theme'); return modes.some(mode => mode.value === value) ? value : 'system' } catch { return 'system' } }

export default function ThemeSelector() {
  const [theme, setTheme] = useState(readTheme)
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      const dark = theme === 'dark' || (theme === 'system' && media.matches)
      document.documentElement.classList.toggle('dark', dark)
      document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
      document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#09090b' : '#ffffff')
    }
    apply()
    const sync = event => { if (event.key === 'haybot-theme' || event.key === null) setTheme(readTheme()) }
    media.addEventListener('change', apply)
    window.addEventListener('storage', sync)
    return () => { media.removeEventListener('change', apply); window.removeEventListener('storage', sync) }
  }, [theme])
  const CurrentIcon = modes.find(mode => mode.value === theme).icon
  return <DropdownMenu.Root><DropdownMenu.Trigger asChild><Button variant="ghost" size="icon" aria-label="切换主题" title="切换主题"><CurrentIcon size={17} /></Button></DropdownMenu.Trigger><DropdownMenu.Portal><DropdownMenu.Content className="theme-menu" sideOffset={8} align="end"><DropdownMenu.Label className="theme-menu-label">外观</DropdownMenu.Label><DropdownMenu.RadioGroup value={theme} onValueChange={value => { try { localStorage.setItem('haybot-theme', value) } catch { /* Keep the theme usable when storage is unavailable. */ } setTheme(value) }}>{modes.map(({ value, label, icon: Icon }) => <DropdownMenu.RadioItem key={value} className="theme-menu-item" value={value}><Icon size={15} /><span>{label}</span><DropdownMenu.ItemIndicator className="theme-check"><Check size={14} /></DropdownMenu.ItemIndicator></DropdownMenu.RadioItem>)}</DropdownMenu.RadioGroup></DropdownMenu.Content></DropdownMenu.Portal></DropdownMenu.Root>
}
