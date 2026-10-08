# A language model for the English, the fact bank for the facts: what decides, fixed before any run

I wrote this on 2026-10-08. I wrote it before either method was run on any question set. The results go in
`docs/FACTBANK_LLM_RESULTS.md`.

## Why

Counting word meanings, from the company's documents or from general English, did not teach the fact bank new words
(`docs/FACTBANK_WORDS_RESULTS.md`, `docs/FACTBANK_GENERAL_RESULTS.md`). Two ways to let a language model handle the
English, while the fact bank still finds every fact and does the reasoning:

| arm | what reads the English | when a model runs |
|---|---|---|
| **v7** | Llama 3.2 3B (local, 4-bit, CPU) rewrites the question as the closest standard question | at every question |
| **v8** | a glossary of everyday phrases, written once by a large language model | once, when the bank is set up; never at question time |
| v4 | nothing: the plan learner alone | never |
| v6 | word meanings counted from the company's documents and general English | never |

### v7 (`cie/src/cie/factbank/reader.py`, `Reader`)

**What the model sees:**
- A menu of 10 standard questions: the first training wording of each kind.
- The person's question.
- It never sees a document.
- Prompt sha256 `7ac2eb466f0737be…`. Model `llama3.2:3b`, Q4_K_M, manifest sha256 `a80c4f17acd55265…`.
- Temperature 0, seed 0, at most 120 tokens.

**What it does:** it answers with one standard question, filled in from the person's question.

**When the rewrite is used:** only if it keeps every key, pull request number, quoted title and named person of the
original. Otherwise the original question is used. The fact bank, with v4's plan weights, answers whichever question
is used. Every rewrite is kept in a cache file.

### v8 (`Glossary` in `cie/src/cie/factbank/reader.py`)

**The glossary:**
- 248 phrases, written by one agent session.
- That session was given only the bank's fields, links, ways of combining and kinds of answer. It saw no question set,
  no code and no training question.
- `docs/benchmarks/factbank_llm/glossary.json`, sha256 `0dd7d0bc2a7788d5…`.
- Examples: "on their plate" → assignee, "eta" → due date, "where things stand" → status, "put up the pr" → author.

**How it is used:**
- A glossary phrase found in a question, as whole stemmed words in order, adds the standard words of its target.
- The standard words come from the training questions' own wordings (`CANON`, fixed now). For example, assignee →
  "assigned", count → "how many number count", earliest → "first earliest sooner".
- The plan weights are learned again on the same 48 training questions with the glossary in place.
- `plan_lessons_v8.json`, sha256 `ad54971605f3864b…`.

## Nothing is tuned

I selected the test wordings by the fixed rule, so I have seen them. So there is no development step:
- the prompt, the menu, the glossary, the standard words and the fallback rule are all frozen as described above;
- the earlier sets (retest, new-words, blind) are run only to be reported.

## Data (frozen)

**The set.** A new sample of the whole benchmark: 20,000 documents, stratified by source, seed 31 (2,316 linking
documents).
- **Excluded:** 205,216 documents. That is every document of every earlier set, and the company lexicon's whole
  200,000-document sample, so the leak found in the last test cannot recur.

| | documents | questions | link | combine | compare | sha256 of questions.jsonl |
|---|---|---|---|---|---|---|
| language-model test set | 50 | 50 | 20 | 22 | 8 | `17225d3df1bad851…` |
| the same, changed information (fixed transform) | 50 | 50 | 20 | 22 | 8 | `a6f6d3019443aa4f…` |

By kind:
- pull request → Linear issue: 8;
- Linear issue → pull request author: 5;
- ticket → linked ticket: 7;
- a person's issue count: 7;
- a person's first issue due: 7;
- an action item's owner → their issues: 8;
- which of two is due first: 8.

**Known before the run:**
- One document is the target of 6 of the 20 link questions.
- One action-item question (action_owner_issues-036) has a customer attendee as the owner. It is scored as generated
  and also reported without.

**Wordings, written blind** (`BLIND2` in `cie/src/cie/eval/factbank_multi.py`):
- Three new independent agent sessions wrote them, in roles not used before: a sales director, a new hire in their first
  week, and an executive assistant writing for a CEO. They saw only what each question must ask.
- The same selection rule as before applies: writers 1 and 2 give the pair, writer 3 stands in for an invalid wording.
  No wording needed replacing.
- Full output: `docs/benchmarks/factbank_llm/writers.json`.
- Examples: "PR #{n} is tied to a Linear ticket, right? Who's got that ticket on their plate?" and "Of everything
  assigned to {p} in Linear, which ticket is due first? Send me the ticket key."

**A bias to keep in mind:**
- The glossary writer and the question writers are the same kind of model, so they may share phrasings ("on their
  plate" appears in both). This can favour v8.
- v7's model is a different, much smaller one.

## Measure

Own answers, no model judging, as before:
- values, dates and single keys must match exactly;
- lists score F1;
- a count must be the right number.

The mean is the mean of the three groups (link, combine, compare).

## Rules

1. **A small model reading the question helps:** v7 − v4 ≥ +0.10, test set.
2. **A glossary written once helps:** v8 − v4 ≥ +0.10, test set.
3. **Principles, not memorisation:** v7 and v8 each on the test set ≥ the same arm on the training questions − 0.15.
4. **It holds when the information changes:** v7 and v8 each on the changed copy ≥ the same arm on the test set − 0.05.
5. **No harm on what was learned:** v7 and v8 each ≥ v4 − 0.03 on the training questions.

**Also reported:**
- v6 on the test set;
- how often v7 used its rewrite, and how often the rewrite was the right standard question;
- v7's time per question;
- every arm on the earlier sets, for information only.
