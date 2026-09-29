# One-project loop: results

The rules were fixed in `docs/LOOP_PREREGISTRATION.md`. The test run used worlds 301, 302 and 303, with 20 changes
each, inside the 50,000-document EnterpriseRAG-Bench memory bank on a Colab A100. The raw report is
`docs/benchmarks/loop/bench_loop_50k_colab.md`. The project data is FICTIONAL and GENERATED; expected answers come
from the generator's world model.

## Outcome

**All six pre-registered criteria were met, for both arms that route changes to tasks.** Over 36 project tasks
and 60 changes (104 of which touched a project's inputs):

| Criterion | Result |
|---|---|
| stale answers served | 0 |
| stale published findings | 0 |
| missed dependencies | 0 of 104 |
| duplicate actions from re-delivered and forwarded events | 0 |
| needed records present in every context; exhaustive scans complete | yes; 0 incomplete |
| findings passing verification; published answers matching the oracle | 100%; 100% |
| tasks ending completed | 36 of 36 |

**Without routing,** the same changes left:
- 347 stale answers served;
- 432 stale published findings;
- 104 of 104 affected projects missed.

The share of answers that were right fell as changes accumulated: 0.71, 0.53 and 0.36 in the three worlds, 0.53
overall.

## The cost of the conservative default

`loop` counts every live-state record in a task's context as an input, which is the context builder's default.
`loop-explicit` counts only the records the analyst named. Both were equally correct. The difference is work:

| | loop | loop-explicit |
|---|---|---|
| re-runs | 295 | 104 (exactly one per affected project, none wasted) |
| routings of unaffected projects | 191 | 0 |
| context tokens | 17.0 M | 7.4 M |
| change to refreshed answers, p50 / worst p95 | 12.1 s / 25.7 s | 3.2 s / 13.3 s |

The analyst calls no model, so these tokens cost nothing here. For a model-driven worker, they are what it would
read. The extra 9.6 M tokens are pure over-invalidation: traversal puts other projects' records into a context,
and a change to them reopens a task whose answer did not depend on them.

## Other measures (no threshold)

- **Search among 50,000 real documents.** For questions about supplier delays, search over the whole company
  memory found 99.5% and 98.9% of the notice and purchase-order passages in the two routing arms.
  Traversal and search together found 97% and 96% of the evidence.
- **Latency.**
  - Applying a change, with REM's rules and routing: p50 0.16–0.23 s.
  - Building a context: p50 1.5–1.7 s at 50k documents.
  - Verification and publication: 0.14 s.
- **Wall time.** The whole Part 2 run took 21 minutes.

## A benchmark artifact, not a routing effect

The `no-routing` arm found less delay-question evidence: 0.75, against 0.96–0.97 in the other arms. Routing does
not touch retrieval, so this is not an effect of routing. It is an artifact of the benchmark's layout:
- Each seed's three arms load the same world into one tenant, in the order `loop`, `loop-explicit`, `no-routing`.
- The copies differ only in a name tag.
- The world loaded last therefore competes with two near-identical copies of every supplier, product and notice.

The traversal channel suffers most, falling from 0.97 to 0.75, because its start hits land on the other copies'
records. Search over passages suffers less, falling from 0.99 to 0.95. The measure falls in step with the number of
copies loaded before it (0.97, then 0.96, then 0.75).

The same effect would appear with real duplicate supplier or product records. That is a reason to resolve
identities (`cie.state.identity`), not a result about routing. A future run should put each arm in its own tenant
so this measure is comparable across arms.

## What this shows and what it does not

**What it shows.** On these generated worlds, the loop does what the architecture asks:
- answers stay right as the project changes;
- nothing affected is missed;
- repeated or forwarded events cause no duplicate work;
- every published finding is verified against the current state.

**What it does not show.**
- **Reasoning.** The analyst is deterministic and applies the same business definition as the oracle. What was
  measured is the loop (what reaches the task, whether it is current, what gets reopened, verified and published),
  not a model's reasoning. With a model doing the analysis, answer accuracy would also depend on the model.
- **A real project.** The project data is generated. The 50,000 real documents only compete in search.
- **External actions.** The action gateway is not built, so "duplicate actions" here means internal state and task
  actions only.

## Next steps suggested by the data

1. **Cheaper precise routing.** Record a task's inputs from what its findings rely on (their state references and
   calculation inputs), in addition to or instead of everything in its context. `loop-explicit` shows this
   removes all wasted re-runs, about 57% of context tokens, and 3.8x of the time to refresh answers, with nothing
   missed.
2. **A model-driven analyst.** Run the same loop with, for example, Llama 3.1 8B on the Colab GPU, to measure
   answer accuracy with real reasoning in the loop.
3. **A real project,** and the action gateway.
