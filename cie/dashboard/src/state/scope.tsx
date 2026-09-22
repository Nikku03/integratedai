import { createContext, useContext, useEffect, useMemo, type ReactNode } from 'react'
import { api } from '../api/endpoints'
import type { ScopeOut } from '../api/types'
import { useAsync } from '../hooks/useAsync'
import { useLocalStorage } from '../hooks/useLocalStorage'
import { useSettings } from './settings'

interface ScopeCtx {
  scopes: ScopeOut[]
  loading: boolean
  error: Error | undefined
  selectedId: string | null
  selected: ScopeOut | undefined
  select: (id: string | null) => void
  reload: () => void
}

const Ctx = createContext<ScopeCtx | null>(null)

/** The selected scope drives scope_id for every page; it is persisted per browser. */
export function ScopeProvider({ children }: { children: ReactNode }) {
  const { apiKey, version } = useSettings()
  const [selectedId, setSelectedId] = useLocalStorage('cie.scopeId')
  const { data, loading, error, reload } = useAsync(() => api.scopes(), [version], Boolean(apiKey))
  const scopes = useMemo(() => data ?? [], [data])

  // Fall back to the company root (or first visible scope) when nothing valid is stored.
  useEffect(() => {
    if (!scopes.length) return
    if (selectedId && scopes.some((s) => s.id === selectedId)) return
    const root = scopes.find((s) => s.parent_id === null) ?? scopes[0]
    setSelectedId(root.id)
  }, [scopes, selectedId, setSelectedId])

  const value = useMemo<ScopeCtx>(
    () => ({
      scopes,
      loading,
      error,
      selectedId,
      selected: scopes.find((s) => s.id === selectedId),
      select: setSelectedId,
      reload,
    }),
    [scopes, loading, error, selectedId, setSelectedId, reload],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useScope(): ScopeCtx {
  const v = useContext(Ctx)
  if (!v) throw new Error('useScope outside ScopeProvider')
  return v
}
