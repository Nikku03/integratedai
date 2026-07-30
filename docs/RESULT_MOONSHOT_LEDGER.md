# Ledger: every moonshot last month and what caused it

**1–29 July 2026.** Universe screened: 5,424 names with daily bars, of which
**3,525 are tradable** (close ≥ $1, median daily dollar volume ≥ $250k).

A "moonshot" is the largest 1-day or forward 5-day close-to-close move each name
made in the window.

## How many

| threshold | movers | share of tradable universe |
|---|---|---|
| **≥10%** | **856** | 24% |
| **≥20%** | **222** | 6% |
| **≥50%** | **34** | 1% |
| biggest | **+602%** (STAK) | |

## What caused them

Each mover is attributed to one cause — whatever it had in the seven days up to
and including the move, with the most economically decisive winning. EDGAR
submissions were fetched directly for all 856 movers rather than relying on the
partial scan, so coverage is 839/856, 218/222 and 33/34.

|  | ≥10% | ≥20% | ≥50% |
|---|---|---|---|
| **TOTAL MOONSHOTS** | **856** | **222** | **34** |
| with EDGAR coverage | 839 | 218 | 33 |
| **SEC filing of any kind** | **477 (57%)** | **139 (64%)** | **22 (67%)** |
| — 8-K | 196 (23%) | **65 (30%)** | 9 (27%) |
| — insider (Form 4 / 144) | 136 (16%) | 22 (10%) | 1 (3%) |
| — offering / dilution | 30 (4%) | 17 (8%) | 2 (6%) |
| — periodic report (10-Q/K) | 55 (7%) | 17 (8%) | 4 (12%) |
| — 13G passive stake | 31 (4%) | 6 (3%) | 2 (6%) |
| — 13D activist stake | 12 (1%) | 5 (2%) | 1 (3%) |
| — merger / tender | 11 (1%) | 4 (2%) | 2 (6%) |
| **GOVERNMENT source** | **9 (1%)** | **4 (2%)** | **1 (3%)** |
| — clinical trial | 8 (1%) | 4 (2%) | 1 (3%) |
| — **FDA approval** | 1 (0%) | **0** | **0** |
| — **DoD contract** | **0** | **0** | **0** |
| **NO KNOWN CAUSE** | **353 (42%)** | **75 (34%)** | **10 (30%)** |

## The three numbers that matter

**SEC filings explain about two-thirds of large moves, and the share rises with
size** — 57% at ≥10%, 64% at ≥20%, 67% at ≥50%. The 8-K alone is the largest
single cause at every threshold, at roughly 30% of ≥20% moves.

**FDA and DoD explain essentially none.** Zero FDA-caused moves at ≥20% or ≥50%,
one at ≥10%. Zero DoD-caused moves at any threshold. Clinical trials manage 4 of
222 at ≥20%. These three sources — the ones this project spent the most effort
building scrapers for — account for **2% of the tail.**

**A third of large moves have no paperwork behind them at all.** 75 of 218 at
≥20%, and 80 of those 81 filed *nothing* with the SEC in the seven days before
the move. This is not a coverage artifact: submissions were pulled directly from
EDGAR for every one of them. The largest include STAK +602%, JLHL +318%,
FXHO +215%, GMM +147%, INLF +138% — and also Workday +31%, Tenet +34%,
Cleveland-Cliffs +36%, none of which filed anything in the window before moving.

Whatever drives that third is sector sympathy, analyst actions, index events,
short squeezes, peer-company news and retail flow. None of it is in EDGAR, and
nothing built in this repository reaches it.

## Reading this against the strategies

The 8-K is the right instrument if you want *one* instrument: it is the single
largest attributable cause of large moves. That is a genuine finding and it
justifies the choice of trigger.

It is also, on the full unconditional population of 1,861 8-K filings, a
**losing** trade — −0.39% same-day to −2.55% at ten days, t=−8.99. Being the
most common cause of a large move and being a profitable signal are different
properties, and the 8-K has the first without the second.

Two ways to read the 34% with no cause:

**Pessimistic.** A third of the opportunity is unreachable by any filing-based
system, so a filing-based system is capped at two-thirds of the tail before it
tries.

**Optimistic.** Those moves happen without paperwork, which means the paperwork
is not what the market is trading on. If the price moves first and the 8-K
follows — as it did for Tenet, CBZ and Blackbaud, all of which filed *after* they
moved — then watching filings is watching the echo.

## Caveats

**Attribution is proximity, not causation.** A company that files a Form 4 in the
same week as a 30% move gets attributed to "insider", but the insider may be
selling *into* the move rather than causing it. The insider and 13G buckets are
the most suspect on this count; the merger and offering buckets least.

**Government name matching is a floor.** Events are matched to tickers by exact
normalised company name, which misses subsidiaries and alternate spellings. The
global match rate was 9% for FDA and trials, 24% for DoD. Real FDA/trial
attribution is somewhat higher than 2% — but not by enough to change the ranking,
since the entire matched gov event population underperforms its own names'
baseline (see `RESULT_GOV_SOURCES.md`).

**One month.** 856 movers is a good sample of moves; it is one draw of a month.
