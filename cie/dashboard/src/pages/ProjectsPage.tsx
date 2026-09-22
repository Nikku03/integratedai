import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/endpoints'
import { StatusBadge } from '../components/Badge'
import { Empty, ErrorBox, Loading, PageHeader, Panel } from '../components/Misc'
import { useAsync } from '../hooks/useAsync'
import { short, trunc } from '../lib/format'
import { useScope } from '../state/scope'
import { useSettings } from '../state/settings'
import { useToast } from '../state/toast'

export default function ProjectsPage() {
  const { version } = useSettings()
  const { selectedId, selected, scopes } = useScope()
  const { push } = useToast()
  const navigate = useNavigate()
  const projects = useAsync(() => api.projects(), [version])
  const [name, setName] = useState('')
  const [objective, setObjective] = useState('')
  const [busy, setBusy] = useState(false)

  async function create(e: FormEvent) {
    e.preventDefault()
    if (!selectedId || !name.trim()) return
    setBusy(true)
    try {
      const p = await api.createProject({ name: name.trim(), parent_scope_id: selectedId, objective: objective.trim() })
      push('success', `Project "${p.name}" created`)
      setName('')
      setObjective('')
      navigate(`/projects/${p.id}`)
    } catch {
      /* toast shown by client */
    } finally {
      setBusy(false)
    }
  }

  const scopeName = (id: string) => scopes.find((s) => s.id === id)?.path || short(id)

  return (
    <div className="page">
      <PageHeader title="Project map" subtitle="Projects run by the head agent. Open one to see its objective, task DAG and ledger." />
      <div className="grid-2 wide-left">
        <Panel title={<span>Projects {projects.data && <span className="muted">({projects.data.length})</span>}</span>} actions={<button type="button" className="btn small" onClick={projects.reload}>refresh</button>}>
          {projects.loading && <Loading />}
          <ErrorBox error={projects.error} />
          {projects.data && projects.data.length === 0 && <Empty>No projects yet. Create one on the right.</Empty>}
          {projects.data && projects.data.length > 0 && (
            <div className="table-wrap">
              <table className="table hover">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Objective</th>
                    <th>Scope</th>
                  </tr>
                </thead>
                <tbody>
                  {projects.data.map((p) => (
                    <tr key={p.id} onClick={() => navigate(`/projects/${p.id}`)}>
                      <td>
                        <Link to={`/projects/${p.id}`} className="cell-title">
                          {p.name}
                        </Link>
                      </td>
                      <td>
                        <StatusBadge status={p.status} />
                      </td>
                      <td className="small">{trunc(p.objective, 140) || <span className="muted">—</span>}</td>
                      <td className="small mono">{scopeName(p.scope_id)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        <Panel title="New project">
          <form className="stack" onSubmit={create}>
            <label className="field">
              <span>Name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </label>
            <label className="field">
              <span>Objective</span>
              <textarea rows={4} value={objective} onChange={(e) => setObjective(e.target.value)} placeholder="What should the head agent achieve?" />
            </label>
            <div className="muted small">
              Parent scope: {selected ? <strong>{selected.path || selected.name}</strong> : <Link to="/scopes">select a scope</Link>}
            </div>
            <button type="submit" className="btn primary" disabled={!selectedId || !name.trim() || busy}>
              {busy ? 'Creating…' : 'Create project'}
            </button>
          </form>
        </Panel>
      </div>
    </div>
  )
}
