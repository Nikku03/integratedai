# Pre-registration: the 2015–2026 test

Committed **before the events, features, labels or model for this window
exist**. At the time of writing, the only wide-window data on disk is a partial
price fetch (candidate pool, no screen applied, no universe chosen). No result
from this window has been computed or looked at.

This is the **third** independent test of the same hypothesis. Two have already
said no. The bar is set accordingly, and so is the decision rule.

## What is being tested

Unchanged from [`PREREGISTRATION.md`](PREREGISTRATION.md): a catalyst-driven
model that ranks names by expected value and takes **5 trades per week**,
targeting **+10%** against a **−7%** stop over a **10-session** horizon, in
small/mid-cap names.

Frozen configuration — `Config.moonshot()`, unchanged:

| | |
|---|---|
| target / stop / horizon | +10% / −7% / 10 sessions |
| trades per week | 5 (max 3 per day) |
| entry | next open after `available_ts` |
| cost | round-trip, ~66 bps modelled |
| CV | purged, embargoed walk-forward, 5 folds, **12d purge** / 3d embargo |
| calibration | isotonic, pooled out-of-fold only |
| ranking | expected value from two models — P(target first), P(stop first) |
| tradability floor | ADV ≥ $500k, price ≥ $1.50 (`cfg.features`) |

Universe: `rolling_universe()` at 2,000 names per quarter, cut by trailing
market cap ($50m–$10bn) and trailing 21-day dollar volume, with a $2.00 price
floor and $500k ADV floor at the *screen* level. Window 2015-01-01 to
2026-01-01.

> **Correction, made before any result existed.** The table first said "10d
> purge". `Config.moonshot()` sets `purge_days = 12`; the 10 was copied from a
> different profile. The *code* is unchanged and was always 12 — this corrects
> a wrong description of the frozen config, not the config itself. Recorded
> here rather than silently edited because a pre-registration that can be
> quietly amended is not one. Nothing from this window had been computed when
> the correction was made; the price fetch was still running.

## Two errors in the last pre-registration, both corrected here

**Error 1: more names is not more trades.** The last one said widening the
universe ~4× would raise trade count to ~2,000 and t to ~3.4. Selection is five
trades a week no matter how many names are available; the count came back at
exactly 515, unchanged. Already documented in
[`RESULT_WIDE.md`](RESULT_WIDE.md).

**Error 2 — not previously caught: the bar was unreachable even if the edge was
real.** Working it out properly:

The 341-name run implies a per-trade standard deviation of **6.80%**
(46.8% win rate, +7.38% average win, −6.25% average loss). At n = 515 the
minimum effect detectable at t > 2.0 is therefore **60 bps per trade**. The
edge being tested for — the +56 bps from the 106-name run — is *smaller than
that*. Had it been completely real, the expected t-statistic was **1.87**:
below the bar I set.

So the last test could not have passed. Failing it was uninformative about the
hypothesis and informative only about the test. This one is sized so that is
not true again.

## Power, stated before the fact

The splitter reserves the first half of the sample for the initial training
window, so usable weeks are **half** the calendar span — a detail the last
estimate also missed (`RESULT_WIDE.md` guessed ~470 weeks for a longer window;
the real figure is half that).

| | 2021–2024 | **2015–2026** |
|---|---|---|
| calendar weeks | 209 | 574 |
| usable test weeks | 104 | **287** |
| trades at 5/week | 515 (observed) | **~1,435** |
| min detectable effect at t=2.0 | 60 bps | **36 bps** |
| expected t if the edge is +56 bps | 1.87 | **3.12** |
| expected t if the edge is +13 bps | 0.43 | **0.72** |

**This is the point of the test.** The two prior samples disagree by a factor
of four, and this window can tell them apart: the first hypothesis predicts
t ≈ 3.1, the second predicts t ≈ 0.7, and the bar sits between them. Neither
prior test could do that.

It is still not a generous test. A 36 bps minimum detectable effect against
66 bps of modelled cost means gross edge must exceed roughly **102 bps per
trade** to register. If the strategy cannot clear that, it cannot be traded
anyway, so the bar being high is a feature.

## Primary criterion

**Net-of-cost mean return per trade, with a week-clustered standard error,
t > 2.0.**

The clustering is new and it is a tightening, not a loosening. Five trades in
the same week are not five independent observations — they share a market
regime, they overlap in holding period, and on bad weeks they lose together.
Treating them as independent overstates t by whatever the within-week
correlation is. Clustering by week removes that, and if the trades really are
independent the two agree.

Reported alongside, not in place of it: the naive per-trade t, so the size of
the dependence is visible rather than assumed.

## Secondary criteria

All three carry over unchanged, plus one new one.

1. **Volatility control.** P(spike) lift > 1.0 inside every volatility bucket,
   and the selected names' median volatility no more than 1.2× the universe
   median. Skill, not a volatility tilt. *(Passed both prior runs.)*
2. **Outlier robustness.** Net per trade stays positive after dropping the 20
   largest winners. *(Failed on 341 names.)*
3. **Temporal spread.** No single calendar year holds more than 35% of trades.
   With eleven years and a per-week selection cap this should be near 9%;
   anything above 35% means the edge lives in one regime. *(Failed on 341
   names, at 50.5%.)*
4. **NEW — the ablation must not flip again.** On 106 names, EV ranking beat
   P(spike) ranking (+56 vs −44 bps). On 341 names the ordering reversed
   (+13 vs +48 bps). A real mechanism does not flip. Whichever way it lands
   here, if it disagrees with *both* prior runs the mechanism is noise
   regardless of what the primary criterion says.

## Decision rule, fixed now

- **Primary passes and ≥3 of 4 secondaries pass** → the result is worth acting
  on, at fractional size, with the caveats reported.
- **Primary passes, ≤2 secondaries pass** → report, do not trade. A significant
  mean that concentrates in one year or in twenty trades is not a strategy.
- **Primary fails** → **stop.** Three independent samples, the third one
  properly powered. There is no fourth test that would be honest, because by
  then the only remaining moves are changing the target, the horizon, or the
  universe — and searching over those is how you manufacture the result you
  wanted. If it fails here, the answer is that this edge is not there.

I expect it to fail. The two prior samples both point that way and the second
was the cleaner of them. Writing that down now is the point: it is what makes a
pass meaningful rather than a thing I talked myself into.

## What a pass would still not establish

Free price data is survivorship biased — Yahoo's history for delisted names is
patchy, and a wide 2015-start universe contains thousands of tickers that no
longer exist. Companies that failed are disproportionately *missing* rather
than present-and-losing, which biases any long strategy upward by an unknown
amount. A pass here would need re-running against a delisting-inclusive vendor
extract (`CsvPrices` is the hook) before it meant anything about live trading.

That caveat is stated now so it cannot be negotiated later.
