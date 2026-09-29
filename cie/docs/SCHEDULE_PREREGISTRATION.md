# Scheduling: what is measured and what counts as shown, fixed before the test run

I wrote this before running any test world. Development runs used worlds 1, 2 and 3 only. The test worlds are
run once with these settings.

## Question

Can specialists finish a project sooner, and redo less when things change, if:

1. each task hands over its named results as soon as it has them, and a task waits only for the results it needs
   (instead of whole tasks)? and
2. workers take next the work that meets deadlines and unblocks the most (instead of priority, then age)?

## Setup (`cie.eval.bench_schedule`)

**Engine and clock.** The workflow engine is real: dependencies, releases, claims, reopenings, stale-input checks
and the schedule order. Only the clock and the work are simulated. This measures the coordination policy, not the
quality of any agent's work.

**Data.** FICTIONAL, GENERATED projects:
- 30 tasks for six specialist roles, one worker per role.
- Each task takes 1 to 8 simulated hours. The planner's estimate is off by -20% to +25%.
- Each task releases 1 to 3 named results, at 15% to 95% of its work.
- A task needs 0 to 3 results of the up to 10 tasks planned just before it.
- Half the tasks that nothing waits on carry a deadline of 1.2 to 2 times their earliest possible finish.
- About 10% of tasks have a higher priority.

**Phase 1** works the plan from start to finish.

**Phase 2** sends 8 changes, one at a time, after the plan is done:
- Each change reopens a task that others depend on. Each of its results changes or stays the same, as drawn.
- A task that re-runs because a result it needs changed may change its own results in turn. Each result changes
  with probability 0.5, drawn per change, task and result, so the draw is the same in every arm.

## Arms

| Arm | Dependencies | Claim order |
|---|---|---|
| `whole-fifo` | whole tasks | priority, then age (the engine's order before this change) |
| `whole-schedule` | whole tasks | schedule: priority, deadline slack, longest chain of work behind the task, tasks unblocked |
| `outputs-fifo` | named results, released early | priority, then age |
| `outputs-schedule` | named results, released early | schedule |

## Test worlds

Seeds 401 to 410, with `--tasks 30 --changes 8`.

## Criteria

1. **Correctness, every arm**: every task completed, and no completed task rests on a stale input, after both
   phases.
2. **Faster**: `outputs-schedule` has a median makespan (phase 1) below `whole-fifo`'s, over the ten worlds.
3. **No wasted re-runs**: `outputs-schedule` never re-runs a task when no result it needs has changed (phase 2).

**Reported with no threshold:**
- makespan per world;
- worker utilisation;
- mean start time;
- deadline misses and lateness;
- re-runs, rework hours, and the time until every answer is current again;
- the schedule order against fifo with the same dependencies.

## Decisions fixed in advance

- **Criteria 1 to 3 are met.** The LLM planner keeps asking for dependencies on named results (it does now), and
  the docs recommend them for hand-offs between specialists.
- **Criterion 1 fails in any arm.** That is a defect in the engine. Nothing is recommended until it is fixed and
  the test is run on new worlds.
- **The schedule order stays the default claim order** if, with results released early, it misses no more
  deadlines than fifo and its median makespan is no longer than fifo's (`outputs-schedule` against
  `outputs-fifo`). Otherwise the default goes back to priority, then age, and the schedule stays available as
  `order="schedule"`.

## What this does not show

- **Real agents.** Durations and results are simulated; real work may not split into early results this neatly.
- **Estimates.** The schedule's gains depend on them; here they are within -20% to +25%.
- **Contention.** Workers per role are fixed at one. More workers per role would reduce waiting in every arm.
