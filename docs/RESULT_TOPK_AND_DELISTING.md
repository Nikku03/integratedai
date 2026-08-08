# Top-k picks profiled, and the delisting universe measured

Two questions: what does the daily shortlist actually deliver, and how much is
the survivorship problem worth. Test period 2024-07-01 to 2025-12-31, 377
sessions, 94,122 scored observations, ranked by the gradient-boosting magnitude
score (which beat the ADRNN, 0.8730 to 0.8618).

## The shortlist

| pick | n | conf | **hit%** | up20% | dn20% | both% | med up | med dn | mean size |
|---|---|---|---|---|---|---|---|---|---|
| **top 1** | 377 | 0.87 | **88.9%** | 48.8% | **66.1%** | 24.4% | +19.0% | −27.1% | 52.8% |
| **top 2** | 754 | 0.85 | **85.5%** | 45.9% | 59.0% | 17.9% | +18.1% | −24.6% | 49.0% |
| **top 3** | 1,131 | 0.83 | **82.9%** | 43.9% | 56.8% | 16.4% | +16.7% | −23.9% | 46.5% |
| **top 5** | 1,885 | 0.80 | **79.6%** | 41.1% | 53.5% | 13.5% | +15.6% | −21.6% | 43.2% |
| top 10 | 3,770 | 0.73 | 73.1% | 38.1% | 46.2% | 9.9% | +14.4% | −18.8% | 39.0% |
| top 20 | 7,540 | 0.64 | 64.7% | 35.0% | 36.9% | 6.3% | +13.1% | −15.2% | 34.0% |
| everything | 94,122 | 0.14 | 14.7% | 8.4% | 7.1% | 0.6% | +5.0% | −4.8% | 12.7% |

`hit%` is P(the stock moves at least 20% either way within ten sessions).
`both%` is the fraction that touched **+20% and −20% in the same window**.

The single highest-confidence name each day moves 20% within two weeks
**88.9% of the time**, against a 14.7% base rate. That is a 6.0x lift, and it
holds across 377 consecutive sessions.

## Timing

| pick | days to first ±20% | to first +20% | to first −20% | day of largest move |
|---|---|---|---|---|
| top 1 | **2** | 3 | 3 | 7 |
| top 2 | 3 | 3 | 3 | 7 |
| top 3 | 3 | 3 | 3 | 7 |
| top 5 | 3 | 3 | 4 | 7 |
| top 20 | 4 | 4 | 5 | 7 |
| everything | 6 | 6 | 6 | 8 |

Medians, in trading sessions from the entry. The top pick resolves in **two
sessions**, not ten, so a slot turns over roughly five times faster than the
label horizon implies. The largest excursion lands around day 7 in every bucket,
which means holding for the extreme costs five extra days beyond the first touch.

## What the picks look like

| pick | median price | median 20d daily vol | annualised | median ADV |
|---|---|---|---|---|
| top 1 | $11.28 | 17.95% | 285% | $16.3m |
| top 5 | $10.06 | 13.31% | 211% | $11.2m |
| top 20 | $8.00 | 8.60% | 137% | $7.1m |
| everything | $26.84 | 2.49% | 40% | $18.4m |

Liquid enough to trade. Also, unmistakably, a selection of already-violent
$8-11 stocks.

## Calibration

The score means what it says, which is not automatic for a boosted tree on a
15% base rate:

| decile | predicted | actual | gap |
|---|---|---|---|
| 0 | 0.3% | 0.3% | 0.0 |
| 4 | 3.8% | 4.2% | +0.4 |
| 7 | 18.3% | 20.9% | +2.6 |
| 8 | 32.7% | 34.9% | +2.2 |
| 9 | 61.3% | 62.2% | +0.9 |

Slightly under-confident in the middle, accurate at the top. A predicted 61%
really is a 62%.

## The finding that matters more than the hit rate

**Read the up20% and dn20% columns again.** For the top pick, 66.1% fall 20%
against 48.8% that rise 20%. Among top-5 picks that actually moved, only
**43.6% broke upward**, with mean max_up +33.7% against mean max_dn −27.7%.

The model is not finding moonshots. It is finding **distress**. Names about to
move violently are disproportionately names about to collapse, which is what
volatility selection does: it picks up companies in trouble, and companies in
trouble mostly resolve downward.

The direction head shifts this a little and not enough -- upper half 47.7% up
against lower half 39.5%, an 8.2pp spread that never crosses 50%.

And every one of those figures is measured on a panel that deleted its
bankruptcies.

## The delisting universe

Reconstructed from EDGAR quarterly form indexes, 2015-2026, using Forms 25,
25-NSE, 15-12B, 15-12G and their foreign equivalents -- a survivorship-free
record, because a filer that no longer exists still appears in the index of the
quarter it died in.

**26,845 delisting-form filings, 8,297 distinct companies**, averaging ~700
deaths per year with no year below 577.

Three things came out of it, and the second was a surprise:

**1. The panel's dead are unrecoverable, by construction.** Of 8,297 delisted
CIKs, only 1,690 (20.4%) still expose a ticker anywhere in EDGAR's submissions
data, and 955 of those are already in the panel. Roughly 735 dead tickers are
even *identifiable*, and a price vendor that dropped them returns nothing. The
bias cannot be repaired from these sources; it can only be measured.

**2. The 967 panel names that filed a delisting form did not die.** This looked
alarming -- 26% of the panel with a delisting filing yet prices running to the
last day. Checking whether the prices continued settled it: of 400 sampled,
370 have 20+ bars afterwards, the median is **1,143 further trading days**, and
100% of those bars carry real volume. Only 8 look frozen. These are SPAC unit
and warrant removals, share-class reclassifications, and NYSE-to-Nasdaq
transfers. The common stock kept trading.

That is good news of a narrow kind: **the panel is not contaminated with phantom
post-death prices.** It is missing names, which is a cleaner failure than fake
ones.

**3. The floor on the missing mass is 11.8%.** Restricting to names the
candidate pool knows about, a universe alive at any point since 2015 holds about
4,154 tickers, of which 492 delisted and are absent from prices. That is a floor
and not an estimate, because the pool is itself built from surviving filers and
never contained the majority of the 8,297 dead in the first place.

## What the bias does to each number above

| number | direction of the error |
|---|---|
| hit% for the top-k | roughly unaffected; a within-day ranking is computed across names that all existed that day |
| calibration | roughly unaffected, same reason |
| median move size | understated -- the largest collapses are missing |
| **up20% vs dn20%** | **badly overstated toward up** |

Applying the missing mass to the up/down split, assuming the absent names broke
downward:

| missing fraction | P(up given a big move), top-5 picks |
|---|---|
| 0% (as measured) | 43.6% |
| 11.8% (the measured floor) | 38.5% |
| 35% (a realistic small-cap rate) | 28.3% |

## Conclusion

What was built works, and it does not do what was wanted. A daily one-name
shortlist that moves 20% within two sessions, 88.9% of the time, calibrated,
across 377 sessions, is a real signal. It is a **volatility and distress**
signal. Directionally it leans the wrong way, and correcting for the delisted
names leans it further wrong.

Usable as: a watchlist for names about to become violent, and a short-side or
straddle candidate generator. Not usable as: a long moonshot finder, which is
what it was asked to be.
