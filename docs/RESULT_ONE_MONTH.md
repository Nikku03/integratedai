# A month: as a holding period, and as a unit of experience

Two readings of the same instruction, both worth answering. Hold for a month
instead of two weeks — and separately, what does one month of this actually feel
like, since seven-year totals hide everything that matters to someone living
through it.

## Holding for a month is better on every axis

Same rules, same selection, same walk-forward. The only change is the horizon,
and the embargo widens with it — a 21-session label needs 30 calendar days of
separation, not 14, or training rows leak into the test block.

| k=1, 3.02 veto | 10 sessions | **21 sessions** |
|---|---|---|
| per trade | +1.004% | **+3.917%** |
| total ROI, 7 years | +107.3% | **+916.9%** |
| CAGR | +11.0% | **+39.3%** |
| max drawdown | −77.7% | **−69.4%** |
| Sharpe | 0.48 | **0.88** |
| P(+20% on a trade) | 15.5% | **24.3%** |

It holds across the whole k grid — +432.7% at k=5, +597.1% at k=2 — and dropping
the 3.02 veto raises it further, to +2,414.8% at k=1. The veto continues to fail
to justify itself.

**The improvement is not market beta.** Under the same accounting: owning the
whole pool equally returned **−6.7%**, and a random five names a day returned
**+5.7%** median across 40 draws, with none of the 40 beating the model.

**It is not the return guard, either.** The `|r| ≤ 3` filter drops 69 of 501,435
candidates at 21 sessions (0.014%) against 12 at ten sessions, and every one
dropped is a *winner* — the largest kept return is +295%. The guard biases the
result down at both horizons.

## The part that matters more than the return

The ten-session book was a lottery: 18 trades carried it, and trimming them
turned it negative. The month-long book is a different animal.

| | 10 sessions | **21 sessions** |
|---|---|---|
| top 10 trades' share of the total | 72.4% | **32.7%** |
| top 20 trades' share | 121.8% | **54.1%** |
| mean after dropping the best 1% | **−0.128%** | **+1.959%** |
| mean after dropping the best 2% | −0.848% | +0.952% |
| mean after a 25% haircut on winners | **−1.215%** | **+0.366%** |

At ten sessions, removing eighteen trades destroyed the strategy. At twenty-one,
the same removal leaves +1.96% per trade — still nearly double the *entire*
ten-session edge. The edge stops being a handful of lottery hits and starts
being a distribution.

Survivorship gets easier too, even though a longer hold means more exposure. The
breakeven rises to **one hidden total loss per 27 trades (3.77%)** while the
measured hazard roughly doubles to about **1.0%** — a margin of 3.8×, wider than
the 2.3× at ten sessions.

Why: the catalysts this model selects need longer than two weeks to resolve.
Ten sessions cuts the tail off before it develops, and the tail is the entire
edge.

## Year by year, the two horizons disagree about which years were good

| | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|
| 10 sessions | +67.4% | −21.1% | +7.1% | −46.6% | +54.0% | +101.3% | −11.4% |
| **21 sessions** | +56.8% | **+50.9%** | +12.0% | −29.8% | **+158.8%** | +8.6% | **+94.7%** |

Six of seven years positive instead of four, and the one loss is smaller.

## What one month actually looks like

Across 84 months at 21 sessions, k=1:

| | |
|---|---|
| positive months | **51 of 84 (61%)** |
| median month | **+3.64%** |
| mean month | +4.19% |
| best month | +60.3% |
| worst month | −30.3% |

At ten sessions those were 50% positive with a **+0.03%** median — a coin flip
that paid nothing in the middle and everything in the tails.

**The last complete month in the data, November 2025, every trade:**

```
11-03  LXEH   -26.48%      11-17  EVH     +4.74%
11-04  YDKG   -75.20%      11-18  BNC    +24.50%
11-05  FMC     -0.80%      11-19  FMC     +4.19%
11-06  LWLG   -16.38%      11-20  NB     +10.29%
11-07  SENS    +8.64%      11-21  UP     -27.79%
11-10  JELD   +21.54%      11-24  SUIG    -7.85%
11-11  AGL    +19.97%      11-25  TMCI   -22.14%
11-12  SOC     -2.42%      11-26  SOC   +104.73%
11-13  NAUT    -0.20%      11-28  IVVD    -3.39%
11-14  VOR    +58.00%
```

19 trades, 9 winners, mean **+3.89%** — and the book still returned **−18.37%**
that month, because the losers landed while more capital was deployed. That gap
between a positive trade average and a negative month is worth sitting with: it
is what overlapping positions do, and no per-trade statistic will show it to you.

For contrast, the same month at ten sessions was **−29.56%** with 7 winners of
19 and a −6.54% trade average. The month-long hold turned SOC from +32% into
+105% and VOR from a −5% loss into +58%.

## What has not changed

* **A 69% drawdown is still a 69% drawdown.** Better than 78%, still not
  something most people hold through — and 2022 still lost 30%.
* **Monthly volatility is enormous.** A median month of +3.6% sits inside a
  range from −30% to +60%. Roughly two months in five lose money.
* **Everything still rests on a survivorship-limited panel.** The correction in
  `RESULT_SURVIVORSHIP.md` says the book survives it with room, but the prices
  of dead companies are still missing and only a vendor extract fixes that.
* **This is one more horizon tested on the same data.** Ten and twenty-one are
  now both measured; that is two points, not a curve, and picking the better of
  two after seeing both results is worth exactly as much as it sounds. The
  honest next step is the full horizon sweep as a pre-registered test, not
  adopting 21 because it won today.

## Reproducing

```
python3 scripts/agreed_strategy.py --horizon 10
python3 scripts/agreed_strategy.py --horizon 21
```

The embargo scales with the horizon automatically, and the per-trade return is
cross-checked against `exit_rules.walk` at both — 1.78e-15 max disagreement at
21 sessions.
