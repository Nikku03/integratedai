# Sizing the catalyst against the company

The idea: a $7m contract is transformative for a $30m company and invisible for a
$14bn one, so the catalyst's dollar magnitude divided by revenue or market cap
should separate real movers from noise. Every earlier grading here scored
catalysts on what they *were* — item code, verdict, a qualitative "impact" label —
and never on how big they were relative to the business.

## What was built

**Fundamentals.** Revenue from the SEC's XBRL *frames* API — one request per
concept × period returning every filer, rather than one request per company. Four
concepts tried because US-GAAP tagging is inconsistent across ASC 606 adoption.

| | coverage |
|---|---|
| tickers | 5,490 |
| with revenue | 4,003 (73%) |
| with market cap | 5,253 (96%) |
| **with both** | **3,874** |

Median revenue $263m, median market cap $720m, median revenue/cap 0.35.

**Catalyst magnitude.** Crawled **2,453 8-K filings** (accession + primary
document from EDGAR submissions) plus **928 EX-99 exhibits**, since half of 8-K
primary documents are two-page cover sheets and the press release with the numbers
is the exhibit. Dollar amounts extracted with context filtering.

## The instrument was not good enough, and that is the main result

The first extractor took the largest dollar figure surviving a boilerplate filter.
Its ten "most material" filings were **all extraction failures**:

| ticker | market cap | extracted | ratio | what it actually grabbed |
|---|---|---|---|---|
| INUV | $40m | **$220,000m** | 5,441× | not a transaction figure |
| SPFI | $587m | $790,000m | 1,346× | bank deposits |
| FMCB | $726m | $948,300m | 1,306× | bank total assets |
| HODO | $97m | $120,000m | 1,238× | — |
| PDLB | $339m | $385,000m | 1,137× | bank balance sheet |

Adding balance-sheet exclusions (total assets, deposits, loan portfolio, AUM, book
value) and requiring the amount to sit near transaction language (award, contract,
acquire, offering, proceeds, milestone) fixed most of it — SPFI fell from $790bn
to $667m, FMCB from $559bn to $77m — **but not all of it**. PDLB still extracts at
1,136× market cap, and **5.8% of amounts remain above 10× market cap**, which is
not a materiality, it is a parse error.

**Extracting "the catalyst amount" needs reading comprehension, not regex.** A
filing contains the contract value, a buyback authorisation, par value, the fee
table, and for a bank its entire balance sheet. Choosing among them is judgement.

## Results, such as they are

After dropping residual parse failures (>10× cap), **722 filings** with a
materiality ratio and a forward five-session label:

| | |
|---|---|
| filings with any dollar amount | 938 of 2,455 (**38%**) |
| usable after parse-failure screen | 722 |
| reached +20% | 48 |
| reached −20% | 71 |
| **AUC of materiality on up-vs-down** | **0.5178** (n=101) |

| amount / market cap | n | +20% | −20% | down:up |
|---|---|---|---|---|
| <1% | 71 | 9.9% | 16.9% | 1.71 |
| 1–5% | 90 | 11.1% | 16.7% | 1.50 |
| 5–20% | 193 | 5.2% | 6.2% | 1.19 |
| 20–100% | 196 | 4.6% | 7.7% | 1.67 |
| >100% | 172 | 7.0% | 9.9% | 1.41 |

**No monotone pattern.** The down:up ratio wanders between 1.19 and 1.71 with no
trend in materiality, consistent with the 2:1 skew found everywhere else in this
universe including at random non-catalyst timestamps.

### Traded out of sample and verified against market data

Model fitted on 1–14 July with materiality, market cap, amount and pre-event
volatility; scored on 15–29 July. "Correct" = reached +20% without first reaching
−20%.

| selection | trades | **correct** | mean 5-day |
|---|---|---|---|
| all filings | 555 | **4.9%** | −0.36% |
| top 50% | 278 | 1.8% | +0.07% |
| top 25% | 139 | 1.4% | −0.14% |
| **top 10%** | 56 | **1.8%** | −0.36% |

**The model's best picks are correct less often than taking everything** — 1.8%
against a 4.9% base rate, Fisher p = 0.51. Selecting on materiality made it worse.

## The one clean materiality finding: DoD

DoD contract values need no extraction — they are stated. Across 111 awards over
seven digest days, **$38.3bn total**:

| | |
|---|---|
| awards matched to a public ticker | 27 of 111 (24%) |
| **median award as % of market cap** | **0.7%** |
| names where all July awards exceed 5% of cap | 4 |
| smallest genuine match | AMTM, $5.3bn |

**There is no small-cap DoD trade.** Awards go to companies too large for a
contract to matter (LMT $116.6bn, RTX $247.3bn) or to private LLCs and JVs with no
stock. A $500m award against a $116bn market cap is 0.4% — materiality is
structurally negligible, and that conclusion rests on exact figures rather than a
regex.

## What this does and does not establish

**It does not disprove the idea.** The hypothesis — that catalyst size relative to
company size predicts the move — was not given a fair test, because the
measurement could not reliably identify which number in a filing is the catalyst.
38% extraction coverage and a 5.8% residual error rate are not adequate.

**It does establish that the mechanical version fails.** Regex over filing text,
even with balance-sheet and transaction-context filters, does not produce a
materiality estimate that predicts direction.

**The version that would work is the one this project already demonstrated at
small scale.** The 83-filing pass where readers actually read the text produced
the single most durable result here: a trap screen that caught four dilution
events invisible to item codes, and Item 3.02 subsequently measured at −11.61% at
ten days over 62 filings. Applying that reading to 2,453 filings — extracting the
*specific* catalyst amount and dividing by revenue — is the real test of this idea,
and it has not been run.

**And it should be run against the right target.** Everything else measured here
says the filing predicts *magnitude*, not direction: the 2:1 down-skew is a
property of the universe and holds at random timestamps with no catalyst at all.
A materiality measure would most plausibly improve the magnitude forecast, not
rescue a direction forecast that nothing has yet moved off 0.5.
