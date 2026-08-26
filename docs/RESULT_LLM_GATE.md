# Reading the filing: three windows, one narrow survivor

Daily k=1 inside the catalyst gate, with the 8-K read before the trade. The
model proposes the top three gated names each session; the reader opens the
filings and judges them; the selections are compared.

Three non-overlapping fifteen-session windows have now been run. The third was
**pre-registered** (`PREREG_LLM_GATE_W3.md`, committed before it was built)
because the first two disagreed and the hypothesis that survived pooling them
was chosen after the fact.

| | A | B | C |
|---|---|---|---|
| sessions | 07-21 → 08-10 | 06-29 → 07-20 | **06-05 → 06-26** |
| filings judged | 45 (24 leak-free) | 45 | 45 |
| reader saw | filing only | filing + context *(corrupted)* | filing + context *(fixed)* |
| ranker saw | REM + surge | REM + surge | **+ 9 context columns** |
| universe | +2.56% | −1.58% | +1.63% |
| status | scored, then hypothesised | scored | **pre-registered** |

## What was broken, and what it did

Window B's context block was wrong in four ways. All are fixed, documented in
`company_context.py`, and were fixed *before* window C was built.

1. **Proxy statements are scaled 1000×.** DEF 14A pay-versus-performance tables
   tag `NetIncomeLoss` for the same fiscal year as the 10-K but a thousand times
   larger — BDTX's FY2025 net income is $22,367,000 in the 10-K and
   **$22,367,000,000** in the DEF 14A filed six weeks later. Preferring the
   latest-filed fact reported a $106M biotech earning $22 billion.
2. **There is no fourth quarter.** Issuers never file a standalone Q4. "The four
   most recent quarterly facts" therefore spans 454 days, fails a naive
   twelve-month check, and falls through to the annual path — straight into (1).
3. **Share counts and prices sit on different split bases.** KUST reports
   626,860 shares while the panel carries pre-reverse-split volume: a $0.8M
   market cap on $9.2M of daily turnover, i.e. 1,161% of the company traded per
   day. Nothing checked.
4. **Public float is up to eighteen months stale** — measured on the last day of
   the most recent second fiscal quarter, at that day's price. Eight of 45 rows
   showed a float larger than the whole company.

A fifth defect was in the *fix*: the year-roll added quarters since year-end
without subtracting the year-ago ones, double-counting them into $7.0B of net
income for a company with $5.4B of assets. Also corrected.

Two things I suspected and checked rather than assumed: a latent
ticker-boundary bug in the lookback windows **never fired** (every shortlisted
name had 343+ prior sessions against a 252-session high), and VISN's $7.0B TTM
net income after the fix is what the issuer actually filed — disposal gains, now
annotated rather than suppressed.

## Window C: the pre-registered result

| arm | mean | win | vs control |
|---|---|---|---|
| model k=1 (control) | +4.05% | 73.3% | — |
| reader k=1 | −4.15% | 33.3% | −8.20pp |
| blanket veto (`judge < 0`) | +1.95% | 60.0% | −2.10pp |
| **veto −2 only (PRE-REGISTERED)** | **+7.16%** | 73.3% | **+3.11pp** |
| veto + most material | −5.40% | 26.7% | −9.45pp |
| rank by judge × materiality | −4.15% | 33.3% | −8.20pp |

Against the four registered hypotheses:

**H1 — the primary — passed on the number and failed on the mechanism.** The
+3.11pp is real arithmetic, and it is **one swap**:

```
2026-06-05  ADCT  +1.67%  ->  RGNX  +48.25%   +46.58pp   <-- the only swap
   ... fourteen sessions identical to the control ...
```

Fifteen sessions produced a single occasion where the model's top pick read −2.
It swapped, and landed on a +48% name. That is one observation, not an edge.

**H2 — the mechanism — failed outright.** Strong-negative filings were supposed
to underperform. In window C they returned **+1.98%** against +0.13% for the
shortlist:

```
judge -2:  SOC-48%  BTCS-10%  HWH-7%  KSCP-5%  ADCT+2%  CRMT+80%
```

CRMT is the clearest miss in this repository: a lender forbearance on
anticipated liquidity and collateral-coverage defaults, extended by **one week**
with all remedies expressly reserved, alongside a management retention program.
I judged it −2 with materiality 3. It returned **+80%**.

**H3 — expected to fail — confirmed.** The blanket veto returned +1.95% against
the control's +4.05%, because it also rejects the −1 bucket, which keeps being
the best one.

**H4 — do the context columns help the ranker? No.** +4.05% with them, +3.78%
without, on picks that agree 9 times out of 15.

## Pooled: 114 filings, 38 sessions

| judge | n | mean | win |
|---|---|---|---|
| **−2** | 19 | **−10.75%** | 15.8% |
| **−1** | 17 | **+3.93%** | **64.7%** |
| 0 | 50 | −2.60% | 46.0% |
| +1 | 15 | −5.92% | 20.0% |
| +2 | 13 | −1.62% | 53.8% |

Spearman **+0.061**. Judged positive −3.92%, judged negative −3.82%: a spread of
**−0.10pp**. Day-clustered bootstrap, negatives against the rest: −0.74pp, CI
[−11.2, +10.3].

**As a direction signal the reading is worth nothing, and three windows now say
so.** The positive end is worse than useless — +1 is the second-worst bucket in
the sample, and across the three windows the specific things I was most
confident about (PENG's record beat-and-raise, −33.9%; TOON's $28M settlement,
−35.6%; KSCP's revenue triple, −21.3%) were among the worst trades.

## The one thing that has not died

| | model k=1 | veto −2 only |
|---|---|---|
| A (8 sessions) | +1.90% | **+11.01%** |
| B (15) | −7.37% | **−4.71%** |
| C (15, pre-registered) | +4.05% | **+7.16%** |
| **pooled (38)** | **−0.91%** | **+3.29%** |

Better than the control in three windows out of three, including the one where
it was declared in advance. Pooled, the strong-negative bucket runs −10.75%
against −1.82% for everything else — a −8.93pp gap, CI [−20.2, +4.7],
**P(not worse) = 0.085**.

That is the honest state of it: consistent in sign across three windows,
directionally large, and still not clear of zero — with the caveat that window
C's contribution rests on a single swap and that window C's own bucket table
contradicted the mechanism. Nineteen strong-negative calls is not a sample.

## What would settle it

Not another fifteen sessions. The −2 bucket accumulates at roughly six per
window, so distinguishing −10.75% from zero needs the historical panel, not live
windows: score every gated 8-K from 2018 on for the specific structural markers
that produced the −2 calls — serial reverse splits, option pools approaching the
share count, evergreen provisions, busted mergers, forbearance agreements,
amendment fees consuming the cash balance — and measure the bucket over
thousands of filings instead of nineteen. That is a job for `llm_extract.py` at
scale, and it is the only version of this question with enough power to answer.

## Reproducing

```
python3 scripts/llm_gate_pick.py --build --chars 3400                     # A
python3 scripts/llm_gate_pick.py --build --chars 3400 --offset 15 \
        --out /root/.iai/wide2015/llm_gate_w2                             # B
python3 scripts/llm_gate_pick.py --build --chars 3400 --offset 30 \
        --out /root/.iai/wide2015/llm_gate_w3                             # C
python3 scripts/llm_gate_pick.py --build --offset 30 --no-context \
        --out /root/.iai/wide2015/llm_gate_w3nc                           # H4
#   ... read bundle_*.md, write labels.json ...
python3 scripts/llm_gate_pick.py --score .../labels.json [--clean] [--out ...]
```
