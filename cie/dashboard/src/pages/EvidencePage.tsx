import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/endpoints'
import type { PageBlock } from '../api/types'
import { Badge, StatusBadge } from '../components/Badge'
import { CitationLink } from '../components/CitationLink'
import { Empty, ErrorBox, KeyVals, Loading, PageHeader, Panel } from '../components/Misc'
import { useAsync } from '../hooks/useAsync'
import { fmtDate, fmtPct, parseBbox, trunc } from '../lib/format'
import { useScope } from '../state/scope'
import { useSettings } from '../state/settings'

type Box = [number, number, number, number]

function overlapArea(a: Box, b: number[]): number {
  if (!b || b.length < 4) return 0
  const w = Math.min(a[2], b[2]) - Math.max(a[0], b[0])
  const h = Math.min(a[3], b[3]) - Math.max(a[1], b[1])
  return w > 0 && h > 0 ? w * h : 0
}

/** Index page: pick a document/page to inspect. */
export function EvidenceIndexPage() {
  const { selectedId } = useScope()
  const { version } = useSettings()
  const navigate = useNavigate()
  const docs = useAsync(() => api.documents({ scope_id: selectedId, limit: 30 }), [selectedId, version], Boolean(selectedId))
  const [docId, setDocId] = useState('')
  const [page, setPage] = useState('1')
  return (
    <div className="page">
      <PageHeader title="Evidence viewer" subtitle="Open a source page with the cited region highlighted. Every citation in the app links here." />
      <div className="grid-2">
        <Panel title="Open a page">
          <form
            className="stack"
            onSubmit={(e) => {
              e.preventDefault()
              if (docId.trim()) navigate(`/evidence/${docId.trim()}/${Math.max(1, Number(page) || 1)}`)
            }}
          >
            <label className="field">
              <span>Document id</span>
              <input value={docId} onChange={(e) => setDocId(e.target.value)} placeholder="uuid" className="mono" />
            </label>
            <label className="field">
              <span>Page</span>
              <input type="number" min={1} value={page} onChange={(e) => setPage(e.target.value)} />
            </label>
            <button className="btn primary" type="submit" disabled={!docId.trim()}>
              Open
            </button>
          </form>
        </Panel>
        <Panel title="Recent documents in scope">
          {docs.loading && <Loading />}
          {docs.data && docs.data.length === 0 && <Empty>No documents in this scope.</Empty>}
          {docs.data && docs.data.length > 0 && (
            <ul className="plain">
              {docs.data.map((d) => (
                <li key={d.id}>
                  <CitationLink cite={{ document_id: d.id, page_no: 1 }} label={d.title} /> <StatusBadge status={d.status} />{' '}
                  <span className="muted small">{d.media_type}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  )
}

export default function EvidencePage() {
  const { documentId = '', pageNo = '1' } = useParams()
  const [sp, setSp] = useSearchParams()
  const navigate = useNavigate()
  const { version } = useSettings()
  const page = Math.max(1, parseInt(pageNo, 10) || 1)
  const bboxStr = sp.get('bbox')
  const blockParam = sp.get('block')
  const bbox = useMemo(() => parseBbox(bboxStr), [bboxStr])

  const pg = useAsync(() => api.page(documentId, page), [documentId, page, version], Boolean(documentId))
  const doc = useAsync(() => api.document(documentId), [documentId, version], Boolean(documentId))
  const ext = useAsync(() => api.documentExtraction(documentId, true), [documentId, version], Boolean(documentId))

  const [dpi, setDpi] = useState(110)
  const [imgStatus, setImgStatus] = useState<'loading' | 'ok' | 'error'>('loading')
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null)
  const [rendered, setRendered] = useState<{ w: number; h: number } | null>(null)
  const [hoverBlock, setHoverBlock] = useState<string | null>(null)
  const [showAllBlocks, setShowAllBlocks] = useState(false)
  const imgRef = useRef<HTMLImageElement>(null)

  useEffect(() => {
    setImgStatus('loading')
    setNatural(null)
  }, [documentId, page, dpi])

  // The bbox is in PDF points; scale by rendered-image size vs page size in points.
  useEffect(() => {
    const el = imgRef.current
    if (!el || imgStatus !== 'ok') return
    const update = () => setRendered({ w: el.clientWidth, h: el.clientHeight })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [imgStatus, documentId, page])

  const pageW = pg.data?.width || 1
  const pageH = pg.data?.height || 1
  const sx = rendered ? rendered.w / pageW : 0
  const sy = rendered ? rendered.h / pageH : 0
  const toPx = (b: number[]) => ({ left: b[0] * sx, top: b[1] * sy, width: Math.max(2, (b[2] - b[0]) * sx), height: Math.max(2, (b[3] - b[1]) * sy) })

  const blocks = pg.data?.blocks ?? []
  const citedBlock = useMemo(() => {
    if (blockParam) {
      const b = blocks.find((x) => x.id === blockParam)
      if (b) return b
    }
    if (!bbox) return null
    let best: PageBlock | null = null
    let bestArea = 0
    for (const b of blocks) {
      const a = overlapArea(bbox, b.bbox)
      if (a > bestArea) {
        bestArea = a
        best = b
      }
    }
    return best
  }, [blocks, bbox, blockParam])

  const pageCount = ext.data?.extraction?.page_count ?? null
  const go = (n: number) => navigate(`/evidence/${documentId}/${n}`)
  const focusBlock = (b: PageBlock) => {
    const q = new URLSearchParams(sp)
    q.set('bbox', b.bbox.map((v) => Math.round(v * 100) / 100).join(','))
    q.set('block', b.id)
    setSp(q)
  }
  const clearHighlight = () => {
    const q = new URLSearchParams(sp)
    q.delete('bbox')
    q.delete('block')
    setSp(q)
  }

  const imgSrc = api.pageImageUrl(documentId, page, dpi)
  const correctionsFor = (blockId: string) => (pg.data?.corrections ?? []).filter((c) => c.block_id === blockId)

  return (
    <div className="page evidence">
      <PageHeader
        title={doc.data ? doc.data.title : 'Evidence'}
        subtitle={
          <span className="badges">
            <span className="mono small">{documentId}</span>
            {doc.data && <StatusBadge status={doc.data.status} />}
            {doc.data && <Badge tone="gray">{doc.data.media_type}</Badge>}
            {pg.data && <Badge tone="gray">extracted via {pg.data.method}</Badge>}
            {pg.data?.confidence !== null && pg.data?.confidence !== undefined && <Badge tone="gray">OCR conf {fmtPct(pg.data.confidence)}</Badge>}
          </span>
        }
        actions={
          <div className="row gap wrap">
            <div className="pager">
              <button type="button" className="btn small" onClick={() => go(page - 1)} disabled={page <= 1}>
                ‹ prev
              </button>
              <span className="mono">
                page {page}
                {pageCount ? ` / ${pageCount}` : ''}
              </span>
              <button type="button" className="btn small" onClick={() => go(page + 1)} disabled={pageCount !== null && page >= pageCount}>
                next ›
              </button>
            </div>
            <label className="field inline">
              <span>DPI</span>
              <select value={dpi} onChange={(e) => setDpi(Number(e.target.value))}>
                {[72, 110, 150, 200].map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </label>
            <label className="check">
              <input type="checkbox" checked={showAllBlocks} onChange={(e) => setShowAllBlocks(e.target.checked)} /> outline all blocks
            </label>
            <a className="btn small" href={api.downloadUrl(documentId)} target="_blank" rel="noreferrer">
              Download source
            </a>
            <Link className="btn small" to={`/documents?doc=${documentId}`}>
              Document details
            </Link>
          </div>
        }
      />
      <ErrorBox error={pg.error} />
      <div className="evidence-grid">
        <Panel className="stage-panel">
          {pg.loading && <Loading text="Loading page…" />}
          {pg.data && (
            <div className="page-stage-wrap">
              {imgStatus === 'error' ? (
                <div className="stage-fallback">
                  <p className="muted">No page image is available for this media type; showing the extracted text.</p>
                  <pre className="page-text">{pg.data.text}</pre>
                </div>
              ) : (
                <div className="page-stage" style={{ aspectRatio: `${pageW} / ${pageH}` }}>
                  {imgStatus === 'loading' && <div className="stage-loading">Rendering page image…</div>}
                  <img
                    ref={imgRef}
                    src={imgSrc}
                    alt={`Page ${page}`}
                    onLoad={(e) => {
                      const el = e.currentTarget
                      setNatural({ w: el.naturalWidth, h: el.naturalHeight })
                      setImgStatus('ok')
                    }}
                    onError={() => setImgStatus('error')}
                    draggable={false}
                  />
                  {imgStatus === 'ok' && rendered && (
                    <>
                      {showAllBlocks &&
                        blocks.map((b) => (
                          <div
                            key={b.id}
                            className={`bbox-block-outline ${hoverBlock === b.id ? 'hover' : ''}`}
                            style={toPx(b.bbox)}
                            onMouseEnter={() => setHoverBlock(b.id)}
                            onMouseLeave={() => setHoverBlock(null)}
                            onClick={() => focusBlock(b)}
                            title={trunc(b.text, 120)}
                          />
                        ))}
                      {!showAllBlocks && hoverBlock && blocks.find((b) => b.id === hoverBlock) && (
                        <div className="bbox-block-outline hover" style={toPx(blocks.find((b) => b.id === hoverBlock)!.bbox)} />
                      )}
                      {citedBlock && (!bbox || overlapArea(bbox, citedBlock.bbox) < (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) * 0.98) && (
                        <div className="bbox-block" style={toPx(citedBlock.bbox)} title="block containing the citation" />
                      )}
                      {bbox && <div className="bbox-hl" style={toPx(bbox)} title={`cited region ${bbox.join(', ')}`} />}
                    </>
                  )}
                </div>
              )}
              <div className="muted small stage-meta">
                page {pageW.toFixed(0)}×{pageH.toFixed(0)} pt
                {natural && ` · image ${natural.w}×${natural.h} px`}
                {rendered && ` · rendered ${rendered.w}×${rendered.h} px · scale ${sx.toFixed(3)} px/pt`}
                {bbox && (
                  <>
                    {' '}
                    · bbox [{bbox.map((v) => v.toFixed(1)).join(', ')}]{' '}
                    <button type="button" className="linklike" onClick={clearHighlight}>
                      clear highlight
                    </button>
                  </>
                )}
              </div>
            </div>
          )}
        </Panel>
        <div className="stack evidence-side">
          <Panel title="Cited region">
            {!bbox && !citedBlock && <div className="muted small">No bbox in the URL. Click a block below to highlight it, or follow a citation from search results.</div>}
            {bbox && !citedBlock && <div className="muted small">Highlighted region has no overlapping text block on this page.</div>}
            {citedBlock && (
              <div className="stack">
                <div className="badges">
                  <Badge tone="blue">{citedBlock.kind}</Badge>
                  {citedBlock.confidence !== null && citedBlock.confidence !== undefined && <Badge tone="gray">conf {fmtPct(citedBlock.confidence)}</Badge>}
                  <span className="mono small">[{citedBlock.bbox.map((v) => v.toFixed(0)).join(', ')}]</span>
                </div>
                <blockquote className="quote big">{citedBlock.text || <span className="muted">(no text)</span>}</blockquote>
                {correctionsFor(citedBlock.id).map((c, i) => (
                  <div key={i} className="info-box small">
                    OCR correction ({c.method}): <s>{c.original}</s> → <strong>{c.corrected}</strong>
                  </div>
                ))}
              </div>
            )}
          </Panel>
          <Panel title={<span>Blocks {pg.data && <span className="muted">({blocks.length})</span>}</span>}>
            {pg.data && blocks.length === 0 && <div className="muted small">No blocks on this page.</div>}
            <ul className="plain block-list">
              {blocks.map((b) => (
                <li
                  key={b.id}
                  className={`block-row ${citedBlock?.id === b.id ? 'cited' : ''} ${hoverBlock === b.id ? 'hover' : ''}`}
                  onMouseEnter={() => setHoverBlock(b.id)}
                  onMouseLeave={() => setHoverBlock(null)}
                  onClick={() => focusBlock(b)}
                >
                  <Badge tone={b.kind === 'heading' || b.kind === 'title' ? 'purple' : b.kind === 'table' ? 'teal' : 'gray'}>{b.kind}</Badge>
                  <span className="block-text">{trunc(b.text, 220) || <span className="muted">(no text)</span>}</span>
                </li>
              ))}
            </ul>
          </Panel>
          {doc.data && (
            <Panel title="Source">
              <KeyVals
                items={[
                  ['File', doc.data.original_filename],
                  ['Version', `v${doc.data.version}`],
                  ['Ingested', fmtDate(doc.data.ingested_at)],
                  ['Sensitivity', String(doc.data.sensitivity)],
                  ['SHA-256', <code className="mono small">{doc.data.sha256.slice(0, 16)}…</code>],
                ]}
              />
            </Panel>
          )}
          {pg.data && (
            <Panel title="Page text">
              <details>
                <summary>Show extracted text</summary>
                <pre className="page-text">{pg.data.text}</pre>
              </details>
            </Panel>
          )}
        </div>
      </div>
    </div>
  )
}
