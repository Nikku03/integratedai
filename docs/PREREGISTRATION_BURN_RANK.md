# Pre-registration: within-window burn rank

Committed **before** the result exists.

## The hypothesis

Absolute cash burn separated the tails strongly in-sample (up share 27.3% → 62.5%
across quintiles, ρ=+0.225, p=0.00001, surviving a market-cap control at p=0.0009)
and failed out of sample (AUC 0.7236 → 0.5320). The diagnosis was that the base
rate moved further than the signal: the up:down ratio swung 4.3× across five
quarters, from 2.00 to 0.46, so a model fitted in a bullish regime met a bearish
one.

**If that diagnosis is right, ranking burn against contemporaneous peers rather
than an absolute threshold should recover the signal**, because a relative rank
carries no regime level.

## The specification

**Rank.** For each readout at time `t`, its burn percentile among **all readouts
in the preceding 90 days**, strictly before `t`. Expanding-trailing and causal —
no readout is ranked against anything that had not yet happened. Readouts with
fewer than 20 prior peers in the window are dropped.

**Cohorts.** HIGH = top tercile of that rank, LOW = bottom tercile.

**Outcome.** Over the 25 sessions after the next session's open:
`up = max_up ≥ +50%`, `down = max_dn ≤ −30%`. These are the thresholds already in
use, unchanged.

**Primary statistic.** The HIGH−LOW spread in `P(up) − P(down)`, computed **within
each calendar quarter** and pooled.

## Criteria, fixed now

| criterion | threshold |
|---|---|
| **PRIMARY** | pooled HIGH−LOW spread > 0 with bootstrap 95% CI excluding zero |
| **REGIME** | spread positive in **at least 4 of 5** quarters |
| supporting | monotone across the three terciles |
| supporting | survives controlling for market cap |
| sanity | ≥ 300 ranked events, else underpowered and reported as such |

**The REGIME criterion is the point of the test.** A signal that is positive only
in the bullish quarters has not solved the problem the absolute version had, and
fails regardless of the pooled number.

## What would falsify it

- Pooled spread ≤ 0, or a CI spanning zero.
- Spread positive in 3 or fewer quarters — that is the same regime-dependence
  under a new name.
- The spread tracking the quarter's own base rate, i.e. large when the market is
  up and negative when it is down.

## Known weaknesses

**Same data.** This re-uses the 1,538 readouts the absolute-burn result came from.
It is a re-specification test, not fresh evidence: it can show the relative form
survives where the absolute form did not, and cannot show the underlying
relationship is real. Only a different period can do that.

**Survivorship.** The ticker list is a current snapshot; biotechs that failed and
delisted are absent, and they are the left tail. Any positive result is an upper
bound.

**Not a strategy.** The HIGH−LOW spread requires shorting microcap biotech, which
earlier work here showed is impractical (borrow 20–100% annualised, adverse moves
to +220%). A positive spread is evidence the signal exists, not a tradable claim.
