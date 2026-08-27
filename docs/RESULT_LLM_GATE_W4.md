# Window D: everything learned, tested forward

Pre-registered in `PREREG_LLM_GATE_W4.md`, committed before the build. Window
**2026-05-14 → 2026-06-04**, fifteen sessions, no overlap with A, B or C.

**Every pre-registered hypothesis about the model passed. Everything still lost
money.** Both halves matter.

## The headline

| arm | n | mean | median | win | sd | **compounds** | $40 → |
|---|---|---|---|---|---|---|---|
| *universe* | 5,924 | +0.63% | +0.53% | 52.6% | | −0.28% | |
| **incumbent** q75, k=1 | 15 | **−8.91%** | −5.94% | 26.7% | **31.0%** | **−17.64%** | **$2.18** |
| learned log+calm, k=1 | 15 | −5.78% | −8.41% | 33.3% | 14.9% | −6.99% | $13.48 |
| learned log+calm, k=3 | 45 | −4.06% | −6.39% | 28.9% | 15.5% | −5.16% | — |
| **learned log+calm, k=5** | 75 | **−2.43%** | **−1.79%** | **41.3%** | **13.5%** | **−3.29%** | **$26.55** |

## Against the pre-registration

**H1 (primary) — PASS.** The learned book's mean log(1+r) is **−0.0335** against
the incumbent's **−0.1941**. The registered prediction was explicitly *less
negative, not positive*, because that is what the panel measured (−0.33% against
−1.77%). Window D delivered −3.29% against −17.64%. The direction, the ordering
and the rough magnitude all came out as declared.

**H2 (secondary) — PASS.** Median −1.79% against −5.94%.

**H3 (fourth test of the veto) — PASS, 4 for 4.**

| | model k=1 | veto −2 only | delta |
|---|---|---|---|
| A | +1.90% | +11.01% | +9.11pp |
| B | −7.37% | −4.71% | +2.66pp |
| C | +4.05% | +7.16% | +3.11pp |
| **D** | −5.78% | **−3.92%** | **+1.86pp** |
| **pooled** | −2.29% | **+1.25%** | **+3.53pp** |

**H4 (reading is worthless) — did not hold this window.** Spearman +0.174,
judged-positive −3.02% against judged-negative −7.68%, a spread of **+4.66pp**
in the right direction. But pooled over 159 filings it is still nothing:

| window | n | spearman | spread |
|---|---|---|---|
| A (clean 8) | 24 | +0.355 | +9.51pp |
| B | 45 | −0.087 | −3.00pp |
| C | 45 | −0.027 | −4.26pp |
| D | 45 | +0.174 | +4.66pp |
| **pooled** | **159** | **+0.080** | **+1.04pp** |

Two windows right, two wrong, and the average of a coin. What *does* hold in all
four is the shape:

| judge | n | mean | win |
|---|---|---|---|
| **−2** | 22 | **−11.33%** | **18.2%** |
| **−1** | 25 | **+1.09%** | **52.0%** |
| 0 | 74 | −2.68% | 41.9% |
| **+1** | 24 | **−4.50%** | **20.8%** |
| +2 | 14 | −2.28% | 50.0% |

Strong-negative is bad, mildly-negative is the best bucket in the sample, and
the positive end is worthless — the same bimodal structure across 53 sessions.
Window D's three −2 calls were LRMR (authorised shares nearly doubled) −11%,
RKTO (a $13.5M shell renaming itself for a space-and-AI-chip story) −34%, and
KRMN (sponsors placing 14M shares above where the stock now trades) +1%.

## What actually changed the outcome

The volatility screen and the objective, not the reading. Standard deviation
falls from **31.0% to 13.5%** — less than half — and that is the whole
difference between $2.18 and $26.55 on a compounded stake. The k=5 book's worst
session was −14.19% against the incumbent's worst single trade of −34.4%.

Session by session, the learned k=5 book:

```
05-14  +0.49%  $40.19     05-27  -7.67%  $40.29
05-15  +5.65%  $42.46     05-28  -4.05%  $38.66
05-18  -5.25%  $40.23     05-29 -14.19%  $33.18
05-19  +3.72%  $41.73     06-01 -10.30%  $29.76
05-20 +17.47%  $49.02     06-02  -0.49%  $29.61
05-21  -5.37%  $46.39     06-03  -7.45%  $27.41
05-22  -5.86%  $43.67     06-04  -3.14%  $26.55
05-26  -0.06%  $43.64
```

Peak $49.02 on 05-20 (RCAT +67% inside a five-name basket), then eleven of the
last twelve sessions negative.

## The thing that has not changed

**The universe returned +0.63% and every arm lost.** The best configuration
this repository has produced, tested forward exactly as declared, still
underperformed buying everything by 3.1pp per trade — and the incumbent
underperformed it by 9.5pp. `RESULT_LOSS_AUTOPSY.md` predicted this precisely:
each fix halves the drag, none of them crosses zero, and the gate's own median
member loses.

Getting from −17.64% to −3.29% is real, measured, and was called in advance. It
is also still a book that shrinks.

## Caveat, registered in advance

Window D begins 2026-05-14, brushing the reader's May 2026 knowledge cutoff in a
way A, B and C did not. Labels resolve into June, but the mid-May filings may be
recallable, so **D's reading arms are weaker evidence than C's**. The model arms
are unaffected — a gradient-boosted ranker has no cutoff — and the model arms are
where this window's result lives.

## Reproducing

```
python3 scripts/llm_gate_pick.py --build --offset 45 --chars 3400 \
        --objective log --calm --out /root/.iai/wide2015/llm_gate_w4      # learned
python3 scripts/llm_gate_pick.py --build --offset 45 \
        --out /root/.iai/wide2015/llm_gate_w4ctl                          # incumbent
python3 scripts/llm_gate_pick.py --score .../labels.json --out .../llm_gate_w4
```
