# When does the 10 / 20 / 50% move actually happen?

Two earlier results looked contradictory: the price has barely moved at catalyst
+ 1 minute (2–19 basis points), yet 856 names moved ≥10% in July. Both are true,
and reconciling them changes what the obstacle actually is.

**7,563 catalyst events, 1,536 names, 1–29 July 2026**, on 1-minute bars.

## The moves take days, not minutes

| threshold | reached UP | median lag | p25 | p75 | reached DOWN | median lag |
|---|---|---|---|---|---|---|
| ±10% | 22.8% | **4.3 days** | 24.6h | 7.7d | **30.2%** | 4.6d |
| ±20% | 7.5% | **3.9 days** | 24.0h | 7.7d | **12.3%** | 7.0d |
| ±50% | 2.0% | **2.7 days** | 28.3h | 8.7d | 1.5% | 7.4d |

A quarter arrive within 24 hours; the median takes **four days**. Nothing about
this is a one-minute phenomenon, or even a one-day one.

## The gap is not the obstacle — this corrects earlier reasoning here

Every move splits into the **gap** (last print before the catalyst → first print
after it, untradeable by definition) and the **continuous part** (everything
after, while the tape runs).

| threshold | n reached | whole move inside the gap | median gap share | **reachable after the first print** |
|---|---|---|---|---|
| +10% | 1,723 | 8% | 8% | **92%** |
| +20% | 566 | 10% | 6% | **90%** |
| +50% | 152 | 10% | 3% | **90%** |

**Ninety percent of every threshold move is reachable.** The gap that earlier
notes here treated as the killer has a median of **+0.076%** across all catalysts
and +0.03% for those landing in regular hours. You are not missing the move
because it gapped away; you are missing it because it had not happened yet.

| session catalyst landed in | n | median gap | \|gap\| ≥5% | time to first print |
|---|---|---|---|---|
| regular | 1,570 | **+0.03%** | 0% | 1 min |
| pre-market | 904 | +0.66% | 21% | 90 min |
| after-hours | 4,764 | +0.24% | 8% | **17.1 h** |
| closed | 325 | +0.25% | 14% | 13.0 h |

Even after-hours filings — which wait seventeen hours for a market — open only
0.24% away in the median case.

## The direction skew is the base rate, not the catalyst

Down moves outnumber up moves 30.2% to 22.8%. That looks like filings being bad
news until you run the control: **6,253 random timestamps in the same names, each
at least 24 hours from any of their filings**, with forward runway equalised to
match.

| threshold | catalyst up | placebo up | catalyst down | placebo down | catalyst skew | **placebo skew** |
|---|---|---|---|---|---|---|
| ±10% | 23.4% | 26.7% | 30.3% | 32.8% | −6.9pp | **−6.2pp** |
| ±20% | 7.8% | 8.8% | 12.3% | 13.6% | −4.5pp | **−4.8pp** |
| ±50% | 2.2% | 2.4% | 1.6% | 1.5% | +0.6pp | +0.9pp |

**The skew is identical with and without a catalyst.** These small caps fall more
often than they rise over a two-week window whether or not anything was filed. At
±20% the catalyst skew (−4.5pp) is if anything *milder* than the placebo (−4.8pp).

Filings are not bad news. The universe is.

## What the catalyst does do: it pulls the move forward

| threshold | catalyst | placebo | difference |
|---|---|---|---|
| +10% | 4.7 days | 5.8 days | **−1.1 days** |
| +20% | 3.9 days | 5.9 days | **−2.0 days** |
| +50% | 2.7 days | 4.9 days | **−2.2 days** |

And it genuinely creates a discontinuity: **8.3% of catalysts open more than 5%
away** against **1.8%** of random timestamps — 4.6× the rate.

So a filing carries real information, and the information is about **timing, not
direction**. It says "this name is about to do something", roughly two days
sooner than it otherwise would, and says nothing about which way.

## By catalyst type

| catalyst type | n | reach +10% | median lag | inside the gap |
|---|---|---|---|---|
| 8-K reg-FD | 301 | **30.6%** | 25.5h | 17% |
| 8-K delisting | 50 | 30.0% | 2.7d | 0% |
| 8-K material agreement | 356 | 28.7% | 2.8d | 16% |
| 8-K other event | 356 | 27.2% | 3.0d | 11% |
| activist 13D | 97 | 26.8% | 2.1d | 23% |
| **8-K earnings** | 607 | 26.7% | **20.5h** | 19% |
| proxy / other | 257 | 25.7% | 3.7d | 14% |
| passive 13G | 402 | 25.1% | 3.8d | 2% |
| insider Form 4 | 3,098 | 22.2% | 5.9d | 3% |
| periodic 10-Q/K | 262 | 22.1% | **19.1h** | 24% |
| merger / tender | 147 | 21.1% | 28.3h | 16% |
| offering / dilution | 1,119 | **15.2%** | 5.6d | 1% |

The fastest are earnings (20.5h) and periodic reports (19.1h) — scheduled events
the market is waiting for. The slowest are insider forms (5.9d) and offerings
(5.6d), which are filed *after* whatever prompted them.

## What this changes

**The one-minute framing was solving the wrong problem.** Being early by a minute
is worth nothing when the move takes four days — and 90% of it is reachable
anyway. Speed was never the binding constraint.

**The real constraint is that the move is symmetric and the universe drifts
down.** You can be in the position, in time, for 90% of the move. It is as likely
to be a −20% move as a +20% one, and slightly more likely, and that is true of
these names with or without a filing.

**What a filing is actually worth:** it compresses a two-week question into a
two-to-four-day one and raises the chance of a >5% discontinuity from 1.8% to
8.3%. That is real, and it is a volatility signal — the right instrument for it
is an options straddle, not a long stock position. Nothing in this repository
tests that, and it is the one direction the evidence here actually points toward.
