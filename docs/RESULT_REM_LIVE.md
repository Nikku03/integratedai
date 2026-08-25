# Testing the REM model on genuinely unseen data

The panel ends 2025-12-31 and every number in `RESULT_REM.md` was walk-forward
inside it. This fetches fresh bars — **3,655 of 3,662 tickers returned data
through 2026-08-24**, 586,302 bars the model has never seen — and scores it on
data that did not exist at training time.

## First, a mistake I made and caught

The initial run had **no liquidity screen**, and it reported arm B at **+14.19%
per trade** and arm C at **+30.96%**. Both were nonsense. The picks were:

```
CNBX   $0.0001   $50/day of dollar volume
GTCH   $0.0001   $73/day
LIPO   $0.00025  $0/day   (zero volume)
CYTOF  $0.063    $19/day
YGMZF  $0.002    $93/day
```

The tell was in the returns themselves — `+50.00%`, `+25.00%`, `+0.00%`,
`+75.00%` — exactly round, because on a stock priced at $0.0001 a single tick
*is* fifty percent. Against the panel's own screen, whose eligible rows have a
**5th-percentile average dollar volume of $1.4 million**, these names are four to
six orders of magnitude too small to trade. The spread alone would exceed the
gain.

The fix is a $1m ADV and $1.00 price floor computed from OHLCV, which reproduces
the panel's screen closely. Everything below is post-fix. **Any figure from the
unscreened run should be discarded.**

## The windows

A ten-session label needs ten sessions *after* entry, so the most recent fifteen
sessions cannot be graded — scoring them on truncated paths would flatter or
punish at random. So:

* **Scored:** 2026-07-21 → 2026-08-10, 15 sessions, outcomes complete.
* **Live:** 2026-08-04 → 2026-08-24, 15 sessions, predictions only.

Trained on 200,000 rows dated before 2026-06-17 — a five-week gap ahead of the
scored window, well clear of the ten-session label overlap.

Arm D, the gradient booster on the 108 panel features, is **absent**: it needs
filings, fundamentals and insider data that were not refetched. Only the arms
that read pure OHLCV extend to live data.

## Result

| arm | scorable picks | mean | median | win rate | best | worst |
|---|---|---|---|---|---|---|
| A REM only (closed form) | 15 | −0.83% | +1.84% | 73.3% | +41.7% | −47.9% |
| **B REM + residual** | 15 | **−1.94%** | −0.13% | 40.0% | +19.7% | −20.6% |
| C direct MLP | 15 | **+2.49%** | +2.53% | 60.0% | +37.5% | −26.0% |
| **the universe itself** | 4,118 | **+2.43%** | | | | |

**Nothing beat owning the universe.** The market handed out +2.43% over that
window; the best arm matched it and the proposed model lost 1.94%, underperforming
by 4.4 percentage points.

Arm B's fifteen picks:

```
2026-07-21  IVF    $  1.04  ADV $ 15.4m    +0.96%
2026-07-22  WRAP   $  1.78  ADV $ 10.3m    +9.04%
2026-07-23  PACK   $  6.31  ADV $  3.2m   -15.29%
2026-07-24  ALOT   $ 28.71  ADV $  4.0m    +0.31%
2026-07-27  BZH    $ 33.05  ADV $ 13.3m    -0.81%
2026-07-28  GBTG   $  9.42  ADV $ 13.9m    +0.32%
2026-07-29  GCTS   $  1.74  ADV $  4.1m   +19.89%
2026-07-30  AMC    $  2.77  ADV $117.7m    -4.36%
2026-07-31  TOP    $ 10.30  ADV $  1.3m   +11.19%
2026-08-03  SG     $  5.92  ADV $ 39.4m    -0.68%
2026-08-04  KSCP   $  1.62  ADV $  4.3m    -9.43%
2026-08-05  WRAP   $  1.93  ADV $ 10.3m   -17.01%
2026-08-06  SAFT   $103.50  ADV $ 36.7m    +0.08%
2026-08-07  ALOT   $ 28.94  ADV $  3.3m    +0.07%
2026-08-10  CRSR   $ 13.71  ADV $ 23.9m   -20.42%
```

Real listed names with $1.3m–$118m of daily volume. The pipeline runs end to end
on live data and the picks are plausible — which was the point of the exercise.

## Five picks a session

Same window, same model, `--k 5`. Seventy-five scorable trades instead of fifteen.

| arm | n | mean | median | win | vs universe | 95% CI (day-clustered) | P(≤universe) |
|---|---|---|---|---|---|---|---|
| A REM only | 75 | +4.48% | +1.22% | 61.3% | +2.00pp | [−2.69, +7.91] | 0.251 |
| **B REM + residual** | 75 | **+4.62%** | +1.71% | 58.7% | **+2.14pp** | [−3.04, +8.04] | 0.238 |
| C direct MLP | 75 | **+5.51%** | +4.97% | 62.7% | **+3.03pp** | [−0.67, +6.90] | **0.055** |
| the universe | 4,118 | +2.48% | | | | | |

Now **all three beat the pool** on the point estimate, by two to three percentage
points. And **none of them clears significance.** Every interval contains zero;
C comes closest at P = 0.055.

The intervals are clustered by session, which is not a technicality. Five picks
taken on the same morning share that day's market move, so this is **fifteen
independent observations, not seventy-five**. Treating them as seventy-five
would shrink the interval by more than half and manufacture a result that is not
there.

### The k=1 to k=5 flip is the whole lesson

At one pick a session, arm B returned **−1.94%**. At five picks a session, over
**the identical window with the identical model**, it returns **+4.62%**. Nothing
changed except how many names were taken each day.

A six-and-a-half point swing from that alone is the clearest possible statement
that fifteen sessions cannot evaluate anything. Neither number is informative
about the model; both are draws from a distribution wide enough to contain them
comfortably.

There is a smaller caution underneath it: re-running the identical script gave
arm B a mean of +3.92% on one pass and +4.62% on the next, because multi-threaded
CPU reductions are not bit-reproducible. That is half a point of pure
implementation noise sitting under every figure in this table.

### What survives all of it

Arm A — the closed-form solver with **no network at all** — beats the universe by
+2.00pp, against B's +2.14pp. Whatever separated the pool from the picks over
these fifteen sessions, the neural correction contributed almost none of it. That
is consistent with `RESULT_REM.md`, where B trailed the incumbent on the traded
metric across fourteen walk-forward blocks.

## What fifteen trades can say

```
n = 15, mean -1.74%, standard error 2.77pp
95% interval on the mean: [-7.28%, +3.79%]
```

The walk-forward estimate was **+0.127% per trade**. This window cannot confirm
or refute it — the interval swallows both that figure and the observed −1.94%.
**This is a smoke test, not evidence.** Fifteen observations against a
per-trade standard deviation near 20% cannot resolve an effect of one percent.

What it *does* establish: the feature pipeline extends to unseen data without
error, the eligibility screen is load-bearing, and the picks are executable names
rather than artefacts.

## One thing the live window does show

The model's predicted magnitudes are badly calibrated. It forecast **+4% to +6%**
on almost every live pick and **+22%** on TOP, against a realised **−1.94%** on
the scored window. Predicting the level and ranking by it are different jobs, and
`RESULT_REM.md` already found that the arms with the best squared error trade
worst. This is the same thing visible from the other side.

Live picks, ungraded:

```
2026-08-11  CERT  $  8.13  ADV $ 30.6m   +3.69%      2026-08-18  HCTI  $  1.07  +6.58%
2026-08-12  VSXY  $ 93.02  ADV $153.5m   +4.56%      2026-08-19  STIM  $  3.14  +5.32%
2026-08-13  CRNX  $ 84.44  ADV $232.3m   +4.97%      2026-08-20  BANL  $ 12.30  +15.11%
2026-08-14  TOP   $ 11.13  ADV $  1.1m  +22.12%      2026-08-21  ALOT  $ 28.92  +5.19%
2026-08-17  EU    $  1.13  ADV $  4.1m   +4.55%      2026-08-24  RFAI  $ 51.04  +6.10%
```

## Caveat carried forward

The test universe is the panel's 3,662 tickers, of which 3,655 still trade — it
is a survivor list by construction, and this window inherits that. It does not
matter much for a forward test on currently-listed names, but it means the
candidate pool is not the real 2026 universe either.

## Reproducing

```
python3 scripts/rem_test_recent.py            # ~20 min including the fetch
python3 scripts/rem_test_recent.py --k 5      # five picks a session
```
