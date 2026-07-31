# Result: the within-window burn rank passes

Pre-registered in [`PREREGISTRATION_BURN_RANK.md`](PREREGISTRATION_BURN_RANK.md),
committed at `ebeb36f` before the result existed. Reported as committed.

## Verdict

```
PRIMARY   HIGH-LOW spread +10.83pp   bootstrap 95% CI [+4.65pp, +17.00pp]
          required CI excluding zero                          -> PASS
REGIME    positive in 5 of 5 quarters (required >= 4)         -> PASS
monotone  LOW -7.6pp  MID +0.8pp  HIGH +3.2pp                 -> PASS
cap ctrl  survives regression; mixed within cap bands         -> PARTIAL
sample    1,485 ranked events (required >= 300)               -> PASS

VERDICT: PASS. The relative form survives where the absolute form did not.
```

**This is the first pre-registered test in this project to pass.**

## The test

Each readout's cash burn ranked against **all readouts in the preceding 90 days**
— strictly causal, minimum 20 peers. 1,485 of 1,505 events ranked.

| tercile | n | P(+50%) | P(−30%) | spread | median burn | median cap |
|---|---|---|---|---|---|---|
| LOW | 499 | 13.0% | **20.6%** | **−7.6pp** | $22.8m | $157m |
| MID | 519 | 13.7% | 12.9% | +0.8pp | $92.9m | $348m |
| HIGH | 467 | 10.5% | **7.3%** | **+3.2pp** | $249.1m | $2,265m |

HIGH−LOW = **+10.83pp**, Welch t = +3.40, p = 0.0007.

## It holds in every regime — which is what the test was for

| quarter | n | HIGH | LOW | **spread** | quarter base rate |
|---|---|---|---|---|---|
| 2025 Q2 | 67 | +27.8pp | +8.0pp | **+19.8pp** | +17.9pp |
| 2025 Q3 | 314 | +6.4pp | −2.9pp | **+9.3pp** | +7.0pp |
| 2025 Q4 | 346 | +13.0pp | −9.1pp | **+22.1pp** | 0.0pp |
| 2026 Q1 | 398 | −1.6pp | −10.8pp | **+9.2pp** | −5.5pp |
| 2026 Q2 | 360 | −7.9pp | −10.0pp | **+2.1pp** | −8.6pp |

**Positive in all five, including the two quarters where the base rate was
negative.** The absolute-burn version collapsed from AUC 0.72 to 0.53 across
exactly this shift; the relative version does not.

## And it beats size in a horse race

OLS of (up − down) on burn rank, HC0 errors:

| specification | burn coefficient | t |
|---|---|---|
| burn alone | +0.188 | **+4.33** |
| + market cap | +0.144 | **+2.48** |
| + cap, dollar volume, price | +0.210 | **+3.27** |
| *reverse: cap controlling for burn* | *+0.026* | *+1.08* |

**Market cap becomes insignificant once burn is included; burn stays significant.**
Given how strongly the two are related — median cap $157m in LOW against $2,265m
in HIGH, 14.4× — that is the more informative direction.

## Three things it is not

**It avoids losers; it does not find winners.**

| | P(+50%) | P(−30%) |
|---|---|---|
| LOW burn | **13.0%** | 20.6% |
| HIGH burn | 10.5% | **7.3%** |

The LOW tercile has *more* moonshots. The entire spread comes from the downside:
7.3% against 20.6%, a 2.8× difference in crash rate. This is a **quality filter**,
and calling it a way to find the big movers would be exactly backwards.

**The within-cap-band evidence is thin.** Burn and size are nearly collinear, so
the cells are badly unbalanced and only one band is significant:

| cap band | HIGH n | LOW n | spread | t | p |
|---|---|---|---|---|---|
| small | 15 | 299 | +19.0pp | +1.54 | 0.141 |
| mid | 127 | 127 | **−8.7pp** | −1.39 | 0.167 |
| large | 320 | 69 | +12.4pp | +2.14 | **0.035** |

The mid band is negative. With 15 HIGH-burn small caps and 69 LOW-burn large caps,
these cells cannot carry much weight either way — but they are not the clean
confirmation the regression suggests.

**The spread still decays with the regime.** +19.8 → +9.3 → +22.1 → +9.2 → +2.1.
Correlation with the quarter's own base rate is ρ = +0.70 (p = 0.188 on five
quarters). It never turns negative, which is the pre-registered criterion, but the
trend is the direction the falsifier warned about and five quarters cannot resolve
it.

## Applied to the trade, it halves the loss and does not cross zero

The clinical-readout trading rule that failed out of sample, filtered by burn:

| cohort | n | mean | median | win | t |
|---|---|---|---|---|---|
| all trades | 1,485 | −2.31% | −1.36% | 43% | −5.86 |
| burn LOW | 499 | **−3.59%** | −2.42% | 40% | −5.61 |
| burn MID | 519 | −2.15% | −1.15% | 43% | −3.33 |
| burn HIGH | 467 | **−1.10%** | −0.80% | 47% | −1.45 |
| POSITIVE + not LOW | 605 | −1.57% | −0.94% | 45% | −2.32 |
| **POSITIVE + HIGH burn** | **287** | **−0.91%** | −1.05% | 45% | −0.85 |

Best cohort: **−0.91%, 95% CI [−2.88%, +1.27%]**. Monotone improvement across
terciles — the filter is doing real work — but it converts a clearly losing
strategy into one indistinguishable from zero, before costs.

And by quarter it still decays: +9.24%, +5.47%, +1.02%, −4.25%, −5.45%.

## What this establishes

**The diagnosis was right.** The absolute-burn signal failed because the base rate
moved further than the signal, and re-specifying it as a contemporaneous rank
recovers it — passing a pre-registered regime criterion that the absolute form
could not.

**The signal is downside avoidance, worth roughly 13 percentage points of crash
rate.** Companies that spend real money on development crash far less often on a
trial readout than companies that do not. That is economically sensible and it is
now measured.

**It is not enough to trade.** −0.91% with a CI spanning zero, before the 60–120bp
round trip these names cost, is not a strategy. What it is, is the first component
in this project that survived being pre-registered — and the right use of it is as
a **blacklist**: whatever else is done with clinical readouts, the bottom burn
tercile should not be bought long.

**Still the same period.** This is a re-specification of the same 1,538 readouts,
so it shows the relative form is robust where the absolute one was fragile. It
cannot show the relationship holds in another year. That test has not been run.
