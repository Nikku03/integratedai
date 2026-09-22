import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/endpoints'
import type { ScopeOut } from '../api/types'
import { Badge, KindBadge } from '../components/Badge'
import { Empty, ErrorBox, KeyVals, Loading, PageHeader, Panel } from '../components/Misc'
import { ScopeTree } from '../components/ScopeTree'
import { useAsync } from '../hooks/useAsync'
import { useScope } from '../state/scope'
import { useSettings } from '../state/settings'

function levelName(level: number): string {
  if (level >= 3) return 'admin'
  if (level >= 2) return 'write'
  if (level >= 1) return 'read'
  return 'none'
}

export default function ScopesPage() {
  const { scopes, loading, error, selectedId, select, selected, reload } = useScope()
  const { version, apiKey } = useSettings()
  const me = useAsync(() => api.me(true), [version], Boolean(apiKey))
  const projects = useAsync(() => api.projects(), [version], Boolean(apiKey))
  const [hideAgents, setHideAgents] = useState(true)

  const annotate = (s: ScopeOut) => {
    const info = me.data?.scopes[s.id]
    return info ? `${levelName(info.level)} · clearance ${info.clearance}` : null
  }

  const children = selected ? scopes.filter((s) => s.parent_id === selected.id) : []
  const parent = selected?.parent_id ? scopes.find((s) => s.id === selected.parent_id) : undefined
  const scopeProjects = selected ? (projects.data ?? []).filter((p) => p.scope_id === selected.id || children.some((c) => c.id === p.scope_id)) : []

  return (
    <div className="page">
      <PageHeader
        title="Departments & projects"
        subtitle="Pick the scope that every other panel searches, lists and runs against. The choice is remembered in this browser."
        actions={
          <div className="row gap">
            <label className="check">
              <input type="checkbox" checked={hideAgents} onChange={(e) => setHideAgents(e.target.checked)} /> hide agent & task scopes
            </label>
            <button type="button" className="btn" onClick={reload}>
              Refresh
            </button>
          </div>
        }
      />
      <div className="grid-2">
        <Panel title="Scope tree">
          {loading && <Loading />}
          <ErrorBox error={error} />
          {!loading && !error && (
            <ScopeTree scopes={scopes} selectedId={selectedId} onSelect={select} annotate={annotate} hideKinds={hideAgents ? ['agent', 'task'] : []} />
          )}
        </Panel>
        <Panel title="Selected scope">
          {!selected ? (
            <Empty>Select a scope in the tree.</Empty>
          ) : (
            <div className="stack">
              <h3>
                <KindBadge kind={selected.kind} /> {selected.name}
              </h3>
              <KeyVals
                items={[
                  ['Path', <code className="mono">{selected.path || '/'}</code>],
                  ['Id', <code className="mono small">{selected.id}</code>],
                  ['Parent', parent ? <button type="button" className="linklike" onClick={() => select(parent.id)}>{parent.name}</button> : '— (root)'],
                  ['Children', children.length ? children.map((c) => (
                    <button key={c.id} type="button" className="linklike" onClick={() => select(c.id)}>
                      {c.name}
                    </button>
                  )) : 'none'],
                  ['Your access', me.data?.scopes[selected.id] ? (
                    <span>
                      <Badge tone="blue">{levelName(me.data.scopes[selected.id].level)}</Badge> clearance {me.data.scopes[selected.id].clearance}
                    </span>
                  ) : (
                    <span className="muted">inherited / unknown</span>
                  )],
                ]}
              />
              <div className="row gap wrap">
                <Link className="btn small" to="/search">
                  Search this scope
                </Link>
                <Link className="btn small" to="/documents">
                  Documents in scope
                </Link>
                <Link className="btn small" to="/conflicts">
                  Conflicts in scope
                </Link>
              </div>
              <h4>Projects in this scope</h4>
              {scopeProjects.length === 0 ? (
                <div className="muted small">No projects directly under this scope.</div>
              ) : (
                <ul className="plain">
                  {scopeProjects.map((p) => (
                    <li key={p.id}>
                      <Link to={`/projects/${p.id}`}>{p.name}</Link> <Badge tone="gray">{p.status}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}
