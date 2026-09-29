# Scheduling benchmark (10 worlds, 30 tasks each, 8 changes each)

FICTIONAL, GENERATED projects; simulated durations over the real workflow engine; one worker per role.

| Measure | whole-fifo | whole-schedule | outputs-fifo | outputs-schedule |
|---|---|---|---|---|
| Makespan, mean (h) | 55.72 | 55.66 | 45.21 | 44.32 |
| Makespan vs whole-fifo, median ratio | 1.0 | 1.01 | 0.811 | 0.803 |
| Worlds shorter / longer than whole-fifo | 0 / 0 | 5 / 5 | 10 / 0 | 10 / 0 |
| Schedule order vs fifo with the same dependencies, median ratio | None | 1.01 | None | 1.0 |
| Worker utilisation, mean | 0.395 | 0.394 | 0.486 | 0.501 |
| Mean task start (h after the start) | 22.13 | 22.17 | 17.1 | 17.28 |
| Deadline misses / deadlines | 9 / 48 | 5 / 48 | 6 / 48 | 2 / 48 |
| Lateness, total (h) | 34.48 | 30.69 | 17.66 | 9.61 |
| Changes: re-runs / not needed | 653 / 419 | 653 / 419 | 237 / 0 | 237 / 0 |
| Changes: rework (h) | 2911.73 | 2911.73 | 1062.29 | 1062.29 |
| Changes: time until every answer is current, total (h) | 1871.35 | 1891.55 | 699.01 | 699.24 |
| Incomplete tasks / completed on a stale input | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

Makespan per world (h):

| World | whole-fifo | whole-schedule | outputs-fifo | outputs-schedule |
|---|---|---|---|---|
| 401 | 56.65 | 59.72 | 42.19 | 43.49 |
| 402 | 50.16 | 50.09 | 42.13 | 43.01 |
| 403 | 49.6 | 52.43 | 43.2 | 45.61 |
| 404 | 43.09 | 45.43 | 33.55 | 34.04 |
| 405 | 70.83 | 70.2 | 52.04 | 52.04 |
| 406 | 44.5 | 42.15 | 35.26 | 29.03 |
| 407 | 65.88 | 62.55 | 47.23 | 47.23 |
| 408 | 67.72 | 61.42 | 56.18 | 56.0 |
| 409 | 45.39 | 46.39 | 44.21 | 37.01 |
| 410 | 63.36 | 66.2 | 56.1 | 55.7 |

**Decision fixed in advance: the schedule order stays the default claim order** (with results released early: deadline misses 2 vs 6 for fifo; median makespan ratio 1.0).

## Pre-registered criteria (docs/SCHEDULE_PREREGISTRATION.md)

**All criteria met.**

| Criterion | Met | Value |
|---|---|---|
| 1. whole-fifo: every task completed and none on a stale input | yes | incomplete 0, stale 0 |
| 1. whole-schedule: every task completed and none on a stale input | yes | incomplete 0, stale 0 |
| 1. outputs-fifo: every task completed and none on a stale input | yes | incomplete 0, stale 0 |
| 1. outputs-schedule: every task completed and none on a stale input | yes | incomplete 0, stale 0 |
| 2. outputs-schedule: median makespan below whole-fifo | yes | 0.803 |
| 3. outputs-schedule: no re-run that was not needed | yes | 0 |
