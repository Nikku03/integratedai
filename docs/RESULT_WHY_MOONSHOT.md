# Why some filings moonshot and others crater

Explanatory rather than a strategy. The dataset is **1,538 clinical readouts over
twelve months** across 356 names — the largest clean event set in this project,
with outcomes spanning **+152% to −59%**. Fundamentals come from SEC XBRL frames
(cash 84% coverage, operating cash flow 87%, net income 88%, liabilities 87%).

Outcomes are measured two ways on purpose. `max_up` / `max_dn` are the extremes
over the 25 sessions after the next open — the move that was *available*,
independent of any exit rule. That is what gets explained here; explaining a
trade's return would confound the world with a rule already shown not to work.

## Every fundamental moves magnitude. Almost none move direction.

For each variable, quintile 1 versus quintile 5:

| variable | span Q1 → Q5 | **span ×** | ratio Q1 → Q5 | **ratio ×** |
|---|---|---|---|---|
| market cap | 36.5% → 21.5% | **0.59** | 0.56 → 1.00 | 1.78 |
| share price | 34.0% → 22.6% | **0.66** | 1.22 → 0.77 | 0.63 |
| dollar volume | 33.6% → 22.0% | **0.66** | 0.72 → 0.83 | 1.16 |
| revenue | 30.7% → 20.5% | 0.67 | 0.60 → 1.75 | **2.94** |
| burn | 33.3% → 22.8% | 0.69 | 0.41 → 1.60 | **3.88** |
| cash runway | 33.2% → 26.5% | 0.80 | 0.63 → 1.00 | 1.58 |
| liabilities / cash | 32.5% → 26.4% | 0.81 | 1.05 → 0.89 | 0.85 |
| equity / market cap | 28.3% → 33.1% | 1.17 | 0.66 → 0.76 | 1.15 |
| prior momentum | 32.1% → 35.1% | 1.09 | 0.52 → 0.72 | 1.40 |

*span = median max-up minus median max-down. ratio = P(+50%) / P(−30%).*

Small, cheap, illiquid, unprofitable, pre-revenue companies swing much harder —
**both ways**:

| | median up | median down | reached +50% | reached −30% |
|---|---|---|---|---|
| smallest cap quintile | +17.6% | −18.9% | 14.8% | 26.2% |
| largest cap quintile | +13.0% | −8.5% | 6.3% | 6.3% |
| pre-revenue (<$1m) | +18.4% | −14.8% | 14.8% | — |
| has revenue | +14.4% | −10.8% | 9.8% | — |
| unprofitable | +17.3% | −13.7% | 13.1% | — |
| profitable | +12.1% | −8.2% | 6.0% | — |

**The runway hypothesis is not supported.** "A company with three months of cash
must dilute into good news, so the spike dies" is economically plausible and it is
not what the data shows: cash runway moves the ratio 1.58×, liabilities/cash 0.85×,
equity/market cap 1.15× — all inside the noise band of the variables that clearly
carry no direction at all.

## One variable does separate the tails: how much the company spends

Among the 385 events that reached exactly one tail:

| burn quintile | n | **% up** | median burn | median cap | median revenue |
|---|---|---|---|---|---|
| 1 (lowest) | 77 | **27.3%** | $12.5m | $65m | $0.2m |
| 2 | 78 | 48.7% | $27.9m | $126m | $1.0m |
| 3 | 76 | 46.1% | $64.3m | $212m | $0.6m |
| 4 | 82 | 52.4% | $122.3m | $546m | $13.1m |
| 5 (highest) | 72 | **62.5%** | $206.4m | $1,265m | $53.0m |

Monotone, **Spearman ρ = +0.225, p = 0.00001**, and it survives controlling for
market cap (bottom vs top burn quintile, Fisher **p = 0.0009**).

**The direction of the effect is the interesting part.** High burn predicts the
*up* tail. That reads backwards until you see what burn is proxying: a company
spending $206m a year is running real Phase 3 programmes with real staff. One
spending $12.5m against a $65m market cap and $0.2m of revenue is a husk issuing
press releases. Burn is not a risk measure here — it is a measure of **whether the
company is actually developing anything.**

Within cap bands the same pattern appears in revenue:

| cap band | revenue tercile | n | +50% | −30% | ratio |
|---|---|---|---|---|---|
| small | low | 115 | 15.7% | 27.8% | **0.56** |
| small | high | 99 | 12.1% | 16.2% | 0.75 |
| mid | low | 117 | 12.0% | 12.0% | 1.00 |
| mid | high | 110 | 7.3% | 1.8% | **4.00** |
| large | low | 115 | 6.1% | 9.6% | 0.64 |
| large | high | 109 | 4.6% | 2.8% | 1.67 |

## But it does not hold out of sample, and here is why

Splitting by date:

| | n | AUC | ρ | low-burn % up | high-burn % up |
|---|---|---|---|---|---|
| train (first half) | 192 | **0.7236** | +0.377, p<0.0001 | 39% | **84%** |
| **test (second half)** | 193 | **0.5320** | +0.052, p=0.47 | 26% | 31% |

The relationship is strong in the first half and absent in the second. The reason
is visible in the base rate:

| quarter | n | +50% | −30% | **up:down ratio** |
|---|---|---|---|---|
| 2025 Q2 | 87 | 23.0% | 11.5% | **2.00** |
| 2025 Q3 | 320 | 17.5% | 10.0% | 1.75 |
| 2025 Q4 | 354 | 14.7% | 14.7% | 1.00 |
| 2026 Q1 | 408 | 8.6% | 14.0% | 0.61 |
| 2026 Q2 | 369 | 7.0% | 15.4% | **0.46** |

**The up:down ratio swings 4.3× across five quarters** — from 2.00 to 0.46. The
train half sat in the bullish regime (61% of one-tail events were up), the test
half in the bearish one (33%). A model fitted on the first learns "high burn goes
up" and meets a period where almost nothing goes up.

Variance in the up-minus-down indicator explained:

| source | share |
|---|---|
| calendar quarter | 1.6% |
| burn quintile | 2.0% |

Both tiny, and comparable to each other. Neither the company nor the calendar
explains much; the residual is idiosyncratic — which trial, which drug, which
result.

## A correction

An earlier line in this analysis claimed the opening gap predicts direction — that
a filing gapping up keeps going up. **It does not.** The quintile ratios are 0.73,
1.21, 1.23, 0.75, 0.79 with no monotone pattern, and
**Spearman ρ = −0.007, p = 0.787.** The market's first reaction carries no
information about the following 25 sessions.

## What this answers

**Why some filings moonshot:** because the company is small, cheap, illiquid and
unprofitable. Those same properties are why others crater. Every structural
variable in the data is a **volatility** variable — it sets how far the stock can
travel, not which way. This is now the fourth independent line of evidence for
that conclusion in this project, and the first built on fundamentals rather than
prices.

**The one directional variable is spending**, and it is best read as a quality
filter: companies that actually spend money on development get the up tail, husks
get the down tail. It is real in-sample (p=0.00001, survives a size control) and
does not replicate out of sample, because the regime moved further than the signal.

**What would make this testable:** the regime shift is the confound to beat.
A within-quarter or industry-neutral formulation — ranking burn *among the
readouts of the same month* rather than against an absolute threshold — would
remove the base-rate drift that broke the split above. That is a genuinely
different specification and it has not been run.
