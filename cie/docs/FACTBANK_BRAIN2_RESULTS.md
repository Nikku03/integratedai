# The company brain, round 2 (v16): results

**Run on 2026-10-11 and 12,** by the rules in `docs/FACTBANK_BRAIN2_PREREGISTRATION.md`, frozen at commit `9033d8d`
(23:22:00 UTC). The test documents were drawn after it, at 23:22:24.
- **Raw results and run log:** `docs/benchmarks/brain2/test/`.
- **All data is fictional:** the benchmark's made-up company.

## In short

**All 12 rules are met on the messy set,** the set that decides. It holds 579 questions on 5,000 documents that v16 had never
seen, typed the way people type.

**v16 is the first version that answers every kind of question we test:**

| | v16 | best earlier version |
|---|---|---|
| mean over the eight kinds (messy) | **0.826** | 0.462 (v15) |
| mean over the eight kinds (tidy) | **0.904** | 0.524 (v15) |

**Where it is clearly better:**
- **Counts** ("how many P2 tickets?"): 0.775 against 0.175.
- **History** ("who left the first comment?"): 0.850 against 0.300.
- **Email and chat:** 1.000 against 0.332.
- **Knowing when not to answer:** 0.825 against 0.243.
- **Speed:** a median of 0.84 s a question, against 4.4 s for v15.

**Where it only ties:**
- **Single-document facts:** 0.736 against v2's 0.715. The 95% interval of the difference runs from −0.08 to +0.12.
- **Free text:** 0.666 against plain keyword search's 0.646 (−0.05 to +0.09). Round 1's v15 lost this rule. v16 meets it,
  but only just.

**What messy typing costs:** v16's mean falls from 0.904 (tidy) to 0.826 (messy). The cost lands mostly on:
- counts: 1.000 to 0.775;
- history: 1.000 to 0.850;
- single-document facts: 0.794 to 0.736.

**Its weakest spot:** questions that describe a document instead of naming it ("the PR that added the latency metric"). v16
gets 0.500 of them; v1 and v2 get 0.725 and 0.750.

**What it shows:** one system, without a language model, answers fact lookups, links across records, counts, history, email and
chat questions, finds free-text answers, and says "not found" when the company has no answer. It does this on documents it
never saw, in casual wording.

**What it does not show:**
- That it beats a modern AI search system. Every arm here is our own; no language model or vector search was compared.
- That it works on a real company's data. The documents are one benchmark's fictional company.
- That it reads every kind of messy question. These were rewritten by language models asked to type like people, not
  typed by people.

## Decision (the messy set)

| Rule | Result |
|---|---|
| 1. Single-document: v16 ≥ best other arm − 0.03 | **Met:** 0.736 against v2's 0.715 (+0.021) |
| 2. Multi-document: v16 ≥ best other arm − 0.03 | **Met:** 0.857 against v15's 0.839 (+0.018) |
| 3. Free text: v16 ≥ best other arm | **Met:** 0.666 against plain search's 0.646 (+0.020) |
| 4. Not found ≥ 0.80 | **Met:** 0.900 |
| 5. No answer in the haystack ≥ 0.70 | **Met:** 0.825 |
| 6. False "not found" ≤ 0.05 | **Met:** 0.042 |
| 7. Counts ≥ 0.70 and ≥ best other + 0.20 | **Met:** 0.775 against 0.175 |
| 8. History ≥ 0.70 and ≥ best other + 0.20 | **Met:** 0.850 against 0.300 |
| 9. Email and chat ≥ 0.70 and ≥ best other + 0.20 | **Met:** 1.000 against 0.332 |
| 10. Mean over the eight ≥ every other arm's + 0.20 | **Met:** 0.826 against 0.462 |
| 11. The right route ≥ 0.90 | **Met:** 0.951 |
| 12. It holds at size (single, multi, free text) | **Met:** −0.023, 0.000, +0.009 against the small set |

**The hash-seed check:** v16 asked again under hash seed 1 gave the same answer to all 579 questions.

**On the tidy set** (reported, not decisive) all 12 rules are met as well.

## Results

**The messy set** (579 questions: single 130, multi 56, free text 150, not found 20, counts 40, history 40, email and chat
40, unanswerable 103):

| arm | single | multi | free text | not found | counts | history | email, chat | unanswerable | mean |
|---|---|---|---|---|---|---|---|---|---|
| plain search, quotes | 0.114 | 0.036 | 0.646 | 0.000 | 0.025 | 0.050 | 0.332 | 0.000 | 0.150 |
| v1 | 0.686 | 0.107 | 0.002 | 0.350 | 0.000 | 0.150 | 0.300 | 0.184 | 0.222 |
| v2 | 0.715 | 0.107 | 0.006 | 0.250 | 0.000 | 0.300 | 0.292 | 0.029 | 0.212 |
| v13 | 0.266 | 0.661 | 0.000 | 0.000 | 0.150 | 0.050 | 0.125 | 0.000 | 0.157 |
| v15 | 0.709 | 0.839 | 0.581 | 0.700 | 0.175 | 0.250 | 0.202 | 0.243 | 0.462 |
| **v16** | **0.736** | **0.857** | **0.666** | **0.900** | **0.775** | **0.850** | **1.000** | **0.825** | **0.826** |

**The tidy set** (the same questions, with the generated ones in the generators' own words):

| arm | single | multi | free text | not found | counts | history | email, chat | unanswerable | mean |
|---|---|---|---|---|---|---|---|---|---|
| plain search, quotes | 0.116 | 0.018 | 0.646 | 0.000 | 0.025 | 0.025 | 0.357 | 0.000 | 0.148 |
| v1 | 0.741 | 0.054 | 0.002 | 0.250 | 0.000 | 0.175 | 0.300 | 0.184 | 0.213 |
| v2 | 0.674 | 0.071 | 0.006 | 0.250 | 0.000 | 0.225 | 0.242 | 0.029 | 0.187 |
| v13 | 0.308 | 0.750 | 0.000 | 0.000 | 0.075 | 0.000 | 0.200 | 0.000 | 0.167 |
| v15 | 0.774 | 0.893 | 0.581 | 1.000 | 0.150 | 0.250 | 0.300 | 0.243 | 0.524 |
| **v16** | **0.794** | **0.893** | **0.666** | **1.000** | **1.000** | **1.000** | **1.000** | **0.883** | **0.904** |

**v16 minus the best other arm** (paired, 95% bootstrap interval):

| family | messy | tidy |
|---|---|---|
| single | +0.021 [−0.083, +0.123] (v2) | +0.019 [−0.029, +0.072] (v15) |
| multi | +0.018 [0.000, +0.054] (v15) | 0.000 [0.000, 0.000] (v15) |
| free text | +0.020 [−0.052, +0.089] (quotes) | the same (the writers' questions are in both sets) |
| not found | +0.200 [+0.05, +0.40] (v15) | 0.000 (v15) |
| counts | +0.600 [+0.45, +0.75] | +0.850 [+0.73, +0.95] |
| history | +0.550 [+0.38, +0.73] | +0.750 [+0.63, +0.88] |
| email, chat | +0.668 [+0.52, +0.80] | +0.643 [+0.49, +0.78] |
| unanswerable | +0.583 [+0.49, +0.68] | +0.641 [+0.54, +0.74] |

**Other measures on the messy set:**
- **Route accuracy:** 0.951 for v16, 0.903 for v15.
- **False "not found"** on answerable questions: 0.042 for v16, 0 for v15. v15 almost never says "not found", which is
  why it fails the unanswerable questions.
- **Strict free text** (facts quoted from a gold document): 0.666 for v16, 0.633 for plain search.
- **Time a question:**

  | | median | 90th percentile |
  |---|---|---|
  | v16 | 0.84 s | 1.5 s |
  | v15 | 4.4 s | 5.7 s |
  | plain search | 0.03 s | |

**The questions:**
- **Writers** (blind, sealed, casual style) kept 44 of 45 descriptive, 168 of 180 free-text and 83 of 94 held-out questions.
  150 of the free-text questions were drawn.
- **Rewriters** reworded all 306 generated questions, and all 306 rewrites passed the check, so the messy set is complete.

## What messy typing costs

The same generated questions, tidy and messy, answered by the same code:

| v16 | tidy | messy | answers lost |
|---|---|---|---|
| single | 0.794 | 0.736 | 10 |
| multi | 0.893 | 0.857 | 2 |
| not found | 1.000 | 0.900 | 2 |
| counts | 1.000 | 0.775 | 9 |
| history | 1.000 | 0.850 | 6 |
| email, chat | 1.000 | 1.000 | 0 |
| unanswerable (empty-field questions) | 1.000 | 0.700 | 6 |

v16 lost 35 answers to messy wording and gained 1. v15 lost 30 and gained 8, from a lower start.

**What broke, read from the 35 questions:**
- **Counts asked in new shapes** (9). The misses include "# of github PRs in the benchmark-lab repo?", "whats the count of
  jira tickets…", "can someone count confluence pages…" and "smb tier hubspot accts forecast to close in 2026-06, how many
  are there?". The counts route expects "how many ... are/have ..."; most of these went to the fact route and returned a
  field.
- **Names people use for fields.** In 6 of the 20 empty-field questions the empty-field check did not recognise the field
  ("customer success manager", "CSM", "crm deal id", "what month … forecast to close"). Another route then answered from a
  different field. "solutions engineer on the … acct" cost a single-document answer the same way.
- **Slips the reading step leaves alone,** so the history lookup does not match (3):
  - "coment" is itself in the ordinary-English word list;
  - "opend" has two candidates (open, pend).

  A fourth, "activty", was fixed, but "when does the activity timeline … start?" is a phrasing the history lookup does not
  know.
- **The coverage check said "not found" to 6 answerable questions,** because the casual wording added many words the
  documents lack:
  - two action items and a meeting named inside long sentences;
  - a customer;
  - two date-range lists ("due 2026-01-10 thru 2026-01-23").
- **Invented titles without quotes.** Two not-found questions name a Linear issue title that does not exist. Without quotes,
  the unknown-title check does not fire, and a near match is answered.

## Where v16 is weak, whatever the wording

**Descriptive questions** (40, written by the writers): 0.500, the same tidy and messy. v1 gets 0.725 and v2 0.750. Of the 16
v16 loses to v2:
- **6 pick the wrong document.** The planner joins on the wrong one.
- **5 say "not found".** The coverage check judges the description too far from any title.
- **3 answer the wrong field.**
- **2 go to the free-text route.**

On development, v16 got 0.750 of 36 descriptive questions (v1 0.639, v2 0.528). The test writers' casual descriptions are
harder, and this is the largest single gap between v16 and the best earlier answer.

**Free text** (150): 0.666. 39 questions score below 0.5:
- 29 quote the wrong passage or the wrong document;
- 3 go to the fact route and return a field;
- 7 say "not found": 4 from the coverage check and 3 from the free-text route's threshold.

Plain keyword search gets 0.646 on the same questions with the same quoting code, so v16's free text is about as good as
keyword search and no better.

**Held-out questions** (83 about documents that are not in the haystack): 0.855, against v15's 0.301. Ten are answered from
the free-text route: a nearby document's passage overlaps the question enough to pass the 0.47 threshold.

## Development against test

| v16 | development (seen) | test, tidy | test, messy |
|---|---|---|---|
| single | 0.878 | 0.794 | 0.736 |
| multi | 0.929 | 0.893 | 0.857 |
| free text | 0.777 | 0.666 | 0.666 |
| not found | 1.000 | 1.000 | 0.900 |
| counts | 1.000 | 1.000 | 0.775 |
| history | 1.000 | 1.000 | 0.850 |
| email, chat | 1.000 | 1.000 | 1.000 |
| unanswerable | 0.887 | 0.883 | 0.825 |
| mean | 0.934 | 0.904 | 0.826 |

The pre-registration warned that development was optimistic. On unseen documents:
- **The template families** (counts, history, email and chat, not found) held at 1.000 when tidy.
- **Writer-made questions** dropped: free text by 0.11 and single by 0.08 (through the descriptive questions).

## Checks

- **The freeze came first:** commit `9033d8d` at 23:22:00 UTC; the test documents were drawn at 23:22:24.
- **Nothing about the test was read before the scores were written.** Every step printed counts, hashes and batch names
  only. The writers and rewriters wrote to files and returned counts.
- **Every step's error file stayed empty.**
- **Hash seed 1:** v16 gave the same 579 answers.
- **The size rule:** the small control sets held the same questions as the 5,000-document sets, tidy and messy.

## What it means, and what is next

v16 is a working "company brain" core:
- one entry point answers eight kinds of question;
- it is fast and checkable;
- it never invents an answer from nothing, and it says "not found" when it should, eight times in ten on natural questions.

**It is not yet a product.** In order of value, the next steps are:
1. **An answer writer on top.** v16 returns a field, a list or a quoted passage. A language model that writes the reply
   from v16's evidence would turn this into answers people can read. It would also cover the descriptive and free-text gap,
   where v16 finds the right document more often than it picks the right passage.
2. **A standard AI search baseline.** Compare against vector search plus a language model on the same 579 questions, so the
   numbers mean something outside this project.
3. **Wording robustness.** Field synonyms ("customer success manager", "SE", "crm deal id"), count shapes ("# of",
   "how many are there"), and slips with more than one candidate word, chosen by context.
4. **Real data.** A pilot on one real team's tools: the true test of everything above.
