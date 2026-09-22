import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { onApiError } from '../api/client'

export type ToastKind = 'error' | 'success' | 'info'

interface Toast {
  id: number
  kind: ToastKind
  text: string
}

interface ToastCtx {
  push: (kind: ToastKind, text: string) => void
}

const Ctx = createContext<ToastCtx | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const seq = useRef(0)

  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), [])

  const push = useCallback(
    (kind: ToastKind, text: string) => {
      const id = ++seq.current
      setToasts((t) => [...t.slice(-4), { id, kind, text }])
      window.setTimeout(() => dismiss(id), kind === 'error' ? 8000 : 4000)
    },
    [dismiss],
  )

  // Every failed API call becomes an error toast (unless the caller asked for silence).
  useEffect(() => onApiError((e) => push('error', e.status ? `API ${e.status}: ${e.message}` : e.message)), [push])

  const value = useMemo(() => ({ push }), [push])
  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`} onClick={() => dismiss(t.id)}>
            {t.text}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}

export function useToast(): ToastCtx {
  const v = useContext(Ctx)
  if (!v) throw new Error('useToast outside ToastProvider')
  return v
}
