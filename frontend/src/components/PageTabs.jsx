import { useSearchParams } from 'react-router-dom'

export function usePageTabs(items, parameter = 'view') {
  const [search, setSearch] = useSearchParams()
  const value = items.some(([id]) => id === search.get(parameter)) ? search.get(parameter) : items[0][0]
  const select = next => setSearch(previous => { const updated = new URLSearchParams(previous); updated.set(parameter, next); return updated }, { replace: true })
  return { value, select, tabs: <nav className="page-tabs" aria-label="页内导航">{items.map(([id, title]) => <button type="button" key={id} className={value === id ? 'is-active' : ''} aria-current={value === id ? 'page' : undefined} onClick={() => select(id)}>{title}</button>)}</nav> }
}

export function Section({ show, children, className = '' }) {
  return <div hidden={!show} className={'page-section '+className}>{children}</div>
}
