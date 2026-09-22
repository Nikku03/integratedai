import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/endpoints'
import { StatusBadge } from '../components/Badge'
import { DagSvg, layoutDag } from '../components/DagSvg'
import { Empty, ErrorBox, Loading, PageHeader, Panel } from '../components/Misc'
import { ProjectPicker, useProjectParam } from '../components/ProjectPicker'
import { TaskDetail } from '../components/TaskDetail'
import { useAsync } from '../hooks/useAsync'
import { useSettings } from '../state/settings'

export default function GraphPage() {
  const { version } = useSettings()
  const [projectId, setProjectId] = useProjectParam()
  const proj = useAsync(() => api.project(projectId!), [projectId, version], Boolean(projectId))
  const [selected, setSelected] = useState<string | null>(null)
  const p = proj.data
  const task = p?.tasks.find((t) => t.id === selected) ?? null
  const layout = p ? layoutDag(p.tasks) : null
  const layers = layout ? new Set(layout.nodes.map((n) => n.layer)).size : 0

  return (
    <div className="page">
      <PageHeader
        title="Dependency graph"
        subtitle="Tasks laid out by dependency depth (left to right). Colour is task status; click a node for details."
        actions={
          <div className="row gap wrap">
            <ProjectPicker value={projectId} onChange={setProjectId} />
            {p && (
              <Link className="btn small" to={`/projects/${p.id}`}>
                open project
              </Link>
            )}
          </div>
        }
      />
      {!projectId && <Empty>Select a project.</Empty>}
      {proj.loading && <Loading />}
      <ErrorBox error={proj.error} />
      {p && (
        <div className="grid-2 wide-left">
          <Panel
            title={
              <span>
                {p.name} <StatusBadge status={p.status} />
              </span>
            }
            actions={
              <span className="muted small">
                {p.tasks.length} tasks · {layers} layer{layers === 1 ? '' : 's'} · {layout?.edges.length ?? 0} edges
              </span>
            }
          >
            <DagSvg tasks={p.tasks} selectedId={selected} onSelect={(t) => setSelected(t.id === selected ? null : t.id)} maxHeight={640} />
          </Panel>
          <Panel title={task ? task.title : 'Task'}>
            {task ? <TaskDetail task={task} /> : <div className="muted small">Click a node to inspect the task, its routing decision and result.</div>}
          </Panel>
        </div>
      )}
    </div>
  )
}
