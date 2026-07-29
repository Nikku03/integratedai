# Does official paperwork lead the press release?

The thesis: government and regulatory databases publish before the company
issues its press release, so scraping the source gives a head start of
milliseconds to sixteen hours depending on the source. Four candidate windows
were proposed — DoD contract awards, USPTO patent grants, SEC 8-K filings, and
ClinicalTrials.gov status changes.

It is a good question and it is testable. Here is what the data says.

## SEC 8-K: the window does not exist for the item types that matter

Measured on **757,042 8-K item-events, 2015–2026**, using EDGAR
`acceptanceDateTime` (to the second):

| item | n | median acceptance (ET) | before 09:30 | 16:00–18:00 | after 18:00 |
|---|---|---|---|---|---|
| 2.02 results of operations | 105,441 | **16:06** | 34.5% | 53.9% | 3.7% |
| 7.01 Reg FD disclosure | 86,789 | **15:53** | 38.2% | 44.8% | 5.0% |
| 8.01 other events | 81,988 | 16:06 | 30.2% | 50.9% | 5.1% |
| 5.02 officer/director change | 61,389 | 16:15 | 19.7% | 64.8% | 3.8% |
| 1.01 material agreement | 49,532 | 16:16 | 23.4% | 61.1% | 5.4% |
| 4.02 non-reliance | 674 | 16:27 | 19.1% | 64.2% | 8.6% |
| 3.01 delisting notice | 4,900 | 16:26 | 15.3% | 73.2% | 3.6% |

Filings pile up in exactly the two windows companies use to issue press
releases: before the open, and immediately after the close. That is not a
coincidence and it is not a race — **for these item types the press release
*is* the filing.** It is attached as Exhibit 99.1. A company does not file at
17:00 and put out a PR at 07:00 the next morning; it does both in one act, and
the 8-K's acceptance timestamp is the PR's timestamp.

The premise had the causality backwards for the dominant item types. There is
no 5-to-30-minute gap to harvest, because there is no gap.

## ClinicalTrials.gov: real source, not backtestable

The v2 API is open, free, needs no key, and the per-study version history
works — 53 versions returned for a single trial. Two things kill the stated
mechanism:

**No clock time.** Every version record carries a *date* and nothing finer:

```json
{"version": 0, "date": "2020-04-29", "status": "NOT_YET_RECRUITING", ...}
```

The claim of an "overnight ~23:00 ET batch, PR at 07:30, eight-hour window"
cannot be measured from the archive at all. It could only be established by
polling forward and timestamping the observations yourself — which means it is
unfalsifiable against history and can never be backtested, only forward-tested.

**Posting lags submission by days.** In the sampled records,
`lastUpdateSubmitDate` 2025-05-27 posted on 2025-05-31: four days. The public
posting is not a real-time event, so "the moment the database updates" is not a
well-defined trading trigger.

## DoD contracts and USPTO: not reachable to check

`defense.gov` returns 403 to this environment's egress, `api.sam.gov` needs a
key, and PatentsView has moved behind one. The mechanism is at least
*structurally* different from the 8-K case — DoD and USPTO publish on their own
schedule, independent of the issuer, so an asymmetry can genuinely exist. Not
tested here, and not claimed either way.

## The objection that survives all four

A latency window is not an edge unless **the price moves at the source
timestamp**. Otherwise the information is public, nobody trades on it until the
open, and the move happens in regular hours where everyone competes.

This project already measured that, in [`CASCADE.md`](CASCADE.md): **only 11%
of the move occurs in the untradable overnight gap.** The remaining 89% happens
intraday, after the opening auction. So a fourteen-hour head start converts to
roughly a ninth of the move — before paying after-hours small-cap spreads,
which run 100–300 bps against the 15 bps of half-spread the cost model charges
in regular hours.

It also inverts the project's own stated premise. The strategy exists because
we are *not* competing with institutional research teams — we are trading
against retail sentiment on small caps. Latency arbitrage is the one arena
where the counterparty is unambiguously the institutions: colocated feeds,
direct EDGAR and PACER scrapers, and firms whose entire business is the first
200 milliseconds. Choosing that fight gives up the only structural advantage
the strategy had.

## What is worth keeping

The **sources** are good; the **mechanism** is wrong.

A DoD contract award and a clinical-trial status flip are real catalysts that
are not pre-announced by the issuer. The way to use them is not to race anyone
to the timestamp, but as ordinary catalyst features that small-cap retail flow
underreacts to **over days** — which is the ten-session horizon this strategy
already trades. That drops straight into the existing `EventSource` contract
with an honest `available_ts`, no infrastructure change, and no competition
with anyone's colocation.

ClinicalTrials.gov is the one to build first: open, free, biotech-heavy, and
material. It would need its own pre-registration — it is a new hypothesis and
cannot ride on [`PREREGISTRATION_2015.md`](PREREGISTRATION_2015.md).
