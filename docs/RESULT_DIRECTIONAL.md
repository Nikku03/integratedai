# Does "up" mean up? Two directional models, and only one of them works

The magnitude model is direction-agnostic by construction: it predicts
`P(|move| >= 20%)` and says nothing about which way. The ADRNN's direction head
does not fix that, because it was trained on `max_up >= -max_dn` -- *which
excursion was larger* -- and a stock that runs +8% then falls -6% counts as "up"
under that label while paying nothing.

So this trains the two models that map onto an actual trade, on the same panel,
features and temporal splits:

```
y_up = 1 if max_up  >= +20%   within ten sessions
y_dn = 1 if max_dn  <= -20%   within ten sessions
```

Test base rates: up 8.27%, down 7.02%, either 14.67%.
Test AUC: UP model 0.8469, DOWN model 0.8577, magnitude control 0.8738.

The AUCs look fine. They are also almost meaningless on their own, because both
labels correlate with volatility and a model can score 0.85 by finding violent
names without knowing anything about direction. The criterion was fixed before
running: **among the UP model's own picks, `P(up20)` must exceed `P(dn20)`.**

## The result

Daily top-k of each model, scored on *both* outcomes:

| model | k | P(up20) | P(dn20) | edge | mean 10d return | median | win% |
|---|---|---|---|---|---|---|---|
| **UP** | 1 | 46.4% | 47.7% | **−1.3** | **−3.39%** | −7.36% | 37.9% |
| **UP** | 3 | 43.4% | 47.0% | **−3.6** | −4.30% | −6.60% | 37.6% |
| **UP** | 5 | 41.5% | 45.9% | **−4.4** | −4.06% | −7.07% | 37.8% |
| **DOWN** | 1 | 44.6% | **67.1%** | −22.5 | −11.16% | −17.55% | 28.9% |
| **DOWN** | 3 | 43.4% | 56.9% | −13.4 | −9.22% | −12.56% | 31.1% |
| **DOWN** | 5 | 40.4% | 51.9% | −11.5 | −7.12% | −10.56% | 33.1% |
| MAG (control) | 1 | 45.6% | 65.8% | −20.2 | −9.24% | −14.75% | 30.2% |
| MAG (control) | 5 | 41.2% | 53.3% | −12.1 | −7.28% | −11.00% | 32.7% |
| everything | — | 8.3% | 7.0% | +1.2 | +0.17% | −0.05% | 49.4% |

**The UP model fails outright.** When it names its single highest-confidence
stock for a +20% move, that stock hits −20% more often than +20%. Buying the top
pick and holding ten sessions loses **3.39%**, wins 37.9% of the time, and has a
median of −7.36%. Week-clustered CI on the k=5 edge is [−10.47, +1.60] with
P(<=0) = 0.9251 — **FAIL**, and not marginally.

**The DOWN model works.** Its top pick hits −20% **67.1%** of the time. Shorting
it returns **+11.16% mean, +17.55% median, 70.6% win rate** over ten sessions.

## But read the control row before believing the short

The direction-agnostic magnitude model scores −20.2pp at k=1 against the DOWN
model's −22.5pp. **The dedicated down-model adds about 2pp over simply ranking
by "will this move at all".** Almost the entire short edge comes from the fact
that violent names fall, not from any directional insight.

There *is* genuine directional separation: the UP model's picks sit at −1.3pp
while the DOWN model's sit at −22.5pp, a 21.2pp gap at k=1 that narrows to
+1.1pp by k=20. The model can tell "less bad" from "very bad". It cannot find
anything that is actually good.

## The tail that ruins the naive short

**44.6% of the DOWN model's top picks still touch +20% at some point** in the
same ten sessions. Nearly half of these shorts go 20% against you before they
work. A position with a stop gets squeezed out of the trades that pay; a
position without one has to survive a 20% adverse excursion on a $9 stock at
200%+ annualised volatility.

## Where survivorship cuts, for once, in our favour

Every other result in this repo is flattered by the panel's missing delistings.
Here it is the opposite: the absent names are the ones that collapsed, so
`P(dn20)` is **understated** and `P(up20)` **overstated**. The short result is
conservative and the long result is worse than it already looks.

## Answer to the question

The model is **not** direction-specific in the way the question assumes. It does
not say "this will move up 20%" and then deliver that.

* When a dedicated model says "up": it is wrong more often than right — 46.4%
  up against 47.7% down, and the position loses money.
* When a dedicated model says "down": it is right 67.1% of the time and a short
  earns 11.16% mean over ten sessions.
* Most of that down-accuracy is available from the direction-agnostic model
  anyway.

The honest summary is that this thing detects **impending distress**. Distress
resolves downward far more often than upward, which makes it a short signal
wearing the costume of a moonshot finder.

## What has not been tested

The short side has costs this panel cannot see: borrow availability and fees on
$8-11 names at 200%+ volatility are frequently 20-100% annualised, which over a
ten-day hold is roughly 0.8-4% -- a material bite out of a 7-11% gross. Locate
failures and buy-ins are not modelled either. Until that is tested, the short
result is a research finding and not a strategy.
