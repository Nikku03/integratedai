import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import AgentsPage from './pages/AgentsPage'
import ApprovalsPage from './pages/ApprovalsPage'
import ConflictsPage from './pages/ConflictsPage'
import DocumentsPage from './pages/DocumentsPage'
import EvidencePage, { EvidenceIndexPage } from './pages/EvidencePage'
import GraphPage from './pages/GraphPage'
import LedgerPage from './pages/LedgerPage'
import MetricsPage from './pages/MetricsPage'
import PerformancePage from './pages/PerformancePage'
import ProjectDetailPage from './pages/ProjectDetailPage'
import ProjectsPage from './pages/ProjectsPage'
import ScopesPage from './pages/ScopesPage'
import SearchPage from './pages/SearchPage'
import SettingsPage from './pages/SettingsPage'
import TasksPage from './pages/TasksPage'
import { ScopeProvider } from './state/scope'
import { SettingsProvider } from './state/settings'
import { ToastProvider } from './state/toast'

function NotFound() {
  return (
    <div className="page">
      <h1>Not found</h1>
      <p className="muted">There is no panel at this address.</p>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <SettingsProvider>
        <ToastProvider>
          <ScopeProvider>
            <Routes>
              <Route element={<Layout />}>
                <Route index element={<Navigate to="/search" replace />} />
                <Route path="/search" element={<SearchPage />} />
                <Route path="/scopes" element={<ScopesPage />} />
                <Route path="/documents" element={<DocumentsPage />} />
                <Route path="/projects" element={<ProjectsPage />} />
                <Route path="/projects/:id" element={<ProjectDetailPage />} />
                <Route path="/agents" element={<AgentsPage />} />
                <Route path="/tasks" element={<TasksPage />} />
                <Route path="/graph" element={<GraphPage />} />
                <Route path="/ledger" element={<LedgerPage />} />
                <Route path="/conflicts" element={<ConflictsPage />} />
                <Route path="/evidence" element={<EvidenceIndexPage />} />
                <Route path="/evidence/:documentId/:pageNo" element={<EvidencePage />} />
                <Route path="/evidence/:documentId" element={<EvidencePage />} />
                <Route path="/performance" element={<PerformancePage />} />
                <Route path="/metrics" element={<MetricsPage />} />
                <Route path="/approvals" element={<ApprovalsPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="*" element={<NotFound />} />
              </Route>
            </Routes>
          </ScopeProvider>
        </ToastProvider>
      </SettingsProvider>
    </BrowserRouter>
  )
}
