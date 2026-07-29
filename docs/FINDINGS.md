# Real-data findings

Everything here comes from live data, not the synthetic world. Three studies,
in order. The third one is the interesting one.

---

## Study 3 (current): small/mid caps, short horizon, five sources

**Universe** 106 US small/mid caps, selected by **point-in-time** market cap
(SEC XBRL shares outstanding × price, quarter by quarter — not today's
snapshot). Cap bands actually traded: 19 micro, 81 small, 86 mid, plus some
band migration.
**Period** 2021-01-01 → 2024-12-31 · 106,222 daily bars.
**Config** `Config.short_horizon()` — 8-session holds, 1.5σ/0.75σ asymmetric
barriers, 15bp half-spread, 45bp impact coefficient.
**Events** 37,562 across five sources:

| source | events | tickers | median latency |
|---|---|---|---|
| flow (volume/price anomalies) | 15,464 | 106 | **0 h** |
| edgar (filings, item-coded) | 12,598 | 106 | 0.25 h |
| insiders (Form 4) | 7,037 | 97 | **55 h** |
| stakes (13D/G) | 2,387 | 106 | 0.25 h |
| news (press-release intensity) | 76 | 29 | 0 h |

### Marginal event study: 1 of 31 kinds survives FDR, and it is confounded

`insider.sell` — drift −0.46%, t = −3.21, p = 0.0013 — survives Benjamini-Hochberg
but is flagged **CONFOUNDED**: `pre_car` = +1.28%, larger than the drift itself.
Insiders sell *after* the stock runs up. Endogenous, not predictive, and −0.46%
over 13 days would not clear costs anyway.

Everything else, including every kind you asked about, fails:

| kind | n | pre_car | day0_car | drift_car | t | survives FDR |
|---|---|---|---|---|---|---|
| `insider.cluster_buy` | 81 | −3.51% | **+1.89%** | +0.78% | 0.55 | no |
| `insider.buy` | 391 | −2.10% | **+2.52%** | +0.81% | 1.21 | no |
| `flow.volume_surge` | 4,838 | +5.55% | +0.13% | +0.13% | 0.56 | no |
| `flow.breakout` | 3,029 | +13.00% | +0.10% | +0.23% | 0.77 | no |
| `flow.accumulation` | 2,633 | +13.41% | +0.06% | −0.11% | −0.34 | no |
| `8-K.1.01` (material agreement) | 603 | +1.08% | +0.53% | +1.11% | 1.52 | no |
| `news.attention_spike` | 76 | +0.29% | −1.00% | −3.20% | −1.78 | no |

Two things in that table are worth dwelling on.

**Insider buys move the stock ~2.5% on the filing day and then stop.**
`day0_car` for `insider.buy` is +2.52% and for `insider.cluster_buy` is +1.89% —
large, real, and **entirely unavailable to you**. By the next open it is gone.
The market prices Form 4s efficiently within the session they hit. That is a
much more useful thing to learn than a Sharpe ratio.

**The flow features are definitionally endogenous.** `flow.breakout` has
`pre_car` of +13% because a breakout *is* a prior price rise — the definition
contains the pre-move. `flow.accumulation` +13.4%, `flow.breakdown` −11.9%.
The `pre_car` column caught this immediately, which is exactly why it exists.

---

### The conjunction: your actual hypothesis, tested properly

A marginal event study asks "does this kind move price on average". Your thesis
was a **conjunction** — insiders moving *and* volume confirming — and a marginal
test is structurally blind to it. So `diagnostics.conditional_event_study()`
tests it directly, always reporting the unconditional arm alongside:

| primary | arm | n | drift (13d) | t |
|---|---|---|---|---|
| `insider.buy` | **with volume surge/accumulation** | 87 | **+3.38%** | **2.28** |
| `insider.buy` | without volume confirmation | 312 | +0.09% | 0.11 |
| `insider.buy` | all | 399 | +0.81% | 1.21 |
| `flow.volume_surge` | with insider buy or 8-K 1.01 | 273 | **+2.30%** | **2.08** |
| `flow.volume_surge` | without | 4,645 | −0.00% | −0.00 |

**The conjunction is ~40× the unconditional effect, and the unconditional arm
is dead flat.** Directionally this is exactly what you proposed.

But `pre_car` for the confirmed arm is **−6.8%** — these are insiders buying
*after a fall, on heavy volume*. That is a well-documented short-term reversal
setup, so the obvious objection is that the insider adds nothing. Control run:

| arm | n | drift (13d) | t | pre_car |
|---|---|---|---|---|
| insider buy + volume, after ≥5% drop | 36 | **+5.01%** | 1.81 | −18.0% |
| insider buy + volume, no big drop | 50 | +2.21% | 1.38 | +1.3% |
| **CONTROL: volume surge after ≥5% drop, no insider** | **1,061** | **+0.45%** | 1.22 | −9.99% |
| insider buy, no volume confirmation | 305 | +0.09% | 0.11 | −0.78% |

**It is not reversal.** Beaten-down-plus-volume alone returns +0.45% over 1,061
events. Add the insider purchase and it is +5.01% — about eleven times larger.
The insider is carrying the information.

**And it still does not clear the bar.** n = 36, t = 1.81. Not significant on
its own, and I tested 11 conditional arms plus 31 marginal kinds to find it —
**0 of 11 conditional arms survive FDR correction**. This is a promising,
economically sensible, badly underpowered result. It is a reason to get more
data, not a reason to trade.

---

### The model: good AUC, negative P&L, and the reason matters

Purged walk-forward, 5 folds, 3 seeds, 87 features.

```
pooled AUC   0.6059        folds: 0.635 / 0.573 / 0.648 / 0.570 / 0.640
pooled Brier 0.1335        calibration: mean p 0.163 vs realised 0.163
```

AUC 0.61 with consistent folds and near-perfect calibration is a genuinely
respectable model. The backtest:

```
CAGR            -4.56%          hit rate         38.3%
Sharpe          -0.61           profit factor     0.79
max drawdown   -23.2%           avg positions      1.2
deflated Sharpe  0.109          avg gross          5.1%
```

**Why a 0.61-AUC model loses money.** The diagnostic that answers it:

| selection | n | hit rate | mean gross return |
|---|---|---|---|
| all rows | 49,717 | 0.163 | +0.02% |
| top 50% by p | 28,037 | 0.201 | +0.16% |
| top 10% by p | 8,088 | 0.227 | +0.10% |
| top 1% by p | 1,354 | 0.251 | **+0.21%** |

The ranking is real — hit rate climbs monotonically from 16% to 25%. But the
best 1% of signals earns **+0.21% gross over an 8-day hold**, and modelled
round-trip cost on this universe is **~48bp** (24bp each way, measured in the
backtest's own cost summary). The edge is real and roughly *half* the size of
the cost of harvesting it.

That is why average gross exposure is 5% against a 150% limit: the edge gate is
working correctly and refusing to deploy capital it cannot justify. The
strategy's honest output is "I don't have enough edge to trade this."

**Where the AUC comes from** is the other half of the story:

| source | out-of-sample AUC drop | share |
|---|---|---|
| market (vol, momentum, liquidity) | 0.0556 | **73.4%** |
| edgar | 0.0172 | 22.6% |
| flow | 0.0023 | 3.1% |
| insider | 0.0004 | 0.6% |
| news | −0.0000 | 0% |
| institutional | −0.0029 | 0% |

Three-quarters of the model's discrimination is market-state features
predicting which names hit volatility-scaled barriers — barrier mechanics, not
catalysts. Strip those out and there is very little left. Note also that this
ordering comes from *permutation* importance; split gain ranks `instl` at 10%,
which is the bias the two-column comparison exists to expose.

---

## Bugs this study found in the code

Real data breaks things synthetic data does not.

1. **Form 4 same-day filings caused time travel.** Transaction dates carry no
   time, so I anchored them at the 16:00 close — which lands *after* a filing
   accepted at 10:42 ET. `validate_events` rejected the batch. Anchored at the
   open and clamped to the filing timestamp.
2. **Negative lower barriers.** MDGL's ~250% NASH-readout gap pushed trailing
   daily vol past 45%, so `sigma × sqrt(8) > 1.0` and
   `entry × (1 − 0.75 × sigma_h)` went **below zero** — a stop that can never
   trade, forcing 41 samples to time-stop labels. Worse, its relative barrier
   width of −648 dragged the payoff-bucket quantiles for all 105,000 rows.
   Winsorised sigma and floored the barrier.
3. **Zero-variance baselines silently ate the biggest spikes.** Z-scoring
   volume and news counts against a rolling std, then dropping the zero cases,
   discards exactly the observation you care about: a quiet name's first big
   day has a near-zero baseline std, so it divides by ~0 and vanishes. Floored
   the denominator (`MIN_LOG_STD`).
4. **A missing sector map throttled the book.** Passing no sectors put all 106
   names in one bucket against a 30% sector cap. That was a limit doing its job
   on bad input, not a bug in the limit — fixed by deriving sectors from SEC
   SIC codes.

---

## What this establishes, and what it does not

**Establishes:**

- The full pipeline runs end to end on real data at scale — 10,432-issuer SEC
  universe resolution, 17,368 Form 4 XML documents parsed, point-in-time
  market-cap screening, five sources, 111 tests green.
- Insider buys and cluster buys **do** move price ~2%, on the filing day, and
  that move is not available to a next-open entry.
- The naive "catalyst kind → drift" hypothesis is dead on this universe.
- **The conjunction hypothesis (insider + volume confirmation) is the most
  promising thing found**, at ~11× its own control, and is underpowered.

**Does not establish:**

- That no edge exists. 106 names over 4 years gives ~36 events in the most
  interesting cell. You cannot conclude much from 36 events, in either
  direction.
- Anything about the sources not tested here — litigation, bills of lading, jet
  convergence — which are the ones where data is genuinely hard to get, and
  therefore where edge is most likely to survive.

---

## What I would do next, in priority order

1. **Widen the universe by 10–20×.** This is the binding constraint on
   everything above. The interesting cell has 36 events; it needs 500. Take the
   full Russell 2000 with a delisting-inclusive price archive
   (`CsvPrices` is the hook) and the same code produces a real test. Expect
   ~350k Form 4 documents — the fetch is already concurrent and cached.
2. **Test the conjunction properly, pre-registered.** Insider buy + volume
   confirmation + drawdown is now a *stated* hypothesis with a specified
   window. Test it once, on new data, and put the p-value through
   `benjamini_hochberg` counting every arm you try.
3. **Attack the cost problem directly**, because a +21bp gross edge against
   48bp costs is the actual blocker. Either move up the cap scale (mid caps
   halve the spread), extend the hold so the edge accumulates against a
   one-time cost, or use limit orders and measure real fill rates. Calibrate
   `impact_coef_bps` against your own fills before believing any net number.
4. **Only then revisit the model.** Nothing above justifies more feature
   engineering. The model is already well calibrated with honest ranking power;
   its problem is that the thing it ranks is not worth enough.

Reproduce with `scripts/run_smallmid.py` then `scripts/model_smallmid.py`.

---

## Studies 1 and 2 (earlier, EDGAR only)

| Run | Universe | Events | Kinds surviving FDR |
|---|---|---|---|
| 1 | 19 high-beta names, 2021–2024 | 3,218 | 0 of 15 |
| 2 | 46 small/mid caps, 2019–2024 | 7,794 | 0 of 15 |

Notable from run 2, both of which drove code changes:

- **`form.424B5` shows +8.0% *before* the filing.** Not latency — the EDGAR
  timestamp is accurate to the second. **Endogeneity**: companies do dilutive
  shelf takedowns *because* the stock ran up. Added the `CONFOUNDED` verdict.
- **Post-earnings drift measured t = −2.07, p = 0.039 — and is not real.**
  Fifteen hypotheses tested at once. The tool originally reported it as
  `tradable drift -0.94%`, which was the tool committing the exact error it
  exists to prevent. Added Benjamini-Hochberg; `survives_fdr` is now the column
  the verdict reads.
