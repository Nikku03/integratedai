# Pre-registration: wide-universe replication of the moonshot result

**Committed before the wide-universe data was fetched.** Check the git history:
if this file's commit is not an ancestor of the commit reporting the result,
the test is worthless and should be treated as such.

## What is being tested

The moonshot configuration produced, on 106 names over two out-of-sample years:

| metric | value |
|---|---|
| net return per trade | **+0.56%** |
| t-statistic | +1.73 |
| trades | 515 (5.0/week) |
| P(spike) lift over universe | 1.25× |
| stop rate | 36.1% |
| Sharpe | 0.58 (SE **0.70**) |

The estimate is positive and statistically meaningless — the standard error is
larger than the estimate. This test asks whether the per-trade edge survives on
roughly four times the universe.

## The hypothesis, stated before seeing the data

> Ranking small/mid-cap candidates by modelled expected value of an absolute
> +10%/−7%/10-session barrier trade, and taking the best five per week, earns a
> positive net-of-cost return per trade.

## Exact configuration — frozen

No parameter below may be changed after seeing the wide-universe result. If any
is changed, the run is exploratory and must be reported as such.

```
profile            Config.moonshot()
target             +10%
stop               -7%
horizon            10 sessions
entry              open of the session after the signal date
selection          top 5 per calendar week, ranked by EV
ranking            EV = P(target)*0.10 - P(stop)*0.07 + P(neither)*E[r|time]
models             two LightGBM ensembles (target, stop), 3 seeds each
validation         purged walk-forward, 5 splits, purge 12d, embargo 3d
calibration        isotonic, fitted on pooled out-of-fold predictions only
cost               2 x total_cost_bps($25,000 order, news_day=True)
position weight    10%
universe           iai.seeds.SMALLMID_SEED, point-in-time cap $50m-$10bn
period             2021-01-01 .. 2024-12-31
command            python scripts/moonshot.py --trades-per-week 5
```

## Success criteria, decided in advance

**Primary.** Net return per trade > 0 with **t > 2.0**.

The 106-name run gave t = 1.73 on 515 trades. If the per-trade edge is real at
+0.56% and the universe grows ~4×, trade count rises to roughly 2,000 and the
t-statistic should land near 3.4. A result of t > 2.0 on the wide universe is
therefore a genuine pass, not a lowered bar.

**Secondary, all three required for the result to be called clean:**

1. **Volatility control.** Lift > 1.0 inside at least three of five volatility
   buckets. Selected median volatility must not exceed 1.2× the universe
   median. (Prevents "the model just picks volatile names".)
2. **Outlier robustness.** Net return per trade stays positive after removing
   the 20 largest outcomes by absolute return.
3. **Temporal spread.** No single calendar year holds more than 50% of the
   selected trades.

**Deflated Sharpe** will be reported with `n_trials = 35` (30 configurations
tried during development, plus this run and a small allowance). It is expected
to remain below 0.95 even on a pass; the primary criterion is the per-trade
t-statistic, because the portfolio Sharpe is bounded by only two years of
out-of-sample history regardless of universe size.

## What each outcome means

| outcome | interpretation | action |
|---|---|---|
| t > 2.0, all secondary pass | edge is probably real | paper trade a quarter |
| t > 2.0, a secondary fails | edge is confounded by whatever failed | investigate, do not trade |
| 0 < t < 2.0 | still underpowered or edge is smaller than measured | do not trade; the 106-name result was optimistic |
| t < 0 | the 106-name result was noise | stop; the shape does not work |

## Commitments

- The wide-universe run is reported **whatever it shows**, including a failure.
- No configuration is tuned after seeing the result. If something obviously
  broken is found (a data bug, not a disappointing number), it is fixed, the
  fix is described, and the run is re-labelled exploratory.
- The 106-name result is not re-run or re-tuned to match.
- Universe differences that are *not* free parameters — how many seed names
  resolve to prices, how many pass the cap screen — are reported as observed.
