# Result: the 2015–2026 test failed. This is the end of the line.

Pre-registered in [`PREREGISTRATION_2015.md`](PREREGISTRATION_2015.md),
committed at `37bdfb7` before the events, features, labels or model for this
window existed. Reported as committed.

## Verdict

```
PRIMARY   net/trade -0.0015  t_clustered = -0.66  (naive t = -0.85 over 278 weeks)
          required clustered t > 2.0                              -> FAIL
vol control     lift>1 in 3/5 buckets, selected vol 0.83x universe -> PASS
outlier robust  net after dropping 20 largest = -0.0029           -> FAIL
temporal spread largest year holds 18.8% of trades (cap 35%)      -> PASS
ablation        EV -0.0015 vs P(spike) -0.0077                    -> PASS

VERDICT: NO EDGE - stop.
```

**The primary criterion failed on the sign, not on significance.** The strategy
did not merely fail to prove itself profitable; it lost money.

## The three samples

| | 106 names<br>2021–24 | 341 names<br>2021–24 | **3,662 names<br>2015–26** |
|---|---|---|---|
| trades | 515 | 515 | **1,386** |
| usable weeks | 104 | 104 | **278** |
| net per trade | +0.56% | +0.13% | **−0.15%** |
| t (naive) | +1.73 | +0.39 | **−0.85** |
| t (week-clustered) | — | — | **−0.66** |
| CAGR | +12.19% | +0.92% | **−5.36%** |
| Sharpe | 0.58 (SE 0.70) | 0.15 (SE 0.71) | **−0.19 (SE 0.44)** |
| max drawdown | −27.0% | −38.7% | **−58.4%** |
| win rate | 50.9% | 46.8% | **44.4%** |
| spike AUC | 0.6035 | 0.6323 | **0.7056** |

Monotone in both columns that matter, in opposite directions. Every increase in
data made the model **more accurate** and the strategy **less profitable**.

This was the test designed to distinguish the first two samples: the +56 bps
hypothesis predicted t ≈ 3.1 here, the +13 bps hypothesis predicted t ≈ 0.7.
The answer came in below both.

## What the failure actually is

Not the model. The model is good, and got better every time it was fed more:

```
spike AUC   0.6035  ->  0.6323  ->  0.7056
stop  AUC   0.5934  ->  0.6127  ->  0.6631
calibration  mean p 0.2132 vs realised 0.2132   (exact to four decimals)
```

An AUC of 0.71 on 2,535,913 out-of-fold rows is a real, well-measured,
well-calibrated forecast. It is also attached to the worst economics of the
three runs. **This is the cleanest demonstration the project will produce that
predictive accuracy and profitability are different quantities.**

The selection ladder says exactly where it dies:

```
trades/wk      n  P(spike)   lift     gross    cost       net       t
       20   3993    0.2289   1.07x   +0.0035  0.0068   -0.0033   -3.19
       10   2766    0.2375   1.11x   +0.0035  0.0068   -0.0033   -2.59
        5   1386    0.2525   1.18x   +0.0052  0.0068   -0.0015   -0.85
        3    834    0.2614   1.23x   +0.0060  0.0068   -0.0008   -0.32
        2    556    0.2626   1.23x   +0.0059  0.0068   -0.0008   -0.29
        1    278    0.2698   1.27x   +0.0078  0.0068   +0.0010   +0.24
```

Selectivity works exactly as designed — lift climbs monotonically from 1.07× to
1.27× as the bar rises. **And gross return never reliably clears the 68 bps of
cost.** The only row where it does is one trade a week, at +10 bps net with
t = +0.24, which is 278 trades of noise.

That is the whole result. The signal is real, it is worth 35–78 bps a trade
gross, and it costs 68 bps to harvest.

## The mechanism is real and it does not save the strategy

The expected-value ranking — the thing `iai.moonshot` exists to do — works:

| ranking | P(spike) | stop rate | net |
|---|---|---|---|
| P(spike) only | 0.3860 | 56.7% | −0.77% |
| expected value | 0.2525 | **33.4%** | **−0.15%** |

Modelling the downside separately cuts the stop rate by 23 percentage points
and improves net by 62 bps. That is a large, coherent effect, and it agrees
with the 106-name run, so criterion 4 passes.

It is also not enough. A mechanism can be genuine and still not clear costs.
Those are different claims and only the second one pays.

Worth stating plainly: **ranking on P(spike) alone is significantly negative**
(t = −3.49, clustered −2.75). The model correctly identifies names that are
about to move 10%, and buying them loses money at −77 bps a trade. Whatever
makes a small-cap spike is not something a buyer captures.

## What survived

**Temporal spread passes for the first time.** The largest year holds 18.8% of
trades against a 35% cap — eleven years of history did what it was supposed to,
and the failure is not a regime artefact.

**The volatility control passes**, but weakly and worth reading honestly: lift
exceeds 1.0 in 3 of 5 buckets, not 5 of 5 as in both prior runs, and bucket 0
is 0.96 while bucket 3 is 1.0000. Selected names carry 0.83× universe
volatility, so it is not a volatility tilt — but the in-bucket skill is thinner
than before.

**The outlier check fails.** Dropping the 20 largest moves takes net from
−0.15% to −0.29%, so what little the strategy has is concentrated in a handful
of trades.

## The stopping rule

The pre-registration fixed this before the data existed:

> **Primary fails → stop.** Three independent samples, the third one properly
> powered. There is no fourth test that would be honest, because by then the
> only remaining moves are changing the target, the horizon, or the universe —
> and searching over those is how you manufacture the result you wanted.

It applies. Three samples, monotone, ending below zero on the one that was
actually powered.

The pre-registration also said: *"I expect it to fail. Writing that down now is
the point: it is what makes a pass meaningful rather than a thing I talked
myself into."* That was written before the data existed and it is the reason
this result can be believed.

## What this does not say

It does not say catalyst trading cannot work, that small caps are efficient, or
that SEC filings carry no information. It says one specific configuration —
insider and filing catalysts, +10%/−7% absolute barriers, ten sessions, five
trades a week, small/mid caps, retail execution costs — does not clear its
costs, and that three samples agree.

It also does not clear the residual caveat the pre-registration recorded in
advance: free price data is survivorship biased, so a long strategy's returns
here are biased **upward** by an unknown amount. The true result is, if
anything, worse than −0.15% per trade.

## Two things worth taking forward

Neither rescues this strategy. Both are real and were measured along the way.

1. **Insider *selling* is roughly half noise.** 39–59% of open-market sales are
   pre-scheduled 10b5-1 executions, consistently across a decade. Buying is
   only 3–12% scheduled. See [`FINDINGS.md`](FINDINGS.md).
2. **News-day execution costs 30 bps more than calm-day execution**, which is
   45% of the total cost line. Entering before the crowd is worth real money —
   to a strategy that has an edge. It cannot manufacture one: −0.15% against a
   36 bps cost is still negative.

## The honest summary of the whole project

The machinery is correct and well tested. The diagnostics did their job
repeatedly and expensively — the lookahead validator caught same-day Form 4s
time-travelling, the FDR correction killed a t = −2.07 "discovery", the first
replication killed the EV finding, and an adversarial review of this run's own
code caught an issuer-matching bug that was silently discarding 18–30% of
open-market insider buys before the analysis ever ran.

No tradable edge survived contact with out-of-sample data. That is a real
result, arrived at honestly, and it is worth more than a backtest that looked
good.
