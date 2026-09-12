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

---

# The option half

The signal was established on the underlying. These are the trades once a
premium had to be paid. Only the leg the rule buys was priced — 45 most-liquid
events, one contract each — so the momentum arm appears by its direction
accuracy alone and its P&L is not measured.

**Twelve of 45 had no weekly expiry** (LSCC 11 days, AXSM 14, NTLA 15, FORM 16,
ESS/IONS/OHI 17, RMBS 18, VICR 25, DGXX 35, MANE no chain). The capacity limit
registered as H4 held again.

## The result

| arm | n | mean | median | win | $40 → |
|---|---|---|---|---|---|
| reversal, all priced | 31 | −4.7% | −21.3% | 32% | **$0.00** |
| reversal, tradeable contract | 12 | **+6.8%** | −12.7% | 25% | **$8.70** |
| where direction was right | 8 | +34.3% | −3.1% | 38% | $171.19 |
| where direction was wrong | 4 | −48.2% | −54.6% | 0% | $2.03 |
| *the underlying, same bets* | 12 | −0.8% | +1.9% | 67% | $33.24 |

Direction accuracy held up — **66.7%** on the twelve priced trades, against
61.9% on the 118-event underlying sample. **The money still went backwards.**

## Why a real edge still lost

**First: the premium is exactly the favourable move.**

| among the 8 trades where the direction was RIGHT | |
|---|---|
| mean gap in your favour | **5.7%** |
| mean premium paid | **5.7%** |
| still lost money | **5 of 8** |

The market prices the gap correctly. Being right on direction buys you a
break-even, not a profit. Rigetti gapped the right way and the put lost 21%;
Onto gapped 5.7% the right way and returned 0%; D-Wave 6.7% the right way, −3%.

**Second: the rule wins small and loses big.**

| | mean \|gap\| | median | max |
|---|---|---|---|
| when RIGHT (18) | **6.0%** | 6.2% | 13.8% |
| when WRONG (13) | **13.6%** | 12.3% | 34.0% |

**It is wrong by 2.3× as much as it is right by.** The rule fades stocks that
rallied into their report. Usually the rally fizzles and the fade earns a
little. Occasionally the rally was the market being early, the report confirms
it, and the stock runs:

```
SITM  ran +18.2% in, gapped +34.0%  ->  put -96%
HUT   ran +11.6% in, gapped +26.2%  ->  put -96%
DOCN  ran +10.0% in, gapped +19.7%  ->  put -99%
QUBT  ran  +7.2% in, gapped +24.8%  ->  put -68%
EOSE  ran +30.0% in, gapped +23.1%  ->  put -68%
```

That skew is why a 66.7% hit rate compounds downward:

```
all priced          arithmetic mean  -4.7%   geometric  -43.8%
tradeable contract  arithmetic mean  +6.8%   geometric  -11.9%
```

**Positive average, negative compounding** — the same shape this entire body of
work opened with. A −96% is not undone by a +50%.

## Against the pre-registration

**H1 — half refuted, and that is the useful half.** I registered that both tape
arms would land near 50%. Reversal reached **61.9%** with a day-clustered
interval of [53.2, 69.7] that excludes 50% and survives the Bonferroni
adjustment for having registered both mirrors. **The direction signal is real.**

**H2 — consistent.** The winning arm is 95 puts against 23 calls, and only 47%
of all screened events gapped up.

**H3 — CONFIRMED, and it is the finding.** Every arm lost money despite the
signal. Break-even accuracy on the actual prices was **58.4%** and the rule
delivered **66.7%** — it cleared the bar on accuracy and still lost, because
break-even accuracy assumes symmetric payoffs and these are not: right by 6.0%,
wrong by 13.6%.

**H4 — confirmed.** 12 of 45 had no weekly contract.

## What this actually means

**A real directional edge is not sufficient.** That is the whole lesson, and it
took a genuine signal to demonstrate it — every earlier attempt failed on
accuracy, so the pricing objection was never tested. Here accuracy was not the
problem and the trade lost anyway, for two reasons that compound:

1. the option is priced at the move it delivers when you are right, so a correct
   call is worth roughly zero before costs;
2. the errors are 2.3× the size of the wins, so the distribution is
   left-skewed and the geometric mean sits far below the arithmetic one.

To make money from this signal you would need the payoff fixed, not the
accuracy. Concretely: a **spread** rather than a naked long option, which caps
the −96% tail at the cost of capping the upside — which is the one structure
this work has repeatedly pointed at and never tested.

## Limitations

* 31 priced trades, 12 with a tradeable contract. The direction result rests on
  118 underlying events; the P&L result does not and should not be quoted with
  the same confidence.
* One window, one regime, and a rising tape.
* No bid-ask. The arithmetic mean of +6.8% on the tradeable subset would not
  survive four crossed spreads.
* Only the reversal leg was priced, to keep the request count inside a
  five-per-minute key.
