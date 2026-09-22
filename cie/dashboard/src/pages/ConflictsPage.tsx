import { useState } from 'react'
import { api } from '../api/endpoints'
import { Badge } from '../components/Badge'
import { Empty, ErrorBox, Loading, PageHeader, Panel } from '../components/Misc'
import { RecordCard } from '../components/RecordCard'
import { useAsync } from '../hooks/useAsync'
import { useScope } from '../state/scope'
import { useSettings } from '../state/settings'

type Tab = 'contradiction' | 'open_question'

export default function ConflictsPage() {
  const { selectedId, selected } = useScope()
  const { version } = useSettings()
  const [tab, setTab] = useState<Tab>('contradiction')
  const [allScopes, setAllScopes] = useState(false)
  const [includeHistory, setIncludeHistory] = useState(false)
  const scope = allScopes ? null : selectedId

  const data = useAsync(
    async () => {
      const [contradictions, questions] = await Promise.all([
        api.records({ type: 'contradiction', scope_id: scope, include_history: includeHistory, limit: 200 }),
        api.records({ type: 'open_question', scope_id: scope, include_history: includeHistory, limit: 200 }),
      ])
      return { contradiction: contradictions, open_question: questions }
    },
    [scope, includeHistory, version],
    allScopes || Boolean(selectedId),
  )

  const list = data.data?.[tab] ?? []

  return (
    <div className="page">
      <PageHeader
        title="Conflicts & unresolved questions"
        subtitle={allScopes ? 'Across every visible scope.' : selected ? `Within ${selected.path || selected.name}` : 'Select a scope first.'}
        actions={
          <div className="row gap wrap">
            <label className="check">
              <input type="checkbox" checked={allScopes} onChange={(e) => setAllScopes(e.target.checked)} /> all visible scopes
            </label>
            <label className="check">
              <input type="checkbox" checked={includeHistory} onChange={(e) => setIncludeHistory(e.target.checked)} /> include superseded
            </label>
            <button type="button" className="btn small" onClick={data.reload}>
              refresh
            </button>
          </div>
        }
      />
      <div className="tabs">
        <button type="button" className={`tab ${tab === 'contradiction' ? 'active' : ''}`} onClick={() => setTab('contradiction')}>
          Contradictions <Badge tone={data.data?.contradiction.length ? 'red' : 'gray'}>{data.data?.contradiction.length ?? '…'}</Badge>
        </button>
        <button type="button" className={`tab ${tab === 'open_question' ? 'active' : ''}`} onClick={() => setTab('open_question')}>
          Open questions <Badge tone={data.data?.open_question.length ? 'amber' : 'gray'}>{data.data?.open_question.length ?? '…'}</Badge>
        </button>
      </div>
      <Panel>
        {data.loading && <Loading />}
        <ErrorBox error={data.error} />
        {data.data && list.length === 0 && (
          <Empty>{tab === 'contradiction' ? 'No contradictions recorded in this scope. Both sides of a disagreement are kept as records linked with "contradicts".' : 'No open questions in this scope.'}</Empty>
        )}
        <div className="stack">
          {list.map((r) => (
            <RecordCard key={r.id} record={r} />
          ))}
        </div>
      </Panel>
    </div>
  )
}
