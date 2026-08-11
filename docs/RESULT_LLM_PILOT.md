# Reading the filings with a model instead of a regex

The regex arm is closed. Twenty-seven hand-written patterns per filing moved the
walk-forward ranking by **−0.217pp** with a confidence interval from −0.838 to
+0.412, and a text-only model reached **0.5366** separability against **0.5365**
for price alone — the same number, meaning the two carried the *same*
information rather than complementary information. The patterns recovered what
kind of filing it was. The panel already knew that from the 8-K item codes.

So the question became whether a reader gets more out of the same documents. The
full corpus is 7,601 filings and reading it costs real money, so the cheap test
came first.

## The protocol

64 filings, drawn from the 7,600 that have a realised ten-session return, split
evenly: 32 that went on to make **≥ +15%** net of costs, and 32 that lost
**≥ 10%**. Both tails are well populated — 907 winners and 1,887 losers in the
corpus — so the sample is a genuine case-control draw, seeded and reproducible.

Blindness is structural, not a promise. `llm_pilot.py --build` writes reading
bundles containing *only* anonymised document text, and writes outcomes to a
separate `truth.parquet`. The reader sees the bundles. `--score` is the first
step that joins the two. There is no way to peek without it appearing in the
command history.

Anonymisation replaces the issuer's legal name and ticker with `COMPANY`. It is
imperfect — exhibit file names, websites, drug names and officers' signatures
leak identity — so the build flags each filing with whether the identity was
**verifiably** removed, and the result is re-measured on that subset. 53 of 64
came out clean.

## What the reading found

The reader was asked for five numbers per filing. `impact` — the expected signed
ten-session move — was designated the primary score before scoring.

| field | AUC | 95% CI | P(≤0.5) |
|---|---|---|---|
| **impact** (primary) | **0.646** | [0.510, 0.773] | 0.018 |
| direction of the news | 0.581 | [0.444, 0.712] | 0.122 |
| substance of the disclosure | 0.460 | [0.326, 0.597] | 0.723 |
| **dilution imminence** | **0.321** | [0.203, 0.452] | 0.996 |
| the reader's own confidence | 0.482 | [0.357, 0.609] | 0.608 |

Two of these matter.

**Dilution at 0.321 is the strongest single signal in the table.** An AUC that
far *below* 0.5 is not a failure, it is an inverted predictor: read the other
way round, "no imminent share issuance" separates winners from losers at
**0.679**, better than the headline judgement. Reading the financing terms —
executed ATM, equity line, closed convertible, priced deal — beats reading the
news.

**The reader's confidence is worthless.** 0.482. It does not know when it knows.
That is the third time this project has found the same shape: the panel model's
score level carried +0.0093 rank correlation, the checklist's confidence tiers
were non-monotone, and now this.

Combining the two informative fields:

| score | AUC | 95% CI | P(≤0.5) |
|---|---|---|---|
| impact alone | 0.646 | [0.510, 0.775] | 0.021 |
| no-dilution alone | 0.679 | [0.544, 0.799] | 0.006 |
| **impact − dilution** | **0.700** | [0.566, 0.826] | 0.004 |
| impact + direction | 0.631 | [0.494, 0.765] | 0.032 |

For reference, the same win-versus-lose question on the 108 numeric panel
features reached **0.5302** out of sample.

## It is reading, not remembering

The obvious objection is that the reader recognises the event and recalls what
happened. The leakage split answers it:

| subset | n | AUC |
|---|---|---|
| identity verifiably removed | 53 | **0.641** |
| identity leaked | 11 | 0.767 |

The clean subset scores essentially the same as the full sample — 0.641 against
0.646. The edge does not depend on knowing who filed. (The leaked subset scores
higher, which is what recall would look like, but eleven filings is far too few
to read anything into.)

## The level is wrong even where the ranking is right

Rank correlation between the predicted move and the realised one is **+0.243**.
Sign agreement is **45.3%** — worse than a coin. Bucketing by predicted impact:

| quartile | n | mean return | win rate |
|---|---|---|---|
| 1 (lowest) | 16 | −4.54% | 37.5% |
| 2 | 16 | +12.99% | 50.0% |
| 3 | 16 | +6.24% | 43.8% |
| 4 (highest) | 16 | +11.87% | 68.8% |

Monotone at the ends, noise in the middle. The ordering carries information; the
number attached to it does not. Anyone using this should rank with it and ignore
the magnitude, exactly as with the panel model.

## The comparison that decides whether to pay

The honest test is not "does the reader beat chance" but "does the reader beat
the regex on the same documents". Scoring all 27 regex features on these same 64
filings, and letting the regex pick its best feature **with hindsight** — a
generosity the reader was not given:

| reader | AUC |
|---|---|
| best regex feature (`tox_any`, inverted, chosen in-sample) | 0.656 |
| LLM `impact − dilution` (fixed before scoring) | 0.700 |
| **paired difference** | **+0.043, 95% CI [−0.066, +0.150], P(≤0) = 0.214** |

**The gap does not clear noise on 64 filings.** That is the result.

There is a second, more uncomfortable reading of that table. `tox_any` reaches
0.656 *here* while contributing nothing panel-wide. The case-control design —
big winners against big losers, nothing in between — is a far easier problem
than ranking a day's 199 candidates. So **0.700 must not be extrapolated to the
panel**; if anything, the regex's inflated showing on this sample is direct
evidence of how much the design flatters both readers.

## Where this leaves it

The pilot did what a pilot should: it made the full run defensible rather than
speculative, and it moved the estimate without settling it.

* A reader does extract something the panel does not have, it survives the
  anonymisation control, and at 0.700 it is the highest separability anything in
  this project has produced against a 0.5302 baseline.
* Most of that comes from reading financing terms, which partly re-derives a
  signal already established — the 8-K item 3.02 veto tested at 15.1% against
  26.9% disaster rate.
* The margin over regex on identical documents is +0.043 with a CI through zero.
* The sample design makes every number here an upper bound on panel behaviour.

Only the full extraction settles it, run through the same harness the regex arm
went through so the comparison stays like-for-like: same 70 tickers, same
covered rows, only the feature columns differing.

`llm_extract.py` is that run, and it needs an API key this container does not
have. Measured cost for all 7,600 filings, 16.2M input and 6.8M output tokens
through the Batches API:

| model | batch cost |
|---|---|
| `claude-opus-5` | $126 |
| `claude-sonnet-5` | $81 |
| `claude-haiku-4-5` | $27 |

It asks for 25 fields per filing — p-values reported versus significant, patient
counts, trial phase, whether the lead endpoint was primary and whether it was
met, partner tier, imminence of issuance, and the two summary judgements that
carried this pilot — writes JSONL keyed by accession so an interrupted run
resumes free, and emits the same table shape as `text_features.py` so
`merge_text_panel.py` and `text_value_test.py` consume it unchanged.

## Known imperfections

* **2.6% of filings never reach the panel.** `merge_text_panel.py` joins on an
  exact ticker-date, so 197 of 7,601 filings whose availability date is not a
  trading day for that ticker are silently dropped. `llm_pilot.py` uses a
  forward search instead and does not lose them. The share is too small to
  explain the regex arm's null, but the merge should adopt the forward search
  before the full LLM arm is scored.
* **The reader here was in-context, not an API call.** Same model family and the
  same documents, but a production run is not bit-identical to this pilot.
* **64 filings.** Every interval in this document is wide and says so.
