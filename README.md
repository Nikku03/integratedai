# integratedai

A catalyst-driven equity research stack. It ingests SEC filings, federal
litigation dockets, partner/counterparty relationships, corporate jet movement
and seaborne trade flows, turns them into point-in-time features, and trades
them with hard-capped position sizing.

The design goal is **safe high variability**: variance from breadth and skew
across many small bets, never from concentration. See
[`docs/RISK.md`](docs/RISK.md) for what that means precisely.

---

## Quick start

```bash
pip install -e ".[dev]"

# Full pipeline on a synthetic world with known ground truth. No network, no keys.
iai demo --fast

# What is actually configured in your environment?
iai doctor

# Real data
export IAI_USER_AGENT="your-name your@email.com"     # the SEC requires this
iai fetch --tickers AAPL,MRNA,PLUG,RIOT --start 2019-01-01 --end 2024-12-31
iai research --save-model --n-trials 1
iai signals
```

---

## What it does

```
sources → point-in-time events → EVENT STUDY → features → triple-barrier labels
        → purged walk-forward → calibrated ensemble → capped Kelly sizing → backtest
```

The **event study runs before the model**, and it is the most useful thing here.
It decomposes abnormal returns around each event kind into:

- **`pre_car`** — the move *before* your timestamp. Large means your data is
  late and someone else has it first.
- **`day0_car`** — the announcement move. Real, but not available to you.
- **`drift_car`** — days +1 to +20. **The only part you can trade.**

A model that scores beautifully on an uncapturable effect still loses money.
This tells you which is which in seconds rather than days.

---

## Verifying it works

`iai demo` runs against a synthetic market with **known planted effects**: four
event kinds carry a forward drift, two are pure noise. Recovering the planted
drift — with the right sign, the right size, and no pre-event move — is what
verifies the point-in-time chain end to end.

```
  event kind             planted  measured       t      pre   verdict
  catalyst.merger         +7.0%   +10.51%    5.85   +1.30%   tradable drift +10.51%
  flight.convergence      +3.0%    +4.37%    4.04   -0.21%   tradable drift +4.37%
  docket.securities       -3.5%    -3.51%   -2.85   -0.43%   tradable drift -3.51%
  8-K.1.01                +2.0%    +2.16%    3.51   +0.12%   tradable drift +2.16%
  shipping.surge          +0.0%    +0.86%    1.23   -0.07%   no detectable effect
  8-K.7.01                +0.0%    -0.58%   -1.45   +0.11%   no detectable effect

  RECOVERY: PASS
```

Both controls read null, both signs are right, `pre_car` is ~0 everywhere (no
leakage), and the planted magnitudes come back within noise.

> **The synthetic backtest prints Sharpe ~2.2. That number means the plumbing is
> connected. It says nothing about whether this strategy works on real markets,
> because the synthetic world contains alpha by construction.**

The planted drifts are deliberately *realistic* in size, which is why the model
AUC is ~0.54 rather than something impressive. That is the honest number for
this problem. A synthetic world tuned to produce AUC 0.75 would validate
nothing except the tuning.

---

## What happened when it was pointed at real data

Full detail in [`docs/FINDINGS.md`](docs/FINDINGS.md). It was run twice:

| Run | Universe | Events | Kinds surviving FDR |
|---|---|---|---|
| 1 | 19 high-beta names, 2021–2024 | 3,218 | **0 of 15** |
| 2 | 46 small/mid caps, 2019–2024 | 7,794 | **0 of 15** |

Two results worth knowing:

- **`form.424B5` shows +8.0% *before* the filing.** Not a latency bug — the
  EDGAR timestamp is accurate to the second. It is **endogeneity**: companies
  do dilutive shelf takedowns *because* the stock ran up. "424B5 predicts
  −2.35%" is confounded, and unlike a late timestamp it is not fixable by
  buying faster data.
- **Post-earnings drift measured t = −2.07, p = 0.039 — and it is not real.**
  Fifteen hypotheses were tested at once, so you expect 0.75 false positives per
  run. It does not survive Benjamini-Hochberg. The first version of this tool
  reported it as `tradable drift -0.94%`; that was the tool committing the
  exact error it exists to prevent, which is why `survives_fdr` is now the
  column the verdict reads.

**This does not prove there is no catalyst edge.** It tests one source
marginally on a small universe — 46 names gives a ~1.2% standard error on a
20-day CAR, so most "no detectable effect" rows are statements about statistical
power, not about the world. It does mean the naive "8-K item type → drift"
hypothesis is dead on arrival, and that the sources worth paying for are the
ones not tested here.

---

## Which data sources are actually worth it

Full detail in [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md). The short version:

| Source | Cost | Verdict |
|---|---|---|
| SEC EDGAR filings + full-text | free | **The backbone.** Best signal per dollar in public markets. |
| Partner spillover (derived) | free | **Underrated.** Differentiated, costs only code. |
| Litigation (CourtListener) | free tier | Useful but **one-sided** — a hit informs, a miss proves nothing. |
| Bills of lading | $1k–10k+/yr | **The only trade tier with single-stock alpha.** |
| AIS vessel tracking | $$$ | Middle tier, operationally annoying. |
| UN Comtrade | free | Macro tilt only. **75-day publication lag.** |
| Private jet ADS-B | free-ish | **Weakest.** Real but small, badly biased. Build it last. |

On jets specifically, since you asked for them: it is lawful (ADS-B is a public
broadcast, the FAA registry is a public record), and the tradable pattern is
**convergence** — aircraft of two different issuers on the ground at the same
airport in a short window — not "the CEO flew somewhere". But coverage is biased
toward companies that are *not* hiding their tails, which correlates with not
being in play, and attribution through single-purpose LLCs is manual. It is the
most fun source and the least profitable.

---

## How lookahead is prevented

Every `Event` carries **two** timestamps: `event_ts` (when it happened) and
`available_ts` (when you could first have acted). Comtrade's gap is 75 days.
EDGAR's is 15 minutes, or overnight after 17:30 ET.

Four layers of defence:

1. `validate_events()` **raises** — not warns — on `available_ts < event_ts`.
2. Expanding-only baselines; the partner graph is rebuilt as-of each date; jet
   ownership is interval-based, because an airframe sold in 2023 was not the
   issuer's aircraft in 2021.
3. `audit_lookahead()` runs a shuffle test against a within-date permutation
   null. `test_audit_catches_injected_lookahead` plants an 80%-pure copy of the
   future label and asserts the alarm fires — a test that only checked clean
   data would also pass with the audit stubbed out.
4. Purged, embargoed walk-forward CV.

The timing convention, applied in exactly one place each:

```
panel row dated t  →  only what was public at the CLOSE of t
trade for row t    →  entered at the OPEN of t+1
```

---

## Notes for whoever runs this next

**Read the permutation importance, not the split gain.** LightGBM's gain metric
is biased toward high-frequency features — in the demo the pure-noise control
ranks near the top by gain and at zero by permutation importance. Vendor-renewal
decisions should read `auc_drop`.

**Pass `--n-trials` honestly.** If you backtest 200 configurations and keep the
best, its Sharpe of 1.8 is roughly what 200 coin flips produce.
`deflated_sharpe_prob` prices that in, but only if you tell it the truth.

**`sharpe_se` is ~0.5 on three years of daily data.** A measured Sharpe of 1.0
is not distinguishable from zero.

**Buy survivorship-bias-free prices before risking money.** A catalyst strategy
is disproportionately exposed to names that later delist, so Yahoo's
survivor-only history is biased in exactly the direction that matters most.
`CsvPrices` takes a vendor extract.

**Keep the label and the backtest in sync.** If `labels.max_holding_days` and
`risk.max_holding_days` diverge, the model is predicting a trade nobody makes.

---

## Layout

```
src/iai/
  core/         Event type, PIT validation, NYSE calendar, identifier resolution
  sources/      one adapter per feed + a synthetic world with known ground truth
  diagnostics/  event study, label lift, coverage — run these first
  features/     event intensity + market controls, and the lookahead audit
  labels.py     triple barrier, overlap-aware sample weights
  model/        purged walk-forward, seed ensemble, isotonic calibration
  risk/         fractional Kelly, hard caps, drawdown kill switch
  backtest/     next-open fills, sqrt impact, deflated Sharpe
docs/           ARCHITECTURE.md · DATA_SOURCES.md · RISK.md
tests/          82 tests, PIT correctness first
```

```bash
pytest tests/ -q          # ~12 min; the model tests train real models
pytest tests/ -q -m "not slow"
```

---

## Status and honest limitations

This is a **research scaffold**, not a trading system you should fund on Monday.

Working and tested end to end: all six source adapters, point-in-time
validation, event study, feature assembly, labelling, purged walk-forward,
calibration, sizing, limits, backtest, CLI.

Not done, and you would need it:

- **No broker integration.** `iai signals` prints orders; nothing sends them.
- **No live scheduler.** No daily cron, no state persistence across runs, no
  reconciliation of intended vs actual positions.
- **Costs are modelled, not measured.** Calibrate `impact_coef_bps` against your
  own fills before trusting any net number.
- **Long only.** Negative Kelly returns zero rather than a short, because borrow
  on hard-to-borrow small caps mid-catalyst frequently exceeds the entire edge.
- **No real-data validation.** The event study has been run against synthetic
  ground truth only. **Run it on your real universe before anything else** — if
  `drift_car` is flat, stop there.
