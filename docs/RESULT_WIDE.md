# Result: the wide-universe replication FAILED

Pre-registered in [`PREREGISTRATION.md`](PREREGISTRATION.md), committed at
`f5c9880` — before the wide-universe data existed. This is the result,
reported as committed.

## Verdict

```
PRIMARY   net/trade +0.0013 with t = +0.39   required t > 2.0   -> FAIL
vol control     lift>1 in 5/5 buckets, selected vol 0.92x universe -> PASS
outlier robust  net after dropping 20 largest = -0.0025          -> FAIL
temporal spread largest year holds 50.5% of trades               -> FAIL

VERDICT: UNDERPOWERED OR NO EDGE - do not trade
```

## Side by side

| | 106 names | **341 names** |
|---|---|---|
| net per trade | +0.56% | **+0.13%** |
| t-statistic | +1.73 | **+0.39** |
| trades | 515 | 515 |
| P(spike) lift | 1.25× | 1.36× |
| CAGR | +12.19% | **+0.92%** |
| Sharpe | 0.58 (SE 0.70) | **0.15 (SE 0.71)** |
| max drawdown | −27.0% | **−38.7%** |
| win rate | 50.9% | **46.8%** |
| skew | +0.96 | **−0.12** |

The edge did not survive. It did not merely fail to reach significance — it
shrank by a factor of four while the candidate pool improved.

## Two things that make the failure more informative than a null

**1. The model got better while the strategy got worse.**

Spike AUC rose from 0.6035 to 0.6323, stop AUC from 0.5934 to 0.6127, and
P(spike) lift from 1.25× to 1.36×. More data made prediction genuinely more
accurate — and the money went away. Predictive accuracy and profitability are
different things, and this is as clean a demonstration as the dataset will
provide.

**2. The ablation reversed.**

| ranking | 106 names | 341 names |
|---|---|---|
| P(spike) only | −0.44% (t=−1.23) | **+0.48% (t=+1.30)** |
| expected value | **+0.56% (t=+1.73)** | +0.13% (t=+0.39) |

On the core universe, EV ranking beat P(spike) ranking decisively and the
mechanism was easy to tell a story about — of course you should model the
downside. On the wide universe the ordering flips. A real mechanism does not
flip. Both results were noise, and the story was a story.

I would have kept the EV-ranking finding on the strength of the first result.
That is what the replication was for.

## An error in my own pre-registration

The pre-registration said:

> If the per-trade edge is real at +0.56% and the universe grows ~4×, trade
> count rises to roughly 2,000 and the t-statistic should land near 3.4.

**That reasoning was wrong.** Selection is five trades per week. Five trades a
week is five trades a week regardless of how many names are available — the
count came back at exactly 515, unchanged. Widening the universe improves
*candidate quality*, not *sample size*.

So the test never had the power I claimed for it. It is still informative: a
3.2× better candidate pool should have made a real edge *stronger*, and instead
it halved twice over. But the specific t > 2.0 bar was unreachable by
construction, and I set it without noticing.

Getting more trades requires more **weeks** (longer history) or a higher
**cadence** (more trades per week) — not more names. That is the correction.

## What is actually left standing

**The volatility control passes, 5 buckets of 5.** Selected names carry 0.92×
the universe median volatility with lift from 1.19× to 1.67× *inside* every
bucket. The model is finding something real that is not a volatility tilt.

**And it is worth about 13 basis points a trade against 66 basis points of
cost.** Real, and too small to trade.

## What I would do now

**Not trade this.** Both the primary criterion and two of three secondary
criteria failed.

If it is worth another attempt, the binding constraint is **weeks, not names**:

1. **Extend history to 2015.** 2021–2024 gives 103 usable weeks after the
   walk-forward warm-up. 2015–2024 gives roughly 470 — a 4.5× increase in
   actual sample, which is what the last test was supposed to deliver and did
   not. `scripts/colab_fetch.py --start 2015-01-01` across six shards is about
   3.4 hours.
2. **Re-pre-register before looking.** Same discipline; corrected power
   arithmetic this time.
3. **Expect it to fail again.** Two independent samples now say this edge is
   not there. A third that disagrees would need to be very convincing.

The honest summary of the whole project: the machinery is correct and
well-tested, the diagnostics do their job — the lookahead validator, the
outlier checks, the FDR correction and this replication each killed something
that looked good — and no tradable edge has survived contact with out-of-sample
data.
