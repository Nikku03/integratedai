# The five upgrades, built and scored

All five were implemented. One found the first real direction signal in this
project; two are refuted by their own data; one could not be built as specified;
one is confirmed.

## 1. Structured extraction replacing regex — **built, with a caveat**

`catalyst_extract.py` emits the proposed schema per filing:
`{event_category, is_binding, transaction_value_usd, value_confidence,
has_toxic_financing, toxic_signals}`.

**No LLM is available in this container** — no Ollama, no anthropic/openai SDK, no
GPU, no key. The extractor is therefore a deterministic stand-in over the
standardised legal vocabulary filings use, dispatched through a pluggable
`extract(text, backend=...)`. Wiring a model in means implementing one function
with the same signature.

Run over **2,453 filings** (primary document + EX-99):

| event_category | n |
|---|---|
| ADMINISTRATIVE | 1,565 |
| DEBT_SETTLEMENT | 198 |
| MA_ACTIVITY | 189 |
| DILUTION_OFFERING | 180 |
| EARNINGS | 156 |
| FDA_APPROVAL | 75 |
| COMMERCIAL_CONTRACT | 47 |
| CLINICAL_RESULT | 43 |

`is_binding` 17.2%, `has_toxic_financing` 13.0%, a transaction value found 15.1%.

**The rules version is much better at classification than at extraction.** 64% of
filings fall to ADMINISTRATIVE, and value coverage is worse than the old max-amount
regex. A model would fix the value field; the category and toxicity fields are
already carrying the weight.

## 2. Normalise by TTM revenue, not market cap — **does not work**

Top-line shock computable for **213 filings** (11.6%):

| shock (value / TTM revenue) | n | +20% | −20% | down:up |
|---|---|---|---|---|
| <10% | 120 | 10.8% | 13.3% | 1.23 |
| 10–50% | 40 | 7.5% | 7.5% | 1.00 |
| 50–200% | 22 | 9.1% | 13.6% | 1.49 |
| >200% | 31 | 9.7% | 16.1% | 1.66 |

**No monotone pattern**, and the proposed >50% "high-conviction" threshold contains
the *worst* ratios. Revenue normalisation is more defensible than market cap in
principle and performs no better in fact. The binding constraint remains extraction
coverage, not the choice of denominator.

## 3. Asymmetric bifurcation — **half right**

| engine | n | +20% | −20% | down:up |
|---|---|---|---|---|
| baseline (all) | 1,936 | 5.5% | 10.3% | 1.89 |
| **NEGATIVE flagged** | 312 | 12.2% | **25.6%** | 2.11 |
| not flagged | 1,624 | 4.2% | 7.4% | 1.76 |
| **LONG passed** | 198 | **12.1%** | 12.6% | **1.04** |
| not passed | 1,738 | 4.7% | 10.1% | 2.13 |

**The negative engine finds volatility, not direction.** Flagging triples the −20%
rate (Fisher p<0.0001) but *also* triples the +20% rate; the ratio barely moves,
2.11 against 1.76. As a short signal it is a leveraged bet on the universe's
existing skew, not new information. As a **blacklist** it is genuinely useful.

**The long engine works.** +20% rate 12.1% vs 4.7% (Fisher p=0.0001), and the
down:up ratio halves from 2.13 to **1.04** — the first thing in this project to
move that ratio at all. Held out on 15–29 July: 9.9% vs 4.2%, p=0.0112.

One counterintuitive result: `is_binding=True` filings are **worse** (−20% rate
18.1% vs 9.0%). Binding language appears in note-purchase and credit agreements as
readily as in commercial contracts, so the field needs the category to be useful.

## 4. Prune the universe — **confirmed, with one correction**

Dropping DoD is right and already measured: median award 0.7% of market cap, 27 of
111 awards matching a public ticker, smallest genuine match $5.3bn.

But the proposed replacements do not survive contact with the data:

| proposed target | n | +20% | −20% | down:up |
|---|---|---|---|---|
| 8-K Item 1.01 → COMMERCIAL_CONTRACT | 37 | 2.7% | 10.8% | **4.00** |
| 8-K Item 8.01 → **FDA_APPROVAL** | 63 | 6.3% | **19.0%** | **3.00** |
| SEC 13D activist | 97 | 2.8% | 2.6% | 1.04 |
| **CLINICAL_RESULT** | 31 | **35.5%** | 12.9% | **0.36** |

**FDA approvals are sell-the-news events at 3:1 down**, consistently in both halves
(2.50 then 3.50). By the approval date the market has priced it. Commercial
contracts are worse still at 4:1. The category that works is the one not on the
list: **clinical readouts**, where the data is a genuine surprise.

## 5. The 180-second RVOL gate — **refuted, and backwards**

RVOL is only computable where the tape is running: **153 of 2,117 filings (7%)**.
Regular hours only:

| RVOL | n | +15m | +60m | +1 day | −20% rate |
|---|---|---|---|---|---|
| <1× | 94 | +0.28% | +0.12% | **+0.60%** | 11.7% |
| 1–3× | 33 | +0.24% | +1.23% | **+0.93%** | 6.1% |
| 3–10× | 17 | −0.90% | −1.63% | **−2.31%** | 11.8% |
| **>10×** | 9 | −7.19% | −11.53% | **−16.24%** | **55.6%** |

**The gate as proposed makes things three times worse**: keeping RVOL≥3 turns
−0.64% into −1.83%. A violent volume spike on an 8-K during market hours is the
market repricing *downward*, and buying the offer a minute later makes you exit
liquidity for informed sellers.

The inverted gate is **not established**: it shows nothing in the first half
(RVOL<3 +0.72% vs RVOL≥3 +0.29%, p=0.84) and a large effect in the second
(+0.67% vs −11.77%, p=0.03) on n=16. That pattern is what noise looks like.

## The one real finding: clinical readouts

The only cohort in this project that inverts the 2:1 down-skew, and it holds in
both halves of the month:

| half | n | +20% | −20% | down:up |
|---|---|---|---|---|
| 1–14 July | 19 | 42.1% | 15.8% | **0.38** |
| 15–29 July | 12 | 25.0% | 8.3% | **0.33** |
| *(baseline)* | *1,936* | *5.5%* | *10.3%* | *1.89* |

Held out: 25.0% vs 4.6%, **Fisher p=0.0166**.

### Traded, and verified against market data

27 signals, entry at the first print after T+1min, +25% target / −10% stop, five
sessions max:

| | |
|---|---|
| trades | 27 |
| mean | **+1.76%** |
| median | **−3.91%** |
| win rate | 41% |
| t | **+0.63** |
| exits | 11 time, 10 stop, 6 target |
| $80, 2 slots, compounded | **$77.29 (−3.4%)** |
| bootstrap 95% CI on the mean | **[−3.45%, +7.34%]** |
| P(mean ≤ 0) | 0.268 |

**The barrier statistics are significant and the trade is not.** The +20% *rate*
is genuinely elevated, but a +25%/−10% rule converts it to a mean of +1.76% with a
median of −3.91% — six targets carry it, ten stops drain it, and at n=27 the
confidence interval spans zero.

### And it is not a one-minute strategy

**Median fill lag is 140 minutes; only 4% fill within three minutes.** Biotech
readouts publish pre-market, so the entry is at the open roughly 2.3 hours later.
Whatever this is, the latency infrastructure is irrelevant to it.

## Where that leaves the pipeline

| upgrade | verdict |
|---|---|
| 1. LLM structured extraction | built as rules; **needs a model** for the value field |
| 2. TTM revenue normalisation | **no improvement** — no monotone pattern |
| 3. Bifurcation | **long engine works** (ratio 2.13 → 1.04); negative engine is a volatility flag |
| 4. Prune universe | **DoD confirmed dead**; but FDA and 1.01 are 3:1 and 4:1 *down* |
| 5. RVOL gate | **refuted** — proposed direction makes it 3× worse |

The single actionable output is the long engine, and inside it the clinical-readout
class. That is 27 signals a month, a genuinely inverted skew, and a trade that has
not yet been shown to make money. The honest next step is a second month — 27
observations with a CI spanning zero is a hypothesis, not an edge.
