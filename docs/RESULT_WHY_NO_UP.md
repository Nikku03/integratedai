# Why the model sees crashes and not rallies

Four hypotheses, each with a test that could kill it. One was refuted, one was
confirmed, and the third turned out to be the mechanism.

## H1 — "up arrives as news, down arrives as decay" — REFUTED

The obvious story: a crash is the visible end of a deterioration you can watch
for weeks, while a rally is an announcement that did not exist at the previous
close. If true, no feature set could ever fix the up side.

Decomposing every clean move into its overnight and intraday channels:

| | up-moves | down-moves |
|---|---|---|
| share of travel carried by overnight gaps | **34.9%** | **31.8%** |
| biggest single day as a share of total travel | 29.2% | 26.7% |
| sessions to the extreme | 8 | 9 |
| largest one-day gap | 5.47% | 6.29% |

Nearly identical. Up-moves are **not** more gap-driven, and neither kind is
dominated by a single day — the biggest session is under 30% of total travel in
both. The hypothesis was wrong, and it was the one I expected to carry the
result.

## H2 — "the features only measure distress" — CONFIRMED, but not the cause

Permutation importance, both models:

| UP model | | DOWN model | |
|---|---|---|---|
| `mean_exc_20d` | **+0.1498** | `mean_exc_20d` | **+0.1672** |
| `vol_60d` | +0.0148 | `f10-Q_since` | +0.0200 |
| `i2.02_since` | +0.0072 | `vol_60d` | +0.0095 |

One feature — trailing 20-day mean absolute excursion — is an order of magnitude
more important than anything else, **in both models**. Nine of the two top-15
lists overlap. Neither model is a directional model; both are volatility
detectors with a thin directional veneer.

## H3 — the leverage effect — THIS IS THE MECHANISM

Forward outcomes by trailing-volatility decile:

| decile | 20d vol | mean 10d return | P(up20) | P(dn20) | **up − dn** |
|---|---|---|---|---|---|
| 5 | 2.70% | +0.16% | 4.95% | 3.98% | +0.97 |
| 6 | 3.22% | +0.89% | 8.25% | 5.48% | +2.77 |
| 7 | 3.97% | +1.24% | 11.89% | 7.85% | +4.04 |
| 8 | 5.18% | +1.18% | 18.90% | 12.96% | **+5.94** |
| **9** | **8.69%** | **−2.47%** | 29.29% | 30.12% | **−0.83** |

**The relationship is not monotonic. It inverts at the top.** Rising volatility
is *bullish* all the way to the ninth decile — more up-moves than down, positive
expected return, edge widening to +5.94pp. Then the tenth decile flips: returns
collapse to −2.47% and down-moves overtake up-moves.

That decile is where distress actually lives. The other nine are just names
getting interesting.

## H4 — "the two models are one model" — CONFIRMED

Rank correlation between the UP and DOWN scores: **ρ = 0.929**. Daily top-5
overlap 44.8%. The UP score scores 0.8526 AUC *on the down label*, against the
purpose-built DOWN model's 0.8577.

## The actual answer

Nothing is wrong with the up label and nothing is missing from the features.
**The objective was wrong.**

Maximising `P(|move| >= 20%)` is a monotone function of volatility, so the model
walks straight into the tenth decile and parks there. That is the single decile
in which large moves skew downward. The model is not bad at predicting up — it is
excellent at finding the one bucket where up does not happen, because that is
exactly what it was asked to do.

## The fix, and what survived out of sample

Rank by `P(up) − P(down)` instead of `P(up)`, and exclude the top volatility
decile (band defined by *training* quantiles, so it is knowable live).

| | k=1 | k=3 | k=5 | k=10 |
|---|---|---|---|---|
| **Test** naive `P(up)` rank | −7.70% | −4.39% | −4.17% | −3.53% |
| **Test** band + net rank | **+1.93%** | **+2.01%** | **+1.84%** | **+1.56%** |
| **Validation** naive `P(up)` rank | −4.81% | −2.08% | −2.37% | −2.17% |
| **Validation** band + net rank | +0.59% | +0.31% | +0.01% | +0.40% |

Mean ten-day return. Validation (2023-01 to 2024-06) was never used to fit these
models, so it is a clean holdout for a rule that was found on test.

**What replicates:** the directional edge. `P(up20) − P(dn20)` on the holdout is
+9.5pp at k=1, +7.9 at k=3, +7.0 at k=5, +6.3 at k=10 — the same shape and
magnitude as on test. And the diagnosis replicates too: naive `P(up)` ranking
loses money in **both** periods, so the poison is real and excluding it helps.

**What does not replicate:** the profit. Holdout returns are +0.59%, +0.31%,
+0.01%, +0.40%, and every confidence interval includes zero (P(<=0) = 0.30, 0.35,
0.49, 0.28). On test the same cells give +1.8% to +2.0% with intervals excluding
zero, which is what finding a rule on a period tends to look like.

## What the gap between those two rows means

The rule genuinely shifts *which barrier gets touched* — that is stable across
both periods and is not a fluke. It does not shift *what a position earns*,
because touching +20% intraday on day 3 is not the same as selling there. These
tests hold to the tenth close with no exit rule at all, and the win rate is 45%,
so the mean depends entirely on a right tail that showed up in one period and
not the other.

The honest position: the diagnosis is solid and replicates, the directional tilt
is real and replicates, and the profitability is unproven. The missing piece is
an exit rule that converts a +20% touch into realised P&L, which is a separate
and testable question — and the one worth doing next.

Survivorship still flatters everything on the long side here: the panel's absent
delistings are the collapses, so real `P(dn20)` is higher than measured and every
edge above is an overestimate.
