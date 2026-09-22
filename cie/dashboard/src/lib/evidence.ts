import type { Citation } from '../api/types'

/** Build the evidence-viewer route for a citation; null when it has no source document. */
export function evidenceHref(c: Citation | null | undefined): string | null {
  if (!c || !c.document_id) return null
  const page = c.page_no && c.page_no > 0 ? c.page_no : 1
  const q = new URLSearchParams()
  if (c.bbox && c.bbox.length === 4 && c.bbox.every((v) => typeof v === 'number' && !Number.isNaN(v))) {
    q.set('bbox', c.bbox.map((v) => Math.round(v * 100) / 100).join(','))
  }
  if (c.block_id) q.set('block', c.block_id)
  const qs = q.toString()
  return `/evidence/${c.document_id}/${page}${qs ? `?${qs}` : ''}`
}

/** Citation pointers may omit document_id (record source_locations); fill it from the parent. */
export function withDocument(c: Citation, documentId: string | null | undefined): Citation {
  return c.document_id ? c : { ...c, document_id: documentId ?? null }
}
