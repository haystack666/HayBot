import { useEffect, useId, useRef, useState } from 'react'
import { Maximize2, Minimize2 } from 'lucide-react'
import { Button } from '@/components/ui/button'

export default function AndroidViewer({ name, children }) {
  const [expanded, setExpanded] = useState(false)
  const viewer = useRef(null), toggle = useRef(null)
  const titleId = useId()
  useEffect(() => {
    if (!expanded) return
    const node = viewer.current, previousFocus = document.activeElement
    const overflow = document.body.style.overflow
    const siblings = []
    // Keep the playing video in place while making the rest of the page inert.
    for (let branch = node; branch?.parentElement; branch = branch.parentElement) {
      for (const sibling of branch.parentElement.children) {
        if (sibling !== branch && sibling instanceof HTMLElement) {
          siblings.push([sibling, sibling.inert]); sibling.inert = true
        }
      }
      if (branch.parentElement === document.body) break
    }
    document.body.style.overflow = 'hidden'
    toggle.current?.focus()
    const keydown = event => {
      if (event.key === 'Escape' && !event.isComposing) {
        event.preventDefault(); event.stopPropagation(); setExpanded(false); return
      }
      if (event.key !== 'Tab') return
      const focusable = [...node.querySelectorAll('button, input, textarea, select, a[href], [tabindex]')]
        .filter(element => !element.disabled && element.tabIndex >= 0 && element.getClientRects().length)
      if (!focusable.length) { event.preventDefault(); node.focus(); return }
      const index = focusable.indexOf(document.activeElement)
      if (event.shiftKey && index <= 0) { event.preventDefault(); focusable.at(-1).focus() }
      else if (!event.shiftKey && (index < 0 || index === focusable.length - 1)) { event.preventDefault(); focusable[0].focus() }
    }
    document.addEventListener('keydown', keydown, true)
    return () => {
      document.removeEventListener('keydown', keydown, true)
      document.body.style.overflow = overflow
      for (const [sibling, inert] of siblings) sibling.inert = inert
      if (previousFocus?.isConnected) previousFocus.focus()
    }
  }, [expanded])
  return <div ref={viewer} className={`android-viewer${expanded ? ' is-expanded' : ''}`} role={expanded ? 'dialog' : undefined} aria-modal={expanded ? true : undefined} aria-labelledby={expanded ? titleId : undefined} tabIndex={expanded ? -1 : undefined}>
    <div className="android-viewer-heading">{expanded && <b id={titleId}>{name}</b>}<Button ref={toggle} type="button" variant="outline" size="sm" onClick={() => setExpanded(value => !value)}>{expanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}{expanded ? '收起画面' : '放大画面'}</Button></div>
    <div className="android-viewer-body">{children}</div>
  </div>
}
