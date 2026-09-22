import { apiFetch, apiUrl, withKey } from './client'
import type {
  AgentOut, AnswerIn, AnswerOut, ApprovalOut, AuditOut, Decision, DocumentFlags, DocumentOut, ExtractionStatus,
  IngestOut, JobOut, LedgerOut, Me, MessageOut, MetricsSummary, PacketOut, PageOut, ProjectDetail, ProjectIn,
  ProjectSummary, RecordLink, RecordOut, RunIn, RunOut, ScopeOut, ScorecardsOut, SearchIn, TaskOut, UUID,
} from './types'

export const api = {
  // identity / scopes
  me: (silent = false) => apiFetch<Me>('/permissions/me', { silent }),
  scopes: () => apiFetch<ScopeOut[]>('/scopes'),

  // memory search / answers
  search: (body: SearchIn) => apiFetch<PacketOut>('/search', { body }),
  answer: (body: AnswerIn) => apiFetch<AnswerOut>('/answer', { body }),

  // documents / ingestion / jobs
  documents: (q: { scope_id?: UUID | null; status?: string | null; limit?: number } = {}) =>
    apiFetch<DocumentOut[]>('/documents', { query: q }),
  document: (id: UUID) => apiFetch<DocumentOut>(`/documents/${id}`),
  documentVersions: (id: UUID) => apiFetch<DocumentOut[]>(`/documents/${id}/versions`),
  documentExtraction: (id: UUID, silent = false) => apiFetch<ExtractionStatus>(`/documents/${id}/extraction`, { silent }),
  documentFlags: (id: UUID) => apiFetch<DocumentFlags>(`/documents/${id}/flags`),
  ingest: (form: FormData) => apiFetch<IngestOut>('/ingest', { form }),
  jobs: (q: { status?: string | null; limit?: number } = {}) => apiFetch<JobOut[]>('/jobs', { query: q }),
  runJobs: (max_jobs = 10) => apiFetch<JobOut[]>('/jobs/run', { method: 'POST', query: { max_jobs } }),

  // sources / evidence
  page: (documentId: UUID, pageNo: number) => apiFetch<PageOut>(`/sources/${documentId}/pages/${pageNo}`),
  pageImageUrl: (documentId: UUID, pageNo: number, dpi?: number) =>
    withKey(apiUrl(`/sources/${documentId}/pages/${pageNo}/image`, dpi ? { dpi } : undefined)),
  downloadUrl: (documentId: UUID) => withKey(apiUrl(`/sources/${documentId}/download`)),

  // metrics / audit
  metrics: () => apiFetch<MetricsSummary>('/metrics/summary'),
  audit: (q: { resource_id?: string; action?: string; limit?: number } = {}) => apiFetch<AuditOut[]>('/audit', { query: q }),

  // projects / tasks / ledger
  projects: () => apiFetch<ProjectSummary[]>('/projects'),
  project: (id: UUID) => apiFetch<ProjectDetail>(`/projects/${id}`),
  createProject: (body: ProjectIn) => apiFetch<ProjectSummary>('/projects', { body }),
  runProject: (id: UUID, body: RunIn) => apiFetch<RunOut>(`/projects/${id}/run`, { body }),
  ledger: (id: UUID) => apiFetch<LedgerOut>(`/projects/${id}/ledger`),
  tasks: (q: { project_id?: UUID | null; status?: string | null } = {}) => apiFetch<TaskOut[]>('/tasks', { query: q }),
  task: (id: UUID) => apiFetch<TaskOut>(`/tasks/${id}`),
  messages: (project_id: UUID, task_id?: UUID) => apiFetch<MessageOut[]>('/messages', { query: { project_id, task_id } }),

  // agents
  agents: () => apiFetch<AgentOut[]>('/agents'),
  scorecards: (agentId: UUID) => apiFetch<ScorecardsOut>(`/agents/${agentId}/scorecards`),

  // approvals
  approvals: (status: string = 'pending') => apiFetch<ApprovalOut[]>('/approvals', { query: { status } }),
  decide: (id: UUID, body: Decision) => apiFetch<{ id: UUID; status: string }>(`/approvals/${id}/decide`, { body }),

  // memory records
  records: (q: { scope_id?: UUID | null; type?: string; document_id?: UUID; include_history?: boolean; limit?: number } = {}) =>
    apiFetch<RecordOut[]>('/memory/records', { query: q }),
  record: (id: UUID) => apiFetch<RecordOut>(`/memory/records/${id}`),
  recordHistory: (id: UUID) => apiFetch<RecordOut[]>(`/memory/records/${id}/history`),
  recordLinks: (id: UUID) => apiFetch<RecordLink[]>(`/memory/records/${id}/links`),
}
