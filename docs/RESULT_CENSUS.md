# Result: start from the moves, not the filings

Every earlier study ran one direction — take filings, measure returns. That can
only find moves that *had* a filing, so it cannot answer the prior question:
**are filings even where the big moves come from?** This runs the other way.

Screened **5,424 names** for daily moves over the trailing 40 days, kept the
**3,525** above $1 with ≥$250k median daily dollar volume, then went looking for
the cause of each large move.

## The opportunity set is 8× what the pipeline was looking at

| threshold | names with a 1-day move | names with a 5-day move |
|---|---|---|
| ≥10% | **646** (18%) | 1,612 (46%) |
| ≥20% | 142 | 471 |
| ≥50% | 30 | 54 |
| max | **+602%** | +893% |

Restricted to 1–29 July, the study's own window: **218 names moved ≥20%**, 33
moved ≥50%. The classification study worked from 83 filings and found 23 with a
≥10% ceiling. It was looking at a few percent of the population.

## What caused the 20%+ moves (n=218, July, full EDGAR coverage)

| cause | n | share | median move | max |
|---|---|---|---|---|
| **no filing at all** | 83 | **38.1%** | +25.4% | +602% |
| **8-K** | 59 | **27.1%** | +31.8% | +313% |
| insider (Form 4/144) | 23 | 10.6% | +27.3% | +58% |
| offering / dilution | 17 | 7.8% | +36.1% | +202% |
| periodic report (10-Q/K) | 15 | 6.9% | +26.5% | +132% |
| passive stake (13G) | 8 | 3.7% | +38.5% | +74% |
| activist stake (13D) | 6 | 2.8% | +27.8% | +363% |
| merger / tender | 4 | 1.8% | **+149.5%** | +703% |
| proxy / other | 3 | 1.4% | +22.2% | +52% |

At ≥50% (n=33) the split is 8-K 30%, no filing 30%, periodic report 12%,
offering 6%, merger 6%.

**38% of 20%+ moves have no SEC paperwork behind them at all** in the seven days
up to the move. Sector sympathy, analyst actions, index events, squeezes,
peer-company news — none of it is in EDGAR, and none of it was reachable by
anything built here.

An earlier pass put that figure at 65%. It was wrong: `recent_filings.parquet`
covered only 2,853 of 5,490 names, so a third of movers came back "not covered"
and were being counted against filings. Backfilling EDGAR submissions for the
134 uncovered movers moved it to 38%.

## The pipeline saw none of the 59 8-K-driven movers

Not one of the 59 appeared in the 83 classified filings. The funnel lost them in
three places:

| stage | surviving |
|---|---|
| had an 8-K within 7 days of a 20%+ move | **59** |
| survived the filing scan — it covered 52% of the universe | 46 |
| survived pool construction — 298 tickers kept of 1,581 8-K filers | 8 |
| survived the tradability screen | **0** |

The last 8 died because **17 of their 18 filings arrived outside regular hours**,
so there was no print at T+1min. That is the latency study's finding arriving
from the other direction: the entry rule requires a market that is open when 92%
of filings are not.

Biggest ones missed: CLRO +313% (material agreement + debt), NVVE +220%,
TVRD +163%, CRNX +126%, FBRX +116%, AGEN +83%, ALIT +80%.

## Fixing the entry does not produce a strategy

The obvious repair is to enter at the **next session's open** instead of T+1min.
Measured on the 59 mover names it looks superb: +10.40% mean by day 10, t=+3.38.

**That number is worthless and the reason matters.** Those 59 names were selected
*because* they moved 20%. Measuring their filings' returns conditions on the
outcome — the exact bias this census set out to escape.

Here is the same test with no conditioning: **every 8-K in the window, 1,861
filings across 1,280 names**, entered at the next open, screened only on price
and prior-session liquidity.

| held | mean | median | win | ≥10% | worst | best | **t** |
|---|---|---|---|---|---|---|---|
| open → close | −0.39% | −0.23% | 46% | 40 | −45.0% | +99.6% | **−2.98** |
| +1 day | −0.84% | −0.56% | 43% | 71 | −58.3% | +92.1% | **−4.69** |
| +3 days | −1.21% | −0.47% | 45% | 81 | −79.3% | +104.7% | **−5.40** |
| +5 days | −1.76% | −0.56% | 44% | 98 | −84.8% | +104.7% | **−7.18** |
| +10 days | **−2.55%** | −0.84% | 43% | 116 | −84.8% | +106.1% | **−8.99** |

Monotonically worse with holding period, and significantly negative at every
horizon on the largest sample in this project — 22× the classification study.

**The selection bias was worth +12.95pp per trade.** +10.40% conditioned on the
outcome against −2.55% unconditioned. That gap is the entire apparent edge of
every "look at the moonshots" framing, quantified.

## One item code survives, and one confirms the trap screen

Entry at next open, held 10 sessions, item codes with ≥30 filings:

| item | what it is | n | mean | median | t | had ≥10% peak |
|---|---|---|---|---|---|---|
| **2.02** | **earnings** | 577 | **+0.78%** | +0.92% | **+2.13** | 18% |
| 7.01 | reg-FD disclosure | 610 | −2.02% | −0.75% | −4.77 | 17% |
| 2.03 | debt incurred | 119 | −2.06% | −0.54% | −1.35 | 24% |
| 5.02 | officer/director change | 386 | −3.05% | −2.23% | −5.27 | 23% |
| 8.01 | other event | 454 | −3.71% | −1.39% | −6.24 | 21% |
| 5.07 | vote results | 60 | −4.37% | −2.80% | −2.69 | 17% |
| 1.01 | material agreement | 294 | −5.66% | −3.54% | −5.88 | 23% |
| 2.01 | acquisition completed | 46 | −6.33% | −5.86% | −3.06 | 13% |
| 5.03 | charter amended | 46 | −10.14% | −6.77% | −3.54 | 28% |
| **3.02** | **equity issued (dilution)** | 62 | **−11.61%** | −9.63% | **−5.70** | 24% |

Item 2.02 is the only positive mean clearing t=2. Everything else is negative
and most are significantly so.

**Item 3.02 at −11.61% (t=−5.70) is the trap screen confirmed on 62 filings**,
15× the n=4 the classification pass had. Excluding dilution on item code alone
was the single best decision in the whole study, and it is now measured rather
than argued.

## The moonshots are real and not identifiable

By day 10 after the next open, **368 of 1,861 filings (20%) had touched +10%** at
some point and 115 (6%) had touched +20%. So the tail is there. But only **6.2%
actually closed +10%**, and the ones that did are almost indistinguishable at the
open from the ones that did not:

| | reached +10% by d10 | did not |
|---|---|---|
| median prior dollar volume | $29.8m | $16.2m |
| median open price | $29 | $27 |

A 1.8× difference in prior volume against a 6.2% base rate is not a screen. The
peak being available is not the same as it being reachable, and nothing in the
filing at the moment of the open tells you which one you have.

## What this means for everything above it

**The 8-K is not the right instrument.** 38% of large moves have no filing, and
across the full population the filings that exist predict *negative* returns. The
one exception is earnings, which is the most-watched, least-exploitable event
there is.

**The earlier positive-cohort result needs re-reading.** The +1.93pp
positive-vs-neutral spread (p=0.012) was measured on 79 filings that had all
passed the T+1min screen — meaning they were filed during regular hours, which
is 8% of filings and a distinct population. It may still hold there. It does not
survive being extended to the population, because the population's mean is
−2.55% with t=−8.99.

**What would need to change to do better than this:** cover the whole universe
rather than 52% of it; enter at the next open rather than T+1min, accepting the
gap; drop 8-K as the trigger and use the item codes that carry signal (2.02
positive, 3.02 short); and find a source for the 38% that EDGAR never sees. The
last of those is the largest single bucket and there is nothing in this
repository that reaches it.
