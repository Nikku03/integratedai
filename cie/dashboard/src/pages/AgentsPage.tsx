import { Link } from 'react-router-dom'
import { api } from '../api/endpoints'
import { Badge } from '../components/Badge'
import { Empty, ErrorBox, Loading, PageHeader } from '../components/Misc'
import { useAsync } from '../hooks/useAsync'
import { fmtUsd } from '../lib/format'
import { useSettings } from '../state/settings'

const ROLE_TONE: Record<string, 'purple' | 'blue' | 'teal' | 'amber' | 'green' | 'gray'> = {
  head: 'purple',
  legal: 'blue',
  finance: 'green',
  operations: 'amber',
  engineering: 'teal',
  research: 'gray',
}

export default function AgentsPage() {
  const { version } = useSettings()
  const agents = useAsync(() => api.agents(), [version])
  const busy = (agents.data ?? []).filter((a) => a.busy).length
  return (
    <div className="page">
      <PageHeader
        title="Active agents"
        subtitle={agents.data ? `${agents.data.length} registered · ${busy} busy` : 'Registered specialist agents and the head agent.'}
        actions={<button type="button" className="btn small" onClick={agents.reload}>refresh</button>}
      />
      {agents.loading && <Loading />}
      <ErrorBox error={agents.error} />
      {agents.data && agents.data.length === 0 && <Empty>No agents registered. Running a project as admin registers the default set.</Empty>}
      <div className="cards">
        {(agents.data ?? []).map((a) => (
          <article key={a.id} className={`card agent ${a.busy ? 'busy' : ''} ${a.active ? '' : 'inactive'}`}>
            <header className="row between">
              <h3>{a.name}</h3>
              <span className={`busy-dot ${a.busy ? 'on' : ''}`} title={a.busy ? 'busy' : 'idle'}>
                {a.busy ? 'busy' : 'idle'}
              </span>
            </header>
            <div className="badges">
              <Badge tone={ROLE_TONE[a.role] ?? 'gray'}>{a.role}</Badge>
              <Badge tone="gray">{a.strategy}</Badge>
              {a.model && <Badge tone="gray">{a.model}</Badge>}
              {!a.active && <Badge tone="red">inactive</Badge>}
            </div>
            <dl className="kv compact">
              <div className="kv-row">
                <dt>Cost / 1k tokens</dt>
                <dd>{fmtUsd(a.cost_per_1k_tokens)}</dd>
              </div>
              <div className="kv-row">
                <dt>Max concurrency</dt>
                <dd>{a.max_concurrency}</dd>
              </div>
            </dl>
            <div>
              <div className="muted small">Task types</div>
              <div className="chips">
                {a.task_types.length ? a.task_types.map((t) => <span key={t} className="chip">{t}</span>) : <span className="muted small">—</span>}
              </div>
            </div>
            <div>
              <div className="muted small">Skills</div>
              <div className="chips">
                {a.skills.length ? a.skills.map((s) => <span key={s} className="chip chip-soft">{s}</span>) : <span className="muted small">—</span>}
              </div>
            </div>
            <footer className="row between small">
              <Link to={`/performance?agent=${a.id}`}>scorecards →</Link>
              <code className="mono muted">{a.id.slice(0, 8)}</code>
            </footer>
          </article>
        ))}
      </div>
    </div>
  )
}
