import { useMemo } from 'react'
import type { TaskOut } from '../api/types'
import { trunc } from '../lib/format'

const NODE_W = 210
const NODE_H = 58
const GAP_X = 90
const GAP_Y = 22
const PAD = 24

interface Positioned {
  task: TaskOut
  layer: number
  x: number
  y: number
}

interface Edge {
  from: Positioned
  to: Positioned
}

export interface DagLayout {
  nodes: Positioned[]
  edges: Edge[]
  width: number
  height: number
  externalDeps: number
}

/**
 * Layered layout: a task's layer is 1 + the deepest layer among its
 * dependencies (longest path from the sources). Nodes inside a layer are
 * ordered by the barycenter of their predecessors to limit crossings.
 */
export function layoutDag(tasks: TaskOut[]): DagLayout {
  const byId = new Map(tasks.map((t) => [t.id, t]))
  const depth = new Map<string, number>()
  const visiting = new Set<string>()
  let externalDeps = 0

  const d = (id: string): number => {
    const known = depth.get(id)
    if (known !== undefined) return known
    if (visiting.has(id)) return 0 // cycle guard
    visiting.add(id)
    const t = byId.get(id)
    let m = 0
    for (const dep of t?.depends_on ?? []) {
      if (byId.has(dep)) m = Math.max(m, d(dep) + 1)
    }
    visiting.delete(id)
    depth.set(id, m)
    return m
  }
  for (const t of tasks) {
    d(t.id)
    for (const dep of t.depends_on) if (!byId.has(dep)) externalDeps++
  }

  const layers = new Map<number, TaskOut[]>()
  for (const t of tasks) {
    const l = depth.get(t.id) ?? 0
    const arr = layers.get(l) ?? []
    arr.push(t)
    layers.set(l, arr)
  }
  const layerKeys = [...layers.keys()].sort((a, b) => a - b)
  const order = new Map<string, number>()
  const positioned: Positioned[] = []
  for (const l of layerKeys) {
    const items = layers.get(l)!
    if (l > 0) {
      const bary = (t: TaskOut) => {
        const ps = t.depends_on.filter((x) => order.has(x)).map((x) => order.get(x)!)
        return ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length : Number.MAX_SAFE_INTEGER
      }
      items.sort((a, b) => bary(a) - bary(b) || a.priority - b.priority)
    } else {
      items.sort((a, b) => a.priority - b.priority || a.created_at.localeCompare(b.created_at))
    }
    items.forEach((t, i) => {
      order.set(t.id, i)
      positioned.push({ task: t, layer: l, x: PAD + l * (NODE_W + GAP_X), y: PAD + i * (NODE_H + GAP_Y) })
    })
  }
  const posById = new Map(positioned.map((p) => [p.task.id, p]))
  const edges: Edge[] = []
  for (const p of positioned) {
    for (const dep of p.task.depends_on) {
      const from = posById.get(dep)
      if (from) edges.push({ from, to: p })
    }
  }
  const maxRows = Math.max(1, ...layerKeys.map((k) => layers.get(k)!.length))
  const width = PAD * 2 + layerKeys.length * NODE_W + Math.max(0, layerKeys.length - 1) * GAP_X
  const height = PAD * 2 + maxRows * NODE_H + Math.max(0, maxRows - 1) * GAP_Y
  return { nodes: positioned, edges, width, height, externalDeps }
}

export const STATUS_ORDER = ['pending', 'blocked', 'assigned', 'running', 'needs_verification', 'awaiting_approval', 'done', 'verified', 'failed']

interface Props {
  tasks: TaskOut[]
  selectedId?: string | null
  onSelect?: (task: TaskOut) => void
  /** Max height of the scroll viewport in px. */
  maxHeight?: number
}

export function DagSvg({ tasks, selectedId, onSelect, maxHeight = 520 }: Props) {
  const layout = useMemo(() => layoutDag(tasks), [tasks])
  if (!tasks.length) return <div className="empty">No tasks yet — run the project to plan a task graph.</div>
  const { nodes, edges, width, height } = layout
  return (
    <div className="dag-wrap">
      <div className="dag-scroll" style={{ maxHeight }}>
        <svg className="dag" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Task dependency graph">
          <defs>
            <marker id="dag-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" className="dag-arrow" />
            </marker>
          </defs>
          {edges.map((e, i) => {
            const x1 = e.from.x + NODE_W
            const y1 = e.from.y + NODE_H / 2
            const x2 = e.to.x
            const y2 = e.to.y + NODE_H / 2
            const c = GAP_X / 2
            const active = selectedId && (e.from.task.id === selectedId || e.to.task.id === selectedId)
            return (
              <path
                key={i}
                className={`dag-edge ${active ? 'active' : ''}`}
                d={`M ${x1} ${y1} C ${x1 + c} ${y1}, ${x2 - c} ${y2}, ${x2} ${y2}`}
                markerEnd="url(#dag-arrow)"
              />
            )
          })}
          {nodes.map((n) => {
            const t = n.task
            const sel = t.id === selectedId
            return (
              <g
                key={t.id}
                className={`dag-node st-${t.status} ${sel ? 'selected' : ''} ${onSelect ? 'clickable' : ''}`}
                transform={`translate(${n.x}, ${n.y})`}
                onClick={onSelect ? () => onSelect(t) : undefined}
                tabIndex={onSelect ? 0 : undefined}
                onKeyDown={onSelect ? (ev) => (ev.key === 'Enter' || ev.key === ' ') && onSelect(t) : undefined}
              >
                <title>{`${t.title}\n${t.task_type} · ${t.status}${t.assigned_agent ? ` · ${t.assigned_agent}` : ''}`}</title>
                <rect width={NODE_W} height={NODE_H} rx={8} ry={8} />
                <text x={12} y={22} className="dag-title">
                  {trunc(t.title, 28)}
                </text>
                <text x={12} y={42} className="dag-sub">
                  {trunc(`${t.task_type} · ${t.assigned_agent ?? 'unassigned'}`, 30)}
                </text>
                <circle cx={NODE_W - 12} cy={12} r={4} className="dag-dot" />
              </g>
            )
          })}
        </svg>
      </div>
      <div className="dag-legend">
        {STATUS_ORDER.map((s) => (
          <span key={s} className="legend-item">
            <span className={`legend-swatch st-${s}`} /> {s.replace(/_/g, ' ')}
          </span>
        ))}
        {layout.externalDeps > 0 && <span className="muted small">{layout.externalDeps} dependency link(s) point outside this task set</span>}
      </div>
    </div>
  )
}
