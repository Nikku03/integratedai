# "Safe high variability" — what that actually means here

You asked for a **safe, high-variability** strategy. Those words pull in
opposite directions unless you are precise about *where* the variance comes
from. This document is that precision, because the risk design is the part of
this system that decides whether you survive being wrong.

---

## The decomposition

> **Variance comes from breadth and skew. Safety comes from every individual
> bet being small and bounded.**

- **High variability** — 20 to 30 concurrent catalyst bets, each with a
  right-skewed payoff (roughly 3:1 win/loss at the default barriers). That
  produces a genuinely wide distribution of monthly outcomes. Best month and
  worst month in the demo differ by about 15 points.
- **Safe** — no position can lose more than 1% of capital, because the stop is
  placed *before* the trade is sized and the size is derived **from** the stop.

The failure mode this rules out is the one that actually kills accounts: a
concentrated position in a name that gaps 60% against you overnight because the
catalyst went the other way.

**It does not, and cannot, rule out a bad month where twenty small bets all lose
at once.** That is the variance you asked for. The drawdown kill switch is what
bounds it.

---

## The sizing chain

Every step only ever *shrinks* the position. There is no step that can increase
size, which means no combination of unusual inputs can produce a large bet.

```
1. Fractional Kelly on the calibrated edge      f = 0.25 × f*
2. Risk cap:  weight ≤ max_risk_per_trade / stop_pct        ← the important one
3. Uncertainty shrink:  × 1/(1 + 8·seed_dispersion)
4. Per-name notional cap                        ≤ 6%
5. Sector cap                                   ≤ 30%
6. Vol target, then gross cap                   ≤ 150%
7. Liquidity cap: ≤ 3 days at 5% of ADV
```

### Step 2 is what makes the downside bounded

`weight × stop_pct` is the fraction of capital lost if the stop trades. Fixing
that at 1% and solving for weight means **a wider stop automatically gets a
smaller position**. A 90%-vol biotech with a 30% stop gets a 3.3% position; a
utility with a 6% stop gets 16%, then hits the 6% name cap.

This is why stops are volatility-scaled rather than fixed. A 3% stop on a
90%-vol biotech is noise and will be hit by lunchtime — you would be
systematically stopped out of your best ideas and pay the spread twice for the
privilege.

### Why a quarter of Kelly

Full Kelly maximises long-run log growth **given the true probabilities**. Ours
are estimates from a noisy model on non-stationary data, and Kelly is brutally
asymmetric to overestimation:

| You bet | Growth vs optimal |
|---|---|
| 0.5× optimal | −25% |
| 1.0× optimal | maximum |
| 2.0× optimal | **negative** |

Overbetting by 2× is worse than underbetting by 2× is bad. Quarter-Kelly gives
up a quarter of theoretical growth to buy a large margin against being wrong
about the edge — which we assuredly are.

### The Kelly guard, and why it exists

Kelly divides by the loss leg. That leg is an *estimate* from a finite sample of
a fat-tailed distribution, and the formula is unbounded as it approaches zero.

This is not hypothetical. With the original barrier multipliers (2.0σ / 1.5σ),
**83% of trades exited on the time stop**, so the "loss" bucket filled up with
flat outcomes and `avg_loss` collapsed to −0.0009. Kelly would have implied a
position of roughly 700× capital.

Two fixes, both in the code:

1. `MIN_LOSS_MAGNITUDE = 0.01` floors the denominator, and `MAX_RAW_KELLY = 3.0`
   caps the result. A payoff table reporting `avg_loss = −0.001` is not telling
   you the trade is riskless; it is telling you the estimate is meaningless.
2. The **barrier multipliers were changed to 1.0σ / 0.8σ**, so roughly a third
   of trades touch each barrier and the payoff ratio lands near 3:1. Barriers
   are not free parameters to tune for Sharpe — they define what the model is
   being asked to predict, and they have to *bind*.

### Step 3: sizing down what the model doesn't know

The seed ensemble's cross-seed standard deviation is a cheap epistemic
uncertainty estimate. High dispersion means the seeds are extrapolating into a
region the training data did not cover. Those positions get shrunk. A model
that is confidently wrong is expensive; a model that *knows* it is unsure and
sizes accordingly is merely unprofitable.

---

## Limits are hard, not soft

Every limit in `risk/limits.py` is a pre-trade check, not a penalty term in an
objective. An optimiser will happily trade a limit breach for expected return if
the return is large enough. The whole point of a limit is that it is not for
sale.

| Limit | Default | Rationale |
|---|---|---|
| `max_risk_per_trade` | 1% | ~7 consecutive full-stop losses to lose 7% |
| `max_weight_per_name` | 6% | bounds overnight gap risk |
| `max_positions` | 30 | breadth is the variance source |
| `max_sector_weight` | 30% | 20 correlated biotechs is one bet |
| `max_gross_exposure` | 150% | |
| `max_drawdown` | 20% | **kill switch: flattens and halts** |

The kill switch latches. Once tripped it stays tripped even if equity recovers,
and a human has to clear it. Auto-resuming after a 20% drawdown is how a 20%
drawdown becomes a 40% one.

---

## Diversification you can actually verify

`effective_bets()` reports how many independent bets the book contains:

> 30 names at 0.6 average pairwise correlation ≈ **3 effective bets**.

If that number is far below the position count, your diversification is
decorative and the drawdown will not be. `correlation_haircut()` scales the book
down until correlation-adjusted risk matches what the gross limit was
implicitly assuming.

Check this on real data. Catalyst strategies cluster hard — small-cap biotech
catalysts are all one XBI bet wearing thirty hats.

---

## Costs, because this universe is the worst case

A catalyst strategy trades **small caps on news days**. Spreads widen on news,
depth evaporates, and the names are illiquid to begin with. A backtest assuming
5bp round-trip here is not optimistic, it is fictional.

```
cost_bps = commission + half_spread × (2 if news_day) + impact_coef × √participation
```

- **Square-root impact** is the standard empirical form. The coefficient is the
  part you must calibrate against **your own fills**; the default is a plausible
  mid-range value for US small caps, not a measurement of your broker.
- **Participation is capped at 5% of ADV and truncation is recorded.** Without
  this, the backtest quietly assumes it can buy $5m of a name that trades $800k
  a day. Capping is more honest than paying a huge modelled impact, because in
  reality you would not get the fill at all. Watch `capped_orders` in the cost
  summary — if it is large, your paper returns depend on impossible fills.
- **Ambiguous bars resolve against you.** When both barriers fall inside one
  daily bar, the stop is assumed to have traded first. Daily data cannot resolve
  the order, and the optimistic assumption flatters exactly the most volatile
  names, where it matters most.

---

## Reading the performance summary honestly

The metrics deliberately include the ones that make a strategy look worse.

- **`sharpe_se`** — on three years of daily data the standard error is ~0.5.
  A measured Sharpe of 1.0 is **not** distinguishable from 0. If your Sharpe is
  not at least 2 standard errors from zero, you have measured nothing.
- **`deflated_sharpe_prob`** — Sharpe adjusted for how many variants you tried.
  Pass `--n-trials` honestly. If you backtested 200 configurations and kept the
  best, its Sharpe of 1.8 is roughly what 200 coin flips produce. Below ~0.95,
  you have not cleared the multiple-testing bar.
- **`top_trade_pnl_share`** — if one trade made the strategy, you do not have a
  strategy.
- **`days_underwater`** and **`ulcer_index`** — drawdown depth is what you feel;
  time underwater is what makes you quit. Sharpe ignores both.
- **`pct_time`** — if most trades exit on the time stop, your barriers are too
  wide and the label is not measuring what you think.

---

## Live-vs-backtest consistency

The backtest's exit rule and the label's triple barrier **must describe the same
trade**. If the model is trained on 15-day barrier outcomes and the live book
holds for 40 days, every probability it emits describes a trade nobody is
making. `test_backtest_on_labels_agrees_with_label_construction` asserts
`risk.max_holding_days == labels.max_holding_days`. If you change one, change
both.

---

## What this design does not protect you against

Stated plainly, because a risk document that only lists mitigations is
marketing:

- **Correlated tail events.** Twenty small-cap catalysts in a March 2020 gap are
  one position. Gross and sector caps limit this; they do not eliminate it.
- **Overnight gaps.** Stops are not guaranteed fills. A halt-then-reopen at −60%
  fills far below your stop. The per-name notional cap is the only real defence,
  which is why it is there as well as the risk cap.
- **Regime change.** The model is fitted on the past. Walk-forward measures how
  fast it decays; it cannot prevent decay. Watch fold-by-fold AUC — in the demo
  it runs 0.56 / 0.51 / 0.55, and that middle fold is what non-stationarity
  looks like.
- **The strategy simply not working.** The synthetic demo proves the plumbing,
  not the edge. Run the event study on **real** data before believing anything.
