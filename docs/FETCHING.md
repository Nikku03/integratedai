# Fetching a wide universe over a long window

The target: **~2,000 small/mid-cap names, 2015–2026.** Roughly five times the
names and three times the history of the run reported in
[`RESULT_WIDE.md`](RESULT_WIDE.md).

Estimated naively from the old fetcher that is **about thirty hours** on one
machine, and the obvious response — rent more machines — is the wrong one. The
SEC enforces its rate limit per IP, so six Colab notebooks give six times the
throughput and still leave five hours; and one of the steps does not shard at
all. It is worth going through where the time actually goes, because four of
the five fixes were not "add parallelism."

## Where the thirty hours were

| step | old cost | share |
|---|---|---|
| Form 4 documents | ~895,000 requests | **99%** |
| EDGAR submissions | ~3,000 requests | <1% |
| prices | ~5,500 requests | <1% |
| XBRL frames | 44 requests | ~0 |

One step was the whole job. Parallelising anything else was rearranging
rounding error.

## Fix 1 — bulk archives instead of per-document XML (~500×)

The Form 4 loop fetched one XML document per filing. The SEC already publishes
the same data pre-parsed, as one zip per quarter, covering every issuer:

```
https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/YYYYqQ_form345.zip
```

Eleven years is **45 downloads**. Measured on this machine: **481 MB in 62
seconds**, versus roughly 28 hours of per-document fetching for the same
coverage.

Validated against the old path on the same 341 tickers and window — 19,923
events versus 20,001, 99% agreement on insider-buy ticker-months, identical
median filing lag of 2.3 days.

The one thing lost is the acceptance *time*: `SUBMISSION.tsv` carries a filing
date with no clock. Availability is therefore assumed to be the **close of the
filing date**, which is pessimistic — about two thirds of Form 4s really are
filed after hours. `enrich_acceptance_times()` backfills exact stamps for a
chosen subset when a study needs them. Never reverse the assumption to win back
the half session.

*Code: [`src/iai/sources/insiders_bulk.py`](../src/iai/sources/insiders_bulk.py)*

## Fix 2 — stop retrying answers (hours, on a wide pool)

This one only appears at scale, and it was worth more than every parallelism
change combined.

Yahoo returns **HTTP 400** for a symbol it does not have. Over 2015–2026 a
5,490-name candidate pool contains thousands of delisted tickers, and the HTTP
client was treating 400 as a transient failure: four attempts with exponential
backoff, ~15 seconds each, before giving up and returning the same `None` it
could have returned immediately.

A 4xx is an *answer* — the symbol does not exist, the CIK never filed. Only
429 and 5xx are worth retrying. Definitive misses are now also cached, with a
deliberately shorter TTL (24h) than a hit (30d): a ticker that 400s today may
list next month, and a permanent negative cache would quietly shrink the
universe over time.

*Code: [`src/iai/core/http.py`](../src/iai/core/http.py)*

## Fix 3 — cache the archives, so a dead run resumes

The bulk zips originally went through `session.get` directly, which meant they
skipped both the disk cache and the rate limiter. On a 45-archive run that is
the difference between resuming in seconds and starting over. `get_bytes()`
caches binary payloads with a write-then-rename, so a killed process cannot
leave a half-archive that later looks like a cache hit.

## Fix 4 — overlap the network with the cores

Only now is parallelism the bottleneck, and it matters *which* kind:

- **Downloads want threads.** They are latency-bound, and the shared rate
  limiter still holds the aggregate under the published ceiling — concurrency
  hides round trips, it does not raise throughput. `EdgarFilings` and
  `YahooPrices` were serial loops; both now issue concurrently.
- **Parsing wants processes.** Unzipping a quarter and reading three TSVs of
  ~110,000 rows is CPU-bound and the GIL makes threads useless for it.
  `load_quarters()` downloads in threads and parses in a process pool, so
  quarter *n* parses while *n+1* is still on the wire.

That is why `parse_archive()` takes bytes rather than a client: a function that
holds an HTTP session cannot be handed to a process pool.

## Fix 5 — stages, so the un-shardable step is not sharded

After the above, the steps have genuinely different shapes, and the old
"fetch everything for these tickers" interface hid that. Sharding the bulk
insider step by ticker would make *every* shard download and parse all 45
archives to keep its own slice: n times the bytes for none of the speed.

| stage | scales with | shardable | ~wall clock, one machine |
|---|---|---|---|
| `candidates` | quarters (44) | no | **15 s** (measured) |
| `prices` | candidates (5,490) | **yes** | **~46 min** (measured, 2 req/s) |
| `screen` | local | no | ~1 min |
| `events` | universe (~2,000) | **yes** | ~8 min |
| `insiders` | quarters (45) | **no** | **62 s** (measured) |
| `merge` | local | no | ~1 min |

**One machine, end to end: about an hour.** Down from thirty. Four machines is
about twenty minutes, and the entire gain comes from the two per-ticker
stages — running `insiders` on four machines would take exactly as long as
running it on one and download four times as much.

Note where the time now sits: **prices are 80% of the remaining budget**, and
they are slow by choice, not by limit. 2 req/s is a self-imposed ceiling
against a host that answers abuse with blocks. That is the honest reason to
shard, and the only step where more machines still buys anything substantial.

*Code: [`scripts/colab_fetch.py`](../scripts/colab_fetch.py)*

## The part that is not about speed

The fastest way to cut the price fetch would be to shrink the candidate pool
first — rank names by filing activity or by anything else, keep the top 2,000,
and save two thirds of the requests.

**Every such ranking is computed over the whole window**, which means it picks
the 2015 universe using facts from 2026. It is the same mistake as screening on
today's market cap, wearing different clothes, and it is exactly the kind of
thing that produces a backtest edge that evaporates live.

So the only filter applied before prices is "did this registrant file a
cover-page share count at all" — which removes funds, trusts and shells, and
nothing else. 5,490 candidates. The cut to ~2,000 happens in the `screen`
stage, using a **trailing** cap-and-liquidity screen: in-band market cap from
the last *filed* quarter, and the top names by trailing 21-day dollar volume as
of that quarter end. Both are knowable on the day membership is set.

Membership is therefore rolling — a name that becomes liquid enters, a name
that dries up leaves, and delisted names stay in the quarters where they
qualified. The extra ~3,500 price series are what that discipline costs, and
after the fixes above they cost ten minutes rather than a day.

*Code: [`src/iai/universe_builder.py`](../src/iai/universe_builder.py)*

## What this does and does not buy

It buys **weeks**, which is the thing [`RESULT_WIDE.md`](RESULT_WIDE.md)
identified as the binding constraint. 2021–2024 gave 103 usable weeks after the
walk-forward warm-up; 2015–2026 gives roughly 470.

It does not buy more trades per week — selection is five a week regardless of
how many names are available, which is the arithmetic error the last
pre-registration made. And it does not fix the survivorship bias in free price
data: Yahoo's history for delisted names is patchy, so some of those 400s are
companies that failed, and they are missing from the sample rather than
present-and-losing. That is a real limitation of this dataset, not something the
fetcher can solve. `CsvPrices` is the hook for a delisting-inclusive vendor
extract.
