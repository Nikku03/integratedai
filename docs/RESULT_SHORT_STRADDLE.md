# Selling the event straddle

Every measurement in this work says the buyer overpays: the straddles cost 11.3%
of spot and the events delivered 6.2%, an edge of −5.1pp. This tests the other
side of the same trade.

**It has positive expectancy and a tail that can take four times your capital on
one trade.** Both halves are the finding.

## The accounting cannot simply be flipped

Reporting a short straddle as "minus the buyer's return" is arithmetically true
and financially misleading. The buyer stakes the premium and cannot lose more
than it. The seller *receives* the premium, posts margin, and has no cap on the
loss. Three denominators, answering different questions:

* **dollars per contract** — what happened;
* **share of premium collected** — the mirror of the buyer, useful only for
  comparing the two sides;
* **share of margin** — the only framing in which this can be compared to
  anything else, because margin is the capital at risk. Reg T on a short
  straddle is roughly the naked leg's 20% of underlying plus the other leg's
  premium; at the money that is about 31% of spot. Brokers differ.

## What actually happened, on 16 real straddles

| set / exit | n | on premium | on margin | win | worst single trade |
|---|---|---|---|---|---|
| all priced, bought back at the open | 16 | **−5.7%** | −3.1% | 56% | **−$1,010** |
| all priced, at that close | 16 | +5.9% | +2.2% | 81% | −$435 |
| executable only, at the open | 5 | **+6.5%** | +2.4% | 80% | −$41 |
| executable only, at that close | 5 | −1.1% | −0.7% | 80% | −$84 |

The measured result is **small and it changes sign depending on which subset and
which exit you pick**. On sixteen trades that is noise, not a finding. The worst
single trade in the set was AXT, which gapped +42.1% and cost the seller $1,010
on $2,047 of margin — half the capital posted, on one name.

## When to buy it back

| bought back at | n | seller, on premium | win |
|---|---|---|---|
| the opening print | 5 | +6.5% | 80% |
| that afternoon's close | 5 | −1.1% | 80% |
| **the end of the hold window** | 5 | **+12.8%** | 80% |
| *the buyer's best minute* | 5 | *−25.5%* | *40%* |

The best is holding on — the mirror of the buyer decaying from the opening bell.
The ordering is **not monotone** and five trades cannot establish it. What it
does show is the structural point: **the edge is an at-expiry quantity.** Closing
early hands most of it back, and closing early is also the only way to cap the
tail. You cannot have both.

## The tail, on 2,842 earnings releases

This is the solid part of the document. Every Q2-2026 earnings release with a
measurable overnight gap, against a premium held to expiry — the optimistic case,
since it assumes the full credit is captured.

| overnight gap | |
|---|---|
| median | 3.6% |
| mean | 6.1% |
| 90th percentile | 15.0% |
| 95th percentile | 21.1% |
| 99th percentile | 36.1% |
| **maximum** | **132.6%** (IVF) |

At a premium of 11.3% of spot, margin about 31.3%:

| | |
|---|---|
| mean return on margin, per trade | **+16.5%** |
| a typical winner | +24.7% |
| win rate | 84.9% |
| the 1-in-100 trade | −79.3% |
| **the worst trade in 2,842** | **−387.6%** — 3.9× the capital posted |
| winners erased by that one trade | **16** |
| trades losing more than the whole margin | 0.53%, about 1 in 189 |

At 13.7% premium the numbers improve to +22.5% mean, 88.2% win rate, worst
−352.8%, 1 in 284 losing more than margin.

**The expectancy is real and it is large.** So is the tail. Both statements come
from the same 2,842 observations.

## The eight gaps a seller would not have survived

| | gap | that day's close |
|---|---|---|
| IVF | **+132.6%** | +57.5% |
| DOCS | +88.1% | +32.6% |
| CAPR | +81.9% | +58.0% |
| FGI | +79.1% | +147.8% |
| BWMN | +55.5% | +55.8% |
| GTE | +51.2% | +38.2% |
| GXAI | +50.5% | +44.7% |
| CVRX | −49.3% | −59.8% |

DOCS traded $497M a day. This is not a small-cap-only hazard.

## What this means in practice

1. **Sizing is the entire strategy.** A trade that can lose 3.9× its margin means
   no single position can exceed roughly a fifth of capital, and that assumes only
   one blows up at a time. Earnings season concentrates dozens of these into three
   weeks, so they are not independent draws — a market-wide repricing hits many at
   once.
2. **The edge and the tail are the same object.** You are paid 16.5% on margin for
   carrying the risk that a stock gaps 130%. That is not a mispricing to harvest;
   it is compensation, and the measured excess over fair compensation is what this
   whole exercise has been trying and failing to establish to any useful precision.
3. **Defined risk changes the question.** Selling a straddle and buying wings
   further out — an iron condor — caps the 387% loss at a known number and gives
   up part of the 16.5%. Nothing here measures that, and it is the obvious next
   test if this direction is pursued.
4. **Sixteen real trades established nothing.** The result flips sign between
   subsets. The 2,842-event distribution is what carries weight, and it is a
   simulation at expiry rather than a backtest with fills.

## Limitations

* **No bid-ask, and it hurts the seller more.** A short straddle is opened by
  selling two spreads and closed by crossing two more. On weekly small-cap
  contracts that is a large fraction of the measured few percent.
* **Assignment is unpriced.** One leg is in the money the instant the stock gaps,
  and American options can be exercised against you overnight. The backtest always
  closes at a market price and is never assigned, which flatters the seller.
* **The tail table holds to expiry**; the real trades did not. The two halves of
  this document are not measuring the same thing, and the honest reading is that
  the simulation shows the shape while the sixteen trades show nothing.
* **One earnings season**, and implied-versus-realised varies by regime — the
  seller's edge is smallest exactly when volatility is rising.
* Margin is a Reg T approximation; portfolio margin would be lower and would make
  both the return and the ruin risk larger.

## Reproducing

```
python3 scripts/options_short_straddle.py
```
