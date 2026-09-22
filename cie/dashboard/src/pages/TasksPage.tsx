import { Fragment, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/endpoints'
import { Badge, RiskBadge, StatusBadge } from '../components/Badge'
import { Empty, ErrorBox, Loading, PageHeader, Panel } from '../components/Misc'
import { ProjectPicker, useProjectParam } from '../components/ProjectPicker'
import { TaskDetail } from '../components/TaskDetail'
import { useAsync } from '../hooks/useAsync'
import { fmtDate, trunc } from '../lib/format'
import { useSettings } from '../state/settings'

const STATUSES = ['pending', 'blocked', 'assigned', 'running', 'needs_verification', 'awaiting_approval', 'done', 'verified', 'failed']

export default function TasksPage() {
  const { version } = useSettings()
  const [projectId, setProjectId] = useProjectParam()
  const [sp] = useSearchParams()
  const [status, setStatus] = useState('')
  const [expanded, setExpanded] = useState<string | null>(sp.get('task'))
  const tasks = useAsync(() => api.tasks({ project_id: projectId || null, status: status || null }), [projectId, status, version])

  useEffect(() => {
    const t = sp.get('task')
    if (t) setExpanded(t)
  }, [sp])

  const counts = (tasks.data ?? []).reduce<Record<string, number>>((acc, t) => ((acc[t.status] = (acc[t.status] ?? 0) + 1), acc), {})

  return (
    <div className="page">
      <PageHeader
        title="Task queue"
        subtitle="Every task with its status, risk and assigned agent. Expand a row to see why the router chose that agent."
        actions={
          <div className="row gap wrap">
            <ProjectPicker value={projectId} onChange={setProjectId} allowAll />
            <label className="field inline">
              <span>Status</span>
              <select value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">any</option>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="btn small" onClick={tasks.reload}>
              refresh
            </button>
          </div>
        }
      />
      <Panel
        title={<span>Tasks {tasks.data && <span className="muted">({tasks.data.length})</span>}</span>}
        actions={
          <div className="badges">
            {Object.entries(counts).map(([s, n]) => (
              <Badge key={s} tone={s === 'failed' ? 'red' : s === 'done' || s === 'verified' ? 'green' : s === 'blocked' || s === 'awaiting_approval' ? 'amber' : 'gray'}>
                {s} {n}
              </Badge>
            ))}
          </div>
        }
      >
        {tasks.loading && <Loading />}
        <ErrorBox error={tasks.error} />
        {tasks.data && tasks.data.length === 0 && <Empty>No tasks match.</Empty>}
        {tasks.data && tasks.data.length > 0 && (
          <div className="table-wrap">
            <table className="table hover">
              <thead>
                <tr>
                  <th></th>
                  <th>Task</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Risk</th>
                  <th>Agent</th>
                  <th>Prio</th>
                  <th>Deps</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {tasks.data.map((t) => {
                  const open = expanded === t.id
                  return (
                    <Fragment key={t.id}>
                      <tr className={open ? 'row-selected' : ''} onClick={() => setExpanded(open ? null : t.id)}>
                        <td className="mono muted">{open ? '▾' : '▸'}</td>
                        <td>
                          <div className="cell-title">{t.title}</div>
                          {t.brief && <div className="muted small">{trunc(t.brief, 120)}</div>}
                        </td>
                        <td>
                          <Badge tone="gray">{t.task_type}</Badge>
                        </td>
                        <td>
                          <StatusBadge status={t.status} />
                        </td>
                        <td>
                          <RiskBadge risk={t.risk_level} />
                        </td>
                        <td>{t.assigned_agent ?? <span className="muted">unassigned</span>}</td>
                        <td className="mono">{t.priority}</td>
                        <td className="mono">{t.depends_on.length || <span className="muted">—</span>}</td>
                        <td className="small">{fmtDate(t.updated_at)}</td>
                      </tr>
                      {open && (
                        <tr className="row-expanded">
                          <td colSpan={9}>
                            <TaskDetail task={t} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}
