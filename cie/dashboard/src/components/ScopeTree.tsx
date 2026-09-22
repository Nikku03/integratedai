import { useMemo, useState } from 'react'
import type { ScopeOut } from '../api/types'
import { KindBadge } from './Badge'

interface Props {
  scopes: ScopeOut[]
  selectedId: string | null
  onSelect: (id: string) => void
  /** Optional per-scope annotation (e.g. clearance / permission level). */
  annotate?: (s: ScopeOut) => string | null
  /** Hide agent/task scopes (they are numerous and rarely a search target). */
  hideKinds?: string[]
}

export function ScopeTree({ scopes, selectedId, onSelect, annotate, hideKinds = [] }: Props) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const { roots, children } = useMemo(() => {
    const ids = new Set(scopes.map((s) => s.id))
    const children = new Map<string, ScopeOut[]>()
    const roots: ScopeOut[] = []
    for (const s of scopes) {
      if (hideKinds.includes(s.kind)) continue
      if (s.parent_id && ids.has(s.parent_id)) {
        const arr = children.get(s.parent_id) ?? []
        arr.push(s)
        children.set(s.parent_id, arr)
      } else roots.push(s)
    }
    const byName = (a: ScopeOut, b: ScopeOut) => a.name.localeCompare(b.name)
    roots.sort(byName)
    children.forEach((arr) => arr.sort(byName))
    return { roots, children }
  }, [scopes, hideKinds])

  const toggle = (id: string) =>
    setCollapsed((c) => {
      const n = new Set(c)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })

  const render = (s: ScopeOut, depth: number) => {
    const kids = children.get(s.id) ?? []
    const isCollapsed = collapsed.has(s.id)
    const note = annotate?.(s)
    return (
      <li key={s.id}>
        <div className={`tree-row ${s.id === selectedId ? 'selected' : ''}`} style={{ paddingLeft: depth * 18 }}>
          {kids.length ? (
            <button type="button" className="tree-toggle" onClick={() => toggle(s.id)} aria-label={isCollapsed ? 'expand' : 'collapse'}>
              {isCollapsed ? '▸' : '▾'}
            </button>
          ) : (
            <span className="tree-toggle-spacer" />
          )}
          <button type="button" className="tree-label" onClick={() => onSelect(s.id)}>
            <KindBadge kind={s.kind} /> <span>{s.name}</span>
          </button>
          {note && <span className="muted small tree-note">{note}</span>}
        </div>
        {!isCollapsed && kids.length > 0 && <ul>{kids.map((k) => render(k, depth + 1))}</ul>}
      </li>
    )
  }

  if (!roots.length) return <div className="empty">No scopes visible to this API key.</div>
  return <ul className="tree">{roots.map((r) => render(r, 0))}</ul>
}
