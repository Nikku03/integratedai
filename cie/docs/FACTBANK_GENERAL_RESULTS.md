# New words from general English, without a language model: results

**Run on 2026-10-08**, by the rules in `docs/FACTBANK_GENERAL_PREREGISTRATION.md`. Those rules were written before the
general-English word counts were built. The frozen choice and its fingerprints were added to that document before the
run.
- **Raw results, development results, the writers' wordings and the review:** `docs/benchmarks/factbank_general/`.
- **Code:** `cie/src/cie/factbank/lexicon.py` (`build_general`, the general-English counts) and `cie/src/cie/factbank/plans.py`
  (`Planner.lenders`, reading nearness from both word spaces).

## In short

**General English did not help.** The planner with word meanings from the company's documents and from 321 million
words of general English (v6) answered 0.769 of the 50 blind questions. That is exactly what the company's word meanings
alone (v5) answered. The planner with no word meanings (v4) answered 0.727.

**Why:**
- The questions' new words were mostly politeness: "could", "please", "thanks", "let me know". The content words were
  mostly ones training had seen.
- General English did give a few real meanings that the company's text lacked: "progress" → "status", "wrote" →
  "author", "whose" → "who". None of these changed an answer on this set.
- Several real new words still found no close known word: "plate", "soonest", "tied", "stand", "sitting".

**A review found five problems in the evaluation code and fixed or measured all of them.** None changes a decision in
any of the five tests. One published number moves: v6 on this test's changed copy goes from 0.806 to 0.769.

## Decision

| Rule | Result |
|---|---|
| 1. New words are understood (v6 − v4 ≥ +0.10) | **Not met:** 0.769 against 0.727 (+0.042) |
| 2. General English adds to the company's words (v6 − v5 ≥ +0.05) | **Not met:** 0.769 against 0.769 (0.000) |
| 3. Principles, not memorisation (test set ≥ training − 0.15) | **Not met:** 0.769 against 0.927 (−0.158) |
| 4. It holds when the information changes (changed ≥ test set − 0.05) | **Met:** 0.806 against 0.769 as run. With the fixed changed copy, 0.769 against 0.769 |
| 5. No harm where v4 already worked (v6 ≥ v4 − 0.03, retest set and training) | **Met:** retest 0.657 against 0.596; training 0.927 against 0.927 |

## Results

Own answers, no model (the mean is the mean of the three groups):

| | link | combine | compare | mean |
|---|---|---|---|---|
| test set, v1 (untrained) | 0.278 | 0.000 | 0.000 | 0.093 |
| test set, v4 (no word meanings) | 0.556 | 0.875 | 0.750 | 0.727 |
| test set, v5 (company words) | 0.556 | 0.875 | 0.875 | 0.769 |
| test set, **v6 (company + general English)** | 0.556 | 0.875 | 0.875 | **0.769** |
| changed copy as run, v4 / v5 / v6 | | | | 0.764 / 0.769 / 0.806 |
| changed copy, fixed, v4 / v5 / v6 | | | | 0.727 / 0.769 / 0.769 |
| retest set (seen), v4 / v5 / v6 | | | | 0.596 / 0.631 / 0.657 |
| training, v4 / v5 / v6 | | | | 0.927 / 0.927 / 0.927 |

**Where the versions differ:**
- **One question on the test set:** "Between {a} and {b}, which ticket has the earlier deadline?" v4 compared the
  creation dates. v5 and v6 compared the due dates, because "deadline" borrowed "date" from both word spaces.
- **Two more questions on the changed copy as run.** These are the renamed-status questions (see Corrections).
  - On the copy as run, v6 got these two right and v5 got them wrong. That made the changed copy look better than the
    original.
  - On the fixed copy, the three versions score as they do on the test set.

**The right plan was always there.** For all 50 questions, one of the enumerated plans gives the right answer. v6 ranked
it first for 38 and within the top three for 41.

**What new words borrowed** (looked at after the run):
- 220 uses of words that no training question used. The company's word space lent a meaning to 112 of them, v6 to 175.
- **The extra borrowings were mostly politeness words borrowing pronouns:** "me" → "someone", "you" → "someone",
  "please" → "them", "thanks" → "owner"/"author". They did no good and, on this set, no harm.
- **A useful one:** "progress" → "status" came only from general English.

## What it learned

**The general-English counts** (`general_lexicon_info.json`):
- WikiText-103 train and two C4 files: 18.4 million sentences and 321 million words.
- 80,000 words kept, window 2, 200 dimensions.
- Built in 11 minutes. The text was streamed and never stored.

**Development words** (training, retest and new-words sets only; general English against company text):

| word | general English | company text |
|---|---|---|
| wrote | author 0.56 | nothing near |
| whose | who 0.57 | nothing near |
| responsible | assign 0.40 | who 0.41, owner 0.35 |
| tally | first 0.59 (wrong), numb(er) 0.50, total 0.48 | nothing near |
| soonest | when 0.43, date 0.35 | nothing near |
| progress | status 0.41 | status 0.41 |
| deadline | date 0.76 | date 0.62, earliest 0.51 |

**What did not work:**
- Several general-English neighbours are wrong: "ship" → "assign", "target" → "count", "nearest" → "open".
- Many similarities sit below 0.5, so more words lend meaning at the chosen 0.4. That lets more noise in.

## Development (the choice, by the rule fixed before development)

| how the spaces combine | closeness | held-out wording | retest set | new-words set | mean |
|---|---|---|---|---|---|
| company only (v5) | 0.5 | 0.752 | 0.631 | 0.576 | 0.653 |
| general only | 0.4 / 0.5 / 0.6 | 0.752 | 0.590 | 0.613 / 0.611 / 0.611 | 0.652 / 0.651 / 0.651 |
| the higher | 0.4 / 0.5 / 0.6 | 0.752 | 0.622 / 0.622 / 0.606 | 0.620 / 0.576 / 0.576 | 0.665 / 0.650 / 0.645 |
| **the mean** | **0.4** / 0.5 / 0.6 | 0.752 | **0.657** / 0.622 / 0.622 | 0.611 | **0.673** / 0.662 / 0.662 |

## The review, and what it changed

After the run, four independent reviewers, each an agent session with its own area, read the whole evaluation pipeline
and its data. A fifth session tried to refute each finding. The full findings are in `review.json`. What held up, and
what was done:

1. **The changed copies renamed statuses** (found before the review, while explaining the changed-copy score).
   - "In Progress" and "In Review" look like two-word names, so `factbank_split.changed` renamed them as people: in the
     documents and in the expected answers. "PM: Jordan Lee" was also renamed apart from "Jordan Lee". This affected
     3–7 questions in the changed copy of each multi-document test.
   - **Fixed:** values of status-like fields are no longer people, and a label before a name is dropped.
     `legacy=True` rebuilds the old copies exactly.
   - **Checked:** every changed copy was rebuilt and every version rerun on it (`changed_fixed_check.json`).
   - **Effect:** every information-change rule is still met, and the tested version now scores exactly what it scores
     on the original (0.083, 0.596, 0.576, 0.769). The one published number that moves is v6's changed score here,
     0.806 → 0.769. The single-document test's changed copy had no such status; its v2 is still 0.550.
2. **The company lexicon held 24 of this test's 50 documents.**
   - The lexicon was built before this test set was drawn, and only the documents of earlier sets were left out. 24 of
     this set's documents were therefore in its 200,000-document sample, against the pre-registration's "no document of
     any test set".
   - **Checked:** the lexicon was rebuilt from the same sample without them (`lexicon200k_w2_noblind.npz`, sha256
     `ef926ef4bfd23048…`). v5 and v6 give the same answer for all 50 questions on the test set and both changed copies
     (`leak_check.json`). Retraining gives the same weights.
   - **No number changes**, but the stated claim was false. The lexicon build can now drop a set's documents after
     sampling. Later sets must also leave out the lexicon's sample.
3. **One-key questions were scored with F1.** "Which is due first?" and "a person's first issue" answered with two
   keys scored 0.667, where the pre-registrations say a single key must match exactly.
   - **Fixed** (`own_score` in `factbank_multi.py`).
   - **No published number changes:** every published report was recomputed. Only an unpublished run had such answers.
4. **A customer attendee is matched to the same-named engineer's tickets.**
   - Action items are joined to Linear assignees by name alone. In 15 questions (5 training, 3 retest, 3 new-words,
     4 here), the owner is a customer attendee who inherits a Redwood engineer's issues.
   - **Without those questions** (`action_owner_check.json`): v4 0.735, v5 0.777, v6 0.777 here, and training 0.941.
     Every rule keeps its outcome (rule 1 +0.042, rule 3 −0.164).
5. **One document carries many questions.**
   - Ticket keys are reused across the benchmark, so a few documents are the target of many questions. 4 of this set's
     8 pull-request questions reach the same ENG-4821 document, and all 8 of the first held-out set's.
   - So the sets hold fewer independent questions than they count, and a kind's score can swing as a block.
   - The reviewer rescored with these grouped, and no rule changes.

**Also found, smaller:**
- The changed copies' pool of new names (28 first × 20 last) makes people share a first name more often than in the
  original. This flipped one v2 answer in the first test, and no rule.
- Meeting timestamps are not date-shifted.
- `Planner.enrich`'s cache ignored its settings. It was not triggered, and is now fixed.
- The results docs said "every piece for 0.99 of the questions" where the measure is the average share of pieces.
  Corrected in `FACTBANK_MULTI_RESULTS.md` and the README.
- The retest pre-registration compared a share of questions (0.917) with a group mean (0.309).
- The "no harm" rules are scored partly on the retest set, which development used. All ten development choices would
  have passed them.

## Limits

- **Few truly new words.** The blind writers mostly used the words the training questions use. The new ones were mostly
  politeness, so this test says little about content words such as "plate" or "soonest".
- **Small numbers.** 50 questions, several sharing one document. One question moves a group's score by 0.04–0.17.
- **General English is not company English.** The general counts know "wrote" means "author" but not that "put up a PR"
  means opening one.

## Reproduce

```bash
python -m cie.eval.factbank_multi fresh --index index.json --root <benchmark> --exclude <earlier sets> --out $T --seed 29 --wordings blind
python -m cie.eval.factbank_split changed --work $T --out $TC              # the fixed copy; --legacy for the copy as run
python -I -m cie.factbank.lexicon general --out general_w2.npz --window 2  # WikiText-103 + C4, streamed
python -m cie.eval.factbank_multi train --work $TRAIN --single lessons.json --plans plan_lessons_v6.json --rules v4 \
  --lexicon lexicon200k_w2.npz --general general_w2.npz --combine mean --floor 0.4
python -m cie.eval.factbank_multi ask --work $T --single lessons.json --plans plan_lessons_v6.json --name factbank_v6
python -m cie.eval.factbank_multi general --work $T --changed $TC --train $TRAIN --retest $RETEST
```
