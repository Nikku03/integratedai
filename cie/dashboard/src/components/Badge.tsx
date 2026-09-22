import type { ReactNode } from 'react'

export type Tone = 'gray' | 'blue' | 'green' | 'amber' | 'red' | 'purple' | 'teal'

export function Badge({ tone = 'gray', children, title, className = '' }: { tone?: Tone; children: ReactNode; title?: string; className?: string }) {
  return (
    <span className={`badge badge-${tone} ${className}`} title={title}>
      {children}
    </span>
  )
}

const STATUS_TONES: Record<string, Tone> = {
  // tasks / jobs / documents / approvals / records
  pending: 'gray',
  queued: 'gray',
  blocked: 'amber',
  assigned: 'blue',
  running: 'blue',
  extracting: 'blue',
  needs_verification: 'purple',
  awaiting_approval: 'amber',
  verified: 'green',
  done: 'green',
  ready: 'green',
  indexed: 'green',
  extracted: 'green',
  approved: 'green',
  answered: 'green',
  failed: 'red',
  rejected: 'red',
  error: 'red',
  conflict: 'red',
  disputed: 'red',
  cancelled: 'gray',
  insufficient_evidence: 'amber',
  unverified: 'gray',
  superseded: 'amber',
  current: 'green',
  active: 'green',
  planning: 'blue',
  open: 'blue',
  closed: 'gray',
}

export function toneFor(status: string | null | undefined): Tone {
  if (!status) return 'gray'
  return STATUS_TONES[status] ?? 'gray'
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  return <Badge tone={toneFor(status)}>{status ?? '—'}</Badge>
}

const RISK_TONES: Record<string, Tone> = { low: 'green', medium: 'amber', high: 'red', critical: 'red' }

export function RiskBadge({ risk }: { risk: string | null | undefined }) {
  return <Badge tone={risk ? RISK_TONES[risk] ?? 'gray' : 'gray'}>{risk ?? '—'}</Badge>
}

const TYPE_TONES: Record<string, Tone> = {
  fact: 'blue',
  entity: 'teal',
  person: 'teal',
  organization: 'teal',
  decision: 'purple',
  requirement: 'purple',
  deadline: 'amber',
  metric: 'blue',
  contract_clause: 'purple',
  risk: 'red',
  hypothesis: 'teal',
  experiment: 'teal',
  result: 'green',
  failure: 'red',
  contradiction: 'red',
  dependency: 'amber',
  open_question: 'amber',
  section: 'gray',
}

export function TypeBadge({ type }: { type: string | null | undefined }) {
  return <Badge tone={type ? TYPE_TONES[type] ?? 'gray' : 'gray'}>{type ?? '—'}</Badge>
}

const KIND_TONES: Record<string, Tone> = { company: 'purple', department: 'blue', project: 'teal', agent: 'amber', task: 'gray' }

export function KindBadge({ kind }: { kind: string }) {
  return <Badge tone={KIND_TONES[kind] ?? 'gray'}>{kind}</Badge>
}
