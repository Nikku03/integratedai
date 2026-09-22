import { useEffect, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/endpoints'
import type { LedgerContent } from '../api/types'
import { Badge, StatusBadge } from '../components/Badge'
import { DagSvg } from '../components/DagSvg'
import { ContentView, Empty, ErrorBox, JsonView, KeyVals, Loading, PageHeader, Panel } from '../components/Misc'
import { TaskDetail } from '../components/TaskDetail'
import { useAsync } from '../hooks/useAsync'
import { fmtDate, fmtNum, scalar, short } from '../lib/format'
import { useSettings } from '../state/settings'
import { useToast } from '../state/toast'

function contentText(c: LedgerContent): string {
  for (const k of ['summary', 'objective', 'reason', 'decision', 'statement', 'title', 'answer', 'text']) {
    const v = c[k]
    if (typeof v === 'string' && v) return v
  }
  const prim = Object.entries(c).filter(([k, v]) => !['seq', 'label', 'at', 'actor', 'refs'].includes(k) && (typeof v === 'string' || typeof v === 'number'))
  return prim.map(([k, v]) => `${k}: ${scalar(v)}`).join(' · ')
}

export default function ProjectDetailPage() {
  const { id = '' } = useParams()
  const { version } = useSettings()
  const { push } = useToast()
  const proj = useAsync(() => api.project(id), [id, version], Boolean(id))
  const msgs = useAsync(() => api.messages(id), [id, version], Boolean(id))
  const [selectedTask, setSelectedTask] = useState<string | null>(null)
  const [objective, setObjective] = useState('')
  const [maxSteps, setMaxSteps] = useState(20)
  const [background, setBackground] = useState(false)
  const [running, setRunning] = useState(false)

  useEffect(() => {
    if (proj.data && !objective) setObjective(proj.data.objective)
  }, [proj.data, objective])

  async function run(e: FormEvent) {
    e.preventDefault()
    if (!objective.trim()) return
    setRunning(true)
    try {
      const out = await api.runProject(id, { objective: objective.trim(), max_steps: maxSteps, background })
      if (out.job_id) push('success', `Run queued as job ${short(out.job_id)}`)
      else push('success', `Run finished · project ${out.status} · ${out.ledger?.entries ?? 0} ledger entries`)
      proj.reload()
      msgs.reload()
    } catch {
      /* toast shown */
    } finally {
      setRunning(false)
    }
  }

  const p = proj.data
  const task = p?.tasks.find((t) => t.id === selectedTask) ?? null
  const led = p?.ledger
  const statusCounts = (p?.tasks ?? []).reduce<Record<string, number>>((acc, t) => ((acc[t.status] = (acc[t.status] ?? 0) + 1), acc), {})

  return (
    <div className="page">
      {proj.loading && <Loading />}
      <ErrorBox error={proj.error} />
      {p && (
        <>
          <PageHeader
            title={
              <span>
                {p.name} <StatusBadge status={p.status} />
              </span>
            }
            subtitle={p.objective || 'No objective yet.'}
            actions={
              <div className="row gap wrap">
                <Link className="btn small" to={`/tasks?project=${p.id}`}>
                  Task queue
                </Link>
                <Link className="btn small" to={`/graph?project=${p.id}`}>
                  Dependency graph
                </Link>
                <Link className="btn small" to={`/ledger?project=${p.id}`}>
                  Decision ledger
                </Link>
                <button type="button" className="btn small" onClick={() => { proj.reload(); msgs.reload() }}>
                  refresh
                </button>
              </div>
            }
          />
          <div className="grid-2 wide-left">
            <div className="stack">
              <Panel
                title="Task DAG"
                actions={
                  <div className="badges">
                    {Object.entries(statusCounts).map(([s, n]) => (
                      <Badge key={s} tone={s === 'failed' ? 'red' : s === 'done' || s === 'verified' ? 'green' : s === 'blocked' ? 'amber' : 'gray'}>
                        {s} {n}
                      </Badge>
                    ))}
                  </div>
                }
              >
                <DagSvg tasks={p.tasks} selectedId={selectedTask} onSelect={(t) => setSelectedTask(t.id === selectedTask ? null : t.id)} />
              </Panel>
              {task && (
                <Panel title={<span>Task · {task.title}</span>} actions={<button type="button" className="btn small" onClick={() => setSelectedTask(null)}>close</button>}>
                  <TaskDetail task={task} />
                </Panel>
              )}
              <Panel title={<span>Agent messages {msgs.data && <span className="muted">({msgs.data.length})</span>}</span>}>
                {msgs.loading && <Loading />}
                {msgs.data && msgs.data.length === 0 && <Empty>No messages exchanged yet.</Empty>}
                {msgs.data && msgs.data.length > 0 && (
                  <div className="table-wrap">
                    <table className="table compact">
                      <thead>
                        <tr>
                          <th>When</th>
                          <th>Kind</th>
                          <th>From → To</th>
                          <th>Task</th>
                          <th>Tokens</th>
                          <th>Payload</th>
                        </tr>
                      </thead>
                      <tbody>
                        {msgs.data.map((m) => (
                          <tr key={m.id}>
                            <td className="small">{fmtDate(m.created_at)}</td>
                            <td>
                              <Badge tone="gray">{m.kind}</Badge>
                            </td>
                            <td className="small">
                              {m.from ?? 'system'} → {m.to ?? '?'}
                            </td>
                            <td className="mono small">{m.task_id ? short(m.task_id) : '—'}</td>
                            <td className="mono">{fmtNum(m.token_estimate)}</td>
                            <td>
                              <JsonView value={m.payload} summary="payload" />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Panel>
            </div>
            <div className="stack">
              <Panel title="Run head agent">
                <form className="stack" onSubmit={run}>
                  <label className="field">
                    <span>Objective</span>
                    <textarea rows={4} value={objective} onChange={(e) => setObjective(e.target.value)} />
                  </label>
                  <div className="row gap">
                    <label className="field">
                      <span>Max steps</span>
                      <input type="number" min={1} max={200} value={maxSteps} onChange={(e) => setMaxSteps(Number(e.target.value) || 1)} />
                    </label>
                    <label className="check">
                      <input type="checkbox" checked={background} onChange={(e) => setBackground(e.target.checked)} /> run in background (worker)
                    </label>
                  </div>
                  <button type="submit" className="btn primary" disabled={running || !objective.trim()}>
                    {running ? 'Running… (this can take a while)' : 'Plan & run'}
                  </button>
                </form>
              </Panel>
              {led && (
                <Panel title="Ledger summary" actions={<Link className="small" to={`/ledger?project=${p.id}`}>full ledger →</Link>}>
                  <KeyVals
                    items={[
                      ['Entries', <span>{led.entries} · head <code className="mono small">{short(led.head_hash, 12)}</code></span>],
                      ['Objectives', String(led.objectives.length)],
                      ['Decisions', String(led.decisions.length)],
                      ['Hypotheses', String(Object.keys(led.hypotheses).length)],
                      ['Contradictions', <Badge tone={led.contradictions.length ? 'red' : 'gray'}>{led.contradictions.length}</Badge>],
                      ['Open blockers', <Badge tone={led.open_blockers.length ? 'amber' : 'gray'}>{led.open_blockers.length}</Badge>],
                    ]}
                  />
                  {led.open_blockers.length > 0 && (
                    <>
                      <h4>Open blockers</h4>
                      <ul className="plain">
                        {led.open_blockers.map((b, i) => (
                          <li key={i} className="small">
                            <Badge tone="amber">#{String(b.seq)}</Badge> {contentText(b)}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  {led.next_actions.length > 0 && (
                    <>
                      <h4>Next actions</h4>
                      <ul className="plain">
                        {led.next_actions.map((b, i) => (
                          <li key={i} className="small">
                            {contentText(b)}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  {led.decisions.length > 0 && (
                    <>
                      <h4>Decisions</h4>
                      <ul className="plain">
                        {led.decisions.slice(-5).map((b, i) => (
                          <li key={i} className="small">
                            <Badge tone="purple">#{String(b.seq)}</Badge> {contentText(b)}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  <h4>Synthesis</h4>
                  {led.synthesis ? <ContentView value={led.synthesis} omit={['refs']} /> : <div className="muted small">No synthesis yet.</div>}
                </Panel>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
