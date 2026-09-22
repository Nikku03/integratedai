// Typed shapes for the CIE API (see docs/openapi.json plus the route
// serializers for endpoints the spec leaves as untyped objects).

export type UUID = string

export type ScopeKind = 'company' | 'department' | 'project' | 'agent' | 'task'

export interface ScopeOut {
  id: UUID
  kind: ScopeKind | string
  name: string
  parent_id: UUID | null
  path: string
}

export interface Me {
  principal: { id: UUID; name: string; kind: string }
  is_admin: boolean
  scopes: Record<string, { clearance: number; level: number }>
}

/** A pointer into a source document: page + bbox in PDF points. */
export interface Citation {
  document_id?: UUID | null
  page_no?: number | null
  bbox?: number[] | null
  quote?: string | null
  block_id?: string | null
  section_id?: string | null
}

export interface Glyph {
  v?: number
  id?: string
  type?: string
  what?: string
  who?: string[]
  why?: string | null
  project?: string | null
  department?: string | null
  time?: Record<string, unknown>
  status?: string
  dependencies?: string[]
  consequences?: string[]
  contradictions?: string[]
  confidence?: number
  verification?: string
  evidence?: Citation[]
  keywords?: string[]
}

export interface SearchIn {
  query: string
  scope_id: UUID
  filters?: Record<string, unknown>
  k?: number
  as_of?: string | null
  use_graph?: boolean
  use_vector?: boolean
  use_lexical?: boolean
  max_records?: number | null
  token_budget?: number | null
}

export interface SearchItem {
  id: UUID
  kind: 'record' | 'section'
  type: string
  summary: string
  detail: string
  content?: Record<string, unknown>
  document_id: UUID | null
  citations: Citation[]
  confidence?: number
  verification?: string
  superseded?: boolean
  superseded_by?: UUID | null
  valid_from?: string | null
  valid_to?: string | null
  recorded_at?: string | null
  conflicts_with?: UUID[]
  score: number | null
  support: number | null
  reasons?: Record<string, unknown>
  horizon?: number
  via?: string | null
  glyph?: Glyph | null
  scope_id?: UUID
  page_start?: number
  page_end?: number
}

export interface PacketOut {
  id: UUID
  query: string
  intent: string
  items: SearchItem[]
  token_estimate: number
  latency_ms: number
  trace: Record<string, unknown>
}

export type AnswerMode = 'strict' | 'assisted'
export type AnswerStatus = 'answered' | 'insufficient_evidence' | 'conflict'

export interface AnswerIn extends SearchIn {
  mode: AnswerMode
}

export interface AnswerCitation extends Citation {
  n: number
  item_id: UUID
  kind?: string
  type?: string | null
  summary?: string | null
}

export interface AnswerOut {
  id: UUID
  packet_id: UUID
  question: string
  answer: string
  status: AnswerStatus | string
  citations: AnswerCitation[]
  confidence: number
  mode: string
  model: string | null
  tokens_in: number
  tokens_out: number
  latency_ms: number
  cost_usd: number
  usage_is_estimate: boolean
  unsupported_claims: string[]
}

export interface DocumentOut {
  id: UUID
  family_id: UUID
  version: number
  title: string
  original_filename: string
  original_location: string | null
  source: string
  scope_id: UUID
  department_id: UUID | null
  project_id: UUID | null
  doc_type: string | null
  language: string | null
  sensitivity: number
  status: string
  sha256: string
  size_bytes: number
  media_type: string
  ingested_at: string
  file_created_at: string | null
  retention_policy: string
  legal_hold: boolean
  injection_flags: number
  pii_flags: number
}

export interface IngestOut {
  document: DocumentOut
  created: boolean
  deduplicated: boolean
  job_id: UUID | null
}

export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

export interface JobOut {
  id: UUID
  kind: string
  status: JobStatus | string
  progress: number
  attempts: number
  checkpoint: Record<string, unknown>
  last_error: string | null
  created_at: string
  updated_at: string
}

export interface ExtractionInfo {
  id: UUID
  extractor: string
  status: string
  page_count: number | null
  pages_done: number | null
  language: string | null
  mean_confidence: number | null
  completeness: number | null
  stats: Record<string, unknown>
}

export interface ExtractionStatus {
  document_id: UUID
  status: string
  extraction: ExtractionInfo | null
  job: JobOut | null
}

export interface DocumentFlags {
  injection: number
  pii_and_secrets: number
}

export interface PageBlock {
  id: string
  kind: string
  bbox: number[]
  text: string
  content?: unknown
  confidence?: number | null
}

export interface PageCorrection {
  block_id: string
  original: string
  corrected: string
  method: string
  confidence: number | null
}

export interface PageOut {
  document_id: UUID
  page_no: number
  width: number
  height: number
  method: string
  confidence: number | null
  text: string
  blocks: PageBlock[]
  corrections: PageCorrection[]
}

export interface MetricStat {
  n: number
  avg: number
  p95: number
  sum: number
}

export interface MetricsSummary {
  metrics: Record<string, MetricStat>
  storage: { blobs: number; raw_bytes: number }
  counts: { documents: number; sections: number; records: number; jobs: Record<string, number> | number }
}

export type TaskStatus =
  | 'pending'
  | 'blocked'
  | 'assigned'
  | 'running'
  | 'needs_verification'
  | 'verified'
  | 'done'
  | 'failed'
  | 'awaiting_approval'

export interface RoutingCandidate {
  agent: string
  score: number
  eligible: boolean
  excluded: string | null
  scorecard?: number
  scorecard_low_support?: boolean
  scorecard_n?: number
  skill_overlap?: number
  cost_factor?: number
  running?: number
  [k: string]: unknown
}

export interface AssignmentReason {
  task_type?: string
  decision?: string
  chosen?: string | null
  candidates?: RoutingCandidate[]
  [k: string]: unknown
}

export interface Finding {
  claim: string
  kind: string
  value: unknown
  confidence: number
  citations: Citation[]
}

export interface TaskResult {
  summary?: string
  strategy?: string
  model?: string | null
  findings?: Finding[]
  open_questions?: string[]
  evidence_requests?: string[]
  unsupported_claims?: string[]
  metrics?: Record<string, number>
  [k: string]: unknown
}

export interface TaskOut {
  id: UUID
  project_id: UUID
  task_type: string
  title: string
  brief: string
  status: TaskStatus | string
  priority: number
  risk_level: string
  assigned_agent: string | null
  assignment_reason: AssignmentReason | null
  evidence_packet_id: UUID | null
  result: TaskResult | null
  verification: Record<string, unknown> | null
  verifies_task_id: UUID | null
  metrics: Record<string, unknown> | null
  depends_on: UUID[]
  created_at: string
  updated_at: string
}

export type LedgerContent = Record<string, unknown> & {
  seq?: number
  label?: string | null
  at?: string
  actor?: string | null
  refs?: Record<string, unknown>
}

export interface HypothesisState extends LedgerContent {
  tests: LedgerContent[]
  results: LedgerContent[]
}

export interface LedgerState {
  objectives: LedgerContent[]
  requirements: LedgerContent[]
  plans: LedgerContent[]
  tasks: Record<string, LedgerContent>
  assignments: Record<string, LedgerContent>
  hypotheses: Record<string, HypothesisState>
  tests: LedgerContent[]
  results: LedgerContent[]
  failures: LedgerContent[]
  decisions: LedgerContent[]
  artifacts: LedgerContent[]
  commits: LedgerContent[]
  blockers: LedgerContent[]
  next_actions: LedgerContent[]
  contradictions: LedgerContent[]
  verifications: LedgerContent[]
  synthesis: LedgerContent | null
  entries: number
  head_hash: string | null
  open_blockers: LedgerContent[]
}

export interface ProjectSummary {
  id: UUID
  scope_id: UUID
  name: string
  objective: string
  status: string
  head_agent_id?: UUID | null
  token_budget?: number | null
}

export interface ProjectDetail extends ProjectSummary {
  tasks: TaskOut[]
  ledger: LedgerState
}

export interface ProjectIn {
  name: string
  parent_scope_id: UUID
  objective?: string
}

export interface RunIn {
  objective: string
  max_steps?: number
  background?: boolean
}

export interface RunOut {
  project_id?: UUID
  status: string
  ledger?: LedgerState
  job_id?: UUID
}

export interface LedgerEntry {
  seq: number
  kind: string
  label: string | null
  content: Record<string, unknown>
  refs: Record<string, unknown>
  actor: string | null
  hash: string
  prev_hash: string | null
  created_at: string
}

export interface LedgerOut {
  chain_valid: boolean
  first_bad_seq: number | null
  state: LedgerState
  entries: LedgerEntry[]
}

export const LEDGER_KINDS = [
  'objective', 'requirement', 'plan', 'task', 'assignment', 'hypothesis', 'test', 'result', 'failure', 'decision',
  'artifact', 'commit', 'blocker', 'next_action', 'contradiction', 'verification', 'synthesis', 'message',
] as const

export interface AgentOut {
  id: UUID
  name: string
  role: string
  skills: string[]
  task_types: string[]
  strategy: string
  model: string | null
  cost_per_1k_tokens: number
  max_concurrency: number
  active: boolean
  principal_id: UUID
  memory_scope_id: UUID | null
  busy: boolean
}

export interface Scorecard {
  task_type: string
  n_tasks: number
  accuracy: number
  citation_quality: number
  completion_rate: number
  latency_ms_avg: number
  tokens_avg: number
  compute_cost_avg: number
  human_corrections: number
  hallucination_rate: number
  verification_score: number
  last_task_at: string | null
  routing_score: number
  low_support: boolean
  components: Record<string, number>
}

export interface ScorecardsOut {
  agent: string
  scorecards: Scorecard[]
}

export interface MessageOut {
  id: UUID
  kind: string
  task_id: UUID | null
  from: string | null
  to: string | null
  payload: Record<string, unknown>
  token_estimate: number
  created_at: string
}

export interface ApprovalOut {
  id: UUID
  kind: string
  subject_id: string
  status: string
  summary: string
  requested_by: string | null
  created_at: string
  decided_at: string | null
  reason: string | null
}

export interface Decision {
  approve: boolean
  reason?: string | null
}

export interface RecordOut {
  id: UUID
  scope_id: UUID
  type: string
  summary: string
  content: Record<string, unknown>
  detail: string
  source_document_id: UUID | null
  source_locations: Citation[]
  event_time: string | null
  valid_from: string | null
  valid_to: string | null
  recorded_at: string
  producing_agent: string | null
  confidence: number
  verification: string
  sensitivity: number
  version: number
  family_id: UUID
  superseded_by_id: UUID | null
  supersedes_id: UUID | null
  keywords: string[]
  glyph: Glyph
}

export interface RecordLink {
  id: UUID
  src_id: UUID
  dst_id: UUID
  kind: string
  weight: number
  justification: string | null
}

export interface AuditOut {
  id: number
  principal_id: UUID | null
  action: string
  resource_kind: string | null
  resource_id: string | null
  details: Record<string, unknown>
  outcome: string
  created_at: string
}
