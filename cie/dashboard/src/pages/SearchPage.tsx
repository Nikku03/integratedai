import { useState, type FormEvent } from 'react'
import { api } from '../api/endpoints'
import type { AnswerCitation, AnswerMode, AnswerOut, PacketOut, SearchItem } from '../api/types'
import { Badge, StatusBadge, TypeBadge } from '../components/Badge'
import { CitationLink, CitationList } from '../components/CitationLink'
import { GlyphCard } from '../components/GlyphCard'
import { ContentView, Empty, ErrorBox, JsonView, Meter, PageHeader, Panel } from '../components/Misc'
import { useLocalStorage } from '../hooks/useLocalStorage'
import { fmtDateShort, fmtMs, fmtNum, fmtPct, fmtScore, fmtUsd, short } from '../lib/format'
import { useScope } from '../state/scope'

export default function SearchPage() {
  const { scopes, selectedId, select } = useScope()
  const [query, setQuery] = useState('')
  const [useGraph, setUseGraph] = useState(true)
  const [modeRaw, setMode] = useLocalStorage('cie.answerMode', 'strict')
  const mode: AnswerMode = modeRaw === 'assisted' ? 'assisted' : 'strict'
  const [packet, setPacket] = useState<PacketOut | null>(null)
  const [answer, setAnswer] = useState<AnswerOut | null>(null)
  const [searching, setSearching] = useState(false)
  const [asking, setAsking] = useState(false)
  const [err, setErr] = useState<Error | undefined>()

  const canRun = query.trim().length > 0 && Boolean(selectedId)

  async function runSearch(e?: FormEvent) {
    e?.preventDefault()
    if (!canRun || !selectedId) return
    setSearching(true)
    setErr(undefined)
    setAnswer(null)
    try {
      setPacket(await api.search({ query: query.trim(), scope_id: selectedId, use_graph: useGraph }))
    } catch (ex) {
      setErr(ex as Error)
    } finally {
      setSearching(false)
    }
  }

  async function ask() {
    if (!canRun || !selectedId) return
    setAsking(true)
    setErr(undefined)
    try {
      setAnswer(await api.answer({ query: query.trim(), scope_id: selectedId, use_graph: useGraph, mode }))
    } catch (ex) {
      setErr(ex as Error)
    } finally {
      setAsking(false)
    }
  }

  const searchScopes = scopes.filter((s) => s.kind !== 'agent' && s.kind !== 'task')

  return (
    <div className="page">
      <PageHeader title="Company memory search" subtitle="Hybrid retrieval over the addressable memory of the selected scope. Every result points back to its source." />
      <Panel>
        <form className="search-form" onSubmit={runSearch}>
          <input
            className="search-input"
            type="search"
            placeholder="Ask about deadlines, contracts, metrics, decisions…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
          <label className="field inline">
            <span>Scope</span>
            <select value={selectedId ?? ''} onChange={(e) => select(e.target.value || null)}>
              {!selectedId && <option value="">Select a scope</option>}
              {searchScopes.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.path || s.name} ({s.kind})
                </option>
              ))}
            </select>
          </label>
          <label className="check">
            <input type="checkbox" checked={useGraph} onChange={(e) => setUseGraph(e.target.checked)} /> graph expansion
          </label>
          <label className="field inline">
            <span>Answer mode</span>
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="strict">strict (extractive)</option>
              <option value="assisted">assisted (LLM, verified)</option>
            </select>
          </label>
          <div className="row gap">
            <button type="submit" className="btn primary" disabled={!canRun || searching}>
              {searching ? 'Searching…' : 'Search'}
            </button>
            <button type="button" className="btn" disabled={!canRun || asking} onClick={ask}>
              {asking ? 'Answering…' : 'Ask'}
            </button>
          </div>
        </form>
        <ErrorBox error={err} />
      </Panel>

      {answer && <AnswerPanel answer={answer} />}

      {packet && (
        <Panel
          title={
            <span>
              Results <span className="muted">({packet.items.length})</span>
            </span>
          }
          actions={
            <div className="badges">
              <Badge tone="purple">intent: {packet.intent}</Badge>
              <Badge tone="gray">{fmtNum(packet.token_estimate)} tokens</Badge>
              <Badge tone="gray">{fmtMs(packet.latency_ms)}</Badge>
              <span className="muted small mono" title={packet.id}>
                packet {short(packet.id)}
              </span>
            </div>
          }
        >
          {packet.items.length === 0 ? (
            <Empty>No items matched in this scope. Try a broader scope or different wording.</Empty>
          ) : (
            <div className="stack">
              {packet.items.map((it, i) => (
                <ResultItem key={it.id} item={it} index={i} />
              ))}
            </div>
          )}
          <JsonView value={packet.trace} summary="Retrieval trace" />
        </Panel>
      )}
    </div>
  )
}

function ResultItem({ item, index }: { item: SearchItem; index: number }) {
  const [expanded, setExpanded] = useState(false)
  const conflicts = item.conflicts_with ?? []
  return (
    <article className={`card result ${item.superseded ? 'record-superseded' : ''}`}>
      <div className="result-rank">{index + 1}</div>
      <div className="result-main stack">
        <div className="badges">
          <Badge tone={item.kind === 'record' ? 'blue' : 'gray'}>{item.kind}</Badge>
          <TypeBadge type={item.type} />
          {item.superseded && (
            <Badge tone="amber" title={item.superseded_by ? `superseded by ${item.superseded_by}` : 'superseded'}>
              superseded
            </Badge>
          )}
          {conflicts.length > 0 && (
            <Badge tone="red" title={`conflicts with ${conflicts.join(', ')}`}>
              conflict ×{conflicts.length}
            </Badge>
          )}
          {item.verification && item.verification !== 'unverified' && <StatusBadge status={item.verification} />}
          {item.via && (
            <Badge tone="teal" title={`reached via ${item.via}${item.horizon ? `, horizon ${item.horizon}` : ''}`}>
              via {item.via}
              {item.horizon ? ` · h${item.horizon}` : ''}
            </Badge>
          )}
          {item.page_start !== undefined && (
            <Badge tone="gray">
              pp. {item.page_start}–{item.page_end ?? item.page_start}
            </Badge>
          )}
        </div>
        <div className="card-title">{item.summary}</div>
        <div className="scores">
          <span className="score">
            <span className="muted small">score</span> <span className="mono">{fmtScore(item.score)}</span> <Meter value={item.score} />
          </span>
          <span className="score">
            <span className="muted small">support</span> <span className="mono">{fmtScore(item.support)}</span> <Meter value={item.support} tone="green" />
          </span>
          {item.confidence !== undefined && (
            <span className="score">
              <span className="muted small">confidence</span> <span className="mono">{fmtPct(item.confidence)}</span>
            </span>
          )}
        </div>
        {item.detail && (
          <p className={`detail ${expanded ? '' : 'clamp'}`} onClick={() => setExpanded((s) => !s)} title="Click to expand">
            {item.detail}
          </p>
        )}
        <div className="row gap wrap small">
          <span>
            <span className="muted">cites:</span> <CitationList cites={item.citations} documentId={item.document_id} />
          </span>
          {item.document_id && (
            <span className="muted mono" title={item.document_id}>
              doc {short(item.document_id)}
            </span>
          )}
          {item.recorded_at && <span className="muted">recorded {fmtDateShort(item.recorded_at)}</span>}
          {item.valid_to && <span className="muted">valid to {fmtDateShort(item.valid_to)}</span>}
        </div>
        {item.kind === 'record' && (
          <details className="glyph-expander">
            <summary>Glyph card</summary>
            <GlyphCard glyph={item.glyph} documentId={item.document_id} />
          </details>
        )}
        {item.reasons && Object.keys(item.reasons).length > 0 && (
          <details>
            <summary>Ranking reasons</summary>
            <ContentView value={item.reasons} />
          </details>
        )}
        {item.content && Object.keys(item.content).length > 0 && (
          <details>
            <summary>Structured content</summary>
            <ContentView value={item.content} />
          </details>
        )}
      </div>
    </article>
  )
}

function AnswerText({ text, citations }: { text: string; citations: AnswerCitation[] }) {
  const parts = text.split(/(\[\d+\])/g)
  return (
    <p className="answer-text">
      {parts.map((p, i) => {
        const m = /^\[(\d+)\]$/.exec(p)
        if (!m) return <span key={i}>{p}</span>
        const n = Number(m[1])
        const c = citations.find((x) => x.n === n)
        return <CitationLink key={i} cite={c} label={`[${n}]`} className="cite-n" />
      })}
    </p>
  )
}

function AnswerPanel({ answer }: { answer: AnswerOut }) {
  return (
    <Panel
      title="Answer"
      actions={
        <div className="badges">
          <StatusBadge status={answer.status} />
          <Badge tone="blue">confidence {fmtPct(answer.confidence)}</Badge>
          <Badge tone="gray">{answer.mode}</Badge>
          {answer.model && <Badge tone="gray">{answer.model}</Badge>}
          <Badge tone="gray" title={answer.usage_is_estimate ? 'token usage is estimated' : 'reported by provider'}>
            {fmtNum(answer.tokens_in)} in / {fmtNum(answer.tokens_out)} out{answer.usage_is_estimate ? ' (est.)' : ''}
          </Badge>
          <Badge tone="gray">{fmtMs(answer.latency_ms)}</Badge>
          <Badge tone="gray">{fmtUsd(answer.cost_usd)}</Badge>
        </div>
      }
    >
      <AnswerText text={answer.answer} citations={answer.citations} />
      {answer.citations.length > 0 && (
        <ol className="citations">
          {answer.citations.map((c) => (
            <li key={c.n} value={c.n}>
              <CitationLink cite={c} label={`[${c.n}]`} className="cite-n" /> <TypeBadge type={c.type ?? c.kind} /> {c.summary}
              {c.quote && <blockquote className="quote">“{c.quote}”</blockquote>}
              <span className="muted small">
                {c.document_id ? `doc ${short(c.document_id)}` : 'no document'}
                {c.page_no ? ` · page ${c.page_no}` : ''}
              </span>
            </li>
          ))}
        </ol>
      )}
      {answer.unsupported_claims.length > 0 && (
        <div className="warn-box">
          <strong>Unsupported claims removed from the answer</strong>
          <ul className="plain">
            {answer.unsupported_claims.map((u, i) => (
              <li key={i}>{u}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="muted small mono">
        answer {answer.id} · packet {answer.packet_id}
      </div>
    </Panel>
  )
}
