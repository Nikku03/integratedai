# Hunting the biggest moves: it works, and it loses money

Two changes from the previous weekly-budget test, both requested and both
material.

**The budget now fills.** The old rule used a fixed bar from the training
distribution and declined when nothing cleared it — three trades in four weeks
instead of twelve. `quota_fill` replaces it: with `r` slots left and `s` sessions
left in the week, the acceptance bar is the quantile that would fill `r` of `s`,
so Monday is selective and Friday takes what is there. Causal throughout, and it
fills.

**The objective aims at the tail.** Everything before optimised a q75 quantile of
return, which is a middle-of-the-tail target and a poor moonshot hunter. Five
objectives are now run — q75, q90, q95, a classifier on P(return ≥ +50%) and one
on P(return ≥ +100%) — and scored on what was actually asked: how many big moves
were caught and how big the biggest was, with the mean reported second.

## The moonshot lift is real and large

Historical, 1,038 trades across 13 walk-forward blocks, inside the catalyst gate:

| objective | trades | mean | median | win | P≥+20% | **P≥+50%** | **P≥+100%** | best |
|---|---|---|---|---|---|---|---|---|
| **the gated pool** | 161,502 | −0.08% | −0.00% | 49.7% | 3.94% | **0.56%** | **0.12%** | +291.6% |
| q75 (incumbent) | 1,038 | −1.18% | −2.60% | 43.8% | 13.10% | 2.50% | 0.39% | +163.8% |
| q90 | 1,038 | −2.70% | −4.19% | 41.5% | **13.58%** | 3.08% | 0.19% | +140.1% |
| **q95** | 1,038 | −2.83% | −5.06% | 40.1% | 13.20% | **4.53%** | **0.87%** | **+213.8%** |
| P50 classifier | 957 | −2.86% | −4.08% | 41.1% | 12.23% | 3.55% | 0.63% | +181.0% |
| P100 classifier | 795 | −3.67% | −5.56% | 36.6% | 10.82% | 2.77% | 0.50% | +152.7% |

**Asking for the tail directly works.** q95 lifts the ≥+50% rate from 0.56% to
**4.53% — 8.1×** — and the ≥+100% rate from 0.12% to **0.87%, 7.3×**. The +20%
rate goes from 3.94% to 13.58% at q90, a 3.4× lift. These are the largest
selection effects anywhere in this repository.

## And every objective loses money

q95 returns **−2.83% per trade** against **−0.08%** for the gated pool it selects
from. Win rate falls from 49.7% to 40.1% and the median from 0.00% to −5.06%.
Pushing further into the tail makes it worse, monotonically: q75 −1.18%, q90
−2.70%, q95 −2.83%, P100 −3.67%.

The arithmetic is not subtle. Lifting the ≥+50% rate by 4 percentage points is
worth roughly +2pp of mean return on its own. The mean falls by 2.75pp instead,
so the losses grew by nearly five points. **Selecting for the up-tail selects the
down-tail with it**, and at these thresholds the down-tail is larger.

That is `RESULT_WHY_NO_UP.md` again, now measured on the metric that was asked
for rather than on a mean: the model can find names about to move violently — it
has never been able to say which way.

## The live two weeks

2026-07-28 to 2026-08-10. The window straddles three ISO weeks, so the quota
filled **9 trades, not 6**. Universe over the window: +2.18% mean, 0.77% of names
moved +50%.

| objective | trades | mean | best | worst | +20% | +50% |
|---|---|---|---|---|---|---|
| q75 | 9 | +4.99% | +67.7% | −21.2% | 2 | 1 |
| q90 | 9 | −2.71% | +67.7% | −25.4% | 1 | 1 |
| **q95** | 9 | **+9.97%** | **+123.1%** | −54.4% | 3 | **2** |
| P50 | 9 | +12.84% | +123.1% | −54.4% | 4 | 1 |
| **P100** | 9 | **+14.90%** | +123.1% | −51.6% | 2 | **2** |

q95's nine:

```
2026-07-28  ASTC     +49.44%
2026-07-30  AGPU      -1.18%
2026-07-31  AMIX    +123.13%   <-- moonshot
2026-08-04  CAPR     +70.19%   <-- moonshot
2026-08-05  SKYQ     -33.68%
2026-08-07  BLZE     -17.00%
2026-08-10  CLRO     -19.56%
2026-08-10  APPS     -25.42%
2026-08-10  MVIS     -54.42%
```

It found AMIX at +123% and CAPR at +70% — exactly the objective. It also found
MVIS at −54%, and in the P100 arm DBGI at −52%.

## Reading the two together

The live +9.97% and the historical −2.83% are the same configuration disagreeing
by thirteen points. The 1,038-trade figure is the one that is real; nine trades
with a +123% inside them is a draw from a very wide distribution, and this is the
fourth consecutive live window to demonstrate that.

What replicates across both is the **catching**, not the profit: 8× the moonshot
rate historically, two moonshots in nine trades live. What does not replicate is
the money.

## Where this leaves the moonshot goal

The problem is no longer finding bigger winners — q95 does that, reliably and by
a large factor. The problem is that **the same selection produces the −54%
losers**, and every attempt in this repository to trim those without also
trimming the winners has failed: all seventeen exit rules, all eighteen checklist
questions, the confidence gate, and the direction head five separate ways.

Two honest options remain. Size the losers down rather than avoid them — which is
a position-sizing question, not a prediction one. Or find genuinely directional
information, which `RESULT_SHORT_DIRECTION.md` suggests exists at AUC ~0.60 for
the *sign* of the move but which no feature set here has yet converted into a
book.

## Reproducing

```
python3 scripts/moonshot_hunt.py                       # 3/week, 2 weeks live
python3 scripts/moonshot_hunt.py --per-week 3 --weeks 2
```
