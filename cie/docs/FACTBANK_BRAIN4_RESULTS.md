# The company brain, round 4 (v18): results

**Run on 2026-10-16,** by the rules in `docs/FACTBANK_BRAIN4_PREREGISTRATION.md`, frozen at commit `bbf5b50`
(01:12:14 UTC). The test documents were drawn after it, from 01:12:21.
- **Raw results and run log:** `docs/benchmarks/brain4/test/`.
- **All data is fictional:** the benchmark's made-up company.

## In short

**The claim is not met, because of free text.** v18 was to raise free text by at least 0.04 over v17; it rose by 0.010
(0.671 to 0.681). Every other rule was met.

**What v18 fixed** (587 messy questions on 5,000 fresh documents):
- **Questions about a document the company does not have:** 0.800 → **1.000** (40 of 40). The 8 made-up titles v17 answered
  from a similar document are now "not found".
- **Counts:** 0.783 → **0.950** (57 of 60).
- **Questions whose answer is in no document:** 0.840 → **0.885** (+0.046; 95% interval +0.015 to +0.084).
- **Mean over the eight kinds of question:** 0.837 → **0.890**.
- **32 answers got better and 4 got worse.** No other family moved, apart from one more single-document question right.

**What it did not fix:**
- **Free text:** 7 answers better, 4 worse.
  - Of the 4, 2 were refused by the new own-terms check because the question had a typo ("supossed", "mixup").
  - The other 2 picked a worse sentence.
  - The gains of development (+0.05 to +0.10) did not carry over to these fresh questions.

**What it shows:**
- Most of a question that names a document the company lacks, or counts, is now answered right even when typed casually.
- The free-text quote is not yet better on fresh questions.

**What it does not show:**
- That it beats a modern AI search system: no language model or vector search was compared.
- That it works on real company data: the documents are one fictional company's.

## Decision (the messy set)

| Rule | Result |
|---|---|
| 1. Not found: v18 ≥ 0.95 and ≥ v17 | **Met:** 1.000 against 0.800 |
| 2. Counts: v18 ≥ 0.95 and ≥ v17 | **Met:** 0.950 against 0.783 (exactly at the bar: 3 misses) |
| 3. Unanswerable: v18 ≥ v17 + 0.03 | **Met:** 0.885 against 0.840 (+0.046) |
| 4. Free text: v18 ≥ v17 + 0.04 | **Not met:** 0.681 against 0.671 (+0.010; 95% interval −0.050 to +0.067) |
| 5. No harm on single, multi, history, email and chat: v18 ≥ v17 − 0.03 | **Met:** single +0.007, the others equal |
| 6. False "not found" ≤ 0.05, and ≤ v17 + 0.01 | **Met:** 0.036 against 0.034 |
| 7. Better overall: mean of the eight families ≥ v17 + 0.02 | **Met:** 0.890 against 0.837 (+0.053) |
| 8. Free-text answers no longer: ≤ 1.05 × v17's | **Met:** 890 characters against 918 |
| 9. It holds at size (reported) | **Met:** single −0.015, multi 0.000, free text −0.009 against the small set |

**The claim (rules 1 to 8) is not met,** because of rule 4.

**The hash-seed check:** v18 asked again under hash seed 1 gave the same answer to all 587 questions.

## Results

**The messy set** (587 questions: single 140, of them 59 descriptive; multi 56; free text 80; not found 40; counts 60;
history 40; email and chat 40; unanswerable 131):

| arm | single | multi | free text | not found | counts | history | email, chat | unanswerable | mean of 8 |
|---|---|---|---|---|---|---|---|---|---|
| plain search, quotes | 0.121 | 0.036 | 0.556 | 0.000 | 0.000 | 0.000 | 0.322 | 0.000 | 0.129 |
| v1 | 0.774 | 0.083 | 0.000 | 0.225 | 0.000 | 0.175 | 0.175 | 0.176 | 0.201 |
| v2 | 0.641 | 0.036 | 0.006 | 0.250 | 0.000 | 0.225 | 0.223 | 0.023 | 0.175 |
| v17 | 0.862 | 0.839 | 0.671 | 0.800 | 0.783 | 0.950 | 0.950 | 0.840 | 0.837 |
| **v18** | **0.869** | 0.839 | **0.681** | **1.000** | **0.950** | 0.950 | 0.950 | **0.885** | **0.890** |

**The tidy set** (the same questions, the generated ones in the generators' own words; reported, not decided on):

| arm | single | multi | free text | not found | counts | history | email, chat | unanswerable | mean of 8 |
|---|---|---|---|---|---|---|---|---|---|
| v17 | 0.929 | 0.946 | 0.671 | 1.000 | 1.000 | 1.000 | 1.000 | 0.885 | 0.929 |
| **v18** | 0.929 | 0.946 | **0.681** | 1.000 | 1.000 | 1.000 | 1.000 | **0.908** | **0.933** |

On the tidy wording v17 already had not found and counts right; the messy wording is what v18 fixed.

**v18 minus v17** (messy set; paired over the questions; 95% bootstrap interval):

| | questions | v18 − v17 | 95% interval | better | worse |
|---|---|---|---|---|---|
| not found | 40 | +0.200 | +0.075 to +0.325 | 8 | 0 |
| counts | 60 | +0.167 | +0.083 to +0.267 | 10 | 0 |
| unanswerable | 131 | +0.046 | +0.015 to +0.084 | 6 | 0 |
| free text | 80 | +0.010 | −0.050 to +0.067 | 7 | 4 |
| single | 140 | +0.007 | 0.000 to +0.029 | 1 | 0 |
| multi, history, email and chat | 136 | 0.000 | | 0 | 0 |
| all | 587 | +0.044 | +0.027 to +0.063 | 32 | 4 |

**Time:** a median of 1.37 s a question for v18 and 1.30 s for v17, asked side by side on a busy machine (round 3's run, on a
quieter machine, gave 0.87 s for v17).

**The questions:**
- **Writers** (blind, sealed, casual) kept 59 of 60 descriptive, 97 of 100 free-text and 91 of 125 held-out questions; 50
  descriptive (the mix's cap) and 80 free-text were drawn.
- **Rewriters** reworded the 366 generated questions; all 366 passed the check.

## The four families

**Not found (40 of 40).** v17 answered 8 of the 10 made-up titles from a similar real document (the described route). The splice
check now catches all 10. The other 30 (invented keys, pull request numbers and names) were already "not found".

**Counts (57 of 60).** All 10 counts v17 missed are now right. The 3 still wrong were wrong for v17 too:
- two counts by the planner, one too many ("enterprise tier hubspot accounts with Arjun Patel as the solutions enginer", a
  typo; "google drive docs in the shared_drives drive area that Marisol Vega owns");
- one filtered list ("linear issues w/ high customer impact and an estimate of 3"), answered with a field value.

**Unanswerable (116 of 131).** 6 more right than v17, none fewer:
- the own-terms check refused 2 free-text quotes about things the company does not have ("clusterization", "Mistral
  Therapeutics");
- 3 came from the empty-field check now running before free text ("the meeting … has no crm deal id");
- 1 came from the check on plans from a named person.

Of the 15 still answered, 12 are free-text quotes from a near document (a "cost-probe sidecar PR" quoted from another probe's
document), and 3 are empty fields answered from another field (a CSM name, a customer impact).

**Free text (0.681).** Of the 80 questions, BM25 found the right document for 79. Of v18's 30 answers short of full marks:
- 23 were answered from the right document, with the answer facts in it, but left one or more facts out (18 quotes, and 5
  answers of other routes);
- 7 were "not found": 6 with the right document (2 of them the own-terms check's typo refusals below), 1 with a wrong one.

The 11 answers that changed:
- **7 better:** the quote picked a sentence holding the asked value (a deletion date and an audit id; a default TTL; a date
  for "by when").
- **2 worse, refused for a typo:** the own-terms check found "supossed" and "mixup" in no document. "supossed" is two
  slips of a letter from "supposed", and the check allows one; "mixup" is "mix-up" written as one word.
- **2 worse, a worse sentence:** the quote dropped a fact v16's quote had held.

**Why development misled.** Development's free-text gain (+0.05 on dev5k, +0.08 to +0.10 on the seen test sets) came from
sets whose questions shaped the quote, or from tidier wording. The test's writers write more casually and with more typos, and
the quote's weights (picked on pooled development sets) did not carry over.

## Checks

- **The freeze came first:** commit `bbf5b50` at 01:12:14 UTC; the test documents were drawn from 01:12:21.
- **The held-out documents of rounds 2 and 3** (94 and 98) were left out of the draw and of the held-out pool.
- **Nothing about the test was read before the scores were written.** Every step printed counts, hashes and batch names
  only; writers and rewriters wrote to files and returned counts.
- **Step 5 stopped once,** when the container was restarted while the arms answered:
  - every file of steps 1 to 4 had been written before the stop and was not changed;
  - step 5 was run again from its start (it collects the rewrites only when the messy folder does not yet exist, and had
    collected them);
  - all arms answered both sets again, in one run.
- **Every step's error file stayed empty.**
- **Hash seed 1:** v18 gave the same 587 answers.
- **The small control sets** held the same questions; rule 9 was met.

## What it means, and what is next

**v18 is a better brain than v17:**
- a question about a document the company does not have is now "not found", however it is typed;
- counts typed casually are counted;
- questions with no answer are refused more often;
- nothing else got worse, apart from 2 free-text answers refused for a typo.

**Its free text is not better.** The quote changes help on some questions and hurt on others; on fresh questions they come out
even.

**Next steps:**
1. **An answer writer for free text** (a language model writing the reply from the document v18 finds). In 79 of 80 questions
   the right document was found; picking sentences by their words is what falls short.
2. **The own-terms check needs a better typo test** (two slips of a letter, joined compounds), or should run only when the
   question names something capitalised.
3. **A standard AI search baseline** and **a pilot on real data**, as before.
