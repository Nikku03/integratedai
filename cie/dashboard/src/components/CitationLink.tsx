import { Link } from 'react-router-dom'
import type { Citation } from '../api/types'
import { evidenceHref } from '../lib/evidence'

interface Props {
  cite: Citation | null | undefined
  /** Text to show; defaults to "p.N". */
  label?: string
  className?: string
}

/** Every citation in the app routes through here to the evidence viewer. */
export function CitationLink({ cite, label, className = '' }: Props) {
  const href = evidenceHref(cite)
  const text = label ?? (cite?.page_no ? `p.${cite.page_no}` : 'source')
  const title = cite?.quote ? `“${cite.quote.slice(0, 200)}”` : cite?.document_id ? `document ${cite.document_id}` : 'no source location'
  if (!href) {
    return (
      <span className={`cite cite-dead ${className}`} title={title}>
        {text}
      </span>
    )
  }
  return (
    <Link className={`cite ${className}`} to={href} title={title}>
      {text}
    </Link>
  )
}

/** A row of citation links for a record/section item. */
export function CitationList({ cites, documentId }: { cites: Citation[] | undefined; documentId?: string | null }) {
  if (!cites || !cites.length) {
    if (documentId) return <CitationLink cite={{ document_id: documentId, page_no: 1 }} label="open document" />
    return <span className="muted small">no citations</span>
  }
  return (
    <span className="cite-list">
      {cites.map((c, i) => (
        <CitationLink key={`${c.block_id ?? c.section_id ?? i}`} cite={c.document_id ? c : { ...c, document_id: documentId ?? null }} />
      ))}
    </span>
  )
}
