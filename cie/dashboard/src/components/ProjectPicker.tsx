import { useCallback, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/endpoints'
import { useAsync } from '../hooks/useAsync'
import { useLocalStorage } from '../hooks/useLocalStorage'
import { useSettings } from '../state/settings'

/** Remembered project selection shared by the tasks, graph and ledger pages. */
export function useProjectSelection(): [string | null, (v: string | null) => void] {
  return useLocalStorage('cie.projectId')
}

/** Project id from ?project= (deep links) falling back to the remembered one; writes both. */
export function useProjectParam(): [string | null, (id: string | null) => void] {
  const [sp, setSp] = useSearchParams()
  const [stored, setStored] = useProjectSelection()
  const value = sp.get('project') || stored
  const set = useCallback(
    (id: string | null) => {
      setStored(id)
      const next = new URLSearchParams(sp)
      if (id) next.set('project', id)
      else next.delete('project')
      setSp(next, { replace: true })
    },
    [sp, setSp, setStored],
  )
  return [value, set]
}

interface Props {
  value: string | null
  onChange: (id: string | null) => void
  allowAll?: boolean
  autoSelectFirst?: boolean
}

export function ProjectPicker({ value, onChange, allowAll = false, autoSelectFirst = true }: Props) {
  const { version } = useSettings()
  const { data, loading } = useAsync(() => api.projects(), [version])
  const projects = data ?? []
  const valid = value && projects.some((p) => p.id === value) ? value : ''

  useEffect(() => {
    if (!loading && projects.length && !valid && autoSelectFirst && !allowAll) onChange(projects[0].id)
  }, [loading, projects, valid, autoSelectFirst, allowAll, onChange])

  return (
    <label className="field inline">
      <span>Project</span>
      <select value={valid} onChange={(e) => onChange(e.target.value || null)} disabled={loading}>
        {allowAll ? (
          <option value="">All projects</option>
        ) : (
          <option value="">{loading ? 'Loading…' : projects.length ? 'Select a project' : 'No projects'}</option>
        )}
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name} · {p.status}
          </option>
        ))}
      </select>
    </label>
  )
}
