import type { ReactNode } from 'react'
import { scalar } from '../lib/format'

export function Panel({ title, actions, children, className = '' }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <header className="panel-head">
          {title && <h2>{title}</h2>}
          {actions && <div className="panel-actions">{actions}</div>}
        </header>
      )}
      <div className="panel-body">{children}</div>
    </section>
  )
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}

export function Loading({ text = 'Loading…' }: { text?: string }) {
  return <div className="loading">{text}</div>
}

export function ErrorBox({ error }: { error: Error | string | undefined }) {
  if (!error) return null
  return <div className="error-box">{typeof error === 'string' ? error : error.message}</div>
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

/** Definition-list style key/value grid. */
export function KeyVals({ items }: { items: Array<[string, ReactNode]> }) {
  return (
    <dl className="kv">
      {items.map(([k, v]) => (
        <div key={k} className="kv-row">
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  )
}

export function JsonView({ value, summary = 'Raw JSON', open = false }: { value: unknown; summary?: string; open?: boolean }) {
  if (value === undefined || value === null) return null
  return (
    <details className="json" open={open}>
      <summary>{summary}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  )
}

/** Renders an object's primitive fields as chips and nested values as JSON. */
export function ContentView({ value, omit = [] }: { value: Record<string, unknown> | null | undefined; omit?: string[] }) {
  if (!value) return <span className="muted">—</span>
  const entries = Object.entries(value).filter(([k]) => !omit.includes(k))
  if (!entries.length) return <span className="muted">—</span>
  const prim = entries.filter(([, v]) => v === null || ['string', 'number', 'boolean'].includes(typeof v))
  const nested = entries.filter(([, v]) => v !== null && typeof v === 'object')
  return (
    <div className="content-view">
      {prim.map(([k, v]) => (
        <div key={k} className="content-kv">
          <span className="content-k">{k}</span>
          <span className="content-v">{scalar(v)}</span>
        </div>
      ))}
      {nested.length > 0 && <JsonView value={Object.fromEntries(nested)} summary={`${nested.length} nested field${nested.length > 1 ? 's' : ''}`} />}
    </div>
  )
}

export function Meter({ value, max = 1, tone = 'blue', label }: { value: number | null | undefined; max?: number; tone?: string; label?: string }) {
  const pct = value === null || value === undefined ? 0 : Math.max(0, Math.min(100, (value / max) * 100))
  return (
    <span className="meter" title={label ?? (value ?? '—').toString()}>
      <span className={`meter-fill meter-${tone}`} style={{ width: `${pct}%` }} />
    </span>
  )
}
