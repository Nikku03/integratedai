"""Scheduling benchmark: specialists hand over results as soon as they have them, and work that unblocks the most
runs first.

A simulation over the real workflow engine. The projects are FICTIONAL, GENERATED: tasks for six specialist
roles, one worker per role. Each task takes a simulated time and releases its named results at points during it;
a task needs specific results of earlier tasks. The engine decides what is ready, what each worker claims next and
what must be redone; only the clock and the work are simulated, so this measures the coordination policy, not the
quality of any agent's work.

Arms (dependencies x claim order):

* ``whole-fifo``: a task waits for the whole tasks it needs; workers take ready work by priority, then age.
* ``whole-schedule``: whole tasks; the schedule order (priority, deadline slack, longest chain of work behind a
  task, tasks it unblocks).
* ``outputs-fifo``: a task waits only for the named results it needs, released early; priority, then age.
* ``outputs-schedule``: named results released early, and the schedule order.

Phase 1 works the plan from start to finish: makespan, worker utilisation, deadline misses and lateness, and when
tasks could start. Phase 2 sends changes one at a time after the plan is done. Each reopens a task, and each of
its results changes or stays the same, as drawn. A task that re-runs because a result it needs changed may change
its own results in turn (each with probability 0.5, drawn per change, task and result, so the same in every arm).
Measured: re-runs, re-runs that were not needed (no result the task needs had changed), rework hours and the time
until every answer is current again. Correctness in every arm: every task completed, and no completed task rests
on a stale input.
"""

from __future__ import annotations

import argparse
import heapq
import json
import random
import statistics
import time
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

ROLES = ("procurement", "logistics", "finance", "legal", "operations", "engineering")
ARMS = ("whole-fifo", "whole-schedule", "outputs-fifo", "outputs-schedule")
DONE = {"findings": [{"claim": "simulated work done", "citations": [{"item_id": "simulation"}]}], "summary": "done"}


@dataclass
class SimTask:
    i: int
    role: str
    hours: float
    estimate: float  # what the planner believes (hours): the true duration within -20% .. +25%
    outputs: list[tuple[str, float]]  # (key, fraction of the work after which it is released)
    needs: list[tuple[int, str]]  # (earlier task, the result of it needed)
    deadline: float | None = None  # hours after the start
    priority: int = 5

    @property
    def title(self) -> str:
        return f"{self.role} task {self.i}"


@dataclass
class World:
    seed: int
    tasks: list[SimTask]
    changes: list[tuple[int, list[str]]] = field(default_factory=list)  # (task reopened, results whose value changes)


def generate(seed: int, n_tasks: int = 30, n_changes: int = 8) -> World:
    """A project DAG: each task needs 0 to 3 results of the (up to 10) tasks planned just before it, so work forms
    chains across roles. Half the tasks nobody waits on carry a deadline between 1.2 and 2 times their earliest
    finish with unlimited workers."""
    rng = random.Random(seed)
    tasks: list[SimTask] = []
    for i in range(n_tasks):
        hours = round(rng.uniform(1.0, 8.0), 2)
        k = rng.choice([1, 2, 2, 3])
        fracs = sorted(round(rng.uniform(0.15, 0.95), 2) for _ in range(k))
        outs = [(f"result{m + 1}", f) for m, f in enumerate(fracs)]
        needs: list[tuple[int, str]] = []
        if i:
            for p in rng.sample(range(max(0, i - 10), i), min(i, rng.choice([0, 1, 1, 2, 2, 3]))):
                needs.append((p, rng.choice(tasks[p].outputs)[0]))
        tasks.append(SimTask(i, rng.choice(ROLES), hours, round(hours * rng.uniform(0.8, 1.25), 2), outs, needs,
                             priority=3 if rng.random() < 0.1 else 5))
    ef: dict[int, float] = {}
    for t in tasks:
        ef[t.i] = max((ef[p] for p, _ in t.needs), default=0.0) + t.hours
    waited_on = {p for t in tasks for p, _ in t.needs}
    for t in tasks:
        if t.i not in waited_on and rng.random() < 0.5:
            t.deadline = round(ef[t.i] * rng.uniform(1.2, 2.0), 2)
    producers = sorted(waited_on)
    changes = []
    for _ in range(n_changes):
        p = rng.choice(producers)
        changes.append((p, [k for k, _ in tasks[p].outputs if rng.random() < 0.5]))
    return World(seed, tasks, changes)


class Sim:
    """One world in one arm: the real engine, a simulated clock (hours) and one worker per role."""

    def __init__(self, session, world: World, arm: str, tag: str):
        from cie.agents.head import create_project
        from cie.core.models import ScopeKind, Tenant
        from cie.memory.scopes import create_scope
        from cie.workflow import engine

        self.s, self.w, self.arm = session, world, arm
        self.by_output, self.order = arm.startswith("outputs"), "schedule" if arm.endswith("schedule") else "fifo"
        self.tenant = Tenant(name=f"sched-{tag}-{uuid.uuid4().hex[:6]}")
        session.add(self.tenant)
        session.flush()
        root = create_scope(session, self.tenant.id, ScopeKind.company, f"Synthetic Co [{tag}]")
        self.project = create_project(session, tenant_id=self.tenant.id, parent_scope=root, name=f"Delivery plan [{tag}]")
        self.t0 = engine.now()
        self.ids: dict[int, uuid.UUID] = {}
        for t in world.tasks:
            wants: dict[int, set[str]] = {}
            for p, k in t.needs:
                wants.setdefault(p, set()).add(k)
            deps = [(self.ids[p], "requires", sorted(ks) if self.by_output else []) for p, ks in wants.items()]
            task = engine.propose(session, tenant_id=self.tenant.id, project_id=self.project.id, scope_id=self.project.scope_id,
                                  task_type=t.role, title=t.title, priority=t.priority, acceptance={"outputs": [k for k, _ in t.outputs]},
                                  deadline_at=self.t0 + timedelta(hours=t.deadline) if t.deadline is not None else None,
                                  metrics={"estimate_seconds": t.estimate * 3600}, depends_on=deps, actor="sim")
            engine.accept(session, task, actor="sim")
            self.ids[t.i] = task.id
        self.idx = {v: k for k, v in self.ids.items()}
        self.clock = 0.0
        self.heap: list[tuple[float, int, str, int, str, int]] = []
        self.n = 0
        self.busy: dict[str, int | None] = dict.fromkeys(ROLES)
        self.run_id = dict.fromkeys(self.ids, 0)
        self.value = {(t.i, k): 0 for t in world.tasks for k, _ in t.outputs}  # the value's revision number
        self.reads: dict[int, dict] = {}
        self.first_start: dict[int, float] = {}
        self.finish: dict[int, float] = {}
        self.busy_hours = 0.0
        self.phase = 1
        self.c = dict.fromkeys(("reruns", "reruns_unneeded", "rework_hours", "redo_on_stale", "claims"), 0)
        session.commit()

    # ------------------------------------------------------------------------------------------ work
    def _push(self, at: float, kind: str, i: int, key: str = "") -> None:
        self.n += 1
        heapq.heappush(self.heap, (at, self.n, kind, i, key, self.run_id[i]))

    def _read(self, i: int) -> dict:
        """The results the task needs, as it reads them now. They are recorded as its inputs: the released results
        (output dependencies) or the whole tasks it waited for (whole-task dependencies)."""
        from cie.core.models import Task
        from cie.workflow import engine
        from cie.workflow.models import TaskOutput

        t = self.s.get(Task, self.ids[i])
        if self.by_output:
            engine.upstream(self.s, t)
        else:
            engine.record_inputs(self.s, t, tasks=[d.task for d in engine.dependencies(self.s, [t.id])[t.id]])
        need = {(self.ids[p], k) for p, k in self.w.tasks[i].needs}
        return {(str(o.task_id), o.key): o.value for o in self.s.query(TaskOutput).filter(TaskOutput.task_id.in_([p for p, _ in need]))
                if (o.task_id, o.key) in need}

    def _begin(self, i: int, role: str) -> None:
        t = self.w.tasks[i]
        self.run_id[i] += 1
        reads = self._read(i)
        if i in self.reads and self.phase == 2:
            self.c["reruns"] += 1
            self.c["rework_hours"] += t.hours
            if i != self._changed and reads == self.reads[i]:
                self.c["reruns_unneeded"] += 1
            elif i != self._changed and i not in self._bumped:  # a result it needs changed: its own results may change
                self._bumped.add(i)
                for k, _ in t.outputs:
                    if random.Random(f"{self.w.seed}:{self._round}:{i}:{k}").random() < 0.5:
                        self.value[(i, k)] += 1
        self.reads[i] = reads
        self.first_start.setdefault(i, self.clock)
        for k, f in t.outputs:
            self._push(self.clock + f * t.hours, "release", i, k)
        self._push(self.clock + t.hours, "finish", i)
        self.busy[role] = i
        self.busy_hours += t.hours

    def _claim(self) -> None:
        from cie.workflow import engine

        for role in ROLES:
            if self.busy[role] is not None:
                continue
            t = engine.claim(self.s, self.tenant.id, worker=f"{role}-worker", task_types=[role], project_id=self.project.id,
                             order=self.order, at=self.t0 + timedelta(hours=self.clock), lease_seconds=10**7)
            if t is not None:
                self.c["claims"] += 1
                self._begin(self.idx[t.id], role)

    def _event(self, kind: str, i: int, key: str) -> None:
        from cie.core.models import TaskStatus
        from cie.workflow import engine

        t, role = self.w.tasks[i], self.w.tasks[i].role
        if kind == "release":
            engine.publish_output(self.s, self.ids[i], worker=f"{role}-worker", key=key, value=f"{t.title} {key} v{self.value[(i, key)]}")
            return
        outs = {k: f"{t.title} {k} v{self.value[(i, k)]}" for k, _ in t.outputs}
        task = engine.submit(self.s, self.ids[i], worker=f"{role}-worker", result={**DONE, "outputs": outs})
        if task.status == TaskStatus.running:  # an input changed while it worked: it redoes the work on the new value
            self.c["redo_on_stale"] += 1
            self.busy_hours -= t.hours  # _begin counts it again
            self._begin(i, role)
            return
        self.busy[role] = None
        self.finish[i] = self.clock

    def run(self) -> None:
        """Until nothing is left to do: fill idle workers, then take the next event."""
        while True:
            self._claim()
            if not self.heap:
                break
            at, _, kind, i, key, rid = heapq.heappop(self.heap)
            if rid != self.run_id[i]:
                continue  # an event of a run that was replaced
            self.clock = max(self.clock, at)
            self._event(kind, i, key)
        self.s.commit()

    # ------------------------------------------------------------------------------------------ phases
    def phase1(self) -> dict[str, Any]:
        self._changed, self._round, self._bumped = -1, -1, set()
        self.run()
        makespan = self.clock
        dl = [t for t in self.w.tasks if t.deadline is not None]
        late = [max(0.0, self.finish.get(t.i, float("inf")) - t.deadline) for t in dl]
        used = [r for r in ROLES if any(t.role == r for t in self.w.tasks)]
        return {"makespan_h": round(makespan, 2), "utilisation": round(self.busy_hours / (len(used) * makespan), 3) if makespan else None,
                "deadlines": len(dl), "deadline_misses": sum(1 for x in late if x > 1e-9), "lateness_h": round(sum(late), 2),
                "mean_start_h": round(statistics.mean(self.first_start.values()), 2), **self.check()}

    def phase2(self) -> dict[str, Any]:
        from cie.workflow import engine

        self.phase = 2
        refresh = []
        for n, (i, keys) in enumerate(self.w.changes):
            self._changed, self._round, self._bumped = i, n, set()
            t0 = self.clock
            engine.reopen(self.s, self.ids[i], actor="sim", reason="an input of this task changed")
            for k in keys:
                self.value[(i, k)] += 1
            self.run()
            refresh.append(self.clock - t0)
        return {"changes": len(self.w.changes), "reruns": self.c["reruns"], "reruns_unneeded": self.c["reruns_unneeded"],
                "rework_hours": round(self.c["rework_hours"], 2), "refresh_h_total": round(sum(refresh), 2),
                "refresh_h_mean": round(statistics.mean(refresh), 2) if refresh else None, "redo_on_stale": self.c["redo_on_stale"],
                **self.check()}

    def check(self) -> dict[str, int]:
        from cie.core.models import Task, TaskStatus
        from cie.workflow import engine

        ts = [self.s.get(Task, x) for x in self.ids.values()]
        return {"incomplete": sum(t.status != TaskStatus.completed for t in ts),
                "stale_inputs": sum(bool(engine.stale_inputs(self.s, t)) for t in ts if t.status == TaskStatus.completed)}


def run_world(factory, seed: int, arm: str, n_tasks: int, n_changes: int, run: str = "") -> dict[str, Any]:
    w = generate(seed, n_tasks, n_changes)
    with factory() as s:
        sim = Sim(s, w, arm, f"s{seed}{arm[:1]}{arm.split('-')[1][:1]}{run}")
        t0 = time.perf_counter()
        p1 = sim.phase1()
        p2 = sim.phase2()
        s.commit()
        return {"world": seed, "arm": arm, "tasks": n_tasks, "phase1": p1, "phase2": p2, "claims": sim.c["claims"],
                "wall_s": round(time.perf_counter() - t0, 2)}


def aggregate(rows: list[dict[str, Any]], base: dict[int, dict[str, Any]] | None, fifo: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    """``base``: whole-fifo rows by world; ``fifo``: for a schedule arm, the fifo arm with the same dependencies."""
    def tot(ph: str, k: str) -> float:
        return sum(r[ph][k] or 0 for r in rows)

    def ratios(b):
        return [r["phase1"]["makespan_h"] / b[r["world"]]["phase1"]["makespan_h"] for r in rows if b and r["world"] in b]

    ratio, same = ratios(base), ratios(fifo)
    return {"worlds": len(rows),
            "makespan_h_mean": round(statistics.mean(r["phase1"]["makespan_h"] for r in rows), 2),
            "makespan_vs_whole_fifo_median": round(statistics.median(ratio), 3) if ratio else None,
            "makespan_vs_fifo_same_dependencies_median": round(statistics.median(same), 3) if same else None,
            "makespan_shorter_worlds": sum(1 for x in ratio if x < 1 - 1e-9), "makespan_longer_worlds": sum(1 for x in ratio if x > 1 + 1e-9),
            "utilisation_mean": round(statistics.mean(r["phase1"]["utilisation"] for r in rows), 3),
            "mean_start_h": round(statistics.mean(r["phase1"]["mean_start_h"] for r in rows), 2),
            "deadlines": int(tot("phase1", "deadlines")), "deadline_misses": int(tot("phase1", "deadline_misses")),
            "lateness_h": round(tot("phase1", "lateness_h"), 2),
            "changes": int(tot("phase2", "changes")), "reruns": int(tot("phase2", "reruns")), "reruns_unneeded": int(tot("phase2", "reruns_unneeded")),
            "rework_hours": round(tot("phase2", "rework_hours"), 2), "refresh_h_total": round(tot("phase2", "refresh_h_total"), 2),
            "incomplete": int(tot("phase1", "incomplete") + tot("phase2", "incomplete")),
            "stale_inputs": int(tot("phase1", "stale_inputs") + tot("phase2", "stale_inputs"))}


def verdict(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The criteria fixed in docs/SCHEDULE_PREREGISTRATION.md."""
    arms = report["arms"]
    out = [{"criterion": f"1. {a}: every task completed and none on a stale input", "met": v["incomplete"] == 0 and v["stale_inputs"] == 0,
            "value": f"incomplete {v['incomplete']}, stale {v['stale_inputs']}"} for a, v in arms.items()]
    if "outputs-schedule" in arms and "whole-fifo" in arms:
        v = arms["outputs-schedule"]
        out.append({"criterion": "2. outputs-schedule: median makespan below whole-fifo", "met": (v["makespan_vs_whole_fifo_median"] or 1) < 1,
                    "value": v["makespan_vs_whole_fifo_median"]})
    if "outputs-schedule" in arms:
        v = arms["outputs-schedule"]
        out.append({"criterion": "3. outputs-schedule: no re-run that was not needed", "met": v["reruns_unneeded"] == 0, "value": v["reruns_unneeded"]})
    return out


def markdown(report: dict[str, Any]) -> str:
    arms = report["arms"]
    names = list(arms)

    def row(label: str, f) -> str:
        return f"| {label} | " + " | ".join(str(f(arms[a])) for a in names) + " |"

    lines = [f"# Scheduling benchmark ({report['worlds']} worlds, {report['tasks']} tasks each, {report['changes']} changes each)", "",
             "FICTIONAL, GENERATED projects; simulated durations over the real workflow engine; one worker per role.", "",
             "| Measure | " + " | ".join(names) + " |", "|---|" + "---|" * len(names),
             row("Makespan, mean (h)", lambda a: a["makespan_h_mean"]),
             row("Makespan vs whole-fifo, median ratio", lambda a: a["makespan_vs_whole_fifo_median"]),
             row("Worlds shorter / longer than whole-fifo", lambda a: f"{a['makespan_shorter_worlds']} / {a['makespan_longer_worlds']}"),
             row("Schedule order vs fifo with the same dependencies, median ratio", lambda a: a["makespan_vs_fifo_same_dependencies_median"]),
             row("Worker utilisation, mean", lambda a: a["utilisation_mean"]),
             row("Mean task start (h after the start)", lambda a: a["mean_start_h"]),
             row("Deadline misses / deadlines", lambda a: f"{a['deadline_misses']} / {a['deadlines']}"),
             row("Lateness, total (h)", lambda a: a["lateness_h"]),
             row("Changes: re-runs / not needed", lambda a: f"{a['reruns']} / {a['reruns_unneeded']}"),
             row("Changes: rework (h)", lambda a: a["rework_hours"]),
             row("Changes: time until every answer is current, total (h)", lambda a: a["refresh_h_total"]),
             row("Incomplete tasks / completed on a stale input", lambda a: f"{a['incomplete']} / {a['stale_inputs']}"),
             "", "Makespan per world (h):", "", "| World | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for i, seed in enumerate(report["seeds"]):
        lines.append(f"| {seed} | " + " | ".join(str(report["per_world"][a][i]["phase1"]["makespan_h"]) for a in names) + " |")
    if "outputs-schedule" in arms and "outputs-fifo" in arms:
        sch, fifo = arms["outputs-schedule"], arms["outputs-fifo"]
        keep = sch["deadline_misses"] <= fifo["deadline_misses"] and (sch["makespan_vs_fifo_same_dependencies_median"] or 1) <= 1
        lines += ["", f"**Decision fixed in advance: the schedule order {'stays' if keep else 'does not stay'} the default claim order** "
                  f"(with results released early: deadline misses {sch['deadline_misses']} vs {fifo['deadline_misses']} for fifo; "
                  f"median makespan ratio {sch['makespan_vs_fifo_same_dependencies_median']})."]
    v = report.get("verdict") or []
    if v:
        lines += ["", "## Pre-registered criteria (docs/SCHEDULE_PREREGISTRATION.md)", "",
                  f"**{'All criteria met' if all(x['met'] for x in v) else 'Not all criteria met'}.**", "",
                  "| Criterion | Met | Value |", "|---|---|---|"] + [f"| {x['criterion']} | {'yes' if x['met'] else '**no**'} | {x['value']} |" for x in v]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> dict[str, Any]:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--tasks", type=int, default=30)
    ap.add_argument("--changes", type=int, default=8)
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--out", default="eval_out/schedule")
    a = ap.parse_args(argv)
    from cie.core.db import session_factory

    factory = session_factory()
    seeds = [int(x) for x in a.seeds.split(",") if x.strip()]
    arms = [x.strip() for x in a.arms.split(",") if x.strip()]
    unknown = set(arms) - set(ARMS)
    if unknown:
        raise SystemExit(f"unknown arm(s) {sorted(unknown)}; choose from {', '.join(ARMS)}")
    run = uuid.uuid4().hex[:4]
    rows: dict[str, list[dict[str, Any]]] = {arm: [] for arm in arms}
    t0 = time.time()
    for seed in seeds:
        for arm in arms:
            rows[arm].append(run_world(factory, seed, arm, a.tasks, a.changes, run))
            r = rows[arm][-1]
            print(json.dumps({"world": seed, "arm": arm, **r["phase1"], **{f"p2_{k}": v for k, v in r["phase2"].items()}}), flush=True)
    base = {r["world"]: r for r in rows.get("whole-fifo", [])}

    def fifo_of(arm: str) -> dict[int, dict[str, Any]] | None:
        f = arm.replace("-schedule", "-fifo")
        return {r["world"]: r for r in rows[f]} if arm.endswith("schedule") and f in rows else None

    report = {"worlds": len(seeds), "seeds": seeds, "tasks": a.tasks, "changes": a.changes, "wall_s": round(time.time() - t0, 1),
              "arms": {arm: aggregate(r, base, fifo_of(arm)) for arm, r in rows.items()}, "per_world": rows}
    report["verdict"] = verdict(report)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "bench_schedule.json").write_text(json.dumps(report, indent=2, default=str))
    (out / "bench_schedule.md").write_text(markdown(report))
    print(markdown(report))
    return report


if __name__ == "__main__":
    main()
