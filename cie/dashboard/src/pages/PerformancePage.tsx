import { Fragment, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/endpoints'
import type { AgentOut, Scorecard } from '../api/types'
import { Badge } from '../components/Badge'
import { Empty, ErrorBox, Loading, Meter, PageHeader, Panel } from '../components/Misc'
import { useAsync } from '../hooks/useAsync'
import { fmtDate, fmtMs, fmtNum, fmtPct, fmtScore, fmtUsd } from '../lib/format'
import { useSettings } from '../state/settings'

interface Row {
  agent: AgentOut
  card: Scorecard
}

export default function PerformancePage() {
  const { version } = useSettings()
  const [sp, setSp] = useSearchParams()
  const agentFilter = sp.get('agent') ?? ''
  const agents = useAsync(() => api.agents(), [version])
  const cards = useAsync(
    async () => {
      const list = agents.data ?? []
      const res = await Promise.all(list.map((a) => api.scorecards(a.id).catch(() => null)))
      return list.map((a, i) => ({ agent: a, cards: res[i]?.scorecards ?? [], failed: res[i] === null }))
    },
    [agents.data],
    Boolean(agents.data),
  )
  const [open, setOpen] = useState<string | null>(null)

  const rows = useMemo<Row[]>(() => {
    const out: Row[] = []
    for (const c of cards.data ?? []) {
      if (agentFilter && c.agent.id !== agentFilter) continue
      for (const card of c.cards) out.push({ agent: c.agent, card })
    }
    return out.sort((a, b) => b.card.routing_score - a.card.routing_score)
  }, [cards.data, agentFilter])

  const noCards = (cards.data ?? []).filter((c) => c.cards.length === 0 && (!agentFilter || c.agent.id === agentFilter))

  return (
    <div className="page">
      <PageHeader
        title="Agent performance"
        subtitle="Per-agent, per-task-type scorecards. routing_score feeds task routing; low-support cards fall back to a neutral prior."
        actions={
          <div className="row gap wrap">
            <label className="field inline">
              <span>Agent</span>
              <select
                value={agentFilter}
                onChange={(e) => {
                  const next = new URLSearchParams(sp)
                  if (e.target.value) next.set('agent', e.target.value)
                  else next.delete('agent')
                  setSp(next, { replace: true })
                }}
              >
                <option value="">all agents</option>
                {(agents.data ?? []).map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="btn small" onClick={agents.reload}>
              refresh
            </button>
          </div>
        }
      />
      {(agents.loading || cards.loading) && <Loading />}
      <ErrorBox error={agents.error} />
      <Panel title={<span>Scorecards {cards.data && <span className="muted">({rows.length})</span>}</span>}>
        {cards.data && rows.length === 0 && <Empty>No scorecards yet. Cards appear after agents complete tasks or humans record outcomes.</Empty>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table className="table hover compact">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Task type</th>
                  <th>n</th>
                  <th>Routing score</th>
                  <th>Accuracy</th>
                  <th>Citation q.</th>
                  <th>Completion</th>
                  <th>Verification</th>
                  <th>Halluc.</th>
                  <th>Corr.</th>
                  <th>Latency</th>
                  <th>Tokens</th>
                  <th>Cost</th>
                  <th>Last task</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ agent, card }) => {
                  const key = `${agent.id}:${card.task_type}`
                  const isOpen = open === key
                  return (
                    <Fragment key={key}>
                      <tr className={isOpen ? 'row-selected' : ''} onClick={() => setOpen(isOpen ? null : key)}>
                        <td>
                          <strong>{agent.name}</strong> <span className="muted small">{agent.role}</span>
                        </td>
                        <td>
                          <Badge tone="gray">{card.task_type}</Badge>
                        </td>
                        <td className="mono">{card.n_tasks}</td>
                        <td>
                          <span className="mono">{fmtScore(card.routing_score)}</span> <Meter value={card.routing_score} tone={card.low_support ? 'amber' : 'blue'} />{' '}
                          {card.low_support && <Badge tone="amber">low support</Badge>}
                        </td>
                        <td className="mono">{fmtPct(card.accuracy)}</td>
                        <td className="mono">{fmtPct(card.citation_quality)}</td>
                        <td className="mono">{fmtPct(card.completion_rate)}</td>
                        <td className="mono">{fmtPct(card.verification_score)}</td>
                        <td className={`mono ${card.hallucination_rate > 0 ? 'text-red' : ''}`}>{fmtPct(card.hallucination_rate)}</td>
                        <td className="mono">{card.human_corrections}</td>
                        <td className="mono">{fmtMs(card.latency_ms_avg)}</td>
                        <td className="mono">{fmtNum(card.tokens_avg)}</td>
                        <td className="mono">{fmtUsd(card.compute_cost_avg)}</td>
                        <td className="small">{fmtDate(card.last_task_at)}</td>
                      </tr>
                      {isOpen && (
                        <tr className="row-expanded">
                          <td colSpan={14}>
                            <div className="row gap wrap">
                              <span className="muted small">routing score components:</span>
                              {Object.entries(card.components).map(([k, v]) => (
                                <span key={k} className={`chip ${v < 0 ? 'chip-neg' : ''}`}>
                                  {k} {v >= 0 ? '+' : ''}
                                  {v.toFixed(3)}
                                </span>
                              ))}
                            </div>
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
        {noCards.length > 0 && (
          <div className="muted small" style={{ marginTop: 12 }}>
            Without scorecards yet: {noCards.map((c) => c.agent.name).join(', ')}
          </div>
        )}
      </Panel>
    </div>
  )
}
