import type { Glyph } from '../api/types'
import { fmtPct, scalar, short } from '../lib/format'
import { Badge, StatusBadge, TypeBadge } from './Badge'
import { CitationLink } from './CitationLink'
import { JsonView } from './Misc'

/** Compact, typed memory card. Always points back to evidence. */
export function GlyphCard({ glyph, documentId }: { glyph: Glyph | null | undefined; documentId?: string | null }) {
  if (!glyph || Object.keys(glyph).length === 0) return <div className="muted small">No glyph on this item.</div>
  const time = glyph.time ?? {}
  const idList = (label: string, ids: string[] | undefined) =>
    ids && ids.length ? (
      <div className="glyph-row">
        <span className="glyph-k">{label}</span>
        <span>
          {ids.map((id) => (
            <code key={id} className="mono small" title={id}>
              {short(id)}
            </code>
          ))}
        </span>
      </div>
    ) : null
  return (
    <div className="glyph">
      <div className="glyph-head">
        <TypeBadge type={glyph.type} />
        <StatusBadge status={glyph.status} />
        {glyph.verification && <Badge tone={glyph.verification === 'verified' ? 'green' : 'gray'}>{glyph.verification}</Badge>}
        {glyph.confidence !== undefined && <Badge tone="blue">conf {fmtPct(glyph.confidence)}</Badge>}
        {glyph.v !== undefined && <span className="muted small">glyph v{glyph.v}</span>}
      </div>
      {glyph.what && <p className="glyph-what">{glyph.what}</p>}
      {glyph.why && (
        <div className="glyph-row">
          <span className="glyph-k">why</span>
          <span>{glyph.why}</span>
        </div>
      )}
      {glyph.who && glyph.who.length > 0 && (
        <div className="glyph-row">
          <span className="glyph-k">who</span>
          <span className="chips">
            {glyph.who.map((w) => (
              <span key={w} className="chip">
                {w}
              </span>
            ))}
          </span>
        </div>
      )}
      {(glyph.project || glyph.department) && (
        <div className="glyph-row">
          <span className="glyph-k">where</span>
          <span>{[glyph.department, glyph.project].filter(Boolean).join(' / ')}</span>
        </div>
      )}
      {Object.keys(time).length > 0 && (
        <div className="glyph-row">
          <span className="glyph-k">time</span>
          <span className="chips">
            {Object.entries(time).map(([k, v]) => (
              <span key={k} className="chip">
                {k}: {scalar(v).slice(0, 19)}
              </span>
            ))}
          </span>
        </div>
      )}
      {idList('depends on', glyph.dependencies)}
      {idList('consequences', glyph.consequences)}
      {idList('contradicts', glyph.contradictions)}
      {glyph.evidence && glyph.evidence.length > 0 && (
        <div className="glyph-row">
          <span className="glyph-k">evidence</span>
          <span className="cite-list">
            {glyph.evidence.map((e, i) => (
              <CitationLink key={i} cite={e.document_id ? e : { ...e, document_id: documentId ?? null }} />
            ))}
          </span>
        </div>
      )}
      {glyph.keywords && glyph.keywords.length > 0 && (
        <div className="glyph-row">
          <span className="glyph-k">keywords</span>
          <span className="chips">
            {glyph.keywords.map((k) => (
              <span key={k} className="chip chip-soft">
                {k}
              </span>
            ))}
          </span>
        </div>
      )}
      <JsonView value={glyph} summary="Glyph JSON" />
    </div>
  )
}
