import { useCallback, useState } from 'react'

/** A string value mirrored into localStorage (per-viewer convenience only). */
export function useLocalStorage(key: string, initial: string | null = null): [string | null, (v: string | null) => void] {
  const [value, setValue] = useState<string | null>(() => {
    try {
      const v = localStorage.getItem(key)
      return v === null ? initial : v
    } catch {
      return initial
    }
  })
  const set = useCallback(
    (v: string | null) => {
      setValue(v)
      try {
        if (v === null || v === '') localStorage.removeItem(key)
        else localStorage.setItem(key, v)
      } catch {
        /* ignore */
      }
    },
    [key],
  )
  return [value, set]
}
