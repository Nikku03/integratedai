# Information latency vs liquidity latency

"How long until the stock responds" is two questions that had been tangled
together in every earlier measurement here:

- **Information latency** — how long after EDGAR accepts the filing does the
  price actually move?
- **Liquidity latency** — how long until the tape prints at all, so an order can
  fill?

If information latency is *longer*, there is a real window: you get filled before
the price moves. If it is *shorter*, the move happens while you wait for a
counterparty and you buy the top of it.

**2,179 8-K filings across 1,454 names, 1–29 July 2026**, on 1-minute bars
including pre- and post-market.

## The order does not vanish

Earlier work here recorded "not fillable at T+1min" and dropped the filing. That
flatters the strategy. A market order placed one minute after acceptance and
finding no counterparty **rests and fills at the first print, whatever it costs**.
Every filing gets a fill here, and filings that waited get the price they waited
into. That is the honest model of "we sent the order but weren't sure of the
liquidity."

## When the order actually fills

| session | n | share | filled ≤2 min | median wait | p90 wait |
|---|---|---|---|---|---|
| **regular** | 168 | **8%** | **45%** | **3 min** | 46 min |
| pre-market | 645 | 29% | 1% | 90 min | 195 min |
| after-hours | 1,354 | 62% | **0%** | **1,034 min** (17h) | 3,914 min |
| closed | 26 | 1% | 0% | 754 min | 808 min |
| **ALL** | **2,193** | | **4%** | **995 min** (16.6h) | 3,870 min |

**Only 4% of orders fill within two minutes.** The median order waits nearly
seventeen hours — not for a better price, but for a market to open.

## When the price responds

First traded print that moved this far from the last pre-filing price:

| threshold | responded | median lag | p25 | p75 |
|---|---|---|---|---|
| ≥1% | 99% | 1,010 min | 147 min | 1,048 min |
| ≥2% | 98% | 1,031 min | 178 min | 1,293 min |
| ≥5% | 83% | 1,339 min | 974 min | 5,366 min |

## The two latencies are the same number, and that is the finding

Median fill: **995 minutes.** Median 1% response: **1,010 minutes.**

They are nearly identical because **both are gated by the same event — the
market opening.** The filing lands at 6pm, nothing happens until 9:30am, and then
the first print and the price response occur together.

| threshold | filled BEFORE the move | median gap |
|---|---|---|
| ≥1% | **39%** | **+0 min** |
| ≥2% | 59% | +3 min |
| ≥5% | 79% | +151 min |

At the 1% threshold it is a coin flip with a zero-minute gap. **There is no
window overnight.** You cannot be early to a market that is not running, and when
it starts running the price has already gapped.

## In regular hours the window is real

The 8% of filings that land while the market is open behave completely
differently:

| | regular hours (n=168) | of those filled ≤2min (n=76) |
|---|---|---|
| filled before a 1% move | 76% | **83%** |
| median gap | +30 min | **+20 min** |
| filled before a 2% move | 89% | 93% |
| already moved at fill | +0.06% median | **+0.09% median** |

**You get filled at roughly nine basis points from the pre-filing price, and the
1% move arrives twenty minutes later.** That is exactly the window the thesis
predicted, and it exists.

## And it is worth nothing

Forward return **from the actual fill price** (buy the offer, sell the bid):

| cohort | n | +15m | +60m | +240m | t(240m) |
|---|---|---|---|---|---|
| all sessions | 2,179 | −0.89% | −0.38% | −0.58% | −0.76 |
| regular hours | 168 | −0.34% | −1.29% | −0.52% | −0.52 |
| **regular + filled ≤2min** | **76** | **−0.25%** | **−1.43%** | **−1.81%** | **−1.85** |
| pre-market | 637 | −1.02% | +1.97% | +0.99% | +0.48 |
| after-hours | 1,348 | −0.88% | −1.31% | −1.25% | −1.67 |

The ideal case — regular hours, filled inside two minutes, the exact scenario the
whole latency thesis describes — returns **−0.25% at 15 minutes, −1.43% at an
hour (t=−2.11), −1.81% at four hours**, winning 47% of the time.

**The window is real and the move that fills it is as often down as up.** 56% of
regular-hours filings are up at fill and 44% down; the subsequent move is
negative on average. Being early is not the same as being right.

## A data artifact worth recording

Fourteen filings (0.6%) showed moves above +100% at fill. All were **reverse
splits**, not price moves — unadjusted minute bars carry the raw print:

| ticker | pre | fill | ratio |
|---|---|---|---|
| DBGI | $0.4751 | $19.38 | 40.8× |
| EDBL | $0.1199 | $4.491 | 37.5× |
| PRPL | $0.3243 | $7.50 | 23.1× |
| VIVK | $0.2115 | $4.11 | 19.4× |
| SGLY | $0.2630 | $3.36 | 12.8× |

Those ratios are round split factors. Leaving them in put the mean "already moved
at fill" at **+7.94%**; removing them gives **+0.72%** — an eleven-fold difference
from fourteen rows out of 2,193. Any statistic on unadjusted minute bars needs
this screen.

## Summary

| question | answer |
|---|---|
| median time to fill an order sent at T+1min | **995 min (16.6 h)** |
| share filling within 2 minutes | **4%** |
| median time until the price moves 1% | **1,010 min** |
| is there a gap between them? | **No — 0 minutes at the 1% threshold** |
| in regular hours? | **Yes — filled 20 min before the move, 83% of the time** |
| what is that window worth? | **−1.43% at 60 min, t=−2.11** |
| how much has price moved when we fill? | **+0.09% median (regular, immediate)** |
