# Pre-positioned weekly options on Q1-2026 earnings — the underlying half

Pre-registered in `PREREG_Q1_PRERELEASE.md` at `ade456c`, committed before any
Q1-2026 price, filing or option data was fetched. Window chosen because every
other window in this session is contaminated: gap **signs** for ~16 Q2 names and
the full outcomes of the August–September 8-K test have been seen here.

**A directional signal that survives every test I registered against it.** This
document covers the underlying; the option-level result is priced separately.

## Sample

```
7,833  8-K filings, 2026-04-20 → 2026-05-15   (20 sessions)
2,949  held across a bell, ticker above $20M/day
1,492  carry item 2.02 — a scheduled earnings release
  187  market cap $300M–$20B and price-to-sales ≥ 8.0x   (100% XBRL coverage)
```

182 names over 20 sessions. Every screen point-in-time: share count filed before
the event, price the last close before acceptance, revenue known at that moment.

## The signal

The rule, fixed in advance: measure the five-session run into the print in units
of the name's own volatility, to the last bell **before acceptance**.

| ran into the print | n | gapped **up** | mean gap |
|---|---|---|---|
| **UP** (z > +0.5) | 95 | **38%** | **−0.93%** |
| flat (\|z\| ≤ 0.5) | 69 | 52% | +1.76% |
| **DOWN** (z < −0.5) | 23 | **65%** | **+3.22%** |

Monotone. A stock that rallies into its report is more likely to gap down, and
one that sells off into it is more likely to gap up.

**REVERSAL — put on the run-ups, call on the sell-offs — was right 61.9% of 118
trades.**

| test | result |
|---|---|
| naive 95% CI | [53.1, 70.6] |
| two-arm Bonferroni (mirrors were registered) | [51.8, 71.9] |
| **day-clustered bootstrap, 18 sessions** | **[53.2, 69.7]** |
| P(accuracy ≤ 50%) | **0.007** |

The momentum arm is its exact mirror at 38.1%, as registered.

## Why this is not the usual confound

Two checks, both of which it passes:

**It runs against the tape.** SPY rose **4.3%** over the window. A rising market
makes "gap up" the easy base case and would flatter any rule that mostly says
call. The winning arm here mostly says **put** — 95 of its 118 trades — and it
still won.

**The base rate was against it too.** Across all 187 screened events only 47%
gapped up and the median gap was **−0.21%**, so the reversal arm was not simply
riding a drift.

## What was registered, and what happened

**H1 — registered expectation: both tape arms land near 50% and both lose.**
Half wrong. Reversal reached 61.9% with an interval excluding 50%. Registering
the expected failure is what makes this worth reporting: the null was the
prediction and the data refused it.

**H2 — always-put beats always-call.** Consistent so far: only 47% of events
gapped up and the median gap was negative.

**H3 — every arm still loses money.** Not yet answered. 61.9% clears the
**55.3%** break-even implied by the leverage measured on 30 real weekly
purchases, and falls short of the **~69%** implied by a realistically marked
premium. Which of those two is right is exactly what the option prices decide,
and they are what this test turns on.

**H4 — weekly chains will be the capacity limit.** Holding: the chain sweep is
rejecting most names for having no expiry within 10 days, as it did in Q2
(21 of 73).

## What this does not establish

* **One window, 20 sessions, one regime.** Pre-earnings reversal appearing in
  April–May 2026 is not proof it appears in October.
* **Events are not independent** — hence the day-clustered interval, which is
  the one to quote.
* **118 trades on the underlying.** The option sample will be far smaller,
  because most of these names have no weekly contract.
* **The signal is about the gap, not about profit.** A 61.9% hit rate on
  direction and a losing option book are entirely compatible, and that is the
  open question.

## Reproducing

```
python3 scripts/window_events.py --dates <20 Q1 sessions>
python3 scripts/events_screen.py --calendar .../q1_earnings.parquet
python3 scripts/window_prefile.py --events .../q1_screened.parquet
POLYGON_API_KEY=... python3 scripts/window_options.py --events .../q1_prefile.parquet
POLYGON_API_KEY=... python3 scripts/q1_price.py
```
