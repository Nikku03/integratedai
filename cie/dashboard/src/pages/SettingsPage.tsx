import { useState, type FormEvent } from 'react'
import { api } from '../api/endpoints'
import type { Me } from '../api/types'
import { Badge } from '../components/Badge'
import { KeyVals, PageHeader, Panel } from '../components/Misc'
import { useSettings } from '../state/settings'
import { useToast } from '../state/toast'

export default function SettingsPage() {
  const { apiBase, apiKey, defaultBase, save } = useSettings()
  const { push } = useToast()
  const [base, setBase] = useState(apiBase)
  const [key, setKey] = useState(apiKey)
  const [show, setShow] = useState(false)
  const [testing, setTesting] = useState(false)
  const [me, setMe] = useState<Me | null>(null)
  const [testErr, setTestErr] = useState<string | null>(null)

  function onSave(e: FormEvent) {
    e.preventDefault()
    save(base, key)
    push('success', 'Settings saved to this browser.')
  }

  async function test() {
    save(base, key)
    setTesting(true)
    setTestErr(null)
    setMe(null)
    try {
      setMe(await api.me(true))
    } catch (ex) {
      setTestErr((ex as Error).message)
    } finally {
      setTesting(false)
    }
  }

  function clearLocal() {
    try {
      ;['cie.scopeId', 'cie.projectId', 'cie.answerMode'].forEach((k) => localStorage.removeItem(k))
    } catch {
      /* ignore */
    }
    push('info', 'Cleared remembered scope/project selections.')
  }

  return (
    <div className="page">
      <PageHeader title="Settings" subtitle="Connection to the CIE API. Values are stored in this browser's localStorage only." />
      <div className="grid-2">
        <Panel title="API connection">
          <form className="stack" onSubmit={onSave}>
            <label className="field">
              <span>API base URL</span>
              <input type="url" value={base} onChange={(e) => setBase(e.target.value)} placeholder={defaultBase} />
              <small className="muted">
                Build default (VITE_API_BASE): <code className="mono">{defaultBase}</code>
              </small>
            </label>
            <label className="field">
              <span>API key (sent as X-API-Key)</span>
              <div className="row gap">
                <input type={show ? 'text' : 'password'} value={key} onChange={(e) => setKey(e.target.value)} placeholder="cie bootstrap prints an admin key" autoComplete="off" />
                <button type="button" className="btn small" onClick={() => setShow((s) => !s)}>
                  {show ? 'hide' : 'show'}
                </button>
              </div>
              <small className="muted">Page images and downloads append the key as <code className="mono">?api_key=</code> because image tags cannot carry headers.</small>
            </label>
            <div className="row gap">
              <button type="submit" className="btn primary">
                Save
              </button>
              <button type="button" className="btn" onClick={test} disabled={testing}>
                {testing ? 'Testing…' : 'Save & test connection'}
              </button>
              <button type="button" className="btn" onClick={clearLocal}>
                Clear remembered selections
              </button>
            </div>
          </form>
        </Panel>
        <Panel title="Connection status">
          {testErr && <div className="error-box">{testErr}</div>}
          {me ? (
            <KeyVals
              items={[
                ['Principal', <span>{me.principal.name} <Badge tone="gray">{me.principal.kind}</Badge></span>],
                ['Principal id', <code className="mono small">{me.principal.id}</code>],
                ['Admin', me.is_admin ? <Badge tone="purple">yes</Badge> : <Badge tone="gray">no</Badge>],
                ['Visible scopes', String(Object.keys(me.scopes).length)],
              ]}
            />
          ) : (
            <p className="muted">Run “Save & test connection” to call <code className="mono">GET /permissions/me</code>.</p>
          )}
          <h4>How to get a key</h4>
          <pre className="code">{`cie migrate
cie bootstrap --tenant acme --company "Acme" --admin admin   # prints an API key`}</pre>
        </Panel>
      </div>
    </div>
  )
}
