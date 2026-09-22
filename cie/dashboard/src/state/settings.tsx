import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { DEFAULT_API_BASE, getApiBase, getApiKey, saveApiSettings } from '../api/client'

interface SettingsCtx {
  apiBase: string
  apiKey: string
  defaultBase: string
  save: (base: string, key: string) => void
  /** Changes whenever settings are saved; pages use it as a reload dependency. */
  version: number
}

const Ctx = createContext<SettingsCtx | null>(null)

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [apiBase, setBase] = useState(getApiBase())
  const [apiKey, setKey] = useState(getApiKey())
  const [version, setVersion] = useState(0)

  const save = useCallback((base: string, key: string) => {
    saveApiSettings(base || DEFAULT_API_BASE, key)
    setBase(getApiBase())
    setKey(getApiKey())
    setVersion((v) => v + 1)
  }, [])

  const value = useMemo<SettingsCtx>(
    () => ({ apiBase, apiKey, defaultBase: DEFAULT_API_BASE, save, version }),
    [apiBase, apiKey, save, version],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSettings(): SettingsCtx {
  const v = useContext(Ctx)
  if (!v) throw new Error('useSettings outside SettingsProvider')
  return v
}
