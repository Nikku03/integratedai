# Data sources: what each one is worth, and what it costs

You asked for catalysts, legal documents, partners, ticker tracking, private-jet
movement, and shipping import/export data. All six are implemented. They are
**not** of equal value, and the gap is large enough that it should drive where
you spend money and attention.

This document is deliberately blunt about the weak ones.

---

## Summary table

| Source | Cost | Coverage | Latency | Honest verdict |
|---|---|---|---|---|
| SEC EDGAR filings | free | ~100% of US issuers | ~15 min | **The backbone.** Best signal-per-dollar in public markets. |
| EDGAR full-text search | free | 2001-present | ~15 min | **Strong.** Finds catalysts with no dedicated form type. |
| Partner spillover (derived) | free | good where deals are disclosed | same as filing | **Underrated.** Genuinely differentiated, costs nothing but code. |
| Litigation (CourtListener/RECAP) | free tier / ~$100s | federal only, patchy | hours to days | **Useful, one-sided.** A hit is informative; a miss means nothing. |
| Price/volume | free (Yahoo) or paid | universal | EOD | Not alpha. Required as controls. |
| Shipping — bills of lading | **$1k-10k+/yr** | ocean imports only | ~4 days | **The only trade tier with single-stock alpha.** |
| Private jet ADS-B | free-ish / $$ | biased, see below | ~2 h | **Weakest.** Real but small, badly biased, high effort. |
| Shipping — UN Comtrade | free | country × commodity | **~75 days** | Macro tilt only. Not a stock signal. |
| AIS vessel tracking | $$$ | global | ~6 h | Middle tier. Operationally annoying. |

---

## 1. SEC EDGAR — the backbone

Two endpoints do almost everything.

**`data.sec.gov/submissions/CIK##########.json`** returns an issuer's entire
filing history in one request, including `acceptanceDateTime` to the second and,
for 8-Ks, the **item codes**. Item codes are the single highest
signal-to-effort field in public market data. One string tells you whether a
filing is a routine investor deck (Item 7.01) or an auditor resignation
(Item 4.01).

The item weights in `sources/edgar.py` encode which disclosures actually move
small and mid caps:

| Item | Meaning | Why it matters |
|---|---|---|
| 4.02 | Non-reliance on prior financials | Restatement. Among the most reliable negative catalysts. |
| 1.03 | Bankruptcy | Terminal. |
| 5.01 | Change in control | The deal already happened. |
| 3.01 | Delisting notice | Distress, and forced selling from index funds. |
| 1.01 | Material definitive agreement | Partnerships, licensing, supply deals. **This is your "partner" signal.** |
| 3.02 | Unregistered equity sale | Dilution, usually a PIPE, usually bad. |
| 2.02 | Earnings | High impact, most crowded trade in the market. |
| 7.01 | Reg FD disclosure | Mostly noise. Weighted low for good reason. |

Non-8-K forms carry their own weights: `SC TO-T` (third-party tender offer),
`SC 13D` (activist stake), `424B5` (shelf takedown — actual dilution today),
`NT 10-K` (late filing — a reliable distress tell).

**`efts.sec.gov/LATEST/search-index`** is full-text search across filing bodies
and exhibits back to 2001. This catches catalysts with no form type of their
own: `"clinical hold"`, `"complete response letter"`, `"formal order of
investigation"`, `"substantial doubt about our ability to continue"`. Phrases
are quoted so EDGAR treats them as exact — unquoted `clinical hold` matches any
filing containing both words anywhere, and precision matters far more than
recall here.

**Timing.** `event_ts` is EDGAR acceptance. `available_ts` adds 15 minutes,
and filings accepted after 17:30 ET defer to the next business morning, because
acceptance and public dissemination are not the same instant. Getting this
wrong is worth a fake percentage point of monthly return.

**Set a real `IAI_USER_AGENT`.** The SEC asks for a contact address and
throttles anonymous scrapers. This is not optional and it is not rate-limiting
theatre — they will block you.

---

## 2. Partner spillover — the best free idea here

Not a purchased dataset. Derived, and genuinely differentiated.

When issuer A files an 8-K Item 1.01 announcing a collaboration with issuer B,
the market reprices A immediately — it is A's filing, A's press release, A's
ticker in the headline. **B is repriced late and incompletely**, especially
when B is larger, less followed, or never files anything because the deal is
immaterial to B's revenue but material to B's option value.

So the tradable object is the spillover: A's disclosed catalyst becomes an
event on B's ticker, timestamped to when A disclosed it — not a second sooner.

The graph is built by extracting entity names from the filing body and
resolving them against the universe. Edges decay, so a decade-old one-off fades
while an active supply relationship stays warm. Critically,
`PartnerGraph.as_of()` rebuilds the graph from edges observed **strictly
before** each date. Building one graph from the full history and applying it
across the whole backtest is the most seductive lookahead bug in this entire
system, because it "obviously" works.

---

## 3. Litigation — useful, and one-sided

CourtListener's RECAP archive covers federal dockets. Securities class actions,
patent suits, antitrust and government enforcement are slow, publicly docketed,
and systematically under-priced in the first days for small and mid caps.

**The catch is coverage.** RECAP ingests when *someone* buys a document off
PACER and contributes it. State courts — where much commercial litigation
actually lives — are largely absent. So:

> **A docket hit is informative. A docket miss is not evidence of no litigation.**

Treat these features as one-sided and never build a "clean legal record" signal
out of their absence.

The `RECAP_LAG` default of one day is deliberately pessimistic. If you upgrade
to a direct PACER feed, drop it to an hour and re-run — **the difference
between those two backtests is a clean estimate of how much of your edge is
pure speed**, which is worth knowing before you pay for speed.

Nature-of-suit codes and cause-of-action strings drive severity: 850
(securities), 410 (antitrust), 830 (patent), `15:78` (Exchange Act). Plaintiff-
side suits are down-weighted by half, because suing someone is not the same
kind of news as being sued.

---

## 4. Private jet tracking — the honest assessment

You listed this and it is implemented properly, so here is the straight answer:
**it is the weakest source in this system**, and I would build everything else
before spending real time on it.

**It is legal.** ADS-B is an unencrypted position broadcast every aircraft is
required to transmit, and the FAA registry is a public record. This is material
*public* information that happens to be inconvenient to collect. That is the
whole thesis. It also means the moment you pair it with an actual tip from
someone inside a deal, you are trading on MNPI and the provenance of your other
features will not save you.

**The patterns that are actually tradable**, none of which is "the CEO flew to
Basel therefore buy":

- **Convergence** — aircraft of two or more *different* issuers on the ground at
  the same airport inside a short window. Principals meet in person for things
  that get announced. This is the one with real content, and in the synthetic
  validation it is the strongest of the alt-data signals.
- **Novel destination** — a tail visiting an airport it has not visited in a
  year.
- **Activity burst** — fleet flight count z-scored against the issuer's own
  baseline, which controls for companies that simply fly constantly.
- **Off-hours** — weekend and late-night legs. Deals get signed on Sundays.

**Three problems you cannot engineer around:**

1. **Selection bias.** Companies can suppress tail numbers via the FAA's LADD
   and PIA programmes, and the sophisticated ones do. Coverage is biased toward
   issuers that are *not* hiding, which correlates with not being in play. This
   is a real bias on the feature, not a data-quality nuisance.
2. **Attribution is manual.** Aircraft are held in single-purpose Delaware LLCs
   whose names share nothing with the operating company. Expect to curate the
   high-value tails by hand and accept partial coverage on the rest.
3. **Ownership is point-in-time.** An airframe sold in 2023 was not the issuer's
   aircraft in 2021. `TailRegistry` stores validity intervals and
   `owner_at(icao24, ts)` enforces this. Using a current registry snapshot
   across a five-year backtest is a lookahead bug that will flatter you.

**Historical OpenSky flights now require an authenticated account.** Anonymous
callers get `You cannot access historical flights`. Without credentials the
source disables itself and says so in `iai doctor`, rather than silently
returning nothing.

---

## 5. Shipping and trade — three tiers, wildly different value

### Tier 1: Bills of lading — **the only tier with single-stock alpha**

US Customs vessel manifests name the consignee, shipper, commodity and
container count for every ocean import. When a consignee resolves to a listed
issuer, you get that issuer's physical import volume weeks before it appears in
a 10-Q.

There is no free API. CBP releases in bulk; ImportGenius, Panjiva/S&P, Descartes
Datamyne and Tradlinx resell it. `BillOfLading` reads a CSV extract, which is
what all of them will sell you.

Two things to know:

- **Air freight is not in manifest data.** Semiconductors and pharmaceuticals
  move by air, so their import signal is systematically understated. This biases
  coverage against exactly the sectors where catalysts are richest.
- **Consignee strings are filthy** — `SAMSUNG ELECTRONICS AMERICA INC C/O
  EXPEDITORS`. Resolution goes through fuzzy name matching and misses are
  *logged*, not silently dropped, because an unmatched consignee is an event
  that quietly never reaches the model.

The emitted event is not "a shipment arrived" but "this issuer's trailing import
volume deviated from its own baseline". A single container is noise; the level
is what matters.

### Tier 2: AIS vessel tracking

Free-ish via AISHub (you must contribute a receiver feed) or NOAA Marine
Cadastre (free, US waters, ~1 year lag — useless live, fine for backtest
construction). Paid: Kpler, Windward, Spire, MarineTraffic.

The useful signal is the **draught delta**: a vessel riding higher on departure
discharged cargo, and how much higher tells you roughly how much. Attribution
needs a berth-to-issuer map you build once by hand.

### Tier 3: UN Comtrade — free, and weak

Monthly bilateral trade by country and commodity. Works with no API key.

**This is a macro tilt, not a stock signal.** It tells you Chinese lithium
carbonate exports to Korea fell 30% month-over-month. That is a sector view and
a cost-input signal, not a reason to buy one ticker.

**The publication lag is ~75 days and it is modelled explicitly.** Using the
reference month as the availability date is the single most common lookahead
bug in trade-data backtests, and it is a big one: you would be trading on
information that did not exist for two and a half months.

Attribution runs through `TradeExposure`, a hand-built map of issuer → HS codes
→ partner countries → signed sensitivity. Build it from 10-K risk factors and
segment disclosures. It is a few hours for a hundred names, and it is the
difference between trade data being a signal and being noise.

---

## 6. Prices

`YahooPrices` is free, needs no key, and is fine for research.

One real caveat: Yahoo applies split and dividend adjustment retroactively to
the whole history, so a naive backtest reading `adjclose` uses *today's*
adjustment factors on a 2019 bar. This adapter keeps raw OHLC and the
adjustment factor **separately** — the backtest trades raw prices, the feature
layer uses adjusted returns.

For anything you would risk money on, buy survivorship-bias-free history with
delisted names included (Polygon, Databento, Norgate) and use `CsvPrices`. A
catalyst strategy is disproportionately exposed to names that later delist, so
a survivorship-biased backtest is biased in precisely the direction that
matters most.

---

## Getting started, in order of value per hour spent

1. **EDGAR filings + full-text search.** Free, immediate, the backbone. Run
   `iai fetch` today.
2. **Partner spillover.** Free, derived from what you already fetched.
3. **Litigation.** Free tier works; get a CourtListener token if you sweep daily.
4. **Bills of lading.** The first thing worth paying for, if your universe is
   import-heavy.
5. **AIS**, if commodities or shipping are core to your names.
6. **Jet tracking**, last. It is the most fun and the least profitable.

Run `iai doctor` to see which sources are actually live in your environment and
what each one is missing.
