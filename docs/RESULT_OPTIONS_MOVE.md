# Aiming for ±100% option swings, and what actually makes a bidirectional trade pay

The target was a setup whose options fluctuate more than ±100%, so a
bidirectional position profits without calling direction. The swings are
reachable. They are not sufficient, and the reason is arithmetic.

## First, the arithmetic

A straddle costs `c + p`. At the money `c ≈ p`. If the winning leg doubles and
the loser goes to zero, the position is worth `2c` against a cost of `2c`.

**A +100% move on one leg is where the trade stops losing, not where it starts
winning.** To profit, the winner has to roughly triple. The condition that
actually matters is:

```
realised move  >  (call premium + put premium) / spot      ← the breakeven move
```

So the question is never how big the move is. It is how big the move is
**relative to the move already priced into the premium**.

## The moves these filings deliver

54 screened name-days with a measurable reaction, measured from the last close
before the filing was accepted:

| | gap only | to D+1 close | to window end |
|---|---|---|---|
| median \|move\| | 1.6% | **4.0%** | 6.3% |
| 90th percentile | 8.7% | 14.7% | 18.4% |
| mean \|move\| | 3.4% | 6.2% | 8.3% |

Only **22%** of filings moved more than 10% by the next close; **3.7%** moved
more than 20%. And the movement is concentrated in exactly the wrong place:

| stock $volume/day | n | mean \|D+1 move\| | share >10% | share >20% |
|---|---|---|---|---|
| **<$10M** | 21 | **8.7%** | **33%** | **10%** |
| $10–30M | 10 | 5.5% | 20% | 0% |
| $30–100M | 16 | 4.6% | 19% | 0% |
| **>$100M** | 7 | **3.1%** | **0%** | **0%** |

Monotone. The names that move are the names with no option chain — the biggest
movers in the window were IRD +39.9%, BBOT −37.7%, OCGN −22.9%, all trading
$1–10M a day. **The screen finds the movement and the option market is not
there to sell it to you.**

## Entered after the filing, no expiry choice works

Every straddle this test bought was priced above what the filing delivered:

| | expiry | DTE | straddle | breakeven | realised | paid off? |
|---|---|---|---|---|---|---|
| RGTI | 09-18 | 10 | 2.05 | 12.5% | 7.5% | no |
| QBTS | 09-18 | 10 | 2.06 | 11.6% | 5.9% | no |
| CORZ | 09-18 | 8 | 1.39 | 7.9% | 1.4% | no |

Shortening the expiry does everything you would hope — and still does not
rescue it:

| RGTI expiry | DTE | breakeven | realised | **call leg** | **put leg** | straddle |
|---|---|---|---|---|---|---|
| **09-11** | **3** | **9.2%** | 7.5% | **−98%** | **+160%** | **−13%** |
| 09-18 | 10 | 12.5% | 7.5% | −80% | +80% | −14% |
| 09-25 | 17 | 15.3% | 7.5% | −67% | +43% | −17% |
| 10-16 | 38 | 20.6% | 7.5% | −48% | +48% | −12% |

**The ±100% target was met** — the 3-day put returned +160%, and QBTS's +100% —
**and the straddle still lost 13%.** Breakeven falls from 20.6% to 9.2% as the
expiry shortens, which is real and useful, but the stock moved 7.5% and the
cheapest straddle available needed 9.2%. No contract choice fixes a move that is
too small for every contract on the board.

## What does work: hold it across the gap, and sell into the gap

A straddle is paid for **net displacement, not for the path**. Rigetti gapped
**+7.8%** on the filing and gave the whole move back within two sessions,
finishing −0.3% from where it started. A straddle held across all of that earns
nothing. One sold at the opening print earns a great deal:

| | expiry | DTE at buy | buy | sell | **straddle** | call leg | put leg | stock gap |
|---|---|---|---|---|---|---|---|---|
| **RGTI** | **09-11** | **7** | 0.95 | 1.58 | **+66.3%** | **+156.1%** | −68.4% | +7.8% |
| RGTI | 09-18 | 14 | 1.56 | 2.01 | +28.8% | +100.0% | −54.2% | +7.8% |
| RGTI | 10-16 | 42 | 2.84 | 3.31 | +16.5% | +66.0% | −38.8% | +7.8% |
| **QBTS** | **09-11** | **7** | 1.08 | 1.96 | **+81.5%** | **+210.0%** | −79.2% | +6.8% |
| QBTS | 09-18 | 14 | 1.72 | 2.67 | +55.2% | +125.0% | −17.9% | +6.8% |
| QBTS | 10-16 | 42 | 3.11 | 3.42 | +10.0% | +58.0% | −31.0% | +6.8% |

Three things fall out, and they are consistent across both names:

1. **Bidirectional and profitable.** No direction was called. The put lost
   68–79% and the position still made 66–82%.
2. **Shorter is better, monotonically.** +66% and +82% at 7 days against +17%
   and +10% at 42 days — the same dollar gap divided by a much smaller premium.
3. **The same trade held to Thursday returned −14.1% and −17.4%.** Exiting into
   the gap is not a detail; it is the entire result.

## The catch, priced

A near-dated straddle bleeds while it waits. The same RGTI contract, over the
sessions before the filing:

| session | stock | straddle | vs 08-28 |
|---|---|---|---|
| 2026-08-28 | 15.59 | 1.68 | — |
| 2026-08-31 | 15.66 | 1.47 | −12.5% |
| 2026-09-02 | 14.87 | 1.11 | −33.9% |
| **2026-09-04** | 15.20 | **0.95** | **−43.5%** |
| 2026-09-08 | 15.81 | 1.17 | −30.4% ← filing lands pre-open |

**−43.5% over five quiet sessions**, roughly 8.7% of premium per session. Buying
this straddle on 08-28 and selling into the 09-08 gap returns **−6%**: the bleed
eats the entire gain. Buying it on 09-04 — the day before — returns **+66%**.

That gives a hard requirement. With the gap paying ~70% and waiting costing
~8.7% a session, a one-session hold needs roughly a **12% chance the event lands
tomorrow** to break even. The base rate is far below that: the median issuer in
this sample went 20–30 days between 8-Ks, so any given session carries a ~4%
chance. Buying straddles and waiting for an unscheduled 8-K loses by a factor of
three before anything else goes wrong.

## What this means for the design

**A bidirectional trade on this strategy works, and 8-K filings are the wrong
event to run it on** — not because the reaction is too small, but because the
date is unknowable and the premium decays faster than the base rate pays.

The fix is to stop using unscheduled filings and use events whose **date is
published in advance**, where a one- or two-session hold is enough:

* **Earnings** — 8-K item 2.02, and the date is announced weeks ahead.
* **PDUFA action dates** — published; Intellia's own filing in this window set
  one for 2027-03-10.
* **Scheduled data readouts and conference presentations** — Disc Medicine's
  Phase 2 results were presented at a named meeting on a known date.
* **Shareholder votes** — item 5.07, noticed in advance.

The rest of the machinery carries over unchanged: the cap and price-to-sales
screens, the point-in-time option-liquidity gate, the requirement for a print
near both ends of the hold. What changes is that the position is opened the
session before a known date and closed at the opening print, on the shortest
expiry that survives the event.

Two things worth keeping from the failed version. The **reading layer is not
needed** for this — a straddle does not care which way the news breaks, which
removes the one component with no measured edge. And the **liquidity gate
becomes more binding, not less**, because a 3-to-7-day contract on a small-cap
is thinner than the monthly.

## Limitations

* **Two names, one event.** RGTI and QBTS announced the same CHIPS Act program
  on the same morning. Everything above is a worked mechanism, not a result.
* **No bid-ask.** The key serves aggregates but 403s on NBBO. A straddle crosses
  four spreads round trip, and on a 3-day small-cap contract that is a large
  fraction of the 66% — quite possibly most of it.
* The gap-exit price is the option's **opening print**, which on a gapping name
  is among the widest and least reliable marks of the day.
* The theta measurement is one contract over five sessions.

None of that changes the direction of the finding — realised versus implied,
and exit at the gap — but every number above should be treated as the best case.

## Reproducing

```
python3 scripts/options_screen.py
python3 scripts/options_features.py --no-gate
POLYGON_API_KEY=... python3 scripts/options_liquidity.py
python3 scripts/options_features.py
POLYGON_API_KEY=... python3 scripts/options_backtest.py
POLYGON_API_KEY=... python3 scripts/options_move.py      # this document
```
