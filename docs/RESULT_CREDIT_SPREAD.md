# Defined-risk selling into scheduled earnings

Structure fixed before pricing: sell the at-the-money call and put at the strike
nearest the close of the last session before acceptance, buy wings at K×1.15 and
K×0.85, enter at that close and exit into the opening gap. Weekly expiry.
Q1-2026 earnings season, the same 34 screened events the long tests used.

**This is the first configuration in this work that makes money.** It is also
the one whose remaining risk is largest and least measured.

## Why this structure and no other

Each step was forced by a measurement, not chosen:

| | |
|---|---|
| unscheduled filings cannot be timed | ~8.7% premium bleed per quiet session against a ~4% daily chance |
| so the event must be **scheduled** | |
| scheduled events are **overpriced** | 13.7% charged vs 9.9% delivered over 2,842 releases; **30 of 30** names above their own gap history |
| so the edge is on the **sell** side | |
| naked selling has an unbounded tail | worst trade **−387% of margin**, 1 in 189 losing more than the whole margin |
| so the tail must be **capped** | → wings |

## The result

| | all priced | both wings traded ≥25 |
|---|---|---|
| n | 22 | 18 |
| **mean return on margin** | **+24.3%** | **+30.0%** |
| median | +32.7% | +32.7% |
| win rate | **77%** | **83%** |
| worst trade | −100% | −100% |
| 95% interval on the mean | [−3, +51]% | [−0, +60]% |
| P(mean ≤ 0) | **0.042** | |

Return is quoted on **maximum loss**, which for a defined-risk spread is both
the worst case and the margin held — a number knowable before the trade rather
than discovered afterwards.

## What the wings bought

| | naked short | with wings |
|---|---|---|
| mean P&L, % of spot | 0.43% | **0.90%** |
| worst trade | **−17.49%** | **−5.30%** |
| standard deviation | 8.16% | **2.44%** |
| trades losing >5% of spot | 5 | **1** |

The wings cut the worst trade by **3.3×** and the standard deviation by **3.3×**
— and in this sample **raised** the mean rather than costing it, because the
naked version's few large losers (Hut −14.1%, DigitalOcean −10.2% of spot)
dominated its arithmetic. That will not always be true; protection normally
costs something. (The naked column is at-expiry arithmetic against actual marks
for the wings, so the mean comparison is indicative, not exact.)

The structure did exactly its job on the worst days. DigitalOcean gapped
**+19.7%** and lost 76% of a known maximum; IREN gapped **+12.3%** and still
*made* 72%, because the credit absorbed a move inside the wings.

## Position sizing is part of the strategy

One trade in 22 hit the full −100%. Risking the whole stake per spread therefore
ends at zero however good the average is:

| risk per trade | $40 becomes | worst drawdown |
|---|---|---|
| 100% | **$0.00** | −100% |
| 50% | $179.54 | −76% |
| 25% | $113.38 | −45% |
| **10%** | **$64.99** | **−20%** |
| 5% | $51.60 | −10% |

This is why "$40 compounded" — the frame used throughout the long tests — is the
wrong one here. A defined-risk seller's result is a function of sizing, and the
sizing has to assume the max loss arrives.

## Two marks had to be corrected

An iron butterfly cannot be worth more than its wing width; the two call legs
cannot be deeper in the money than the distance between them, and arbitrage
enforces it. Two closing marks exceeded the width — QUBT by 0.34 and EOSE by
0.02, both on gaps far beyond the upper wing — meaning the short leg's opening
print and the wing's came from different moments. Clamping them to the width
moved the worst trade from an impossible −163% to the structural −100% and the
mean from +21.1% to +24.3%. Reporting the raw figure would have been reporting a
loss the position cannot take.

## What is not established

* **22 trades, one window, one regime.** P(mean ≤ 0) = 0.042 is suggestive, not
  settled, and the interval's lower edge sits on zero.
* **No bid-ask, and this is the structure where that matters most.** Four legs
  to open and four to close is **eight** spreads crossed. On weekly contracts
  whose wings printed 3, 9, 16 and 19 times in a session, that cost could
  plausibly consume the entire +24%. This is the single largest unmeasured risk
  in the result and it cuts against it.
* **Assignment is unpriced.** A short leg goes in the money the instant the
  stock gaps and American options can be exercised overnight; the backtest
  always closes at a market price.
* Wing width was fixed at 15% in advance and never varied. Whether that is the
  right width is untested — narrower keeps less credit and caps harder.
* The liquid subset is 18 of 22, and the four dropped are not random: they are
  the thinnest chains.

## What would settle it

A second season, and a spread-cost model. The edge as measured is +24% on
margin; a realistic four-leg round trip on contracts this thin could be a large
fraction of that. Until that is measured, this is a promising result rather than
a working strategy — but it is the first one here that survived its own test.

## Reproducing

```
POLYGON_API_KEY=... python3 scripts/credit_spread.py
python3 scripts/condor_report.py
```

---

# Settled: the edge lives in illiquidity and cannot be harvested

The result above was gross of transaction costs, and for a four-legged structure
that was the open question. It is now closed.

## Estimating the spread failed, twice, and that is itself the finding

There are no quotes on this key. Two standard recoveries from trade prints were
tried and both broke:

* **Corwin-Schultz**, which separates spread from volatility using consecutive
  high-low ranges, returned a **0.00% spread for the thinnest contracts** and a
  wider one for the busiest — exactly inverted. A contract that prints once in a
  bar has high equal to low, so the estimator sees no range and reports no
  spread. It degenerates precisely where the cost is largest.
* **Price clustering** would work if a contract traded all session between a
  fixed bid and ask. It does not: AAOI's put printed **51 distinct prices in 70
  trades**, because the underlying moves all day. A day's interquartile range
  mixes spread with drift and is an upper bound, not a measurement.

So the spread is not estimated. The question is inverted instead, which requires
no estimate and cannot be wrong.

## How much cost the edge can absorb

A round trip on four legs pays **eight half-spreads — four full spreads**.

| spread per leg | cost per share | mean on margin | win rate |
|---|---|---|---|
| $0.00 | — | **+24.3%** | 77% |
| $0.01 | $0.04 | +20.4% | 73% |
| $0.03 | $0.12 | +12.7% | 68% |
| **$0.05** | $0.20 | **+4.9%** | 64% |
| $0.075 | $0.30 | −4.7% | 55% |
| $0.10 | $0.40 | **−14.4%** | 50% |

**Break-even spread: $0.063 per leg.**

US options quote in $0.01 increments below $3 and **$0.05 above**. So on most of
these legs the *tightest market that can exist* is a nickel, which leaves
+4.9% — inside the noise of a 22-trade sample.

## The liquidity filter makes it worse, not better

The obvious rescue is to trade only butterflies whose legs are busy enough to be
quoted tightly. It fails, and the way it fails is the whole answer:

| thinnest leg traded | n | **gross** | at $0.05 | break-even spread |
|---|---|---|---|---|
| any | 22 | +24.3% | +4.9% | $0.063 |
| ≥100 | 17 | +27.4% | +4.1% | $0.059 |
| ≥250 | 13 | +29.3% | +2.3% | $0.054 |
| **≥500** | 8 | **+1.0%** | −32.9% | **$0.001** |
| **≥1000** | 4 | **+2.0%** | −42.4% | **$0.002** |

**In the most liquid names the gross edge is +1.0% — there is no edge there at
all.** The +24.3% is concentrated in contracts whose legs trade a few dozen
times a session, which are exactly the ones no one quotes a nickel wide.

Where the spread is tight enough to trade, the edge is absent. Where the edge
exists, the spread consumes it. That is not a problem to be engineered around;
it is what an efficiently-priced illiquidity premium looks like from the inside.

For scale: a nickel on four legs is $0.20 against a mean margin of $1.39 in the
liquid tier — **14% of the capital at risk, paid on every trade before the
market moves at all.**

## Verdict

The structure was the right deduction from every prior measurement, and it does
what it was designed to do: it caps the tail, cuts the worst trade from −17.5%
to −5.3% of spot, and cuts volatility by 3.3×. **The overpricing it harvests is
real.** It is simply not larger than the cost of reaching it.

The second earnings season, named earlier as the other half of settling this,
was not run — and the cost result makes it moot. A second season confirming
+24% gross would still net to roughly zero at a nickel, and to less than that on
the thin legs that carry the gross figure.

**This closes the line of enquiry.** Buying scheduled-event options loses to
overpricing; selling them naked carries a −387%-of-margin tail; selling them
with defined risk harvests a real premium that is smaller than the eight
spreads required to collect it.

## What is left, honestly

Two things would change the arithmetic rather than argue with it:

1. **Fewer legs.** A two-legged vertical crosses four spreads instead of eight,
   halving the cost — but it is directional, and direction was measured at 61.9%
   accuracy with a payoff so skewed it still lost.
2. **Real quotes.** Every number in this repository is gross of the spread
   because the data has no bid or ask in it. That is the single most valuable
   upgrade available, and it would re-open every result here, not just this one.
