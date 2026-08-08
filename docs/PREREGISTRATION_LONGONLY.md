# Pre-registration: long-only, risk-adjusted, walk-forward

Written before the run. Frozen.

## Why the previous build could not have worked

Three defects, and they compound.

**The label was monotone in volatility.** `P(|move| >= 20%)` is maximised by the
most violent names in the panel, so the model learned to rank by
`mean_exc_20d` and nothing else mattered (permutation importance +0.15 against
+0.015 for the next feature). A long-only book cannot live in the top volatility
decile.

**The label was not the trade.** The model was trained on whether a barrier was
*touched* and then an exit rule was bolted on afterwards. A name that reaches
+20% intraday on day 3 and gives it back is a win to the label and a loss to the
account. All seventeen exit rules lost money on validation; the best was −0.04%.

**One fixed split hid a regime flip.** The top volatility decile returned +1.1%
in 2015-2022 and −2.2% in 2024-2025. A single train/test split cannot see that,
and the "fix" derived from it was fitted to the later regime.

## What changes

**Target.** Risk-adjusted realised return:

```
ret10   = close[t+10] / open[t+1] - 1          (what a position earns)
y       = ret10 / max(vol_20d, floor)          (per unit of risk taken)
```

Dividing by trailing volatility is the whole point. It is a target the model
**cannot** maximise by selecting violent names, because volatility is in the
denominator. Two secondary targets are run alongside for comparison: raw
`ret10`, and the return under a fixed `TP +20% / SL -10%` bracket.

Regression, not classification. The previous build threw away the difference
between +21% and +200%.

**Evaluation.** Walk-forward. Train on everything up to the start of a block,
predict that block, roll forward, retrain. Six-month blocks from 2019-01 to
2025-12, giving 14 consecutive out-of-sample periods instead of one. Regime
shift is then something the protocol survives rather than something discovered
afterwards.

**Direction.** Long only. No short leg is reported, because it cannot be traded.

**Costs.** 20bps round trip, with sensitivity to 0/10/40/80.

## The benchmark, which is the part that matters

The eligible universe returns roughly +0.17% per ten sessions. **Beating zero is
not the test.** The strategy must beat an equal-weight buy of the eligible
universe over the same windows, because that is what the money would otherwise
do.

## Pass/fail, fixed now

**Primary.** Mean net ten-day return of the daily top-k (k=5), long only, after
20bps, pooled across all 14 walk-forward blocks, exceeds the equal-weight
eligible universe over the same blocks, with a week-clustered bootstrap 95% CI
on the difference excluding zero.

**Secondary (consistency).** The top-k beats the universe in at least 9 of the
14 blocks. A strategy that works in three blocks and is carried by one is not a
strategy.

**Tertiary (is the risk adjustment doing anything).** The vol-scaled target beats
the raw-return target on the primary metric. If it does not, the diagnosis was
wrong and the label change was cosmetic.

## Ablation, to prevent the obvious self-deception

The model will be run twice: with the volatility features, and with every
volatility and excursion feature removed (`vol_5d`, `vol_20d`, `vol_60d`,
`mean_exc_20d`, `max_exc_20d`, `rvol`). If performance is unchanged without
them, the signal is genuinely elsewhere. If it collapses, the model is still a
volatility detector wearing a different label.

## Registered prediction

I expect the vol-scaled target to beat the raw-return target, and I expect the
absolute edge over the universe to be small — under 1% per ten sessions — and to
fail the consistency criterion. Four directional attempts in this project have
failed. Writing the expectation down first is the only thing that stops a
marginal result being reported as a good one.

## Standing caveats

The panel has no delistings, so long-side returns are overstated; the measured
floor on the missing mass is 11.8% and the true figure is higher. Every number
is a within-panel comparison against a benchmark computed on the same biased
panel, which is the only reason the comparison is meaningful at all.
