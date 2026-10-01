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

Steps 1 and 2 are now built: `inputs="relied"` (see `docs/OPERATING_SYSTEM.md`, section 5) and the `llm-*` arms.
Both were pre-registered as study 2 in `docs/LOOP_PREREGISTRATION.md`, on new test worlds 304 to 306. The results
are below.

---

# Study 2: inputs from what an answer relied on, and Llama 3.1 8B as the analyst

The rules were fixed in the study-2 section of `docs/LOOP_PREREGISTRATION.md`. The test run used worlds 304, 305
and 306, with 20 changes each, inside a new load of the same 50,000-document memory bank (tenant
`erbfull-50000-96a2d0`) on a Colab A100. The code was cbe890a. The model was Llama 3.1 8B through Ollama on the
same GPU. The raw report is `docs/benchmarks/loop/bench_loop_50k_colab_study2.md`. The project data is FICTIONAL
and GENERATED.

## Outcome

**Every pre-registered criterion was met:** `loop` met 1 to 6, `loop-relied` 1 to 7, and `llm-relied` 1 to 4.

| Criterion | loop | loop-relied | llm-relied |
|---|---|---|---|
| 1. stale answers served / stale published findings | 0 / 0 | 0 / 0 | 0 / 0 |
| 2. missed dependencies | 0 of 119 | 0 of 119 | 0 of 117 |
| 3. duplicate actions | 0 | 0 | 0 |
| 4. needed records in the context; incomplete scans | 1.0; 0 | 1.0; 0 | 1.0; 0 |
| 5. findings verified; published answers correct | 1.0; 1.0 | 1.0; 1.0 | not applied |
| 6. tasks completed | 36 of 36 | 36 of 36 | not applied |
| 7. re-runs of unaffected projects | – | 0 | – |

The decision fixed in advance for this outcome applies. **Relied inputs are safe on these worlds**, with the
deterministic analyst and with this model. They are now the recommended setting for tasks whose results carry
state references. Workers whose results carry none keep `inputs="all"`, which stays the default, because they would
otherwise have no inputs and never be refreshed.

## Relied inputs against everything in the context

| | loop (`all`) | loop-relied (`relied`) |
|---|---|---|
| re-runs | 173 | 119: exactly one per affected project |
| routings of unaffected projects | 54 | 0 |
| context tokens | 10.7 M | 8.5 M (21% fewer) |
| change to refreshed answers, p50 | 9.9 s | 5.1 s |
| change to refreshed answers, worst p95 | 26.9 s | 27.4 s |

Both arms were equally correct. Relied inputs removed every wasted re-run and halved the typical time to refresh
answers. The slowest refreshes did not get faster.

## Llama 3.1 8B as the analyst

**No answer was right.** Of the answers the model gave, none matched the oracle as a whole. By part:

| Part of the answer | Right |
|---|---|
| delivery verdict (can every milestone be met) | 52% |
| budget verdict (within budget or not) | 72% |
| cost of the open orders | 0% |
| set of milestones at risk | 20% |

The cost was never right. The replies that were not in the requested JSON form show the model writing the
arithmetic (`123 * 46 + 123 * 15 + 310 * 60`) where a number was asked for. Judging which milestones are at risk,
from stock and open orders, was also mostly wrong.

**What verification caught.**
- It blocked every wrong cost or budget figure (152 of 152) and no right one.
- The answer rests on those figures (`depends_on`), so the publication gate blocked every answer as well. No model
  answer reached shared memory.
- At-risk judgments have no recalculation, so verification cannot catch them. Here they were kept out only because
  the same answers' figures were also wrong.

**What it did not stop.** A task whose answer the gate blocked still completed, holding that answer as its result.
After the changes, 735 checks found a completed task holding a wrong answer. These answers were never published,
but anything that reads the task's result would get them. A blocked answer does not send the task back.

**The loop's guarantees held with the model.**
- No stale answers, no missed dependencies and no duplicate actions.
- The answers cited 99.4% of the records they needed. No change on these worlds hit a record an answer left out,
  so nothing was missed. A change to an uncited record would not reach the task: relied inputs trust the model's
  citations.
- Two runs gave no usable answer, even after the retry. Two affected projects' tasks held no answer to refresh;
  these are counted apart from missed dependencies, as pre-registered.

**The model itself.** 158 calls, with 110,687 tokens in and 34,132 out. A call took 1.7 s (p50). Six replies were
not in the requested JSON form, and no record id was invented. The cost was USD 0, on the Colab GPU.

## What routing prevents when a model is the analyst

Without routing, the model arm missed 115 of 115 affected projects and left 347 stale published findings. The
pre-registered comparison of served-answer accuracy cannot show the difference: it was 0.0 in both arms, because no
model answer was right in the first place.

## Other measures (no threshold)

- **Search among 50,000 real documents.** For questions about supplier delays, traversal and search together found
  91–92% of the evidence, and search over the whole memory found 95–99% of the passages. Study 1's routing arms
  found 96–97% and 99%. Four arms shared one tenant here, against three in study 1, so each world competed with
  more copies of itself (see "A benchmark artifact" above).
- **Latency.**
  - Applying a change: p50 0.22–0.29 s.
  - Building a context: p50 2.7–3.7 s, about twice study 1's 1.5–1.7 s. The context builder and the benchmark
    both changed since study 1, and the tenant held more copies of each world. The cause was not isolated.
  - Verification and publication: 0.11–0.16 s.
- **Wall time.** The whole Part 2 run took 49 minutes.

## What this shows and what it does not

**What it shows.**
- Recording only what an answer relied on keeps answers right and removes every re-run of an unaffected project,
  with a deterministic analyst.
- With a model as the analyst, the loop still delivers every change to the tasks that depend on it.
- Verification keeps every wrong figure, and every answer built on one, out of shared memory.

**What it does not show.**
- **That an 8B model can do this analysis.** It cannot: no answer was right. A stronger model was not measured.
- **Safety of relied inputs in general.** It holds on these worlds. With a model that cites less, a change to an
  uncited record would be missed.
- **A real project.** The project data is generated.

## Next steps suggested by the data

1. **Let code do the arithmetic.** The model should choose what counts (which orders, which milestones), and the
   cost should be calculated from the records. Verification already recalculates it. This removes the cost errors;
   the at-risk judgments stay the model's.
2. **Send a blocked answer back.** When the publication gate blocks a task's answer, the task should return to its
   worker with the failed check (one retry), and then go to a person. It should not complete holding the answer.
3. **A stronger model.** Run the two model arms again with a stronger model, on new test worlds.
4. **One tenant per arm,** so that search measures are comparable across arms.

## A repeat of study 2's worlds (BM25 as the keyword engine)

Study 2's test worlds (304 to 306) were run again on Colab, inside a fresh load of the 50,000-document memory bank,
with later code (c00ed8d). The main difference is that BM25 is now the default keyword engine. This is a repeat, not
a new pre-registered test; the raw report is `docs/benchmarks/loop/bench_loop_50k_colab_study2_rerun.md`.

**Every study-2 criterion was met again**: no stale answers, no missed dependencies (0 of 119), no duplicate
actions, every task completed, and no re-runs of unaffected projects with relied inputs.

| | Study 2 | Repeat |
|---|---|---|
| loop-relied: re-runs (one per affected project) | 119 | 119 |
| loop-relied: context tokens | 8.5 M | 8.3 M |
| loop-relied: change to refreshed answers, p50 / worst p95 | 5.1 s / 27.4 s | 2.9 s / 12.4 s |
| context build p50, by arm | 2.7–3.7 s | 1.3–1.8 s |
| llm-relied: answers right / wrong figures blocked | 0% / 152 of 152 | 0% / 155 of 155 |
| llm-no-routing: missed / stale published findings | 115 of 115 / 347 | 113 of 113 / 393 |

The model results repeated closely. Llama 3.1 8B again got no answer right and never got the cost right: once more,
it wrote out the sum (`10800.0 + 12301.0 + 840.0`) instead of the result.

**Two measures moved, and their cause was not isolated.**
- **Search over passages** found 89–93% of the delay notices, against 95–99% in study 2. To test whether BM25 is the
  cause, the benchmark can now ask every delay question with both engines at the same moment
  (`CIE_LOOP_COMPARE_KEYWORD_ENGINES=1`). On development worlds 1 and 2, inside the local 5,000-document memory bank,
  the two engines found the same share: 0.993 and 0.993, with the BM25 index ready for every question. So the engine
  does not explain the drop there. The notebook now runs this comparison at 50,000 documents too.
- **The `loop` arm** (every record in the context counts as an input) routed 165 unaffected projects, against 54 in
  study 2, and re-ran 284 times, against 173. The arm that the results recommend, `loop-relied`, is unaffected: it
  re-ran exactly once per affected project in both runs.
