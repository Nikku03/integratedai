# Scheduling results: results released early, and the schedule order

The pre-registered test run, on worlds 401 to 410. Settings and criteria were fixed beforehand in
`docs/SCHEDULE_PREREGISTRATION.md`, and the full report is in
`docs/benchmarks/schedule/bench_schedule_401-410.md`.

**Setup.**
- FICTIONAL, GENERATED projects: 30 tasks for six specialist roles, one worker per role, and 8 changes after the
  plan is done.
- Durations are simulated over the real workflow engine. This measures the coordination policy, not the quality of
  any agent's work.

## Result: every criterion met

| Criterion | Result |
|---|---|
| 1. every task completed, none on a stale input (all four arms, both phases) | 0 incomplete, 0 stale |
| 2. `outputs-schedule` median makespan below `whole-fifo` | median ratio 0.803 |
| 3. `outputs-schedule` no re-run that was not needed | 0 |

## What releasing results early does

Tasks wait only for the results they need, released as soon as they exist. Compared with waiting for whole tasks
(`outputs-fifo` against `whole-fifo`, same claim order):

| | Whole tasks | Results released early |
|---|---|---|
| Makespan, mean | 55.7 h | 45.2 h (median ratio 0.81; shorter on all 10 worlds) |
| Worker utilisation | 0.40 | 0.49 |
| Mean task start | 22.1 h | 17.1 h |
| Re-runs after 80 changes | 653 (419 not needed) | 237 (0 not needed) |
| Rework after changes | 2,912 h | 1,062 h |
| Time until every answer is current again | 1,871 h | 699 h |

The re-run savings come from two rules:
- a task is disturbed only when a result it actually needs changes value;
- re-releasing an unchanged result disturbs nobody.

With whole-task dependencies, every dependant of a reopened task is redone. 419 of those 653 re-runs changed
nothing.

## What the schedule order does

The schedule order takes work by priority, then deadline slack, then the longest chain of work behind it, then
how many tasks it unblocks.

| | Priority, then age | Schedule order |
|---|---|---|
| Deadline misses (48 deadlines), results released early | 6 | 2 |
| Lateness, total, results released early | 17.7 h | 9.6 h |
| Median makespan ratio against priority-then-age, results released early | 1.0 | 1.0 (4 worlds shorter, 4 longer, 2 equal) |
| Median makespan ratio against priority-then-age, whole tasks | 1.0 | 1.01 (5 shorter, 5 longer) |

It is a deadline tool, not a speed tool. It moves work that has a deadline downstream forward, which halves the
misses. It does not shorten the whole project, because with one worker per role the order within a role changes
little of the total.

As fixed in advance, it stays the default claim order: it missed fewer deadlines, and its median makespan was no
longer. `order="fifo"` remains available.

## What this does not show

- **Real agents.** Durations and results are simulated; real work may not split into early results this neatly.
- **Estimates.** The schedule's gains depend on them; here they are within -20% to +25% of the true durations.
- **More workers.** With more than one worker per role, waiting falls in every arm, and the differences may shrink
  or grow.
