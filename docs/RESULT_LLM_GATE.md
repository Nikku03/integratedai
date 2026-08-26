# Reading the filing: one window said yes, the next said no

Daily k=1 inside the catalyst gate, with the 8-K actually read before the trade.
The model proposes the top three gated names each session; the reader opens the
filings and judges them; three selections are compared.

Two non-overlapping windows have now been run. **They disagree, and pooling them
leaves nothing.** This document records both, because the first one on its own
was the more encouraging result and reporting it alone would be a lie by
omission.

| | window A | window B |
|---|---|---|
| sessions | 2026-07-21 → 08-10 | 2026-06-29 → 07-20 |
| filings read | 45 (24 leak-free) | 45 |
| context given to the reader | filing text only | filing **+ company context** |
| universe over the window | **+2.56%** | **−1.58%** |

## Window A: the reader looked useful

Reported first, and still true as far as it goes. 24 leak-free filings, 8
sessions:

| arm | mean | win |
|---|---|---|
| model k=1 (control) | +1.90% | 50.0% |
| reader k=1 | +1.93% | 75.0% |
| **reader veto** | **+5.13%** | 62.5% |
| shortlist average | −0.47% | — |

Judgement correlated with outcome at +0.355; negatives −8.22% against +4.17% for
the rest; day-clustered bootstrap −12.39pp, CI [−26.5, +1.7].

> Twenty-one of window A's 45 judgements were not blind — `RESULT_CATALYST_GATE.md`
> and `RESULT_MOONSHOT_HUNT.md` publish the picks with returns for seven of its
> fifteen sessions, and both had been re-read in the same session. The `--clean`
> flag drops those; the table above is already the clean subset. Window B has no
> such problem: no result document covers it.

## Window B: it reversed

Same protocol, the immediately preceding fifteen sessions, plus a point-in-time
company-context block the reader did not have the first time.

| arm | mean | win | vs universe (−1.58%) |
|---|---|---|---|
| model k=1 (control) | −7.37% | 40.0% | −5.79pp |
| reader k=1 | **−11.30%** | 20.0% | −9.72pp |
| reader veto | −9.26% | 26.7% | −7.68pp |
| shortlist average | −8.27% | 31.1% | −6.69pp |
| veto + most material | −9.18% | 20.0% | |
| rank by judge × materiality | −11.54% | 13.3% | |
| positive **and** material | −9.43% | 25.0% | |

**Every reader arm lost to the model it was supposed to improve.** Rank
correlation −0.087. Judged-positive −8.40%, judged-negative −5.40% — the spread
is **−3.00pp**, the wrong sign.

The market was down 1.6% in this window against up 2.6% in window A, so four
points of the gap are conditions. The other five are the gated top-three pool
doing badly and the reading making it worse.

The veto swapped four times and got three of them wrong:

```
2026-07-13  BYRN  -1   +7.92%  ->  PENG  +2  -33.86%   -41.77pp
2026-07-14  ZSQR  -2  -13.97%  ->  EFOR  +1  +33.96%   +47.94pp
2026-07-15  CABO  -2   +4.63%  ->  CUE   +2   -3.38%    -8.01pp
2026-07-16  SOC   -1   +5.21%  ->  SPRO  +1  -21.25%   -26.46pp
```

## Pooled, there is no effect

69 filings, 23 sessions, both windows:

| | negatives | rest | difference | 95% CI | P(not worse) |
|---|---|---|---|---|---|
| window A | −8.22% | +4.17% | −12.39pp | [−26.5, +1.7] | 0.044 |
| window B | −5.40% | −9.71% | **+4.31pp** | [−9.2, +18.8] | 0.726 |
| **pooled** | −6.46% | −5.08% | **−1.38pp** | [−11.9, +9.6] | 0.404 |

Spearman correlation pooled: **+0.098**. Pooled arms: model k=1 −4.15%, reader
k=1 −6.70%, reader veto −4.25%. The reading layer is worth nothing.

## The one thing that survived

| judge | n | mean | win |
|---|---|---|---|
| **−2** | 13 | **−16.63%** | **7.7%** |
| −1 | 11 | **+5.56%** | **72.7%** |
| 0 | 29 | −5.26% | 37.9% |
| +1 | 9 | −6.19% | 22.2% |
| +2 | 7 | −2.93% | 57.1% |

```
-2:  MSS-46  FABC-37  SSTK-27  NUWE-25  SSTK-17  TYGO-16  ZSQR-14  EZRA-14
     NMAD-12  VRRM-6  FRMM-5  SSTK-2  CABO+5
```

**Twelve of thirteen strong-negative calls lost, mean −16.6%.** Serial reverse
splits, a 3.4×-dilution option pool, a collapsed merger, a CEO walking out after
it, an exchange offer the issuer is threatening to abandon, insiders vesting
their own stock five weeks after granting it. That bucket has now held across
both windows and it is the only thing here that has.

**But the scale is bimodal, not monotone, which is why the veto fails.** Judged
−1 is the *best* bucket in the whole sample — +5.56% and 8 winners in 11. A
blanket "reject anything negative" throws those away, and in window B that cost
more than the −2 calls saved. Meanwhile the positive end is inverted: +1 returns
−6.19% and +2 returns −2.93%, both worse than "no information at all."

## Post-hoc, and labelled as such

Vetoing **only** the −2 calls, leaving −1 alone:

| | model k=1 | veto −2 only | delta |
|---|---|---|---|
| window A | +1.90% | +11.01% | +9.11pp |
| window B | −7.37% | −4.71% | +2.66pp |
| pooled | −4.15% | **+0.76%** | **+4.90pp** |

Positive in both windows. **This threshold was chosen after looking at the
bucket table**, on 13 events, so it is a hypothesis for a third window and not a
result. Recording it because it is the natural next test, not because it is
evidence.

## The company context did not help

Window B's bundles carried point-in-time market cap, public float, TTM revenue,
net income, cash, assets, valuation multiples, ADV, turnover, 20d/60d momentum,
distance from the 52-week high, realised volatility, the filing-day volume
against its own 20-day median, and the 8-K count in the prior 90 days — all
filtered on XBRL `filed` dates so nothing post-dates the entry. There is no news
or social feed here, so "how the company is seen" is proxied by turnover,
momentum and filing frequency; those are attention measures, not sentiment, and
calling them sentiment would overstate them.

It made the materiality question answerable — a $25M convertible is survival for
a $60M company and noise for a $6B one, and the filing never says which. Every
arm built on it lost anyway: veto + most material −9.18%, rank by judge ×
materiality −11.54%, positive **and** material −9.43%, against the plain veto's
−9.26%. Knowing how big the news is does not help when the sign is wrong.

## The emblematic miss

**PENG: record Q3, net sales $479M +48%, GAAP operating income +417%, non-GAAP
EPS +79%, full-year outlook raised on both lines. Judged +2. Returned −33.9%.**

The context block said why, and I read it and traded through it: the stock was
**+196% over 60 days** going into the print. The news was excellent and entirely
in the price. That is the whole failure of the positive end of the scale in one
name, and it is the same lesson as `RESULT_MOONSHOT_HUNT.md` — the model finds
names about to move, and neither it nor the reader can call the direction.

## Where this leaves the reading layer

One window suggested a reader was worth ~3pp. The next, with more information,
lost more than the control. The honest summary of 23 sessions is that reading
the filing changes nothing, with a single durable exception: **filings that are
plainly, structurally bad — dilution machinery, busted deals, forced financings
— are legible, and they fall.** Twelve of thirteen. Everything else in the
judgement, including everything positive, is noise.

The next test is the narrow one: veto on −2 only, on a third window, declared in
advance. Not the broad one.

## Reproducing

```
python3 scripts/llm_gate_pick.py --build --chars 3400                    # window A
python3 scripts/llm_gate_pick.py --build --chars 3400 --offset 15 \
        --out /root/.iai/wide2015/llm_gate_w2                            # window B, with context
#   ... read bundle_*.md, write labels.json ...
python3 scripts/llm_gate_pick.py --score .../labels.json [--clean]
python3 scripts/llm_gate_pick.py --score .../labels.json --out .../llm_gate_w2
```
