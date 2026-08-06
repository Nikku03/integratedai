# ADRNN result: magnitude is predictable, direction is not usable, and the
# sequence model lost to gradient boosting

Run against `docs/PREREGISTRATION_ADRNN.md`, whose criteria were fixed before
the panel was built. Test period 2024-07-01 to 2025-12-31, scored once,
94,375 samples across 3,304 tickers.

## The three headline numbers

| | test AUC | verdict |
|---|---|---|
| base rate (14.67%) | -- | -- |
| trailing-volatility logistic | 0.8260 | the pre-registered bar |
| **gradient boosting, flat features** | **0.8730** | **best model** |
| ADRNN (attention + residual GRU) | 0.8618 | passed the bar, lost to boosting |

**Primary criterion: PASS.** ADRNN minus the volatility baseline is **+0.0359**,
week-clustered 95% CI [+0.0262, +0.0449], P(<=0) = 0.0000.

**And it does not matter, because the ADRNN lost to plain gradient boosting on
the same features with the time axis collapsed.** A rank-average of the two
scores 0.8727, which is boosting's 0.8730 within noise. The sequence contributed
nothing. The architecture that was asked for is not the architecture to use.

## Magnitude prediction genuinely works

Ranked daily, taking the top *k* names by score:

| k | hit rate (moved >=20% in 10d) | mean max up | mean max down |
|---|---|---|---|
| 5 | **79.4%** | +29.6% | -25.0% |
| 10 | 72.9% | +27.1% | -22.0% |
| 20 | 64.6% | +24.1% | -18.6% |
| 50 | 47.5% | +18.1% | -14.4% |
| all | 14.7% | +8.7% | -7.5% |

Nearly four in five of the top five names move at least 20% within ten sessions,
against a base rate of one in seven. The prediction is made at the close and
entered at the next open, so the lead time is about 17.5 hours -- not the thirty
minutes asked for, but far more, and unlike thirty minutes it is achievable.

This is the first thing in this project that has passed a pre-registered
out-of-sample test.

## Direction survives its controls and is still not tradeable

The pre-registration predicted the direction head would fail, and committed in
advance to re-testing a pass rather than believing it. It returned 0.5677
pooled, CI [0.5462, 0.5901]. The re-test:

| control | AUC | what it rules out |
|---|---|---|
| pooled | 0.5677 | -- |
| within month | 0.5443 | predicting the era rather than the name |
| within week | 0.5510 | same, tighter |

So roughly 40% of the pooled signal was tracking the drift in `P(up | big move)`
through time, which is useless on any given day because within a day that rate
is a constant. What remains, 0.544 within month, is real but small. The decile
spread is wider than the AUC suggests -- top decile 67.0% up against bottom
decile 43.1%, a 23.9pp spread.

**Then the survivorship catastrophe eats it.** Zero of 3,662 tickers delisted in
eleven years, so the names that fell 90% and never returned are simply absent
from the label:

| assumed missing fraction, all downward | true P(up given a big move) |
|---|---|
| 0% (what the model was trained on) | 54.5% |
| 20% | 43.6% |
| 35% | 35.4% |
| 50% | 27.3% |

A realistic small-cap universe loses 40-60% over eleven years. The direction
head's *ranking* may partly survive that -- ranking is more robust to a shifted
base rate than calibration is -- but every probability it emits is wrong by
roughly the missing mass, and it is wrong in the flattering direction.

## The finding that actually decides the strategy

Among the top-20 daily magnitude picks, over the following ten sessions:

```
P(max_up  >= +20%) = 34.5%
P(max_dn  <= -20%) = 36.3%
```

**Big down-moves are more common than big up-moves among exactly the names the
model flags** -- and that is measured on a panel biased upward by having deleted
every bankruptcy. The real ratio is worse.

So the model answers "when will there be fireworks", not "which way". That is a
volatility signal, not a moonshot signal, and it points at a strategy this
repository cannot evaluate: the picks carry a **median 211% annualised
volatility at the top five and $10.03 median share price**. Options on names
like that are priced for exactly the move being forecast. Predicting volatility
that is already in the premium earns nothing, and there is no options data here
to test whether any of it survives the spread.

## What to do with this

1. **Use gradient boosting, not the ADRNN.** It is better, it trains in about a
   minute, and the sequence model has no measured advantage.
2. **Use it as a watchlist generator, not a signal.** A daily top-20 with a
   64.6% chance of a 20% move is a genuinely good place to point attention.
3. **Do not take direction from the direction head.** Take it from the screens
   that have a mechanism: the dilution-armed registration check, the balance
   sheet, and the dated-catalyst calendar.
4. **Fix the universe before believing any absolute number.** Delistings must
   be reconstructed from Form 25 and Form 15 filings. Until then this model
   ranks names against each other on a given day and cannot estimate what it
   earns.

## Registered prediction, scored

The pre-registration said: magnitude passes, direction fails. Magnitude passed.
Direction nominally passed and then failed the test that mattered -- not the
significance test, which it survived, but the question of whether the number
means anything once the panel's missing bankruptcies are accounted for. Being
half wrong in advance is recorded here rather than quietly revised.
