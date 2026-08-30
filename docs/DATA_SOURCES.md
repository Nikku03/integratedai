# Data sources

## Where to look for new ones

**<https://github.com/public-apis/public-apis>** — the catalogue of public APIs.
Raw list for programmatic use:

```
https://raw.githubusercontent.com/public-apis/public-apis/master/README.md
```

It is a markdown table per category, one row per API with an `Auth` column
(`No`, `apiKey`, `OAuth`). The categories that matter here are **Finance**,
**Government**, **Health**, **Open Data**, **Science & Math** and **Business** —
375 entries across those six, of which 202 need no authentication.

Two cautions learned from using it:

* **The `Auth: No` column is about the API, not about usefulness.** Of the 75
  entries whose name or description matches anything this project cares about,
  only 24 are keyless, and most of those are municipal open-data portals.
* **A listing is not a working endpoint.** Several entries are marketing pages
  for products that no longer exist, and at least one free-tier claim in the
  table is contradicted by the vendor's own pricing page. Everything below was
  probed with real requests from this container before being written down.

Extraction that produced the candidate set:

```bash
curl -sS https://raw.githubusercontent.com/public-apis/public-apis/master/README.md -o papis.md
# rows look like: | [Name](url) | Description | `apiKey` | Yes | Unknown |
```

## What this project actually needs

Ranked by how much each is blocking, from the results in `docs/`:

| # | Need | Why it blocks | Status |
|---|---|---|---|
| 1 | **Survivorship-free price history** | The panel has 3,662 tickers and zero delistings in eleven years. Yahoo 404s on every dead ticker and returned *recycled* data for SBNY. `RESULT_SURVIVORSHIP.md` | **still blocked — costs money** |
| 2 | **Short interest / days-to-cover** | Named in `RESULT_WHY_LOSERS.md` as missing information; the model's 108 features are exhausted at 0.5302 separability | **solved, free** (FINRA) |
| 3 | **Float, shares outstanding, ownership** | Same; dilution structure is only visible through filings today | partial via SEC |
| 4 | **Clinical trial and FDA catalyst detail** | The LLM pilot showed the gap is effect sizes, endpoints and dates, not filing categories. `RESULT_LLM_PILOT.md` | **solved, free** (CTG + openFDA) |
| 5 | **Point-in-time listing universe** | Prerequisite for fixing #1 — you cannot rebuild a universe you cannot enumerate historically | **solved, free** (Tiingo bulk file) |
| 6 | **Macro regime** | Lower priority; the vol-decile edge inverted between train and test regimes | **solved, free** (FRED, Treasury) |

## What works, with no credential

All six were probed from this container and are re-checkable at any time with
`python3 scripts/api_check.py`, which fails loudly rather than reporting from
memory. Adapters live in `src/iai/sources/`.

| Source | Endpoint | Gives | Module |
|---|---|---|---|
| **Tiingo bulk tickers** | `apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip` | 108,327 rows of `ticker, exchange, assetType, priceCurrency, startDate, endDate`, refreshed daily. `endDate` is a **last-bar date**, so it dates deaths. | `universe.py` |
| **FINRA short interest** | `POST api.finra.org/data/group/otcMarket/name/consolidatedShortInterest` | Semi-monthly short position, average daily volume and **`daysToCoverQuantity`**, from 2017-12-29. Survives the company: ZGNX returns 101 settlements ending 2022-02-28. | `shortinterest.py` |
| **ClinicalTrials.gov v2** | `clinicaltrials.gov/api/v2/studies` | 598,690 studies — sponsor, phase, enrolment, status, **primary completion date**. Versioned records via `/{nct}/history`. | `catalysts.py` |
| **openFDA** | `api.fda.gov/drug/drugsfda.json` | Application numbers, NDA/BLA/ANDA submission types and dated approval events. | `catalysts.py` |
| **FRED** | `fred.stlouisfed.org/graph/fredgraph.csv?id=…` | Any FRED series as CSV **without an API key** — the documented REST path requires one, this does not. | — |
| **US Treasury** | `api.fiscaldata.treasury.gov/services/api/fiscal_service/…` | Rates and fiscal series, paginated JSON. | — |

### The one that changed a published number

The Tiingo file settles the denominator that `RESULT_SURVIVORSHIP.md` previously
had to borrow. Counting symbols live on each month-end gives **5,541 US-listed
common stocks in Jan 2015 rising to 7,615 in Dec 2025, mean 6,644** — well above
the 4,000–5,500 that was assumed, which means every earlier hazard estimate in
this repo was *too high*. The involuntary delisting rate falls from 1.44–1.98%
a year to **1.19%**.

It also puts a number on the hole:

```
panel tickers                       3,662
US-listed stocks at the midpoint    6,058
panel as a share of that             60.4%
deaths in window (>=1yr history)    5,818
of those, absent from the panel     5,692
```

**The panel is 60% of the universe and is missing 5,692 dead names.**

### Traps found the hard way

* **Recycled symbols.** 1,270 US tickers have more than one row in the Tiingo
  file because the symbol was reissued. Join on `(ticker, date-in-window)`,
  never on ticker alone — that is precisely how Yahoo served post-2024 bars
  under `SBNY` for a bank that failed in 2023.
* **A stale `endDate` is not always a death.** A delisted name that keeps
  quoting on the pink sheets shows a current `endDate`. Use the exchange field
  and treat NASDAQ/NYSE → PINK as the event.
* **FINRA answers CSV to a JSON request.** `Content-Type: text/plain`; parsing
  it as JSON raises `Extra data: line 1 column 28`, which is a header row.
  Sorting also 400s unless every partition key is in an EQUAL filter.
* **Both registries serve today's record, not the historical one.** A trial
  edited after it failed will read as failed against a 2019 row. Anything
  historical must go through `catalysts.study_history`.

## What is still not free

Every price vendor tested refuses unauthenticated access, and the published
demo keys are whitelisted to a handful of mega-caps:

| Vendor | Unauthenticated | Free tier, and why it does not solve #1 |
|---|---|---|
| Tiingo | `403 {"detail":"Please supply a token"}` | 500 unique symbols/month — a ~17,000-name panel takes years to backfill |
| Polygon (now Massive) | `401 API Key was not provided` | Free tier is **2 years** of history; only the $199/mo Advanced tier reaches 2015 |
| Alpaca | `401` | — |
| Finnhub | `401` | — |
| Alpha Vantage, Twelve Data, Marketstack, FMP, EODHD, StockData | key required | demo keys serve a fixed handful of large caps |

**Blocker #1 is a purchase, not a search.** Polygon's `/v3/reference/tickers`
documents `active=false`, `delisted_utc` and a point-in-time `date` parameter and
reaches full history on the $29/mo tier, so the *universe* is cheap there; the
delisted *bars* need the $199/mo tier. That is the decision to make, and it is
now a priced one rather than an open question.

## Already in use

| Source | Auth | Used for |
|---|---|---|
| SEC EDGAR (`www.sec.gov`, `data.sec.gov`) | none, UA required | filings, 8-K items, Form 25 delisting census, XBRL fundamentals |
| EDGAR full-index (`full-index/{year}/QTR{q}/form.idx`) | none | the delisting census — the only survivorship-free record in the stack |
| Yahoo chart (`query2.finance.yahoo.com/v8/finance/chart`) | none | the daily price panel — **survivorship-biased, see #1** |

Rate discipline: SEC asks for ≤10 req/s and a real User-Agent with a contact
address. `iai.core.http.HttpClient` enforces the throttle, caches to disk, and
deliberately refuses to cache 401/403/407 as misses — the SEC answers abuse with
a 403 on the whole IP, and caching that as "nothing here" would poison every URL
attempted during the block.

## Stocklake (MCP connector, evaluated 2026-08)

Tried as a replacement for the lost price panel. **Rejected: the daily bars are
not usable for this work**, on three independent grounds.

**1. The volume series degrades to a thin single-venue feed, at a different date
for every symbol, and interleaves with the real tape.**

```
RCAT   2026-01-22   16,030,391   real consolidated tape
       2026-01-23          218   collapses
       2026-02-19   12,739,500   real again for one day
       2026-02-20        2,017   thin again
       2026-03-18   31,541,988   real       close 17.000
       2026-03-19        1,109   thin       close 14.255
       2026-03-20        3,611   thin       close 13.250
       2026-03-23   19,322,453   real       close 15.150

AAPL breaks 2026-05-19 (42,000,000 -> 31,253)
MSFT breaks 2026-07-21 (27,915,800 -> 335,169)
```

Bars from 2026-08-12 carry an explicit `"source":"ibkr"` tag, so the feed is a
single broker's prints rather than the consolidated tape.

This is fatal here rather than merely inconvenient. The eligibility screen is
`ADV >= $1M/day` computed as close x volume, so understating volume by 50-1000x
empties the universe and biases it toward whichever symbols degraded latest. The
whole `surge_features` block, `ctx_logadv`, `ctx_turn`, `ctx_volratio` and
`pre_volratio` are volume-derived, and a 1000x single-day drop registers as the
most extreme surge in the panel's history -- an artifact the model would happily
learn.

**2. The closes on thin days are not reliable either.** RCAT prints 17.00 on
31.5M shares, then 14.255 on 1,109 shares, then 15.15 on 19.3M. A -16% and +6%
round trip on odd-lot prints. Forward returns, ATR and realised volatility are
all computed from these closes, so the labels are corrupted, not just the
features.

**3. Structural limits, independent of the above.** `get_stock_history` caps at
**365 trading days**, against a training set that needs 2018 onward; it serves
**one symbol per call** against a ~3,500-name universe; and coverage is current
listings only, which reintroduces exactly the survivorship bias
`RESULT_SURVIVORSHIP.md` measured and corrected.

There is no clean sub-window to retreat to: RCAT is already degraded in January
2026, and the 365-day cap prevents going back to an era before the transition.

| verdict | Unusable for backtesting. Possibly fine for a current quote or a fundamentals lookup, which is what the other endpoints do. |
|---|---|
