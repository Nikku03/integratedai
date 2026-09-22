import type { RoutingCandidate, TaskOut } from '../api/types'
import { fmtDate, fmtMs, fmtNum, fmtPct, fmtScore, fmtUsd, scalar } from '../lib/format'
import { Badge, RiskBadge, StatusBadge } from './Badge'
import { CitationLink } from './CitationLink'
import { ContentView, JsonView, KeyVals, Meter } from './Misc'

const CANDIDATE_COLS: Array<[keyof RoutingCandidate & string, string]> = [
  ['scorecard', 'scorecard'],
  ['scorecard_n', 'n'],
  ['skill_overlap', 'skill overlap'],
  ['cost_factor', 'cost factor'],
  ['running', 'running'],
]

/** "Why this agent": the router's decision plus every candidate's factors. */
export function AssignmentReasonView({ task }: { task: TaskOut }) {
  const r = task.assignment_reason
  if (!r) return <div className="muted small">Not routed yet — no assignment reason recorded.</div>
  const candidates = r.candidates ?? []
  return (
    <div className="stack">
      {r.decision && <p className="decision">{r.decision}</p>}
      {candidates.length > 0 ? (
        <div className="table-wrap">
          <table className="table compact">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Score</th>
                <th>Eligible</th>
                {CANDIDATE_COLS.map(([k, label]) => (
                  <th key={k}>{label}</th>
                ))}
                <th>Low support</th>
                <th>Excluded because</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((c) => (
                <tr key={c.agent} className={c.agent === r.chosen ? 'row-chosen' : c.eligible ? '' : 'row-dim'}>
                  <td>
                    {c.agent} {c.agent === r.chosen && <Badge tone="green">chosen</Badge>}
                  </td>
                  <td>
                    <span className="mono">{fmtScore(c.score)}</span> <Meter value={c.score} />
                  </td>
                  <td>{c.eligible ? <Badge tone="green">yes</Badge> : <Badge tone="red">no</Badge>}</td>
                  {CANDIDATE_COLS.map(([k]) => (
                    <td key={k} className="mono">
                      {scalar(c[k])}
                    </td>
                  ))}
                  <td>{c.scorecard_low_support ? <Badge tone="amber">low support</Badge> : <span className="muted">—</span>}</td>
                  <td className="muted small">{c.excluded ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="muted small">No candidates recorded.</div>
      )}
      <JsonView value={r} summary="Full assignment reason" />
    </div>
  )
}

export function TaskDetail({ task }: { task: TaskOut }) {
  const res = task.result
  const m = (res?.metrics ?? {}) as Record<string, number>
  return (
    <div className="stack">
      <div className="badges">
        <StatusBadge status={task.status} />
        <RiskBadge risk={task.risk_level} />
        <Badge tone="gray">{task.task_type}</Badge>
        <Badge tone="gray">priority {task.priority}</Badge>
        {task.assigned_agent && <Badge tone="blue">{task.assigned_agent}</Badge>}
      </div>
      {task.brief && <p>{task.brief}</p>}
      <KeyVals
        items={[
          ['Task id', <code className="mono small">{task.id}</code>],
          ['Depends on', task.depends_on.length ? task.depends_on.map((d) => <code key={d} className="mono small">{d.slice(0, 8)} </code>) : '—'],
          ['Evidence packet', task.evidence_packet_id ? <code className="mono small">{task.evidence_packet_id}</code> : '—'],
          ['Updated', fmtDate(task.updated_at)],
        ]}
      />
      <h4>Why this agent</h4>
      <AssignmentReasonView task={task} />
      <h4>Result</h4>
      {res ? (
        <div className="stack">
          {res.summary && <p>{res.summary}</p>}
          <div className="badges">
            {res.strategy && <Badge tone="gray">{res.strategy}</Badge>}
            {res.model && <Badge tone="gray">{res.model}</Badge>}
            {m.tokens_in !== undefined && <Badge tone="gray">{fmtNum(m.tokens_in + (m.tokens_out ?? 0))} tokens</Badge>}
            {m.latency_ms !== undefined && <Badge tone="gray">{fmtMs(m.latency_ms)}</Badge>}
            {m.cost_usd !== undefined && <Badge tone="gray">{fmtUsd(m.cost_usd)}</Badge>}
          </div>
          {res.findings && res.findings.length > 0 && (
            <div className="table-wrap">
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Finding</th>
                    <th>Kind</th>
                    <th>Value</th>
                    <th>Conf.</th>
                    <th>Citations</th>
                  </tr>
                </thead>
                <tbody>
                  {res.findings.map((f, i) => (
                    <tr key={i}>
                      <td>{f.claim}</td>
                      <td>
                        <Badge tone="gray">{f.kind}</Badge>
                      </td>
                      <td className="mono small">{scalar(f.value)}</td>
                      <td className="mono">{fmtPct(f.confidence)}</td>
                      <td>
                        <span className="cite-list">
                          {(f.citations ?? []).map((c, j) => (
                            <CitationLink key={j} cite={c} />
                          ))}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {res.open_questions && res.open_questions.length > 0 && (
            <div>
              <strong>Open questions</strong>
              <ul className="plain">
                {res.open_questions.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </div>
          )}
          {res.unsupported_claims && res.unsupported_claims.length > 0 && (
            <div className="warn-box">
              <strong>Unsupported claims removed:</strong>
              <ul className="plain">
                {res.unsupported_claims.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </div>
          )}
          <JsonView value={res} summary="Full result" />
        </div>
      ) : (
        <div className="muted small">No result yet.</div>
      )}
      <h4>Verification</h4>
      <ContentView value={task.verification} />
      <h4>Metrics</h4>
      <ContentView value={task.metrics} />
    </div>
  )
}
