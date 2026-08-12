# Putting the dead companies back

The panel has zero delistings across 3,662 tickers in eleven years, and every
result in this repository sits on it. This is the attempt to fix that, and it
produced two findings — one correcting an error of mine, one settling the
question.

## First, a correction

I have repeatedly written that EDGAR shows **8,297 real deaths** and that the
survivorship gap is "roughly an order of magnitude larger than the edge". Both
statements were wrong, and they came from `delist_resolved.parquet`.

That table counted delisting *filings* and then resolved each dead CIK back to a
ticker through the SEC submissions API. The API returns the issuer's **current**
tickers, so the resolved death list is headed by:

```
APD   Air Products & Chemicals    25-NSE  2020-08-07
BMY   Bristol Myers Squibb        25-NSE  2021-01-04
CAT   Caterpillar                 25-NSE  2021-03-15
AIG   American International      25-NSE  2021-01-14
AMAT  Applied Materials           15-12G  2018-12-12
```

All alive. Their Form 25s delisted bonds and preferred classes. A survivorship
correction built on that table would have charged the strategy for Caterpillar
dying.

## What the filings actually say

A Form 25 is a small XML with two fields that settle it — `descriptionClass
Security` (what was removed) and `ruleProvision` (why). `delist_census.py` reads
both out of all 10,743 Form 25/25-NSE filings from 2015 to 2025.

Of 9,579 filings with a readable security class, only **37.3% were common
stock**. The rest were notes, debentures, preferred, warrants, units and
depositary shares. Then the rule provision splits what remains:

| | 2015–2025 |
|---|---|
| common-stock delistings | **3,569** |
| — involuntary, exchange struck it (12d2-2(b)) | **871** |
| — voluntary, issuer withdrew (mergers, moves) | **2,698** |

**871 involuntary common-stock deaths in eleven years — 79 a year**, not 8,297.

Coverage is not the weak point: Form 25-NSE is filed by the exchange and is XML
in every year, parsing at 99.8–100% throughout. The gaps are all in issuer-filed
Form 25s, which are HTML and are overwhelmingly debt redemptions.

Year by year, involuntary common-stock delistings:

| 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|---|---|
| 56 | 84 | 51 | 43 | 68 | 76 | **15** | 37 | 135 | **159** | 147 |

The 2021 trough and the 2023–25 spike are the SPAC boom and the microcap
washout that followed.

## The panel cannot literally be rebuilt

Twenty-two tickers were tested against Yahoo. Every genuinely dead one returned
**404** — SIVBQ, BBBYQ, WEWKQ, HTZGQ, PRTYQ, RADCQ, OTIC, ZGNX, KDMN, CHMA,
AMRS, LORL — and so did every acquired one: ATVI, TWTR, XLNX, CERN, ZNGA, NUAN.

Two answered, and both are worse than silence. **SBNY** returned 345 bars
beginning August 2024 — seventeen months after Signature Bank failed — because
the ticker was reissued to a different company. **FRCB** returned an unbroken
2015–2025 history for a bank that failed in May 2023. Missing data announces
itself; recycled data does not. Stooq, the usual free fallback, is unreachable
from this network (connection reset, including for AAPL).

`src/iai/sources/prices.py` already documented the fix — a paid extract with
delisted history — and nothing free substitutes for it. **The rate is
recoverable from primary sources. The prices are not.**

## So: does the rate kill the strategy?

`RESULT_AGREED_STRATEGY.md` reduced this to a single number. The k=5 book earns
+1.115% per trade and breaks even once about **1.10% of trades** are undisclosed
total losses. The question is whether the real hazard clears that.

Two inputs, both measured:

**The rate.** 79 involuntary common-stock delistings a year against a US listed
universe of 4,000–5,500 gives λ = **1.44% to 1.98% a year**.

**The over-exposure.** The picks are not a random draw — median pick price
**$6.39** against **$30.59** for the pool, sitting in sub-$5 names **6.07×** as
often and sub-$2 names **10.35×** as often. Since involuntary delistings happen
almost entirely inside that band, that ratio *is* the multiplier.

Probability a given ten-session position is in a name about to be struck:

| universe | λ/yr | m=1 | m=3 | **m=6** | m=10 |
|---|---|---|---|---|---|
| 4,000 | 1.98% | 0.079% | 0.236% | **0.471%** | 0.786% |
| 5,500 | 1.44% | 0.057% | 0.171% | **0.343%** | 0.571% |

Breakeven is **1.10%**. At the measured 6.07× the hazard is 0.34–0.47% —
**two to three times below the level that would erase the edge.**

Turned around, the book breaks only if the picks carry **14× to 19×** the
average delisting rate at a total loss, or **17× to 32×** at a 60–80% loss.
Measured, they carry 6.07×.

## The corrected book

Corrected mean per trade (measured +1.115%):

| universe | m | hazard | loss 60% | loss 80% | loss 100% |
|---|---|---|---|---|---|
| 4,000 | 6 | 0.471% | +0.827% | +0.733% | **+0.638%** |
| 4,000 | 10 | 0.786% | +0.635% | +0.478% | +0.321% |
| 5,500 | 6 | 0.343% | +0.906% | +0.837% | **+0.768%** |
| 5,500 | 10 | 0.571% | +0.766% | +0.652% | +0.537% |

Scaling the measured +292.7% total by the ratio of corrected to measured
per-trade mean:

| universe | m | loss 60% | loss 80% | loss 100% |
|---|---|---|---|---|
| 4,000 | 6 | +175.8% | +145.7% | **+118.8%** |
| 4,000 | 10 | +117.9% | +79.7% | +48.2% |
| 5,500 | 6 | +203.7% | +179.2% | **+156.7%** |
| 5,500 | 10 | +155.9% | +122.4% | +93.3% |

**The seven-year return survives at roughly +120% to +200% instead of +293%** —
a haircut of a third to a half, not an annihilation.

## The bias runs both ways

The finding that most changes the picture: **2,698 of the 3,569 common-stock
delistings were voluntary — mergers and exchange moves.** Those names are absent
from the panel too, and a takeover is the *good* outcome. Being acquired at a
premium is exactly the kind of large upward move this strategy exists to catch.

So the panel's survivorship bias removes 871 failures, which flatters the
results, *and* 2,698 takeovers, which understates them, at roughly three
takeovers per failure. That does not net to zero — the failures are larger
losses than the takeovers are gains, and picks are concentrated in the failing
population — but it is not the one-sided catastrophe I described.

## What is still wrong

* **The prices are still gone.** This is a rate correction, not a rebuilt panel.
  A name that fell 95% before being struck contributed nothing to the measured
  results either. Only a vendor extract fixes that.
* **The denominator is an external anchor.** 4,000–5,500 listed US common stocks
  is not derivable from EDGAR — 10-K filers include bond-only and unlisted
  registrants — so it enters as a range and every figure is shown at both ends.
* **m = 6.07 assumes hazard is uniform inside the sub-$5 band.** Deaths cluster
  below $1, and the picks are 0.0% sub-$1, which argues m is if anything
  overstated. But sub-$1 names heading to zero are themselves partly missing
  from the panel, so this cannot be settled from inside the data.
* **Delisting is not the only zero.** Bankruptcy usually destroys the equity
  weeks before the Form 25, while the stock still trades — and those bars *are*
  in the panel, so that part is already counted.
* **None of this touches the real fragility.** The book still rests on 18
  trades, still draws down 71%, and a 25% haircut on winners still turns it
  negative. Survivorship was never the biggest problem; it was just the one I
  had mis-sized.

## Reproducing

```
python3 scripts/delist_census.py --workers 24     # ~12 min, 10,743 filings
python3 scripts/survivorship_correct.py
```
