import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/endpoints'
import type { ApprovalOut } from '../api/types'
import { Badge, StatusBadge } from '../components/Badge'
import { Empty, ErrorBox, Loading, PageHeader, Panel } from '../components/Misc'
import { useAsync } from '../hooks/useAsync'
import { fmtDate, short } from '../lib/format'
import { useSettings } from '../state/settings'
import { useToast } from '../state/toast'

export default function ApprovalsPage() {
  const { version } = useSettings()
  const [status, setStatus] = useState('pending')
  const list = useAsync(() => api.approvals(status), [status, version])
  return (
    <div className="page">
      <PageHeader
        title="Human approval queue"
        subtitle="High-risk task results and deletion requests wait here. Approving a task result marks it verified; approving a deletion executes it."
        actions={
          <div className="row gap wrap">
            <label className="field inline">
              <span>Status</span>
              <select value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="pending">pending</option>
                <option value="approved">approved</option>
                <option value="rejected">rejected</option>
              </select>
            </label>
            <button type="button" className="btn small" onClick={list.reload}>
              refresh
            </button>
          </div>
        }
      />
      <Panel title={<span>{status} {list.data && <span className="muted">({list.data.length})</span>}</span>}>
        {list.loading && <Loading />}
        <ErrorBox error={list.error} />
        {list.data && list.data.length === 0 && <Empty>Nothing {status}.</Empty>}
        <div className="stack">
          {(list.data ?? []).map((a) => (
            <ApprovalRow key={a.id} a={a} onDecided={list.reload} />
          ))}
        </div>
      </Panel>
    </div>
  )
}

function subjectLink(a: ApprovalOut) {
  if (a.kind === 'task_result') return <Link to={`/tasks?task=${a.subject_id}`}>task {short(a.subject_id)}</Link>
  if (a.kind === 'deletion') return <Link to={`/documents?doc=${a.subject_id}`}>document {short(a.subject_id)}</Link>
  return <code className="mono small">{a.subject_id}</code>
}

function ApprovalRow({ a, onDecided }: { a: ApprovalOut; onDecided: () => void }) {
  const { push } = useToast()
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  async function decide(approve: boolean) {
    setBusy(true)
    try {
      const r = await api.decide(a.id, { approve, reason: reason.trim() || null })
      push('success', `Approval ${short(a.id)} ${r.status}`)
      onDecided()
    } catch {
      /* toast shown */
    } finally {
      setBusy(false)
    }
  }
  return (
    <article className="card approval">
      <div className="row between wrap">
        <div className="badges">
          <Badge tone={a.kind === 'deletion' ? 'red' : 'purple'}>{a.kind}</Badge>
          <StatusBadge status={a.status} />
          <span className="small">{subjectLink(a)}</span>
        </div>
        <span className="muted small">
          requested by {a.requested_by ?? 'system'} · {fmtDate(a.created_at)}
        </span>
      </div>
      <div className="card-title">{a.summary}</div>
      {a.status === 'pending' ? (
        <div className="row gap wrap">
          <input className="grow" placeholder="Reason (optional, recorded in the audit log)" value={reason} onChange={(e) => setReason(e.target.value)} />
          <button type="button" className="btn primary" disabled={busy} onClick={() => decide(true)}>
            Approve
          </button>
          <button type="button" className="btn danger" disabled={busy} onClick={() => decide(false)}>
            Reject
          </button>
        </div>
      ) : (
        <div className="muted small">
          decided {fmtDate(a.decided_at)}
          {a.reason ? ` · reason: ${a.reason}` : ''}
        </div>
      )}
    </article>
  )
}
