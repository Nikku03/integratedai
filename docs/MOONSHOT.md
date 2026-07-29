# Moonshot: five trades a week, hunting +10%

A different shape of strategy: fewer, larger, lower-probability bets with a
big absolute target instead of many small volatility-scaled ones.

**Result: +12.2% CAGR, Sharpe 0.58 ± 0.70, over two out-of-sample years.**
It makes money in backtest and it is **not statistically distinguishable from
luck**. Both halves of that sentence matter.

---

## Why the shape change fixes the real problem

The previous configuration chased a **+21bp** edge against **~48bp** of
round-trip cost. That is not a modelling problem, it is arithmetic: no amount
of feature engineering wins when the bill is twice the revenue.

Against a **+1000bp** target the same 48bp is roughly a tenth of the gross
edge. Nothing about the alpha improved — the denominator changed.

| | old (vol-scaled, 8d) | moonshot (+10%/−7%, 10d) |
|---|---|---|
| gross edge per trade | +0.08% | **+1.22%** |
| round-trip cost | 0.65% | 0.66% |
| **net** | **−0.57%** | **+0.56%** |
| cost as % of gross | 810% | **54%** |

---

## The two things that made it work

### 1. Rank on expected value, not on P(spike)

This is the single most important finding in this document.

Selecting the names most likely to jump +10% selects the names most likely to
**move at all** — which is the same set as the names most likely to drop −7%.
So a second model estimates P(stop first), and candidates are ranked on

```
EV = P(target)·(+10%) − P(stop)·(−7%) + P(neither)·E[r | time exit]
```

Same features, same universe, same period, same number of trades:

| ranking | P(spike) | stop rate | **net/trade** | t |
|---|---|---|---|---|
| P(spike) only | 38.8% | **53.6%** | **−0.44%** | −1.23 |
| **expected value** | 33.0% | **36.1%** | **+0.56%** | +1.73 |

Ranking on P(spike) alone picks a *higher* spike rate and still loses money,
because it drags the stop rate up with it. The downside model is not a
refinement; it is the difference between losing and not.

### 2. Select per week, not globally

Taking the global top-N across pooled walk-forward folds lets whichever fold
has the widest prediction scale dominate. The first version of this put **490
of 492 chosen trades into a single calendar year** — a strategy that required
knowing in advance which year to show up for.

Selecting the best `k` in each week is both the honest construction and a
literal statement of "five trades a week".

---

## Does it survive the controls?

**Volatility control — yes.** An absolute +10% barrier is mechanically easier
for a volatile name, so the obvious null is "the model just picks volatility".
It does not: selected names have **0.76×** the universe median volatility, and
the lift holds *within* every volatility bucket.

| vol bucket | median vol | universe P | selected P | lift |
|---|---|---|---|---|
| 0 (calmest) | 0.018 | 18.4% | 30.4% | **1.66×** |
| 1 | 0.024 | 21.4% | 30.9% | 1.44× |
| 2 | 0.029 | 27.2% | 40.0% | 1.47× |
| 3 | 0.037 | 29.2% | 34.6% | 1.19× |
| 4 (wildest) | 0.053 | 35.7% | 39.5% | 1.11× |

**Outlier control — yes.** Unlike the earlier insider result, this one is not
carried by a handful of trades. Median trade return is **positive**, and net
survives dropping the ten largest outcomes (+0.39%, t=1.19).

**Statistical significance — no.** Sharpe 0.58 with a standard error of 0.70.
Deflated Sharpe, accounting for ~30 configurations tried, is **0.108** against
a 0.95 bar. Two years and 515 trades is not enough.

---

## What the strategy actually looks like

```
period            2022-12-30 .. 2024-12-27   (2 out-of-sample years)
CAGR              +12.19%
volatility         25.13%
Sharpe             +0.58  (SE 0.70)
max drawdown      -27.04%
worst month       -14.05%
skew               +0.96      <- right-tailed, as intended
trades               515      exactly 5.0/week
win rate            50.9%
avg win             +7.23%
avg loss            -6.35%
avg positions          6.8    max 14
avg gross              68%
```

At 10% per position with ~7 concurrent, the book runs ~68% invested. Scaling
the weight scales return and drawdown together and leaves Sharpe unchanged —
15% weight gives +16% CAGR and −38% drawdown, 20% gives +18% and −48%.

**Selectivity is not monotone.** 10 trades/week is the sweet spot in this
sample (+0.61%/trade, t=2.66) and 2/week is the worst (+0.10%, t=0.20). That
non-monotonicity is itself evidence of how noisy these estimates are — a real
effect would degrade smoothly.

---

## Honest limitations

- **Two years of out-of-sample data.** The walk-forward reserves the first half
  of 2021–2024 for training, so the tradeable record starts in December 2022.
- **106 names.** The same power problem as everything else in this repository.
- **~30 configurations tried** across barrier levels, horizons and selectivity.
  The deflated Sharpe prices that in and the answer is 0.108.
- **50.9% win rate with a −6.35% average loss.** Expect long, ugly stretches.
  A −14% month is inside normal behaviour, which is why
  `Config.moonshot()` sets the drawdown kill switch at 35% rather than 20% —
  a tighter one would stop the strategy out of its own variance.
- **No short side.** `424B5` shelf takedowns remain the largest robust effect
  in the whole study and they are negative; capturing that needs borrow, which
  on these names frequently costs more than the edge.

## What would settle it

Widen the universe. 515 trades over two years gives a Sharpe standard error of
0.70; the same per-trade edge across 2,000 names would produce roughly 10,000
trades and cut that error by more than half. That is the difference between
"observed" and "measured", and it is the only thing that will settle whether
+0.56% per trade is real.

Reproduce with `python scripts/moonshot.py --trades-per-week 5`.
