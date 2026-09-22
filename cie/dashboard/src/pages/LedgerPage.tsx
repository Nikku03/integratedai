import { Fragment, useMemo, useState } from 'react'
import { api } from '../api/endpoints'
import type { LedgerContent, LedgerEntry } from '../api/types'
import { Badge, type Tone } from '../components/Badge'
import { ContentView, Empty, ErrorBox, JsonView, Loading, PageHeader, Panel } from '../components/Misc'
import { ProjectPicker, useProjectParam } from '../components/ProjectPicker'
import { useAsync } from '../hooks/useAsync'
import { fmtDate, scalar, short } from '../lib/format'
import { useSettings } from '../state/settings'

const KIND_TONE: Record<string, Tone> = {
  objective: 'purple',
  requirement: 'purple',
  plan: 'blue',
  task: 'gray',
  assignment: 'blue',
  hypothesis: 'teal',
  test: 'teal',
  result: 'green',
  failure: 'red',
  decision: 'purple',
  artifact: 'gray',
  commit: 'gray',
  blocker: 'amber',
  next_action: 'amber',
  contradiction: 'red',
  verification: 'green',
  synthesis: 'green',
  message: 'gray',
}

function summarize(content: Record<string, unknown>): string {
  for (const k of ['summary', 'objective', 'reason', 'decision', 'statement', 'hypothesis', 'title', 'answer', 'verdict', 'error']) {
    const v = content[k]
    if (typeof v === 'string' && v && k !== 'hypothesis') return v
    if (k === 'hypothesis' && typeof v === 'string' && !('title' in content)) return `on ${v}`
  }
  const prim = Object.entries(content).filter(([, v]) => typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean')
  return prim
    .slice(0, 4)
    .map(([k, v]) => `${k}: ${scalar(v)}`)
    .join(' · ')
}

export default function LedgerPage() {
  const { version } = useSettings()
  const [projectId, setProjectId] = useProjectParam()
  const ledger = useAsync(() => api.ledger(projectId!), [projectId, version], Boolean(projectId))
  const [kinds, setKinds] = useState<Set<string>>(new Set())
  const [open, setOpen] = useState<number | null>(null)

  const present = useMemo(() => [...new Set((ledger.data?.entries ?? []).map((e) => e.kind))], [ledger.data])
  const entries = (ledger.data?.entries ?? []).filter((e) => kinds.size === 0 || kinds.has(e.kind))
  const toggleKind = (k: string) =>
    setKinds((s) => {
      const n = new Set(s)
      if (n.has(k)) n.delete(k)
      else n.add(k)
      return n
    })

  const hyps = Object.entries(ledger.data?.state.hypotheses ?? {})

  return (
    <div className="page">
      <PageHeader
        title="Decision ledger"
        subtitle="Append-only, hash-chained record of objectives, plans, assignments, hypotheses, tests, results, decisions and blockers."
        actions={
          <div className="row gap wrap">
            <ProjectPicker value={projectId} onChange={setProjectId} />
            <button type="button" className="btn small" onClick={ledger.reload}>
              refresh
            </button>
          </div>
        }
      />
      {!projectId && <Empty>Select a project.</Empty>}
      {ledger.loading && <Loading />}
      <ErrorBox error={ledger.error} />
      {ledger.data && (
        <>
          <div className="row gap wrap ledger-head">
            {ledger.data.chain_valid ? (
              <Badge tone="green">chain valid</Badge>
            ) : (
              <Badge tone="red">chain broken{ledger.data.first_bad_seq !== null ? ` at seq ${ledger.data.first_bad_seq}` : ''}</Badge>
            )}
            <Badge tone="gray">{ledger.data.entries.length} entries</Badge>
            <span className="muted small mono">head {short(ledger.data.state.head_hash, 16)}</span>
            <span className="grow" />
            <span className="muted small">filter:</span>
            {present.map((k) => (
              <button key={k} type="button" className={`chip clickable ${kinds.size === 0 || kinds.has(k) ? 'on' : 'off'}`} onClick={() => toggleKind(k)}>
                {k}
              </button>
            ))}
            {kinds.size > 0 && (
              <button type="button" className="linklike small" onClick={() => setKinds(new Set())}>
                clear
              </button>
            )}
          </div>

          <div className="grid-2 wide-left">
            <Panel title="Entries">
              {entries.length === 0 && <Empty>No entries{kinds.size ? ' for this filter' : ' yet'}.</Empty>}
              {entries.length > 0 && (
                <div className="table-wrap">
                  <table className="table hover compact">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Kind</th>
                        <th>Label</th>
                        <th>Summary</th>
                        <th>Actor</th>
                        <th>Hash</th>
                        <th>When</th>
                      </tr>
                    </thead>
                    <tbody>
                      {entries.map((e) => (
                        <LedgerRow key={e.seq} e={e} open={open === e.seq} onToggle={() => setOpen(open === e.seq ? null : e.seq)} />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
            <Panel title={<span>Hypothesis → test → result {hyps.length > 0 && <span className="muted">({hyps.length})</span>}</span>}>
              {hyps.length === 0 ? (
                <div className="muted small">No hypothesis chains recorded yet. Agents append `hypothesis`, `test` and `result` entries with a shared label.</div>
              ) : (
                <div className="stack">
                  {hyps.map(([label, h]) => (
                    <HypothesisChain key={label} label={label} h={h} />
                  ))}
                </div>
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  )
}

function LedgerRow({ e, open, onToggle }: { e: LedgerEntry; open: boolean; onToggle: () => void }) {
  return (
    <Fragment>
      <tr className={open ? 'row-selected' : ''} onClick={onToggle}>
        <td className="mono">{e.seq}</td>
        <td>
          <Badge tone={KIND_TONE[e.kind] ?? 'gray'}>{e.kind}</Badge>
        </td>
        <td className="mono small">{e.label ?? ''}</td>
        <td className="small">{summarize(e.content)}</td>
        <td className="small">{e.actor ?? <span className="muted">—</span>}</td>
        <td className="mono small" title={`hash ${e.hash}\nprev ${e.prev_hash ?? '∅'}`}>
          {short(e.hash, 10)}
        </td>
        <td className="small">{fmtDate(e.created_at)}</td>
      </tr>
      {open && (
        <tr className="row-expanded">
          <td colSpan={7}>
            <div className="stack">
              <ContentView value={e.content} />
              {Object.keys(e.refs ?? {}).length > 0 && (
                <div>
                  <span className="muted small">refs</span> <ContentView value={e.refs} />
                </div>
              )}
              <div className="muted small mono">
                hash {e.hash}
                <br />
                prev {e.prev_hash ?? '∅ (genesis)'}
              </div>
              <JsonView value={e} summary="Entry JSON" />
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  )
}

function HypothesisChain({ label, h }: { label: string; h: LedgerContent & { tests: LedgerContent[]; results: LedgerContent[] } }) {
  const text = summarize(h as Record<string, unknown>)
  const verdicts = h.results.map((r) => scalar(r.status ?? r.verdict ?? r.outcome))
  const tone: Tone = verdicts.some((v) => /fail|reject|false/i.test(v)) ? 'red' : verdicts.some((v) => /pass|confirm|done|true|support/i.test(v)) ? 'green' : 'gray'
  return (
    <div className="chain">
      <div className="chain-step">
        <Badge tone="teal">hypothesis</Badge> <strong>{label}</strong>
        <div className="small">{text}</div>
      </div>
      <div className="chain-arrow">↓ {h.tests.length} test{h.tests.length === 1 ? '' : 's'}</div>
      {h.tests.length === 0 ? (
        <div className="chain-step muted small">no tests yet</div>
      ) : (
        h.tests.map((t, i) => (
          <div key={i} className="chain-step">
            <Badge tone="teal">test</Badge> <span className="mono small">#{String(t.seq)}</span> <span className="small">{summarize(t as Record<string, unknown>)}</span>
          </div>
        ))
      )}
      <div className="chain-arrow">↓ {h.results.length} result{h.results.length === 1 ? '' : 's'}</div>
      {h.results.length === 0 ? (
        <div className="chain-step muted small">no results yet</div>
      ) : (
        h.results.map((r, i) => (
          <div key={i} className="chain-step">
            <Badge tone={tone}>result</Badge> <span className="mono small">#{String(r.seq)}</span> <span className="small">{summarize(r as Record<string, unknown>)}</span>
          </div>
        ))
      )}
    </div>
  )
}
