import { useState } from 'react'
import { api } from '../api/endpoints'
import type { MetricStat } from '../api/types'
import { Badge } from '../components/Badge'
import { ErrorBox, Loading, PageHeader, Panel } from '../components/Misc'
import { useAsync } from '../hooks/useAsync'
import { fmtBytes, fmtMs, fmtNum, fmtUsd } from '../lib/format'
import { useSettings } from '../state/settings'

type Stat = keyof MetricStat

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {sub && <div className="tile-sub muted small">{sub}</div>}
    </div>
  )
}

function formatFor(name: string, stat: Stat, v: number): string {
  if (stat === 'n') return fmtNum(v)
  if (/latency|_ms\b|duration/i.test(name)) return fmtMs(v)
  if (/cost|usd/i.test(name)) return fmtUsd(v)
  if (/bytes/i.test(name)) return fmtBytes(v)
  return fmtNum(v, v < 10 ? 3 : 0)
}

export default function MetricsPage() {
  const { version } = useSettings()
  const m = useAsync(() => api.metrics(), [version])
  const [stat, setStat] = useState<Stat>('p95')
  const d = m.data
  const metrics = Object.entries(d?.metrics ?? {})

  const tokens = metrics.filter(([n]) => /token/i.test(n)).reduce((a, [, s]) => a + s.sum, 0)
  const cost = metrics.filter(([n]) => /cost|usd/i.test(n)).reduce((a, [, s]) => a + s.sum, 0)
  const latency = metrics.filter(([n]) => /latency/i.test(n))
  const latP95 = latency.length ? Math.max(...latency.map(([, s]) => s.p95)) : null
  const worstLatency = latency.sort((a, b) => b[1].p95 - a[1].p95)[0]?.[0]
  const jobs = d?.counts.jobs
  const jobsText = typeof jobs === 'number' ? fmtNum(jobs) : jobs ? fmtNum(Object.values(jobs).reduce((a, b) => a + b, 0)) : '—'

  const sorted = [...metrics].sort((a, b) => b[1][stat] - a[1][stat])
  const max = sorted.length ? Math.max(...sorted.map(([, s]) => s[stat])) || 1 : 1

  return (
    <div className="page">
      <PageHeader title="Metrics" subtitle="Tenant-wide counters from /metrics/summary: retrieval and agent latency, token usage, cost and storage." actions={<button type="button" className="btn small" onClick={m.reload}>refresh</button>} />
      {m.loading && <Loading />}
      <ErrorBox error={m.error} />
      {d && (
        <>
          <div className="tiles">
            <Tile label="Documents" value={fmtNum(d.counts.documents)} />
            <Tile label="Sections" value={fmtNum(d.counts.sections)} />
            <Tile label="Memory records" value={fmtNum(d.counts.records)} />
            <Tile label="Jobs" value={jobsText} sub={jobs && typeof jobs === 'object' ? Object.entries(jobs).map(([k, v]) => `${k} ${v}`).join(' · ') : undefined} />
            <Tile label="Storage" value={fmtBytes(d.storage.raw_bytes)} sub={`${fmtNum(d.storage.blobs)} blobs`} />
            <Tile label="Tokens (total)" value={fmtNum(tokens)} sub={metrics.filter(([n]) => /token/i.test(n)).length ? `${metrics.filter(([n]) => /token/i.test(n)).length} token metrics` : 'no token metrics yet'} />
            <Tile label="Latency p95 (worst)" value={latP95 === null ? '—' : fmtMs(latP95)} sub={worstLatency} />
            <Tile label="Cost (total)" value={fmtUsd(cost)} sub={cost === 0 ? 'extractive mode costs nothing' : undefined} />
          </div>
          <Panel
            title={<span>All metrics {metrics.length > 0 && <span className="muted">({metrics.length})</span>}</span>}
            actions={
              <label className="field inline">
                <span>Bar shows</span>
                <select value={stat} onChange={(e) => setStat(e.target.value as Stat)}>
                  <option value="p95">p95</option>
                  <option value="avg">avg</option>
                  <option value="sum">sum</option>
                  <option value="n">count</option>
                </select>
              </label>
            }
          >
            {metrics.length === 0 && <div className="muted">No metrics recorded yet. Run a search, answer or project to populate them.</div>}
            <div className="bars">
              {sorted.map(([name, s]) => (
                <div key={name} className="bar-row">
                  <div className="bar-label" title={name}>
                    {name}
                  </div>
                  <div className="bar-track">
                    <div className={`bar-fill ${/latency/i.test(name) ? 'amber' : /cost/i.test(name) ? 'red' : /token/i.test(name) ? 'purple' : 'blue'}`} style={{ width: `${Math.max(1, (s[stat] / max) * 100)}%` }} />
                  </div>
                  <div className="bar-value mono">{formatFor(name, stat, s[stat])}</div>
                  <div className="bar-meta muted small">
                    n {fmtNum(s.n)} · avg {formatFor(name, 'avg', s.avg)} · p95 {formatFor(name, 'p95', s.p95)} · sum {formatFor(name, 'sum', s.sum)}
                  </div>
                </div>
              ))}
            </div>
          </Panel>
          {jobs && typeof jobs === 'object' && (
            <div className="badges">
              {Object.entries(jobs).map(([k, v]) => (
                <Badge key={k} tone={k === 'failed' ? 'red' : k === 'done' ? 'green' : k === 'running' ? 'blue' : 'gray'}>
                  jobs {k}: {v}
                </Badge>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
