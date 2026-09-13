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
