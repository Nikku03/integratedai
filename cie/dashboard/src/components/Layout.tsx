import { NavLink, Outlet, Link } from 'react-router-dom'
import { api } from '../api/endpoints'
import { useAsync } from '../hooks/useAsync'
import { useScope } from '../state/scope'
import { useSettings } from '../state/settings'
import { Badge } from './Badge'

const NAV: Array<{ to: string; label: string; group?: string }> = [
  { to: '/search', label: 'Memory search', group: 'Memory' },
  { to: '/scopes', label: 'Departments & projects' },
  { to: '/documents', label: 'Document library' },
  { to: '/conflicts', label: 'Conflicts & questions' },
  { to: '/evidence', label: 'Evidence viewer' },
  { to: '/projects', label: 'Project map', group: 'Agents' },
  { to: '/agents', label: 'Active agents' },
  { to: '/tasks', label: 'Task queue' },
  { to: '/graph', label: 'Dependency graph' },
  { to: '/ledger', label: 'Decision ledger' },
  { to: '/approvals', label: 'Approval queue' },
  { to: '/performance', label: 'Agent performance', group: 'Operations' },
  { to: '/metrics', label: 'Metrics' },
  { to: '/settings', label: 'Settings' },
]

export function Layout() {
  const { apiKey, apiBase, version } = useSettings()
  const { selected, loading: scopesLoading } = useScope()
  const me = useAsync(() => api.me(true), [version], Boolean(apiKey))

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">CIE</span>
          <span className="brand-name">Control</span>
        </div>
        <nav>
          {NAV.map((n) => (
            <div key={n.to}>
              {n.group && <div className="nav-group">{n.group}</div>}
              <NavLink to={n.to} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
                {n.label}
              </NavLink>
            </div>
          ))}
        </nav>
        <div className="sidebar-foot muted small">
          <div title={apiBase}>{apiBase.replace(/^https?:\/\//, '')}</div>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <Link to="/scopes" className="scope-pill" title="Change the active scope">
            <span className="muted small">Scope</span>{' '}
            {selected ? (
              <span>
                <Badge tone="blue">{selected.kind}</Badge> {selected.path || selected.name}
              </span>
            ) : scopesLoading ? (
              <span className="muted">loading…</span>
            ) : (
              <span className="muted">none selected</span>
            )}
          </Link>
          <div className="conn">
            {!apiKey ? (
              <Link to="/settings">
                <Badge tone="amber">no API key — open Settings</Badge>
              </Link>
            ) : me.loading ? (
              <Badge tone="gray">connecting…</Badge>
            ) : me.error ? (
              <Link to="/settings">
                <Badge tone="red">disconnected: {me.error.message}</Badge>
              </Link>
            ) : me.data ? (
              <span>
                <Badge tone="green">connected</Badge> <span className="muted">{me.data.principal.name}</span>{' '}
                {me.data.is_admin && <Badge tone="purple">admin</Badge>}
              </span>
            ) : null}
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
