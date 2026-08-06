# Pre-registration: ADRNN two-head moonshot model

Written before the dataset is built and before any result is seen. Everything
below is frozen. If a number disappoints, the number gets reported, not the
specification.

This project has killed four of its own hypotheses (catalyst type p=0.759;
clinical sentiment OOS p=0.809 on 940 trades; the RVOL gate, which ran
backwards; and this morning's pre-open filter, which lost to its own reject
pile by 0.75pp). Every one of them looked good until it was tested on data that
had not been used to build it. That is the only reason this document exists.

## What is being predicted, and why it is not the obvious thing

The stated goal is to see a moonshot coming with at least thirty minutes of
warning. The event itself cannot be predicted at all: if the move is caused by
news that becomes public at time T, no model has access to it at T-30min. On
3 Aug 2026 every one of 94 filings landed before the open, and REPL's +107%
traded no fillable price between $5.41 and $11.38.

So the target is not the event. It is the **state that precedes the event**:
given everything knowable about a company at the close of day *t*, how likely
is a large move in the following ten sessions?

This is worth doing because of an asymmetry that is real and well established:
the magnitude of returns is autocorrelated and forecastable, while the sign is
close to a martingale. Every failed test in this project attacked the sign.
Magnitude has never been attacked here at all.

## Universe and period

* `w2015_prices`: 3,662 tickers, 2015-01-02 to 2025-12-31, daily OHLCV.
* Rows required to be `tradable` with 20-day `adv_usd` >= $1,000,000 at the
  prediction date. An untradeable prediction is not a prediction.
* Minimum 250 prior trading days, so every sequence is full.

## Label

Prediction is made at the **close of day t**. Entry is the **open of day t+1**,
which is the earliest fillable price and gives roughly 17.5 hours of lead time
-- far more than the thirty minutes asked for, and unlike thirty minutes it is
actually achievable.

Over the window t+1 open to t+H close with **H = 10** trading days:

```
entry   = open[t+1]
max_up  = max(high[t+1 .. t+H]) / entry - 1
max_dn  = min(low [t+1 .. t+H]) / entry - 1
y_mag   = 1 if max(max_up, -max_dn) >= 0.20
y_dir   = 1 if max_up >= -max_dn        (defined only where y_mag == 1)
```

`y_dir` is trained with a **masked loss**: rows with `y_mag == 0` contribute
nothing to the direction head. Asking which way a move went when there was no
move is asking about noise.

Bars with an absolute daily move over 60% and no accompanying volume are
treated as split artifacts and dropped, per the reverse-split problem already
found in this data (DBGI 40.8x, EDBL 37.5x).

## Features

All features are computed from information with `available_ts <= t` (the events
table carries this field, and 0.00% of rows have availability before the event).
Fundamentals are forward-filled from the filing that disclosed them, never from
a period end that had not yet been reported.

**Price block** -- returns over 1/5/20/60d; realised volatility over 5/20/60d;
log price; log dollar volume; RVOL against a 20-day median; position within the
60-day range; and the trailing 20-day maximum absolute excursion, which is the
direct autocorrelation term the magnitude head is expected to lean on.

**Event block** -- counts in trailing 5/20/60-day windows of each 8-K item code
(1.01, 2.01, 2.02, 2.03, 3.01, 3.02, 5.02, 5.03, 5.07, 7.01, 8.01, 9.01), of
forms 10-Q, 10-K, S-3, 424B5, SC 13D, SC 13G, and of insider buy, sell and
cluster-buy. Days since the most recent of each.

**Registration block** -- the dilution-armed score from `dilution_armed.py`,
reconstructed historically from S-3 and 424B5 events. This is the one screen
built this session that has a documented mechanism rather than a fitted
coefficient.

**Fundamental block** -- log market cap, cash over market cap, runway years,
liabilities over cash, share-count growth, profitability and pre-revenue flags.

**Government block** -- FDA approval and contract events from `gov_events`,
as counts and recency.

## Architecture

ADRNN, as chosen: attention over a residual recurrent stack.

* input projection F -> d_model = 128
* 3 residual GRU blocks, `h = h + GRU(LayerNorm(h))`, dropout 0.1
* 4-head self-attention over the 60-step time axis, then attention pooling
* two linear heads on the pooled vector: magnitude and direction
* loss = BCE(magnitude) + `lambda` * masked BCE(direction), `lambda` = 1.0
* AdamW, lr 1e-3, cosine decay, early stopping on validation magnitude AUC

Class imbalance is handled by positive weighting in the BCE, not by resampling,
so calibration is preserved.

## Splits

Strictly temporal, never shuffled. A random split of a price panel leaks the
future through cross-sectional correlation and is the single most common way
this kind of model produces a fake result.

| split | period | use |
|---|---|---|
| train | 2015-01-01 .. 2022-12-31 | fitting |
| validation | 2023-01-01 .. 2024-06-30 | early stopping, threshold choice |
| test | 2024-07-01 .. 2025-12-31 | **touched once, at the end** |

A 10-day embargo is applied at each boundary so no label window straddles a
split.

## Baselines the model must beat

A neural network that cannot beat a one-variable logistic regression has
learned nothing worth the complexity.

1. **Base rate** -- predict the training frequency of `y_mag` for everyone.
2. **Trailing volatility** -- logistic regression on 20-day realised volatility
   alone. This is the honest bar, because volatility clustering already
   predicts large moves and any credible result must exceed it.
3. **Gradient boosting on flat features** -- the same features with the time
   axis collapsed to the last row. Isolates whether the sequence matters.

## Pass/fail criteria, fixed now

**Primary (magnitude).** Test-set AUC of the magnitude head exceeds the
trailing-volatility logistic baseline, with a bootstrap 95% CI on the paired
difference excluding zero. Bootstrap is clustered by week to respect the
cross-sectional correlation of returns.

**Secondary (usable).** Precision at the top 20 names per day exceeds the test
base rate, CI excluding zero. This is the number that decides whether the thing
is tradeable, since a ranked daily shortlist is how it would be used.

**Direction.** Test AUC of the direction head, on the `y_mag == 1` subset, with
a bootstrap 95% CI excluding 0.50.

**Registered prediction, so it cannot be claimed afterwards:** I expect the
magnitude head to pass and the direction head to fail. Four independent
directional tests in this project have already failed, and nothing in this
feature set is obviously more informative about sign than what those used. If
direction passes it will be treated as surprising and re-tested before being
believed.

## The caveat that outranks every result below it

**The panel has no survivors problem -- it has a survivors catastrophe.** Zero
of 3,662 tickers stopped trading before the panel ends. Not one delisting,
bankruptcy or liquidation in eleven years, in a universe that includes hundreds
of small-cap biotechs. The true figure should be 40-60%.

The consequences are specific and asymmetric:

* Absolute returns everywhere in this repo are optimistic. Already known.
* The names deleted from the panel are disproportionately the ones that fell
  90% and never recovered, so **the direction head is trained on a world where
  large moves are more often upward than reality**. Any direction result is
  biased toward the answer the model is being asked to produce, which is the
  worst possible direction for a bias to run.
* The magnitude head is less exposed, since a name heading to zero is volatile
  either way, but it is not unexposed.

No result in this study should be read as an estimate of live performance. The
comparison against baselines is meaningful because every baseline is computed
on the same biased panel; the absolute numbers are not.

Fixing this needs a delisting-inclusive universe (CRSP, or reconstructing
delistings from EDGAR Form 25 and 15 filings). That is a separate build, and
until it exists this model can be used to rank names against each other on a
given day but not to estimate what it will earn.

---

## Amendment 1 — 2026-08-03, before the ADRNN was trained

Recorded before any ADRNN result existed. The baselines had been run; the
network had not.

The frozen architecture (d_model 128, three residual GRU blocks, 250,000
training samples, 60 timesteps) costs roughly **2.5 hours per epoch** on the
four CPU cores available here, so the eight-epoch protocol would take about
twenty hours. A recurrent stack is sequential over its 60 steps and does not
parallelise across cores, so this is not a tuning problem.

Changed, for compute reasons only:

| | frozen | run |
|---|---|---|
| d_model | 128 | 64 |
| residual GRU blocks | 3 | 2 |
| training samples | 250,000 | 120,000 |
| epochs | 8 | 6 |
| batch | 256 | 512 |

Unchanged: the feature set, the label, the 60-step sequence, the temporal
splits and embargo, the train-only scaler, the week-clustered bootstrap, the
baselines, and every pass/fail criterion.

This weakens the model, so it makes the primary criterion **harder** to pass,
not easier. If the ADRNN fails, the honest reading is that this study did not
demonstrate a sequence model beats the flat baselines *at this capacity* --
not that no sequence model could. If it passes at reduced capacity, the result
stands on its own.

The baseline numbers this is measured against, fixed here so they cannot drift:
trailing-volatility logistic **0.8260**, gradient boosting **0.8738**, test base
rate **14.67%**.
