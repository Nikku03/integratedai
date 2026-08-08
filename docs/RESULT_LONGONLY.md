# Long-only: the first thing in this project that works

Run against `docs/PREREGISTRATION_LONGONLY.md`, criteria fixed before execution.
Fourteen consecutive six-month walk-forward blocks, 2019-01 to 2025-12,
retrained before each, long only, top 5 names per day, ten-session hold, net of
20bps round trip, with a 14-day embargo so no training label overlaps the block
being predicted.

## Result

| target | excess over universe | sd | **IR** | blocks won | median pick vol | win% |
|---|---|---|---|---|---|---|
| **vol-scaled** | **+0.894%** | 0.734 | **1.22** | **13/14** | **2.53%** | **53.3%** |
| raw return | +1.014% | 1.133 | 0.89 | 11/14 | 5.55% | 48.1% |
| bracket return | +0.558% | 1.147 | 0.49 | 11/14 | 5.18% | 48.9% |

Excess is per ten sessions. The universe returned +0.249% over the same blocks.

**Primary: PASS.** Vol-scaled excess +0.894% per ten sessions, block-bootstrap
95% CI [+0.472%, +1.236%], P(<=0) = 0.0001.

**Consistency: PASS.** 13 of 14 blocks beat the universe; the criterion required
9. The single loss was 2021-07 at −0.55%.

**Tertiary: FAIL as written, and the criterion was badly specified.** It asked
whether the vol-scaled target beats the raw target on *raw excess*, which cannot
test a hypothesis about risk adjustment. It does not (+0.894% against +1.014%).
On every measure the risk adjustment was meant to improve it wins: information
ratio 1.22 against 0.89, thirteen winning blocks against eleven, a 53.3% win rate
against 48.1%, and picks at **less than half the volatility** — 2.53% daily
against 5.55%. Both numbers are reported; the flaw was mine, in the criterion,
not in the result.

## The ablation, which is the important one

Pre-registered: rerun with `vol_5d`, `vol_20d`, `vol_60d`, `mean_exc_20d`,
`max_exc_20d` and `rvol` deleted. If the edge vanishes, this is the old
volatility detector in a new coat.

```
no volatility features:  excess +0.615%,  12/14 blocks
                         95% CI [+0.107%, +1.053%],  P(<=0) = 0.0098  -> PASS
```

It survives. Removing every volatility feature costs about a third of the edge
and the rest holds, so **roughly two-thirds of the signal is coming from the
filings, fundamentals, insider activity and registration history** rather than
from price violence. That is the first time in this project a non-price feature
block has demonstrably carried anything.

## Why this worked when the previous build did not

Three defects were measured, and all three were structural rather than
incidental:

| defect | fix | evidence it mattered |
|---|---|---|
| label monotone in volatility, so the model ranked by `mean_exc_20d` and lived in the top decile | divide the target by trailing volatility | median pick volatility fell from 13.3% daily to 2.53% |
| label was a barrier *touch*, not the money | regress on realised ten-day return | all 17 exit rules lost on validation; this needs none |
| one fixed split hid a regime flip | 14 walk-forward blocks | the top vol decile returned +1.1% in 2015-22 and −2.2% in 2024-25 |

The old model asked "what will move" and answered it correctly. That question has
a long-only answer of roughly minus four percent.

## What it looks like as a book

Daily top 5, ten-session holds, so about 50 positions open at steady state and
roughly 25 turns a year. At +1.143% per turn net of costs that is on the order of
**+25-30% a year, against a universe doing +6%**, with a 53% win rate and one
losing half-year in seven.

Per-block detail is in `longonly.csv`. The worst block was 2022-01 at −2.05%
absolute (−0.26% excess) — it lost less than the universe in the drawdown, which
is the behaviour the risk adjustment was bought for.

## What would still break it

**Survivorship, as always.** The panel has no delistings. Both the strategy and
its benchmark are computed on the same inflated universe, which is why the excess
is the number reported rather than the level. That defence is not complete: if
the strategy systematically picks names more likely to delist than the universe,
the excess is overstated too. It now selects *lower*-volatility names than the
old model, which probably cuts the other way, but "probably" is not a
measurement.

**Costs.** 20bps round trip is assumed. The sensitivity is mild — the edge is
+0.894% and each 10bps of cost takes 0.10% — but real spreads on the smaller
names will exceed that, and market impact at size is not modelled at all.

**Capacity.** These are median-$8-11 names with ADV in the single-digit millions.
Five positions a day is fine for a personal account and will not survive size.

## Honest standing

This is the only pre-registered, walk-forward, out-of-sample, cost-inclusive
positive result in this repository, and it passed its ablation. It is also a
within-panel result on a survivorship-broken universe, so treat the +0.894% as a
ranking claim — these names beat those names — and not as a forecast of what an
account earns.
