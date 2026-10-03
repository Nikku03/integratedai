# Quoting evidence-only answers: what is measured and what decides the default, fixed before the test run

I wrote this before running anything on the test half below. The setting was chosen on the development half only.

## Question

Without a model (strict mode), the answer is extractive. Today it gives the top memory records' summaries and the
start of their text (`cards`). On the 5,000-document memory bank, every answer fact reached what a model would read
for 72% of judged questions, but the evidence-only answer itself held only 12% of the checkable answer facts. Most of
its length repeats the memory card: the summary twice, then tags and people.

`quotes` (`cie.retrieval.answer.quote_answer`) quotes the sentences of the first 20 packet items that best match the
question instead:
- a sentence scores the IDF-weighted share of the question's search terms it holds, less a small penalty for a
  lower-ranked item;
- each chosen sentence brings the one after it;
- memory-card lines (summary, tags, people) are skipped;
- at most 1,100 characters, labels included; each quoted item is named by its title and cited.

The evidence check, declines and conflicts are unchanged: they run before the answer is composed. Exact-field
questions with a value keep today's value-and-quote answer.

**Does quoting put more of the answer in the evidence-only answer, at no greater length?**

## Development (odd question numbers, 189 judged questions)

Tenant `erbfull-5000-9688c2`, BM25 with document expansion (the defaults), evidence audit (`cie.eval.evidence_audit`).

| | cards (today) | quotes |
|---|---|---|
| answer facts in the answer (of 673) | 79 (12%) | 171 (25%) |
| questions with every fact in the answer | 20 | 51 |
| mean answer length | 1,137 characters | 1,035 characters |
| longest answer | 1,792 characters | 1,088 characters |
| declined (insufficient evidence) | 4 | 4 |

Settings tried in a prototype on the same half (facts in the answer): 1,100 characters with a pool of 12 items: 158;
pool of 20: 167 (chosen); pool of 20 with no rank penalty: 159; 800 characters: 136. The code above is the chosen
setting.

**Fixed for the test:** pool 20, window 1 (the next sentence), rank penalty 0.15, 1,100 characters, 60-character
labels.

## Test run

The evidence audit on the **even half**, once with `CIE_EXTRACTIVE_ANSWER=cards` and once with `quotes`, same tenant
and defaults. Run once.

The fact check is the audit's: a fact counts as in the answer when every number in it appears as a whole number and
at least 70% of its content words appear after stemming. It is lexical, not a judge.

## Criteria

`quotes` becomes the default evidence-only answer (`extractive_answer = "quotes"`) if all of these hold:

1. **More facts.** Answer facts in the answer: at least 1.5 times as many as `cards`.
2. **More complete answers.** Questions with every fact in the answer: at least 1.5 times as many as `cards`.
3. **Not longer.** The mean answer length is at most `cards`' mean, and no answer exceeds 1,100 characters.
4. **Same declines.** The number of declined answers (insufficient evidence) and conflict answers each differ from
   `cards` by at most 1.

## Reported, with no threshold

- Both measures by question type.
- On Colab, the benchmark judge's correctness for the evidence-only answers (Part 1c grades them when no model
  composes answers).

## Decisions fixed in advance

- **All criteria met.** The default becomes `quotes`. `cards` stays available (`CIE_EXTRACTIVE_ANSWER=cards`).
- **Any criterion fails.** The default stays `cards`, and `quotes` stays available.

Every result is reported, including failures.

## Outcome of the test (added after the run)

**Every criterion was met** on the even half: 233 facts in the answer against 85 (2.74 times), 65 questions with every
fact against 18, mean length 1,050 against 1,141 characters (longest 1,087), and declines and conflicts identical.
The default evidence-only answer is now `quotes`.

After the test, an acceptance test showed that quoting raw passages mixed an old fee with a later amendment's for an
"as of" question. Questions that name a date or ask for an earlier version now keep the card answer, and superseded
records are never quoted. Re-measured (not pre-registered): 227 facts against 85, 64 complete answers against 18.
Details are in `docs/QUOTES_RESULTS.md`.
