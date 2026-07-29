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

### Two profiles

`Config()` is the default: 15-day horizon, symmetric-ish barriers, liquid names.

`Config.short_horizon()` is the fast small/mid-cap profile — 8-session holds,
**asymmetric 1.5σ up / 0.75σ down barriers** (lower hit rate, ~4:1 payoff,
which is what "big reward on a short trade" means mechanically), 1–3 day
feature decay half-lives, a $750k ADV floor so small caps actually qualify, and
**tripled spread and impact assumptions** because that is what trading small
caps on news days actually costs. The backtest gets worse and more honest at
the same time.

```python
from iai.core.config import Config
from iai.pipeline import fetch_smallmid, run_research

cfg = Config.short_horizon()
prices, events, uni, caps = fetch_smallmid(cfg, "2021-01-01", "2024-12-31", max_names=120)
print(run_research(prices, events, cfg, extra_features=caps).report())
```

Universe selection uses **point-in-time market caps** from SEC XBRL shares
outstanding × price, not today's snapshot. Screening on today's cap sorts on
the future in two directions at once: survivorship (the zeros are gone) and
migration (today's small caps are yesterday's mid caps that fell 60%).

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

## Moonshot profile: five trades a week, +10% targets

Full detail in [`docs/MOONSHOT.md`](docs/MOONSHOT.md).

```bash
python scripts/moonshot.py --trades-per-week 5
```

Fewer, larger, lower-probability bets with an **absolute** +10% target and −7%
stop rather than many small volatility-scaled ones. The shape change fixes the
arithmetic that killed the previous version: a +21bp edge against 48bp of cost
is hopeless, a +122bp edge against the same 48bp is not.

**+12.2% CAGR, Sharpe 0.58 ± 0.70** over two out-of-sample years, 515 trades at
exactly 5.0/week, 50.9% win rate, +0.96 skew. It makes money in backtest and is
**not statistically distinguishable from luck** — deflated Sharpe 0.108 after
accounting for ~30 configurations tried.

**The one finding worth keeping regardless:** rank on expected value, not on
P(spike). A second model for the *downside* changes everything:

| ranking | P(spike) | stop rate | net/trade |
|---|---|---|---|
| P(spike) only | 38.8% | 53.6% | **−0.44%** |
| **expected value** | 33.0% | **36.1%** | **+0.56%** |

Picking the names most likely to jump 10% picks the names most likely to *move*,
which are the same names most likely to drop 7%. It passes the volatility
control too — selected names have 0.76× the universe median volatility, with
lift inside every volatility bucket.

---

## What moves the price, and in what order

Full detail in [`docs/CASCADE.md`](docs/CASCADE.md). The question was whether
the filing lands first and the crowd follows. Measured across 37,562 events:

```
SEC filing (t=0)  ->  media pickup (+8h)  ->  volume surge (+23h)  ->  breakout (+22h)
```

Earnings 8-Ks lead their volume surge 82% of the time by a median 23 hours. And
the move is overwhelmingly *after* the bell you can trade at:

| leg | median absolute move | tradable? |
|---|---|---|
| overnight gap (machines) | **0.89%** | no |
| intraday + next 5 sessions (crowd) | **6.76%** | **yes** |
| gap's share of the whole move | **11%** | |

So ~89% of the movement is reachable. **The catch is direction**: median
capturable return is ~0 for most event kinds and win rates sit at 51–54%. Only
4 of 25 kinds survive an outlier-robust sign test with FDR correction, and the
largest is *negative* — a `424B5` shelf takedown is followed by a further
−2.50% median (39% positive).

One exception matters: `8-K.1.01` (material agreements) is the single kind where
volume arrives *before* the filing. Deals leak; that is the one hand where you
are demonstrably last to know, and the right move is not to play it.

---

## What happened when it was pointed at real data

Full detail and reproduction steps in [`docs/FINDINGS.md`](docs/FINDINGS.md).
The headline run: **106 small/mid caps, 2021–2024, 37,562 events across five
sources** (volume/flow, EDGAR filings, Form 4 insiders, 13D/G stakes,
press-release intensity), universe selected on **point-in-time** market caps.

**Marginal event study: 1 of 31 event kinds survives FDR correction, and it is
confounded.** But two results are genuinely worth knowing:

**1. Insider buys move the stock ~2.5% — on the filing day, and then stop.**

| kind | n | pre | **day 0** | drift +1..+13 | t |
|---|---|---|---|---|---|
| `insider.buy` | 391 | −2.10% | **+2.52%** | +0.81% | 1.21 |
| `insider.cluster_buy` | 81 | −3.51% | **+1.89%** | +0.78% | 0.55 |

The announcement move is large and real. It is also **entirely unavailable** to
a next-open entry — the market prices Form 4s within the session they hit.

**2. Your conjunction thesis — promising on means, tail-driven on inspection.**
(Superseded: see [`docs/CASCADE.md`](docs/CASCADE.md) §4. Dropping the 20 largest
of 340 insider-buy outcomes takes t from 3.15 to 0.42; median is +0.21% at a
51.5% win rate. A date-shuffled placebo came back at −0.20%, so it is not a
methodological artifact — it is a lottery-ticket payoff, not a reliable one.) A marginal event study is structurally blind to "insiders
moving *and* volume confirming", so `conditional_event_study()` tests it
directly:

| arm | n | drift (13d) | t |
|---|---|---|---|
| insider buy **with** volume confirmation | 87 | **+3.38%** | 2.28 |
| insider buy without | 312 | +0.09% | 0.11 |
| ↳ narrowed: also after a ≥5% drop | 36 | **+5.01%** | 1.81 |
| **control: that drop + volume, no insider** | **1,061** | **+0.45%** | 1.22 |

The conjunction is ~40× the unconditional effect, and the control rules out
short-term reversal — beaten-down-plus-volume alone gives +0.45%, adding the
insider gives +5.01%. **But n = 36, and 0 of 11 conditional arms survive FDR.**
Promising, economically sensible, and not yet evidence.

**3. The model has real ranking power and still loses money, for an
instructive reason.** AUC 0.606 out-of-sample, perfectly calibrated
(mean p 0.163 vs realised 0.163), hit rate climbing monotonically 16% → 25%
across prediction deciles. Backtest: **−4.6% CAGR, Sharpe −0.61.**

The best 1% of signals earns **+0.21% gross** over 8 days. Modelled round-trip
cost on small caps is **~48bp**. The edge is real and about half the size of
what it costs to harvest. Average gross exposure sits at 5% against a 150%
limit because the edge gate is correctly refusing to deploy capital.

And 73% of that AUC comes from *market-state* features predicting which names
hit volatility-scaled barriers — barrier mechanics, not catalysts. Insider
features contribute 0.6%; news, −0.0%.

**None of this proves there is no edge.** 106 names over 4 years leaves 36
events in the most interesting cell. That is a statement about statistical
power, not about the world — which is why the top recommendation is a 10–20×
wider universe, not more feature engineering.

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
  core/              Event type, PIT validation, NYSE calendar, identifier resolution
  sources/           edgar · insiders (Form 4) · institutional (13F, 13D/G) ·
                     flow (volume anomalies) · news · litigation · flights ·
                     shipping · prices + a synthetic world with known ground truth
  diagnostics.py     event study, CONDITIONAL event study, FDR correction — run first
  universe_builder   point-in-time market caps from SEC XBRL
  features/          event intensity + market controls, and the lookahead audit
  labels.py          triple barrier, overlap-aware sample weights
  model/             purged walk-forward, seed ensemble, isotonic calibration
  risk/              fractional Kelly, hard caps, drawdown kill switch
  backtest/          next-open fills, sqrt impact, deflated Sharpe
docs/                ARCHITECTURE.md · DATA_SOURCES.md · RISK.md · FINDINGS.md
scripts/             run_smallmid.py (fetch) · model_smallmid.py (train+backtest)
tests/               111 tests, PIT correctness first
```

```bash
pytest tests/ -q          # ~90s
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
