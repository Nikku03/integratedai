// Small typed fetch client. Settings (API base URL and key) live in
// localStorage so they survive reloads; the key is sent as X-API-Key. For
// <img>/<a> targets that cannot carry headers, withKey() appends ?api_key=.

export const DEFAULT_API_BASE: string = import.meta.env.VITE_API_BASE || 'http://localhost:8000/api'

const LS_BASE = 'cie.apiBase'
const LS_KEY = 'cie.apiKey'

function lsGet(k: string): string | null {
  try {
    return localStorage.getItem(k)
  } catch {
    return null
  }
}

function lsSet(k: string, v: string): void {
  try {
    if (v) localStorage.setItem(k, v)
    else localStorage.removeItem(k)
  } catch {
    /* storage unavailable (private mode etc.) */
  }
}

export function getApiBase(): string {
  return (lsGet(LS_BASE) || DEFAULT_API_BASE).replace(/\/+$/, '')
}

export function getApiKey(): string {
  return lsGet(LS_KEY) || ''
}

export function saveApiSettings(base: string, key: string): void {
  lsSet(LS_BASE, base.trim())
  lsSet(LS_KEY, key.trim())
}

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

type ErrorListener = (e: ApiError) => void
const listeners = new Set<ErrorListener>()

/** Subscribe to API failures (used by the toast provider). */
export function onApiError(fn: ErrorListener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

function emit(e: ApiError): void {
  listeners.forEach((fn) => fn(e))
}

export type Query = Record<string, string | number | boolean | null | undefined>

export function apiUrl(path: string, query?: Query): string {
  const url = getApiBase() + (path.startsWith('/') ? path : `/${path}`)
  if (!query) return url
  const qs = Object.entries(query)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&')
  return qs ? `${url}?${qs}` : url
}

/** Append the API key as a query parameter (for <img src> and download links). */
export function withKey(url: string): string {
  const key = getApiKey()
  if (!key) return url
  return `${url}${url.includes('?') ? '&' : '?'}api_key=${encodeURIComponent(key)}`
}

export interface FetchOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  form?: FormData
  query?: Query
  /** Do not surface this failure as a toast. */
  silent?: boolean
  signal?: AbortSignal
}

interface ValidationItem {
  loc?: (string | number)[]
  msg?: string
}

async function toApiError(res: Response): Promise<ApiError> {
  let text = ''
  let detail: unknown
  try {
    text = await res.text()
    detail = JSON.parse(text)
  } catch {
    detail = text
  }
  let message = `${res.status} ${res.statusText || 'error'}`
  const d = (detail as { detail?: unknown } | null)?.detail
  if (typeof d === 'string') message = d
  else if (Array.isArray(d)) {
    message = (d as ValidationItem[])
      .map((x) => `${(x.loc || []).filter((p) => p !== 'body').join('.')}: ${x.msg ?? ''}`)
      .join('; ')
  } else if (text && text.length < 200) message = `${message}: ${text}`
  return new ApiError(res.status, message, detail)
}

export async function apiFetch<T>(path: string, opts: FetchOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const key = getApiKey()
  if (key) headers['X-API-Key'] = key
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  const method = opts.method || (body !== undefined ? 'POST' : 'GET')
  let res: Response
  try {
    res = await fetch(apiUrl(path, opts.query), { method, headers, body, signal: opts.signal })
  } catch (e) {
    const err = e as Error
    if (err.name === 'AbortError') throw err
    const apiErr = new ApiError(0, `Cannot reach API at ${getApiBase()} (${err.message})`)
    if (!opts.silent) emit(apiErr)
    throw apiErr
  }
  if (!res.ok) {
    const err = await toApiError(res)
    if (!opts.silent) emit(err)
    throw err
  }
  if (res.status === 204) return undefined as T
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('application/json')) return (await res.json()) as T
  return (await res.text()) as unknown as T
}
