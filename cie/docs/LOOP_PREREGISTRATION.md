# One-project loop: what is measured and what counts as proven, fixed before the test run

I wrote this before running any test world. The development runs used worlds 1 and 2. Test worlds are
evaluated once with these settings.

## Question

Does the operating loop keep answers about a project right while the project changes? The loop is: live state,
context builder, workflow engine, event routing to tasks, verification and the publication gate.

## Setup (`cie.eval.bench_loop`)

**Data.** The data is FICTIONAL, GENERATED project data from the controlled dependency generator
(`cie.eval.rem_dataset`), with unit prices and a budget per project. Expected answers come from the generator's own
world model. Each world has 12 projects and a stream of 20 generator steps.

**Host corpus.** Worlds are loaded into the tenant holding the 50,000-document EnterpriseRAG-Bench memory bank
that the notebook builds. Search over the whole company memory has to find each world's documents among that
corpus. Supplier, product and project names carry a world tag.

**Task.** One task per project: "Can <project> deliver every milestone on time and within budget?"
- A deterministic analyst answers it through the context builder, with the operations agent's principal.
- It applies the documented business definition (see the module docstring).
- Its findings carry versioned state references and a recalculable cost.

**Changes.** Each change is applied as an event, with REM's change rules as the analysis. Every event is delivered
a second time with the same key, and each supplier notice a second time under a new key.

## Arms

| Arm | Description |
|---|---|
| `loop` | event routing on; every live-state record in a task's context counts as an input (the context builder's default) |
| `loop-explicit` | event routing on; only the records the analyst named and the collections it scanned count as inputs |
| `no-routing` | the same events with routing off (answer once, never revisit) |

## Test worlds

Seeds 301, 302 and 303, with `--events 20`. The notebook default is `LOOP_SEEDS = "301,302,303"`.

## The loop counts as proven on these worlds if, for both `loop` and `loop-explicit`:

1. **Stale-state errors**: no stale answer is served, and no published finding is stale (both counts 0).
2. **Missed dependencies**: 0. The oracle's affected projects are those whose milestones, orders or stock the change
   touched.
3. **Duplicate actions**: 0 extra state versions, task reopenings, task transitions and suggestions from
   re-delivered or forwarded events.
4. **Retrieval completeness, needed records**: every record an answer needs is in the task's context (1.0), and no
   exhaustive scan is incomplete.
5. **Citation accuracy**: at least 0.99 of findings pass verification at publication, and every published answer
   matches the oracle.
6. **Task completion**: every task ends completed, with none failed and none waiting on a person.

**Reported, with no threshold:**
- evidence found for delay questions (traversal plus search among the host corpus);
- over-invalidation (tasks routed that were not affected) and re-runs;
- latencies and context tokens;
- the `no-routing` arm's served-answer accuracy, which measures what routing prevents.

Every result is reported, including failures.

## What this does not show

- **Reasoning quality.** The analyst is deterministic and applies the same business definition as the oracle, so
  the measures isolate the loop (what the context holds, whether it is current, what reaches the task), not a
  model's reasoning.
- **A real project.** The project data is generated. The host corpus is real text but serves only as search
  competition; it plays no part in the project.
- **External actions.** Duplicate actions here are internal (state versions, task transitions). The action gateway
  for external systems is not built.

## Outcome (added after the single test run)

**All six criteria were met, for both `loop` and `loop-explicit`.** Over worlds 301 to 303 (36 tasks, 60
changes):

| Criterion | Result |
|---|---|
| stale answers served / stale published findings | 0 / 0 |
| missed dependencies | 0 of 104 |
| duplicate actions | 0 / 0 / 0 / 0 |
| needed records in the context | 1.0, with no incomplete scans |
| findings verified / published answers correct | 1.0 / 1.0 |
| tasks completed | 36 of 36 |

`no-routing` served 347 stale answers and missed 104 of 104 affected projects. Details are in
`docs/LOOP_RESULTS.md`.
