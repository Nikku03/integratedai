# The company brain at 50,000 documents, with a language model as its reasoning engine: plan

**Written on 2026-10-17, before any language model answered a question of this test.** The rules below are fixed now;
the run is the Colab notebook `notebooks/company_brain_50k_colab.ipynb` on an A100. Code: `cie.eval.brain50k` (draw,
questions, arms, score), `cie.eval.complex_questions` (the complex questions) and `cie.factbank.reasoner` (the reasoning
engine). All data is the benchmark's fictional company.

## In short

Two questions:
1. **Does the brain hold at 50,000 documents?** Round 4 tested v18 on 5,000. Here the same questions are asked among ten
   times as many documents.
2. **Does a bigger reasoning engine help?** The brain reasons with exact rules: lookups, counts, and plans of at most two
   steps. Its free-text answers quote sentences and miss facts (round 4: 0.681), and it cannot chain three steps. The
   reasoning engine here is **Qwen3.8-27B** (August 2026, open weights, 27 billion parameters, thinks before it
   answers), working on top of the brain: it reads the brain's answer and can ask it more, search, read records, and
   count and list with exact filters before it answers.

"Reasoning engine" means this language model. The brain-wired spiking neurons of `cie.neuro` were tested before
(`docs/BRAIN_WIRING_RESULTS.md`) and made no difference, so they stay out.

## The haystack

`brain50k draw`: round 4's 5,000 test documents (`docs/benchmarks/brain4/test/test5k/haystack.json`) and 45,000 more of
the benchmark (commit `d36685e`), every system in its share of what is left (seed 5050). Left out of the 45,000:
- round 4's 91 held-out documents (their questions must stay unanswerable);
- a ticket key or pull request number already drawn (one document per name, as every round's draw);
- a document that links a ticket of the 5,000, or whose ticket the 5,000 link (so that a round-4 question about a link keeps
  its one answer).

This draw was run on 2026-10-17 to write this plan; the notebook checks it gets the same documents (`dsids_sha256`
`9a344aaac47f662c`). Of the 45,000 candidates the draw passed over 547 that link a ticket of the 5,000, 403 with a key
already drawn, 249 whose ticket the 5,000 link, 24 with a pull request number already drawn and 10 with a malformed key.

The bank of the 50,000 documents: 1.03 GB, 1,162,089 facts, 114,341 entities.

## The questions

Two folders share the bank: `w50k_messy` (decides) and `w50k` (reported).

**Round 4's 587 questions,** each kept only if it still has one right answer among 50,000 documents (`still_holds`):
- a generated question is drawn again among the 50,000 with round 4's seed (1020), and must come out with the same answer
  (`brain_test.not_reproduced`, `brain2_test.not_reproduced2`, the functions round 4's small control set used);
- a count or list that changed is **counted again** (its filters over the 50,000 documents) and kept with its new answer,
  unless no document holds its filters or a list grows past 10 keys;
- a question naming a document the company does not have: its name must still be written nowhere;
- the writers' free-text and descriptive questions: `brain_test.why_aside` again;
- the held-out questions: checks (1) to (4) of round 2's held-out draw, run against the 50,000 documents.

The messy folder holds them in the rewriters' casual wordings (as round 4 decided on), the tidy folder in the generators'.

**The complex questions** (`complex_questions.py`, seed 5051, up to 16 of each kind): two to four steps across two or more
records, with answers computed from the raw fields, and every step required to have one reading in the haystack:

| kind | steps | answer |
|---|---|---|
| pr_assignee_load | pull request → its Linear issue → the assignee → that person's issues, counted | count |
| pr_parent_assignee | pull request → its Linear issue → the parent issue → its assignee | person |
| meeting_account_owner | Fireflies meeting → its customer → the HubSpot account → the owner | person |
| meeting_account_stage | Fireflies meeting → its customer → the HubSpot account → the stage | value |
| email_account_owner | email thread → its account → the HubSpot account → the owner | person |
| creator_jira_load | Linear issue → its creator → the Jira tickets assigned to that person, counted | count |
| project_first_due | a Linear project → its issues → the one due first → its assignee | person |
| compare_due_assignee | two Linear issues → the one due first → its assignee | person |
| assignee_open_p | Linear issue → its assignee → that person's open issues of one priority, counted | count |
| owner_meetings | Fireflies meeting → its Redwood owner → the meetings that person owned, counted | count |

Each kind has three wordings, one typed casually; the questions are the same in both folders. A count is at least 2, so
neither "not found" nor a guess of one is right by chance.

**The questions, as drawn on 2026-10-17 for this plan** (the notebook checks it draws the same: questions.jsonl sha256
`a3ee9b75b6eaf947` messy, `beeeac18480aa022` tidy):
- **Round 4's: 509 of 587 still hold**, 55 of them counts or lists counted again. By family: single 124, multi 31, free
  text 80, not found 37, counts 57, history 40, email and chat 40, unanswerable 100. Set aside 78: unanswerable 31 (19 with
  an anchor of the held-out document now written in the haystack, 9 whose answer facts a haystack document now holds, 3 by
  title), multi 25, single 16, counts 3 (a list grew past 10 keys) and not found 3, the rest because drawn again they were
  not asked or had another answer.
- **Complex: 126**, 16 of each kind but three: meeting_account_owner and meeting_account_stage 7 each (a meeting's customer
  is the title of one HubSpot account for 7 meetings), pr_parent_assignee none (no linked issue's parent is in the
  haystack).
- **635 questions in each folder.**

## The arms

| arm | what answers |
|---|---|
| **v18** | the brain alone, exactly as frozen in round 4 (`Brain(..., v18=True)`, round 4's lessons in `docs/benchmarks/brain2/lessons`) |
| **rag** | the model alone: the question and the 12 best passages of a keyword search over the 50,000 documents (BM25, `brain_test.Passages`, as round 4's quotes arm searched), one turn |
| **reasoner** | the model as the brain's reasoning engine (`cie.factbank.reasoner`): it is shown the brain's answer, route and evidence, and may call five tools, up to 8 calls: **brain** (ask the brain a question), **search** (BM25 over the records), **read** (a record's fields and text), **find** (every record of a system whose fields hold given values: a count and up to 40 of them), **values** (the values a field takes). A conversation that ends with no answer it can read keeps the brain's answer. |

The model: Qwen3.8-27B (`Qwen/Qwen3.8-27B` at `1d4bf0f` in bf16 on an 80 GB A100; Qwen's FP8 copy `017b9c7` on a 40 GB one),
vLLM 0.30.0, thinking on with reasoning effort "medium", Qwen's sampling for thinking (temperature 1.0, top_p 0.95,
top_k 20, seed 0), at most 6,144 tokens a turn. Answers are capped at 1,100 characters, as the brain's free-text quote
is. The model arms answer the messy folder; the tidy folder only with `MODEL_ON_TIDY`.

The prompts (`reasoner.SYSTEM`, `reasoner.RAG_SYSTEM`) were written before any test question was asked of a model, and
were not tuned on them. The plumbing was checked locally with Qwen3 0.6B (through Ollama, no GPU) on 16 questions of
round 1's development set: there it showed that a small model copies a placeholder such as "<final answer>", so both
prompts now show the reply format by example. Then the whole notebook ran locally, end to end, with `LIMIT = 4` (four
test questions per folder) and the same small model; nothing was changed after it but the report's labels.

The draw, the bank's size and the questions of this plan are in `docs/benchmarks/brain50k/plan/`.

## Scoring

Every answer is scored as round 4 scores it (`brain2_test.score_one`): a field by its value, a count by its first number,
lists by F1, free text by the share of its answer facts present, not found and unanswerable by saying "not found". A
complex question scores 1 when its count, person or value is in the answer line (`complex_questions.score`), 0 for
"not found". The report gives every arm's score per family, the mean of round 4's eight families, the complex
family by kind and by steps, false "not found" on answerable questions, and the paired difference of each pair of arms
with its 95% bootstrap interval.

## Rules (the messy folder)

| rule | met when |
|---|---|
| 1. The brain holds at size | v18 at 50,000 documents minus v18 at 5,000 (round 4's answers), on the questions both answered and not counted again, averaged over the eight families: ≥ −0.05 |
| 2. The reasoning engine is better overall | reasoner's mean of the eight families ≥ v18's + 0.03 |
| 3. Free text | reasoner ≥ v18 + 0.10 |
| 4. Complex questions | reasoner ≥ v18 + 0.20 |
| 5. No harm where the brain is exact | on not found, counts and unanswerable, reasoner each ≥ v18 − 0.05 |
| 6. Few false "not found" | reasoner says "not found" to at most 0.05 of the answerable questions (complex included) |
| 7. Better than plain search with the same model | reasoner's mean of the eight families ≥ rag's + 0.05 |
| 8. … and on complex questions | reasoner ≥ rag + 0.10 |

**The claim "a bigger reasoning engine makes the brain better" is met if rules 2 to 8 are.** Rule 1 decides "the brain
holds at 50,000 documents". A run with `LIMIT` is a quick look and decides nothing.

## What it will not show

- **Seen questions:** round 4's questions were scored once already; the brain was not changed since, but this is a test
  at size, not a fresh test.
- **One company, generated documents and templated complex questions.** The complex questions are generated from fields,
  in wordings written here, so they are tidier than people's.
- **One run of a sampled model:** thinking samples at temperature 1.0, so a rerun gives somewhat different answers.
- **The scorer is code, not a judge:** a free-text answer is scored by the facts it holds, not by how well it reads.
- **Speed:** at 50,000 documents the brain takes about 7 s a question on one CPU (round 4: about 1.6 s at 5,000);
  the notebook runs it in parallel processes. The report gives the model's tokens; the notebook's log gives the times.
