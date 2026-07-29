# Data sources: what each one is worth, and what it costs

You asked for catalysts, legal documents, partners, ticker tracking, private-jet
movement, and shipping import/export data. All six are implemented. They are
**not** of equal value, and the gap is large enough that it should drive where
you spend money and attention.

This document is deliberately blunt about the weak ones.

---

## Summary table

Sorted by **latency**, which for a days-to-weeks trade is the property that
matters most. A source that is 45 days stale cannot time a two-week bet no
matter how good its content is.

| Source | Cost | Coverage | Latency | Honest verdict |
|---|---|---|---|---|
| **Volume / flow anomalies** | free | universal | **0 days** | **Best free short-horizon source.** Cannot be suppressed. |
| SEC EDGAR filings | free | ~100% of US issuers | ~15 min | **The backbone.** Best signal-per-dollar in public markets. |
| EDGAR full-text search | free | 2001-present | ~15 min | Strong, but slow to sweep. Off in the fast profile. |
| Press-release intensity (derived) | free | ~100% | ~15 min | The only free *backtestable* news proxy. |
| **Form 4 insider trades** | free | ~100% | **~2 days** | **The real institutional signal.** Cluster buys especially. |
| Partner spillover (derived) | free | where deals are disclosed | same as filing | Underrated. Costs only code. |
| SC 13D (activist stake) | free | event-driven | ~10 days | Carries *intent*. Worth its weight. |
| Litigation (CourtListener/RECAP) | free tier | federal only, patchy | hours to days | Useful, one-sided. A hit informs; a miss proves nothing. |
| Shipping — bills of lading | **$1k-10k+/yr** | ocean imports only | ~4 days | The only trade tier with single-stock alpha. |
| Private jet ADS-B | free-ish / $$ | biased, see below | ~2 h | **Weakest.** Real but small, badly biased, high effort. |
| **13F institutional holdings** | free | quarterly | **45-135 days** | **Not a timing signal.** Off by default. See below. |
| Shipping — UN Comtrade | free | country × commodity | **~75 days** | Macro tilt only. Not a stock signal. |
| AIS vessel tracking | $$$ | global | ~6 h | Middle tier. Operationally annoying. |
| Historical news (vendor) | $300+/mo | good | seconds-hours | Buy it if the strategy justifies it. No free option works. |

---

## Volume and flow anomalies — the best free short-horizon source

`sources/flow.py`. Everything else tells you *what happened*; volume tells you
*who is acting on it*, today rather than in two days or forty-five.

An institution accumulating a small-cap position **cannot hide the print**.
There is no filing delay, no coverage bias, no suppression programme, and no
subscription. For a days-to-weeks small-cap strategy this is the source I would
build first and cut last.

Detected patterns:

- **`flow.volume_surge`** — dollar volume z-scored against the name's *own*
  trailing baseline, in logs. Not a fixed multiple: a stock that normally
  trades $500k doing $3m is a far bigger event than a $200m name doing $600m.
- **`flow.accumulation` / `flow.distribution`** — the institutional-footprint
  shape. Several sessions of above-baseline volume with closes clustering near
  the top (or bottom) of each day's range and net drift. That is a fund working
  an order over days rather than a single print.
- **`flow.breakout` / `flow.breakdown`** — a close through a trailing extreme,
  **volume-confirmed**. An unconfirmed breakout is a tick.
- **`flow.churn`** — heavy volume, small net move. Two large parties trading
  with each other; resolution usually comes later.
- **`flow.gap`** — volatility-scaled overnight gap.

One implementation detail that is a real bug in most versions of this idea:
the trailing standard deviation used for z-scoring must be **floored**. A name
that traded near-identical volume for a quarter has a baseline std near zero,
so the day it finally does 20x divides by ~0 and gets dropped as NaN — silently
discarding the single highest-signal observation in the series for being too
extreme. `MIN_LOG_STD` exists for that.

---

## Form 4 insider transactions — the institutional signal that is actually fast

`sources/insiders.py`. Ranked by how quickly ownership information reaches you:

| Filing | Deadline | Usable for a 2-week trade? |
|---|---|---|
| **Form 4** | **2 business days** | **Yes — this one** |
| SC 13D | 10 days after crossing 5% | Yes, and it carries intent |
| SC 13G | 45 days after year-end | Marginal |
| **13F-HR** | **45 days after quarter end** | **No** |

**Most Form 4s are noise, and that is why naive insider signals fail.** The
transaction code is everything:

- **`P` (open-market purchase)** — the signal. An officer spending their own
  money at the market price is the only transaction here with unambiguous
  information content.
- `S` (sale) — weak and asymmetric. Insiders sell for diversification, tax
  bills, and house purchases. A purchase is strong evidence; a sale is mild.
- `A` (grant), `M` (option exercise), `F` (tax withholding) — **dropped
  entirely**, not down-weighted. They are mechanical and they add variance to
  the cluster counts.

Two refinements, both well supported in the literature (Lakonishok–Lee,
Jeng–Metrick–Zeckhauser, Cohen–Malloy–Pomorski) and both implemented:

1. **Cluster buying dominates single buys.** Three *different* insiders buying
   inside a fortnight beats one insider buying three times. `insider.cluster_buy`
   fires on distinct-buyer counts, and its availability is the filing date of
   the **last** purchase in the cluster — dating it to the first would be a
   lookahead bug worth several points of fake return.
2. **Role matters.** A CEO or CFO purchase carries more than a director's; a
   10% owner's is often mechanical rebalancing.

Verified against live SEC data during development: Cleveland-Cliffs (CLF) shows
a genuine CEO + CFO + President + Director cluster buy across late April–early
May 2023, with a 2.3-day median filing lag.

---

## 13F — why it is off by default

A 13F filed 45 days after quarter end describes positions that are between 45
and 135 days old. The fund has had a full quarter to finish accumulating or to
leave entirely.

For a two-week holding period **that is not a timing signal**, and
`ThirteenF.health()` says so rather than quietly contributing a feature that
will look fine in a backtest fitted on it. Pass `allow_stale=True` if you want
it as slow *context* — "is this name already crowded?" is a legitimate
conditioning variable — but never as a trigger.

It also needs a CUSIP→ticker map, which is a genuine obstacle: CUSIP Global
Services licenses those identifiers and they are not freely redistributable.

---

## News — the honest state of free historical data

`sources/news.py`. The gap between "news data exists" and "news data you can
backtest on" is wide and expensive.

- **`FilingNews` (default)** — press-release intensity from 8-K Items 7.01,
  8.01 and 2.02. This is *company news*, timestamped to the second, complete
  for every US issuer back to 2001, and free. It is the only free historical
  news source that is genuinely backtestable, which is why it is the default.
- **`YahooNews`** — free and keyless, but returns ~10 recent items with no
  date-range parameter. **Live only.** Fine as a last-mile check before sending
  an order; useless for history.
- **`GdeltNews`** — genuinely date-rangeable and free, 2015-present. Rate
  limited to one request per five seconds, and **it blocks shared cloud egress
  IPs outright** — it is blocked from the environment this was developed in.
  From a residential or dedicated IP it works and it is the best free option.
- **`CsvNews`** — point it at a vendor archive. Benzinga (~$300/mo, good
  historical API), Marketaux, Alpha Vantage (cheap, thin), RavenPack
  (institutional).

**The signal is attention, not sentiment.** An abnormal article *count* against
the name's own baseline is far more robust than a sentiment score. "Beats
estimates, stock falls" is a headline every off-the-shelf classifier gets
backwards, and the market's actual reaction is measured better by volume.

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
