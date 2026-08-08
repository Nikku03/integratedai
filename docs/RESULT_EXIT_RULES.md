# Exit rules do not rescue the long side, and the explanation I gave was wrong

Two findings, and the second one retracts something from the previous document.

## 1. The volatility inversion is a regime, not a mechanism

`RESULT_WHY_NO_UP.md` explained the up-side failure by a non-monotonic
relationship between volatility and direction: bullish through nine deciles,
inverting in the tenth. That was measured on the test period. Measured on
training:

| period | d6 | d7 | d8 | **d9 (top)** | top-decile mean return |
|---|---|---|---|---|---|
| **train** 2015-2022 | +0.8 | +1.9 | +3.2 | **+6.7** | **+1.1%** |
| **test** 2024-07..2025-12 | +2.2 | +3.5 | +5.6 | **−1.1** | **−2.2%** |

Edge in percentage points, `P(up20) − P(dn20)`.

**In 2015-2022 the top volatility decile was the best bucket in the panel** —
the edge kept rising to +6.7pp and the mean return was positive. In 2024-2025 it
is the worst. The inversion is not a structural property of markets; it is a
feature of the recent regime.

That retracts the mechanism. "Maximising P(|move|) walks the model into the one
decile where up does not happen" is true of the test period and false of the
training period. The correct statement is narrower and less satisfying: **the
model was trained on a regime where high volatility skewed up and deployed into
one where it skewed down.** That is a regime shift, which is exactly the failure
mode the base rates warned about at the start — `P(|move| >= 20%)` swings from
4.46% in 2017 to 23.68% in 2020 in this panel.

It also means the vol-band fix was fitted to the test period. It would have lost
money over 2015-2022 by excluding the best decile.

## 2. No exit rule makes the long side pay

Seventeen rules, frozen before running, selected on validation and reported once
on test. Costs 20bps round trip. Same-day barrier ambiguity resolves **against**
the position; barriers are not honoured on zero-volume bars.

**Every rule loses money on validation:**

| rule | mean | median | win% |
|---|---|---|---|
| TP +20% / SL −10% *(best)* | **−0.04%** | −4.98% | 40.8% |
| SL −10% only | −0.05% | −5.73% | 39.5% |
| time stop day 5 | −0.06% | −1.09% | 44.7% |
| hold to close | −0.19% | −1.98% | 44.5% |
| trail: arm +8%, trail 8% | −0.41% | +0.16% | 50.9% |
| SL −15% only *(worst)* | −0.46% | −2.64% | 42.7% |

The best of seventeen is −0.04%. There is nothing to select.

**And the selected rule fails out of sample:**

```
TP +20% / SL -10%,  test 2024-07..2025-12
n = 1,890   mean +0.46%   median -4.60%   win 41.7%
week-clustered 95% CI [-0.62%, +1.58%]   P(<=0) = 0.2004   -> FAIL
```

Bonferroni for a 17-rule grid puts the required alpha at 0.0029. This does not
reach 0.05.

For completeness, the whole grid on test runs +0.13% to +1.26%, all with
per-trade Sharpe between 0.01 and 0.06 against a 10-20% standard deviation.
`hold to close` is the best rule on test at +1.26% — the opposite of the
validation ranking, which is what noise looks like.

## A bug found and fixed mid-run

The first execution reported **+293.44% mean with a 10,906% standard deviation
and a −4.56% median**. That is not a result, and the cause was mine: `walk()`
had no ticker-boundary check, so a position near the end of one ticker's history
walked into the next ticker's prices — a $2 name followed by a $500 name reads
as a 250x return. `forward_close_return` and `decompose` both guard for this;
this function did not.

Fixed, plus the same |return| <= 3.0 reverse-split guard the label already
carries. Every number above is post-fix. The tell was the median: a mean three
orders of magnitude from the median is a data artifact, never a strategy.

## Where this leaves the long side

The chain of results is now:

1. Magnitude is genuinely predictable — top-1 hits 88.9%, calibrated, 377
   sessions. **Stands.**
2. The picks skew down, not up. **Stands.**
3. A vol-band + net-rank rule flips the edge positive. **Stands out of sample as
   an edge** (+6.3 to +9.5pp on the holdout) but the band choice was fitted to
   the test regime and would have been wrong historically.
4. That edge converts to profit. **Fails.** Not at ten-day hold, and not under
   any of seventeen exit rules.

The touch-versus-capture gap is real and it does not close. A name that reaches
+20% intraday on day 3 is, on these picks, a name that gives it back — which is
consistent with the picks being distressed and volatile rather than
appreciating.

What has not been tried, and is the only honest remaining direction on the long
side: a model trained to predict the *realised* forward return under a specific
exit rule, rather than trained on a barrier-touch label and then having an exit
bolted on afterwards. The label and the trade should be the same object. That is
a different build, not a tweak.

The short side remains the only thing in this project with a positive
out-of-sample expectation, and it remains untested against borrow cost.
