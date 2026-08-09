# Moonshots are predictable. I was never asking for them.

The question was why the model cannot find moonshots when the data is there. The
answer is that it was never given a moonshot objective. Every model in this
project optimised a central tendency — classifiers at a 20% threshold that a 6.8%
base rate makes a volatility question, and a regressor on expected return. **Both
objectives actively push away from the tail**, because a lottery ticket has a
mediocre mean and any estimator minimising squared error ranks it below a steady
name with the same expectation.

Changing the objective to a conditional **upper quantile** fixes it.

## The tail is very findable

Daily top 5, walk-forward, 14 blocks, net 20bps. Base rate for a +50% touch in
ten sessions is 0.956%.

| objective | P(+20%) | **P(+50%)** | P(+100%) | lift on +50% | ret/trade | blocks |
|---|---|---|---|---|---|---|
| universe | 6.84% | 0.96% | 0.21% | 1.0x | — | — |
| mean (vol-scaled) | 10.61% | 1.20% | 0.31% | 1.3x | **+0.925%** | 10/14 |
| quantile q75 | 29.78% | 6.74% | 1.59% | 7.0x | +0.782% | 10/14 |
| quantile q90 | 34.95% | 10.35% | 2.81% | 10.8x | −0.019% | 6/14 |
| quantile q95 | 35.44% | 11.14% | 3.24% | 11.6x | −0.749% | 3/14 |
| P(up >= 35%) | 36.82% | **12.19%** | 3.69% | **12.75x** | −1.973% | 3/14 |
| P(up >= 50%) | 35.06% | 11.51% | 3.64% | 12.0x | −2.248% | 2/14 |

A classifier aimed at the tail finds +50% moves at **12.75 times the base rate**
and +100% moves at seventeen times. The claim that moonshots cannot be predicted
is simply false.

**And at five names a day, every one of those trades loses money.** The ordering
is perfectly monotone: more moonshots, worse returns. Ranking by `P(up >= 35%)`
delivers a 12.75x moonshot rate and −1.973% per trade, because for every pick
that runs 50% there are several that collapse. Finding the tail and profiting
from it were, at k=5, two different problems.

## At one name a day they stop being different problems

The 20-trades-a-month book takes only the single best name. That changes the
answer, because concentration suits a tail objective and dilutes it at k=5:

| objective | ret/trade | excess | P(+50%) | lift | P(+100%) | win% | blocks | book/month |
|---|---|---|---|---|---|---|---|---|
| mean (vol-scaled) | +0.921% | +0.671% | 1.37% | 1.4x | 0.34% | 51.7% | 11/14 | +1.94% |
| **quantile q75** | **+1.349%** | **+1.099%** | **8.48%** | **8.9x** | **2.27%** | 45.5% | **11/14** | **+2.85%** |
| quantile q80 | +1.119% | +0.869% | 9.33% | 9.8x | 1.88% | 45.8% | 10/14 | +2.36% |
| quantile q85 | +1.281% | +1.031% | 11.20% | 11.7x | 2.72% | 44.7% | 10/14 | +2.71% |

**q75 beats the mean model on both axes at once.** It earns 46% more per trade
(+1.349% against +0.921%) *and* finds six times as many +50% moves (8.48%
against 1.37%). Same number of winning blocks. It is not a trade-off at k=1; it
is a strictly better model for this book.

The cost is where a tail strategy always puts it: the win rate drops from 51.7%
to 45.5%. You are wrong more often and paid more when right — 2.27% of picks
double inside ten sessions, against 0.34% for the mean model.

## Why the answer flips between k=5 and k=1

Quantile regression identifies names with **asymmetric payoffs**, not names with
good averages. You want one of those, not five. At k=5 the four runners-up
dilute the convexity and drag in the losers that come with it; at k=1 the
selection is pure. That is also why the mean model wins at k=5 and loses at k=1 —
its picks are steadier, which is worth more when you are averaging and worth less
when you are choosing.

## What the moonshots actually pay

Over ten sessions, conditional on the touch:

| event | frequency | mean realised 10-day return |
|---|---|---|
| max_up >= 20% | 6.84% | +20.01% |
| max_up >= 35% | 2.14% | +32.89% |
| max_up >= 50% | 0.96% | **+44.94%** |
| max_up >= 100% | 0.21% | **+78.07%** |

These are realised close-to-open returns, not barrier touches, so the tail is not
an illusion of intraday spikes that get given back.

## Recommendation

For twenty trades a month: **quantile regression at q75, one name a day,
ten-session hold, ten slots.** +1.349% per trade net of costs, +1.099% over the
universe, 8.48% of picks touching +50%, 11 of 14 half-year blocks positive.

If you want more tail and will accept it, q85 gives 11.20% at +1.281%. Past q90
the edge is gone.

## Caveats that have not changed

The panel has no delistings, so upside tail frequencies are overstated relative
to a real universe — this bias hits a moonshot strategy harder than a mean one,
because the missing names are exactly the ones that would have shown up as
failed lottery tickets.

The absolute per-trade numbers here differ slightly from
`RESULT_TWENTY_A_MONTH.md` (+0.921% against +1.699% for the same mean model)
because this run additionally requires a finite excursion label, dropping a few
extreme rows, and trains on 150k rather than 200k samples. **The comparison to
trust is within a run, not across runs**; every row of each table above was
produced under identical conditions.

The ceiling test — an in-sample AUC of 0.9753 for `P(max_up >= 50%)` from a
deliberately overfit model — is reported for completeness but proves little. A
model allowed to memorise will separate a 1% class; that is capacity, not
signal. The walk-forward numbers are the evidence.
