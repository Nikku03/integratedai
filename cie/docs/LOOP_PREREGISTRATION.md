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

---

# Study 2: inputs from what an answer relied on, and a language model as the analyst

I wrote this section before running any study-2 test world. Development runs used worlds 1 and 2 only. The study-1
test worlds (301 to 303) are not reused.

## Questions

1. **Relied inputs.** Suppose a task's inputs are only the records its answer relied on: its findings' state
   references and calculation inputs, read at the snapshot of the context it was given. Is every answer still kept
   right, while unaffected projects are no longer re-run? In study 1, `loop` re-ran 191 unaffected projects, because
   everything in the context counted as an input.
2. **A model in the loop.** With Llama 3.1 8B as the analyst, how accurate are the answers? What does verification
   catch? And are relied inputs still safe when the model decides what to cite?

## What changed since study 1

- **Relied inputs** (`ContextRequest.inputs = "relied"`, `cie.workflow.engine.relied_on`):
  - The context builder records no inputs; it notes the context's snapshot (`seq`).
  - On submit, the result's state references and calculation inputs become the task's inputs, at their versions as
    of that snapshot.
  - A change between reading the context and submitting sends the task back.
  - A project also changes when a record joins or leaves it (an order added to it, deleted, or moved), so an
    answer that cites the project is refreshed when its set of open orders changes.
- **The model analyst** (`llm-*` arms):
  - The model gets the same data as the deterministic analyst: the project's budget and stock, and its milestones
    and open orders under short aliases. It also gets the business definition in plain words.
  - It replies with JSON: each milestone at risk or not, the cost lines, the cost, the budget and both verdicts.
  - The harness builds the findings from that reply. It cites exactly the milestones and orders the model listed,
    with the versions read. The cost finding is a calculation over the model's cost lines. The budget finding states
    the model's figure against the project record.
  - The answer finding rests on the others (`depends_on`), so the publication gate blocks it when a figure it uses
    fails verification.
  - Verification can therefore catch a wrong cost or budget figure, and keep an answer built on it from being
    published. It cannot catch a wrong at-risk judgment, which has no recalculation.
  - The provider is local through Ollama, at temperature 0 with at most 2,000 output tokens. A reply that is not
    in the requested JSON form (every key present; objects the model splits the reply into are merged) gets one
    retry, which names the missing keys.
- **Measures added**:
  - needed records the answer relied on (its recorded inputs);
  - answer accuracy when given (whole answer, and each part: delivery verdict, budget verdict, cost, set of
    milestones at risk);
  - wrong answers served because the analyst erred, kept apart from stale answers (an answer counts as stale only
    if it was right when given);
  - wrong and right figures blocked by verification;
  - runs without a usable answer;
  - model calls, tokens, replies not in the requested JSON form, and invented record ids;
  - affected projects whose task held no answer. These are counted apart from missed dependencies: a task with no
    answer has nothing to refresh.

## Arms

| Arm | Analyst | Inputs | Routing |
|---|---|---|---|
| `loop` | deterministic | everything in the context | on |
| `loop-relied` | deterministic | what the answer relied on | on |
| `llm-relied` | Llama 3.1 8B (`llama3.1:8b` through Ollama on the Colab GPU) | what the answer relied on | on |
| `llm-no-routing` | the same model | what the answer relied on | off |

`loop` is included so that re-runs and tokens are compared with `loop-relied` on the same worlds.

## Test worlds

Seeds 304, 305 and 306, with `--events 20`. The setup is otherwise as in study 1: the host corpus is the
50,000-document memory bank, with duplicate deliveries and forwarded notices. The notebook defaults are
`LOOP_SEEDS = "304,305,306"` and `LOOP_ARMS = "loop,loop-relied,llm-relied,llm-no-routing"`.

## Criteria

**`loop` and `loop-relied`** must each meet criteria 1 to 6 of study 1 (above). **`loop-relied`** must also meet:

7. **No re-runs of unaffected projects**: 0 tasks routed whose project the change did not affect.

**`llm-relied`** must meet criteria 1 to 4, the guarantees the loop gives whatever the analyst concludes:

1. no stale answer served and no stale published finding;
2. no missed dependencies;
3. no duplicate actions;
4. every needed record in the task's context, with no incomplete scan.

Criteria 5 and 6 are not applied to the model arms. Whether the model's answers are right is what this study
measures, not a guarantee of the loop.

## Reported, with no threshold

- `loop-relied` against `loop` on the same worlds: re-runs, tasks routed, context tokens, and time from a change to
  refreshed answers.
- For the model arms:
  - answer accuracy when given, overall and by part;
  - wrong answers served because the analyst erred;
  - wrong figures blocked by verification, and right figures blocked;
  - runs without a usable answer, and tasks left waiting on a person;
  - replies not in the requested JSON form, and invented ids;
  - model latency and tokens;
  - needed records the answer relied on;
  - affected projects whose task held no answer.
- `llm-no-routing` against `llm-relied`: served-answer accuracy, which measures what routing prevents when a model
  is the analyst.

## Decisions fixed in advance

- **`loop-relied` meets 1 to 7 and `llm-relied` meets 1 to 4.** Relied inputs are safe on these worlds, with the
  deterministic analyst and with this model. They become the recommended setting for tasks whose results carry
  state references. Workers whose results carry none keep `inputs="all"`, because they would otherwise have no
  inputs and never be refreshed.
- **`loop-relied` meets 1 to 6 but not 7.** Relied inputs are safe but do not remove every unaffected re-run. The
  re-runs left are reported with their cause.
- **`loop-relied` fails any of 1 to 6.** Relied inputs are not safe; `inputs="all"` stays.
- **`loop-relied` meets 1 to 6 but `llm-relied` fails 1 or 2.** Relied inputs are not safe with this model, which
  under-cites the records its answer depends on. Model-driven tasks keep `inputs="all"` (or `"explicit"`). The count
  of stale answers or missed projects is reported as the cost of trusting the model's citations.
- Answer accuracy has no pass mark. It is reported as measured, together with what verification caught and what it
  cannot catch (at-risk judgments).

Every result is reported, including failures. The model run is done once, on these three worlds.
