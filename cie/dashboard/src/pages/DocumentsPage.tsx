import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/endpoints'
import type { DocumentOut, JobOut } from '../api/types'
import { Badge, StatusBadge } from '../components/Badge'
import { CitationLink } from '../components/CitationLink'
import { Empty, ErrorBox, JsonView, KeyVals, Loading, Meter, PageHeader, Panel } from '../components/Misc'
import { useAsync } from '../hooks/useAsync'
import { fmtBytes, fmtDate, fmtPct, short } from '../lib/format'
import { useScope } from '../state/scope'
import { useSettings } from '../state/settings'
import { useToast } from '../state/toast'

export default function DocumentsPage() {
  const { selectedId, selected, scopes } = useScope()
  const { version } = useSettings()
  const [sp, setSp] = useSearchParams()
  const [allScopes, setAllScopes] = useState(false)
  const [status, setStatus] = useState('')
  const openId = sp.get('doc')
  const setOpenId = (id: string | null) => {
    const next = new URLSearchParams(sp)
    if (id) next.set('doc', id)
    else next.delete('doc')
    setSp(next, { replace: true })
  }

  const docs = useAsync(
    () => api.documents({ scope_id: allScopes ? null : selectedId, status: status || null, limit: 200 }),
    [selectedId, allScopes, status, version],
    allScopes || Boolean(selectedId),
  )
  const jobs = useAsync(() => api.jobs({ limit: 15 }), [version])

  const statuses = [...new Set((docs.data ?? []).map((d) => d.status))].sort()

  return (
    <div className="page">
      <PageHeader
        title="Document library"
        subtitle={allScopes ? 'All documents visible to this key.' : selected ? `Documents in ${selected.path || selected.name}` : 'Select a scope first.'}
        actions={
          <div className="row gap wrap">
            <label className="check">
              <input type="checkbox" checked={allScopes} onChange={(e) => setAllScopes(e.target.checked)} /> all visible scopes
            </label>
            <label className="field inline">
              <span>Status</span>
              <select value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">any</option>
                {statuses.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="btn" onClick={docs.reload}>
              Refresh
            </button>
          </div>
        }
      />
      <div className="grid-2 wide-left">
        <Panel title={<span>Documents {docs.data && <span className="muted">({docs.data.length})</span>}</span>}>
          {docs.loading && <Loading />}
          <ErrorBox error={docs.error} />
          {docs.data && docs.data.length === 0 && <Empty>No documents in this scope yet. Upload one on the right.</Empty>}
          {docs.data && docs.data.length > 0 && (
            <div className="table-wrap">
              <table className="table hover">
                <thead>
                  <tr>
                    <th>Title</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Ver.</th>
                    <th>Sens.</th>
                    <th>Flags</th>
                    <th>Size</th>
                    <th>Ingested</th>
                  </tr>
                </thead>
                <tbody>
                  {docs.data.map((d) => (
                    <tr key={d.id} className={d.id === openId ? 'row-selected' : ''} onClick={() => setOpenId(d.id)}>
                      <td>
                        <div className="cell-title">{d.title}</div>
                        <div className="muted small">{d.original_filename}</div>
                      </td>
                      <td>{d.doc_type ?? <span className="muted">—</span>}</td>
                      <td>
                        <StatusBadge status={d.status} />
                      </td>
                      <td className="mono">v{d.version}</td>
                      <td>
                        <Badge tone={d.sensitivity > 1 ? 'red' : 'gray'}>{d.sensitivity}</Badge>
                      </td>
                      <td>
                        <FlagBadges injection={d.injection_flags} pii={d.pii_flags} legalHold={d.legal_hold} />
                      </td>
                      <td className="mono small">{fmtBytes(d.size_bytes)}</td>
                      <td className="small">{fmtDate(d.ingested_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        <div className="stack">
          <UploadPanel
            defaultScopeId={selectedId}
            scopes={scopes.filter((s) => s.kind !== 'agent' && s.kind !== 'task')}
            onDone={() => {
              docs.reload()
              jobs.reload()
            }}
          />
          {openId && <DocumentDetail id={openId} onClose={() => setOpenId(null)} />}
          <JobsPanel jobs={jobs.data} loading={jobs.loading} onRefresh={jobs.reload} onRan={() => { jobs.reload(); docs.reload() }} />
        </div>
      </div>
    </div>
  )
}

function FlagBadges({ injection, pii, legalHold }: { injection: number; pii: number; legalHold?: boolean }) {
  const total = injection + pii
  return (
    <span className="badges">
      {total === 0 && !legalHold && <span className="muted">0</span>}
      {injection > 0 && (
        <Badge tone="red" title="prompt-injection flags">
          inj {injection}
        </Badge>
      )}
      {pii > 0 && (
        <Badge tone="amber" title="PII / secrets flags">
          pii {pii}
        </Badge>
      )}
      {legalHold && <Badge tone="purple">legal hold</Badge>}
    </span>
  )
}

function DocumentDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { version } = useSettings()
  const doc = useAsync(() => api.document(id), [id, version])
  const versions = useAsync(() => api.documentVersions(id), [id, version])
  const extraction = useAsync(() => api.documentExtraction(id, true), [id, version])
  const flags = useAsync(() => api.documentFlags(id), [id, version])
  const records = useAsync(() => api.records({ document_id: id, limit: 50 }), [id, version])
  const d = doc.data
  const ex = extraction.data?.extraction
  return (
    <Panel
      title="Document"
      actions={
        <button type="button" className="btn small" onClick={onClose}>
          close
        </button>
      }
    >
      {doc.loading && <Loading />}
      <ErrorBox error={doc.error} />
      {d && (
        <div className="stack">
          <h3>{d.title}</h3>
          <div className="badges">
            <StatusBadge status={d.status} />
            <Badge tone="gray">v{d.version}</Badge>
            <Badge tone="gray">{d.media_type}</Badge>
            <Badge tone={d.sensitivity > 1 ? 'red' : 'gray'}>sensitivity {d.sensitivity}</Badge>
            <FlagBadges injection={d.injection_flags} pii={d.pii_flags} legalHold={d.legal_hold} />
          </div>
          <KeyVals
            items={[
              ['Id', <code className="mono small">{d.id}</code>],
              ['Family', <code className="mono small">{d.family_id}</code>],
              ['File', `${d.original_filename} · ${fmtBytes(d.size_bytes)}`],
              ['Type / language', `${d.doc_type ?? '—'} / ${d.language ?? '—'}`],
              ['Source', `${d.source}${d.original_location ? ` · ${d.original_location}` : ''}`],
              ['Ingested', fmtDate(d.ingested_at)],
              ['Retention', `${d.retention_policy}${d.legal_hold ? ' · legal hold' : ''}`],
              ['SHA-256', <code className="mono small">{short(d.sha256, 16)}…</code>],
            ]}
          />
          <div className="row gap wrap">
            <CitationLink cite={{ document_id: d.id, page_no: 1 }} label="Open in evidence viewer" className="btn small" />
            <a className="btn small" href={api.downloadUrl(d.id)} target="_blank" rel="noreferrer">
              Download source
            </a>
          </div>

          <h4>Extraction</h4>
          {extraction.error && <div className="muted small">Extraction status unavailable: {extraction.error.message}</div>}
          {extraction.data && !ex && <div className="muted small">Not extracted yet {extraction.data.job ? `· job ${extraction.data.job.status}` : '· no job queued'}.</div>}
          {ex && (
            <KeyVals
              items={[
                ['Extractor', `${ex.extractor} · ${ex.status}`],
                ['Pages', (
                  <span>
                    {ex.pages_done ?? 0}/{ex.page_count ?? '?'} <Meter value={ex.pages_done ?? 0} max={ex.page_count || 1} tone="green" />
                  </span>
                )],
                ['Confidence', fmtPct(ex.mean_confidence)],
                ['Completeness', fmtPct(ex.completeness)],
                ['Language', ex.language ?? '—'],
              ]}
            />
          )}
          {extraction.data?.job && (
            <div className="small">
              Job <StatusBadge status={extraction.data.job.status} /> {fmtPct(extraction.data.job.progress)} · attempts {extraction.data.job.attempts}
              {extraction.data.job.last_error && <div className="error-box small">{extraction.data.job.last_error}</div>}
            </div>
          )}
          {ex?.stats && Object.keys(ex.stats).length > 0 && <JsonView value={ex.stats} summary="Extraction stats" />}

          <h4>Flags</h4>
          {flags.data ? (
            <div className="badges">
              <Badge tone={flags.data.injection ? 'red' : 'gray'}>injection {flags.data.injection}</Badge>
              <Badge tone={flags.data.pii_and_secrets ? 'amber' : 'gray'}>PII & secrets {flags.data.pii_and_secrets}</Badge>
            </div>
          ) : (
            <span className="muted small">—</span>
          )}

          <h4>Versions {versions.data && <span className="muted">({versions.data.length})</span>}</h4>
          {versions.data && (
            <div className="table-wrap">
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Ver.</th>
                    <th>Status</th>
                    <th>Ingested</th>
                    <th>Size</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {versions.data.map((v: DocumentOut) => (
                    <tr key={v.id} className={v.id === d.id ? 'row-selected' : ''}>
                      <td className="mono">v{v.version}</td>
                      <td>
                        <StatusBadge status={v.status} />
                      </td>
                      <td className="small">{fmtDate(v.ingested_at)}</td>
                      <td className="mono small">{fmtBytes(v.size_bytes)}</td>
                      <td>
                        <Link to={`/documents?doc=${v.id}`} className="small">
                          details
                        </Link>{' '}
                        <CitationLink cite={{ document_id: v.id, page_no: 1 }} label="view" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h4>Memory records from this document {records.data && <span className="muted">({records.data.length})</span>}</h4>
          {records.data && records.data.length === 0 && <div className="muted small">None yet.</div>}
          {records.data && records.data.length > 0 && (
            <ul className="plain">
              {records.data.slice(0, 25).map((r) => (
                <li key={r.id} className="small">
                  <Badge tone="gray">{r.type}</Badge> {r.summary}{' '}
                  {r.source_locations[0] && <CitationLink cite={{ ...r.source_locations[0], document_id: r.source_document_id }} />}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Panel>
  )
}

function UploadPanel({ defaultScopeId, scopes, onDone }: { defaultScopeId: string | null; scopes: { id: string; name: string; path: string }[]; onDone: () => void }) {
  const { push } = useToast()
  const [file, setFile] = useState<File | null>(null)
  const [scopeId, setScopeId] = useState<string>('')
  const [title, setTitle] = useState('')
  const [docType, setDocType] = useState('')
  const [sensitivity, setSensitivity] = useState('1')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const effectiveScope = scopeId || defaultScopeId || ''

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!file || !effectiveScope) return
    setBusy(true)
    setResult(null)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('scope_id', effectiveScope)
      if (title.trim()) form.append('title', title.trim())
      if (docType.trim()) form.append('doc_type', docType.trim())
      form.append('sensitivity', sensitivity)
      const res = await api.ingest(form)
      const msg = res.deduplicated ? `Already ingested: "${res.document.title}" (deduplicated)` : `Ingested "${res.document.title}" v${res.document.version}`
      push('success', msg)
      let ran = ''
      if (res.created) {
        try {
          const jobs = await api.runJobs(10)
          ran = ` · processed ${jobs.length} job(s)${jobs.some((j) => j.status === 'failed') ? ' (some failed)' : ''}`
          push(jobs.some((j) => j.status === 'failed') ? 'error' : 'success', `Job runner: ${jobs.length} job(s) processed`)
        } catch {
          ran = ' · job queued (worker will pick it up)'
        }
      }
      setResult(msg + ran)
      setFile(null)
      setTitle('')
      onDone()
    } catch (ex) {
      setResult((ex as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel title="Upload document">
      <form className="stack" onSubmit={submit}>
        <label className="field">
          <span>File</span>
          <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <label className="field">
          <span>Scope</span>
          <select value={effectiveScope} onChange={(e) => setScopeId(e.target.value)}>
            {!effectiveScope && <option value="">Select a scope</option>}
            {scopes.map((s) => (
              <option key={s.id} value={s.id}>
                {s.path || s.name}
              </option>
            ))}
          </select>
        </label>
        <div className="row gap">
          <label className="field grow">
            <span>Title (optional)</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="field grow">
            <span>Doc type</span>
            <input value={docType} onChange={(e) => setDocType(e.target.value)} placeholder="contract, policy, report…" list="doc-types" />
            <datalist id="doc-types">
              {['contract', 'policy', 'report', 'invoice', 'memo', 'spec', 'minutes', 'email'].map((t) => (
                <option key={t} value={t} />
              ))}
            </datalist>
          </label>
          <label className="field">
            <span>Sensitivity</span>
            <select value={sensitivity} onChange={(e) => setSensitivity(e.target.value)}>
              <option value="1">1 · internal</option>
              <option value="2">2 · confidential</option>
              <option value="3">3 · restricted</option>
            </select>
          </label>
        </div>
        <div className="row gap">
          <button type="submit" className="btn primary" disabled={!file || !effectiveScope || busy}>
            {busy ? 'Uploading…' : 'Ingest & run jobs'}
          </button>
          <span className="muted small">POST /ingest then POST /jobs/run (admin)</span>
        </div>
        {result && <div className="info-box small">{result}</div>}
      </form>
    </Panel>
  )
}

function JobsPanel({ jobs, loading, onRefresh, onRan }: { jobs: JobOut[] | undefined; loading: boolean; onRefresh: () => void; onRan: () => void }) {
  const { push } = useToast()
  const [busy, setBusy] = useState(false)
  async function run() {
    setBusy(true)
    try {
      const done = await api.runJobs(10)
      push(done.length ? 'success' : 'info', done.length ? `Processed ${done.length} job(s)` : 'No queued jobs')
      onRan()
    } catch {
      /* toast already shown */
    } finally {
      setBusy(false)
    }
  }
  return (
    <Panel
      title="Recent jobs"
      actions={
        <div className="row gap">
          <button type="button" className="btn small" onClick={onRefresh}>
            refresh
          </button>
          <button type="button" className="btn small primary" onClick={run} disabled={busy}>
            {busy ? 'Running…' : 'Run queued jobs'}
          </button>
        </div>
      }
    >
      {loading && <Loading />}
      {jobs && jobs.length === 0 && <div className="muted small">No jobs.</div>}
      {jobs && jobs.length > 0 && (
        <div className="table-wrap">
          <table className="table compact">
            <thead>
              <tr>
                <th>Kind</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Att.</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id} title={j.last_error ?? j.id}>
                  <td>{j.kind}</td>
                  <td>
                    <StatusBadge status={j.status} />
                  </td>
                  <td>
                    <Meter value={j.progress} tone={j.status === 'failed' ? 'red' : 'green'} /> <span className="mono small">{fmtPct(j.progress)}</span>
                  </td>
                  <td className="mono">{j.attempts}</td>
                  <td className="small">{fmtDate(j.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}
