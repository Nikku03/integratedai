# Long weekly options on 8-K events: fifteen blind sessions

Pre-registered in `PREREG_WINDOW_W5.md` at `1faab1e`, committed before a single
option was priced. Judgements made from filing text by readers forbidden from
touching market data. Window chosen to exclude every date whose per-name outcomes
had already been seen in this session.

**The option mechanics are fine. The reading is the problem — and I predicted the
opposite.**

## Funnel

```
2,756  8-K filings, 2026-08-17 → 2026-09-04     (15 sessions, 1,997 filers)
  746  held across a bell, ticker above $20M/day
   81  market cap $300M–$20B and price-to-sales ≥ 8.0x   (100% XBRL coverage)
   48  have a WEEKLY chain (nearest expiry ≤ 10 days)
   30  and a non-zero directional reading
   23  and a contract that actually traded
```

36 of 81 filings were judged **0 — no directional information at all**, and 42 of
81 routine. That is what an 8-K usually is.

## The headline

| arm | n | mean | median | win | $40 → |
|---|---|---|---|---|---|
| all directional trades | 30 | −0.1% | +0.0% | 40% | **$0.01** |
| **tradeable only** | **23** | **−6.8%** | −30.0% | 43% | **$0.07** |
| positive readings (calls) | 16 | **−23.3%** | −15.0% | 44% | $0.05 |
| **negative readings (puts)** | 7 | **+31.2%** | −35.6% | 43% | **$55.17** |
| *the same bets on the stock itself* | 23 | +0.6% | −0.8% | 48% | **$42.81** |

Trading the underlying on the same judgements roughly breaks even. Trading the
option destroys the stake. Leverage on a coin flip is not a strategy.

## What actually breaks it

| | |
|---|---|
| a correct call returns | **+40.3%** (n=11) |
| a wrong one returns | **−49.9%** (n=12) |
| break-even therefore needs | **55.3%** accuracy |
| the reading delivered | **47.8%** |
| shortfall | **−7.5 percentage points** |

Losses are near-total and wins are not, so a coin flip compounds downward. Seven
and a half points of accuracy is the entire gap between this and a working
strategy.

## H4 was wrong, and it was my hypothesis

I registered that *the option would lose even where the direction was right* —
that an at-the-money weekly is nearly all extrinsic value and a resolved event
destroys it whichever way it resolves. The evidence for that came from a case
where a stock rose 24% and its call rose only 12%.

| where the direction was RIGHT (n=11) | |
|---|---|
| the stock moved | +6.3% the right way |
| the option returned | **+40.3%** |
| lost money anyway | **1 of 11** |

**Refuted.** With the strike set at the money *of the session you actually buy in*
and 2–8 days to expiry, being right paid 6.4× the underlying move. The earlier
result came from a strike chosen against the wrong reference price — the session
before the gap rather than the session of purchase — which left the contract far
from the money by the time it was bought. That was a bug in the measurement, not
a property of options.

## The other registered hypotheses

**H1 — the reading does not predict direction.** 47.8% correct, a coin. The
registered asymmetry did appear: puts beat calls by **−54.7pp** (calls minus
puts), 95% CI [−118.7, +6.7]. It points where four earlier windows pointed — the
negative readings carry the signal and the positive ones do not — and on seven
puts the interval still spans zero.

**H2 — avoiding names that already moved is worth +28.0pp**, 95% CI [−16.3,
+73.5]. Your rule, measured: of 23 tradeable events, 4 were flagged as already
priced and they returned −29.7% against −1.9% for the rest. The direction is
right and four observations cannot establish it, which is exactly what the panel
test on 160,920 rows said when it put this rule at −0.06pp with an interval
spanning zero.

**H3 — the "is this actually news?" flag works.** Filings judged to carry
genuinely new information moved their stocks **5.8%**; those merely furnishing an
already-known matter moved **3.6%**. The reading layer can tell a real event from
an administrative one even where it cannot tell up from down.

## The registered alternative exits

| sell at | n | mean | $40 → |
|---|---|---|---|
| the opening print | 19 | −2.6% | $6.28 |
| one hour in | 23 | −2.4% | $2.81 |
| two hours in | 23 | −1.1% | $1.16 |
| **the close (registered primary)** | 23 | **−6.8%** | $0.07 |

Every exit loses. Naming the primary in advance is what makes that statement
worth anything.

## The trades that worked, and the one that did not

Three puts carried the entire positive arm: **USA Rare Earth +147%** on a merger
closing that issued 126.8M shares with a third unlocked, **Enovix +121%**, and
**D-Wave +115%**. Two calls: **Amylyx +204%** on clinical data and **Summit
+46%**.

The clearest miss is **EyePoint**, judged −2 on clinical data, bought as a put —
the stock rose **20.0%** and the put lost 46.7%. A −2 is the reading this
repository trusts most, and here it was simply wrong.

## Limitations

* **23 tradeable trades.** Nothing here is established. The 7-put arm that
  carries the result is the thinnest part of it.
* **No bid-ask.** The key serves aggregates but 403s on NBBO. On weekly
  small-caps that spread is a large fraction of a −6.8% mean.
* **One name kept with a flag:** CAPR's 2026-08-13 gap was seen earlier today,
  though the 2026-08-24 event traded here is a different filing. IVF was excluded
  outright.
* The window is fifteen sessions of one market regime.

## What would have to change

The gap is **7.5 points of direction accuracy**. Nothing about the instrument,
the expiry, the strike or the exit closes that — all four were tested and the
best of them still loses. Either the reading improves past 55%, or the
conclusion is that 8-K text does not contain tradeable direction and the durable
signal is the narrower one this work keeps re-finding: strongly negative filings,
traded as puts or as short stock.

## Reproducing

```
python3 scripts/window_events.py --dates <15 sessions> --exclude IVF
python3 scripts/events_screen.py --calendar .../win_events.parquet --out .../win_screened.parquet
python3 scripts/window_prefile.py
POLYGON_API_KEY=... python3 scripts/window_options.py      # chains, direction-agnostic
POLYGON_API_KEY=... python3 scripts/window_trade.py        # one leg per judged event
python3 scripts/window_report.py
```
