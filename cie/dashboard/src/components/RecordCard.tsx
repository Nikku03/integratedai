import { useState } from 'react'
import { api } from '../api/endpoints'
import type { RecordLink, RecordOut } from '../api/types'
import { fmtDate, fmtPct, short } from '../lib/format'
import { Badge, StatusBadge, TypeBadge } from './Badge'
import { CitationList } from './CitationLink'
import { GlyphCard } from './GlyphCard'
import { ContentView, ErrorBox, JsonView, Loading } from './Misc'

/** A memory record with lazily loaded history and graph links. */
export function RecordCard({ record, defaultOpen = false }: { record: RecordOut; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const [history, setHistory] = useState<RecordOut[] | null>(null)
  const [links, setLinks] = useState<RecordLink[] | null>(null)
  const [linked, setLinked] = useState<Record<string, RecordOut>>({})
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<Error | undefined>()

  const loadMore = async () => {
    setBusy(true)
    setErr(undefined)
    try {
      const [h, l] = await Promise.all([api.recordHistory(record.id), api.recordLinks(record.id)])
      setHistory(h)
      setLinks(l)
      const others = [...new Set(l.map((e) => (e.src_id === record.id ? e.dst_id : e.src_id)))].slice(0, 12)
      const fetched = await Promise.all(others.map((id) => api.record(id).catch(() => null)))
      const map: Record<string, RecordOut> = {}
      fetched.forEach((r, i) => {
        if (r) map[others[i]] = r
      })
      setLinked(map)
    } catch (e) {
      setErr(e as Error)
    } finally {
      setBusy(false)
    }
  }

  const superseded = record.superseded_by_id !== null
  return (
    <article className={`card record ${superseded ? 'record-superseded' : ''}`}>
      <header className="card-head" onClick={() => setOpen((o) => !o)} role="button" tabIndex={0}>
        <div className="badges">
          <TypeBadge type={record.type} />
          <StatusBadge status={record.verification} />
          {superseded && <Badge tone="amber">superseded</Badge>}
          <Badge tone="gray">conf {fmtPct(record.confidence)}</Badge>
          <Badge tone="gray">v{record.version}</Badge>
          {record.sensitivity > 1 && <Badge tone="red">sensitivity {record.sensitivity}</Badge>}
        </div>
        <div className="card-title">{record.summary}</div>
        <div className="muted small">
          {record.producing_agent ?? 'unknown producer'} · {fmtDate(record.recorded_at)} · <CitationList cites={record.source_locations} documentId={record.source_document_id} />
        </div>
      </header>
      {open && (
        <div className="card-body stack">
          {record.detail && <p className="detail">{record.detail}</p>}
          <ContentView value={record.content} />
          {record.keywords.length > 0 && (
            <div className="chips">
              {record.keywords.map((k) => (
                <span key={k} className="chip chip-soft">
                  {k}
                </span>
              ))}
            </div>
          )}
          <details>
            <summary>Glyph card</summary>
            <GlyphCard glyph={record.glyph} documentId={record.source_document_id} />
          </details>
          <div className="row gap">
            <button type="button" className="btn small" onClick={loadMore} disabled={busy}>
              {busy ? 'Loading…' : history ? 'Refresh history & links' : 'Load history & links'}
            </button>
            <code className="mono small">{record.id}</code>
          </div>
          {busy && <Loading />}
          <ErrorBox error={err} />
          {history && (
            <div>
              <h4>History ({history.length} version{history.length === 1 ? '' : 's'})</h4>
              <ul className="plain timeline">
                {history.map((h) => (
                  <li key={h.id}>
                    <Badge tone={h.id === record.id ? 'blue' : 'gray'}>v{h.version}</Badge> {h.summary}{' '}
                    <span className="muted small">
                      {fmtDate(h.recorded_at)} {h.superseded_by_id ? '· superseded' : '· current'}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {links && (
            <div>
              <h4>Links ({links.length})</h4>
              {links.length === 0 ? (
                <div className="muted small">No graph edges touch this record.</div>
              ) : (
                <ul className="plain">
                  {links.map((e) => {
                    const otherId = e.src_id === record.id ? e.dst_id : e.src_id
                    const dir = e.src_id === record.id ? '→' : '←'
                    const other = linked[otherId]
                    return (
                      <li key={e.id} className="link-row">
                        <Badge tone={e.kind === 'contradicts' ? 'red' : e.kind === 'confirms' ? 'green' : 'gray'}>{e.kind}</Badge> <span className="mono small">{dir}</span>{' '}
                        {other ? (
                          <span>
                            <TypeBadge type={other.type} /> {other.summary}{' '}
                            <CitationList cites={other.source_locations} documentId={other.source_document_id} />
                          </span>
                        ) : (
                          <code className="mono small">{short(otherId)}</code>
                        )}
                        {e.justification && <div className="muted small">{e.justification}</div>}
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          )}
          <JsonView value={record} summary="Record JSON" />
        </div>
      )}
    </article>
  )
}
