# Pre-registration: short vertical credit spread on scheduled earnings

Committed before the window's events were assembled or priced. Every element is
forced by a prior measurement in this repository rather than chosen, and the
derivation is given so the rule cannot be quietly changed afterwards.

## What each failure forces

| measured failure | what it rules in or out |
|---|---|
| bought at the open after a filing, missed the gap; Rigetti gapped +7.8% then faded | be positioned **before** the release |
| an unscheduled filing bleeds ~8.7% of premium per quiet session against a ~4% daily chance | **scheduled events only** |
| the market charged 13.7% for a move delivering 9.9% over 2,842 releases; **30 of 30** names priced above their own gap history | **sell** premium, never buy it |
| naked selling's worst trade was **−387% of margin** | the loss must be **capped** |
| the four-legged butterfly's +24.3% died at $0.063 per leg, and its edge was **+1.0%** in liquid names | **two legs, not four** |
| the reversal signal is real (61.9%, day-clustered CI [53.2, 69.7]) but long options on it lost, winning 6.0% and losing 13.6% | express the signal as a **seller**, where a flat tape also wins |

A two-legged short vertical is the only structure satisfying all six.

## Why selling changes the signal's economics

A long put on a stock that ran up needs the stock to **fall more than the premium**
— one way to win. A short call spread on the same stock wins if the stock falls,
stays flat, **or rises a little**. The skew that killed the long version — win
small, lose big — inverts: the seller's win is the full credit and the loss is
capped by the long leg.

## The rule

**Universe.** 8-K item 2.02 (a scheduled earnings release) in the window; held
across a bell, never intraday; ticker trading ≥$20M/day; market cap $300M–$20B;
trailing price-to-sales ≥ 8.0x; a weekly expiry within 10 days of entry. All
screens point-in-time.

**Signal.** `run_z` = the five-session return into the last close before
acceptance, in units of that name's own volatility.

* `run_z > +0.5` — the stock ran up → **sell a call spread**
* `run_z < −0.5` — the stock ran down → **sell a put spread**
* otherwise — **no trade**

**Structure.** Sell the strike nearest that last pre-release close. Buy the
strike nearest **10% further out** in the direction of the risk. Credit is what
the short leg fetches less the long leg's cost; **maximum loss is the width less
the credit**, which is also the margin.

**Timing.** Enter at the close of the last session before acceptance. Exit at the
open of the first session after — the gap is the whole move.

**Costs, applied from the start this time.** Two legs in and two out is **four
spread crossings**. The base case charges **$0.05 per crossing**, the smallest
increment US options quote above $3. Reported gross and net, with sensitivity.

## Hypotheses

**H1.** The gross return on margin is positive. The seller collects a premium
measured as systematically rich and holds a directional view measured at 61.9%.

**H2 (the one that matters).** It stays positive **net of $0.05 per leg**. This
is precisely the test the butterfly failed, and halving the leg count is the
only reason to expect a different answer.

**H3.** The break-even spread should be roughly **double** the butterfly's
$0.063, because the structure crosses half as many spreads for a comparable
credit. A checkable prediction, not a hope.

**H4.** Sample will be small. Mid-August to mid-September falls between earnings
seasons, so few issuers report and fewer carry weeklies.

## Disclosure

This window is **not blind**. Outcomes across 2026-08-17 → 09-11 have been seen
in this session, including gap signs for a number of names. The rule is
mechanical — a formula over price history and a fixed structure, with no reading
and no discretion — so knowledge of outcomes cannot enter it, and it is committed
here before the events are assembled. But it is weaker evidence than the genuinely
blind tests earlier in this work, and should be read as a consistency check on a
strategy derived elsewhere rather than as an independent confirmation of it.
