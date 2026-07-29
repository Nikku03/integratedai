# Architecture

```
                    ┌──────────────────────────────────────────┐
   sources/         │ EDGAR · EDGAR-FTS · litigation · partners │
                    │ flights · shipping · trade · prices       │
                    └────────────────┬─────────────────────────┘
                                     │  Event(event_ts, available_ts, …)
                                     ▼
                    ┌──────────────────────────────────────────┐
   core/types.py    │ validate_events: available_ts >= event_ts │  ← hard failure
                    └────────────────┬─────────────────────────┘
                                     ▼
                    ┌──────────────────────────────────────────┐
   diagnostics.py   │ EVENT STUDY — does this even move price?  │  ← run before modelling
                    └────────────────┬─────────────────────────┘
                                     ▼
                    ┌──────────────────────────────────────────┐
   features/        │ event intensity · novelty · recency       │
                    │ + market controls (vol, momentum, ADV)    │
                    │ audit_lookahead: shuffle test             │  ← hard failure
                    └────────────────┬─────────────────────────┘
                                     ▼
                    ┌──────────────────────────────────────────┐
   labels.py        │ triple barrier, volatility-scaled         │
                    └────────────────┬─────────────────────────┘
                                     ▼
                    ┌──────────────────────────────────────────┐
   model/           │ purged walk-forward → seed ensemble →     │
                    │ isotonic calibration → payoff table       │
                    └────────────────┬─────────────────────────┘
                                     ▼
                    ┌──────────────────────────────────────────┐
   risk/            │ fractional Kelly → risk cap → dispersion  │
                    │ shrink → name/sector/gross caps → stops   │
                    └────────────────┬─────────────────────────┘
                                     ▼
                    ┌──────────────────────────────────────────┐
   backtest/        │ fill at next open · sqrt impact ·         │
                    │ participation cap · deflated Sharpe       │
                    └──────────────────────────────────────────┘
```

---

## The one idea that matters: `event_ts` vs `available_ts`

Every `Event` carries two timestamps.

- **`event_ts`** — when the thing happened in the world. A complaint was filed,
  a jet touched down, a vessel discharged, a board signed.
- **`available_ts`** — the first moment *you* could have acted on it.

They are never the same, and the gap is where backtests go to die:

| Source | Gap | Why |
|---|---|---|
| EDGAR | 15 min, or next morning after 17:30 ET | acceptance ≠ dissemination |
| Litigation | ~1 day | RECAP ingests when someone buys the doc off PACER |
| Flights | ~2 h | legs appear once complete; ownership lookup is monthly |
| Bills of lading | ~4 days | manifest → CBP → reseller |
| **Comtrade** | **~75 days** | publication lag, then revisions |

`validate_events()` raises `LookaheadError` — not a warning — if any event has
`available_ts < event_ts`. A silent lookahead bug is worth more negative alpha
than any feature in this repository is worth positive.

---

## The timing convention

Stated once, applied in exactly one place each:

```
panel row dated t  →  contains only what was public at the CLOSE of t
trade for row t    →  entered at the OPEN of t+1
```

- Market features on row `t` use bars through `t`. That is close-of-`t`
  information. No shift needed.
- Event features come from `attach_entry_session()`, which maps `available_ts`
  to the session by whose close it was public. Events after 15:45 ET roll to
  the next session. **No lag of its own.**
- The single session between knowing and trading lives in `labels.py` and in
  the backtest engine, both of which fill at the open of `t+1`.

> **Regression note.** An earlier version applied a `shift(1)` in the assembler
> *on top of* the lag already inside the event mapping. Event features landed
> two to three sessions late, which discards the first and largest part of every
> catalyst move. `test_single_lag_not_double` exists to stop that coming back.
> If you add a lag, add it in one place and write down which.

---

## Preventing lookahead, in four layers

1. **Type level.** `validate_events` rejects `available_ts < event_ts`.
2. **Construction level.** Features use expanding (never full-sample) baselines;
   the partner graph is rebuilt as-of each date from edges observed strictly
   before it; tail-number ownership is interval-based.
3. **Statistical level.** `audit_lookahead()` runs a shuffle test: it permutes
   the label *within each date* and compares each feature's real correlation
   against that null. A genuine cross-sectional equity signal lands at
   |rho| < 0.10; anything six sigma outside its own null with |rho| > 0.15 is
   flagged. `test_audit_catches_injected_lookahead` plants an 80%-pure copy of
   the future label and asserts the alarm fires — a test that only checks clean
   data would also pass with the audit stubbed out.
4. **Validation level.** Purged, embargoed walk-forward (below).

---

## Why the event study comes before the model

`diagnostics.event_study()` decomposes abnormal returns around each event kind
into three windows, and the decomposition is worth more than an AUC:

- **`pre_car`** (days −5..−1). If the move is here, the market already knew and
  **your timestamp is late**. Very common with litigation and with anything
  derived from a monthly-refreshed registry.
- **`day0_car`**. Real but **uncapturable** — it happened in the print.
- **`drift_car`** (days +1..+20). **The only part you can trade.**

A model that scores well on an uncapturable effect still loses money. The event
study is what tells them apart, and it costs seconds instead of days.

---

## Purged walk-forward CV

Standard k-fold on financial panel data is broken three separate ways, each
sufficient on its own to produce an untradeable backtest:

1. **It shuffles time.** Training on 2023 to predict 2019 is not a thing you can
   do with money.
2. **Labels overlap the test window.** A sample dated 5 January with a 15-day
   triple-barrier label depends on prices through ~26 January. If the test fold
   starts on 10 January, the model has seen the answer.
3. **Serial correlation bleeds across the boundary.** The sample just after the
   split is nearly the same observation as the one just before it.

Fixes, in order: walk forward only; **purge** training samples whose label
window intrudes into the test window; **embargo** a buffer after it.

`purge_days` must be ≥ `max_holding_days`, and `walk_forward()` warns loudly if
it isn't. Overlapping samples are additionally down-weighted by
`sample_weights()` — daily signals on one name share most of their outcome
window, so treating them as independent inflates the effective sample size by
roughly the holding period and makes every significance test a fantasy.

---

## Why gradient-boosted trees

The feature set is a few hundred mostly-sparse tabular columns with heavy
missingness, threshold effects (`days_since < 3`) and strong interactions.
That is exactly where GBDTs dominate and where a neural net needs ten times the
data to draw level.

LightGBM also handles NaN natively, which matters more than it sounds: *"no
event has ever happened here"* and *"we have no data for this name"* are
genuinely different states, and imputing both to zero destroys the distinction.

**Seed averaging.** Boosted trees on noisy financial data swing 0.01–0.02 AUC
across seeds. Five seeds is the cheapest variance reduction available, and the
cross-seed standard deviation doubles as an epistemic-uncertainty estimate —
when the seeds disagree about a name, the model is extrapolating, and the risk
layer shrinks the position.

**Calibration is mandatory.** Kelly consumes a *probability*, and raw GBDT
scores are not probabilities — they are overconfident at the extremes, exactly
where the sizing formula is most sensitive. Isotonic regression is fitted on
pooled **out-of-fold** predictions only. Fitting it in-sample would produce a
perfectly calibrated model on data it has memorised, which is worse than no
calibration because it looks correct.

### Use permutation importance, not split gain

LightGBM's `importance_type="gain"` is biased toward features with many
distinct values: such a feature offers more candidate split points and
accumulates gain across many shallow, individually worthless splits. **A
pure-noise column that fires often will out-rank a genuinely predictive column
that fires rarely** — backwards for a catalyst strategy, where the valuable
events are the rare ones.

The demo shows this directly: the high-frequency noise control ranks near the
top by gain and at zero by permutation importance. `family_importance(perm,
"auc_drop")` is the number to read when deciding whether a vendor invoice is
worth paying.

---

## Module map

| Path | Responsibility |
|---|---|
| `core/types.py` | `Event`, PIT validation, `LookaheadError` |
| `core/calendar.py` | NYSE sessions, `available_ts` → session mapping |
| `core/universe.py` | ticker ↔ CIK ↔ name resolution, fuzzy matching |
| `core/http.py` | throttling, retry, content-addressed disk cache |
| `sources/*` | one adapter per feed, all returning `Event` |
| `sources/synthetic.py` | deterministic world with **known ground truth** |
| `diagnostics.py` | event study, label lift, coverage report |
| `features/events.py` | decayed intensity, novelty, recency, breadth |
| `features/market.py` | momentum, vol, liquidity, beta — the controls |
| `features/assembler.py` | the join, and the shuffle-test audit |
| `labels.py` | triple barrier, overlap-aware sample weights |
| `model/splitter.py` | purged, embargoed walk-forward |
| `model/ensemble.py` | seed ensemble, calibration, permutation importance |
| `risk/sizing.py` | fractional Kelly and every cap |
| `risk/limits.py` | pre-trade checks, drawdown kill switch |
| `backtest/engine.py` | daily simulation, next-open fills |
| `backtest/metrics.py` | Sharpe SE, deflated Sharpe, ulcer index |
| `pipeline.py` | orchestration and the research report |

---

## Extending it

**A new data source** — subclass `EventSource`, implement `fetch(start, end)`
returning `Event` objects, set `default_latency` honestly, and implement
`health()` so `iai doctor` reports what is missing. Register it in
`build_sources()`. The registry isolates failures, so a dead vendor costs you a
feature block rather than the run.

**A new feature family** — add to `FAMILIES` in `features/events.py`. The
decayed-intensity, novelty and recency block is generated automatically.

**Shorts** — the sizing layer deliberately returns 0 for negative Kelly rather
than a short. Borrow on hard-to-borrow small caps in the middle of a catalyst
runs 20–100% annualised, frequently larger than the entire expected edge. If
you add shorts, model borrow per name; `CostConfig.borrow_bps_annual` is a
placeholder, not a measurement.
