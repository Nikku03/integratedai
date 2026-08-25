# The catalyst as gate, tested live

Making the catalyst a **gate** rather than one feature among 108 is the change
that worked. This records what it is worth historically, and what fifteen
sessions of unseen 2026 data say about it.

## Historically: the gate helps, the basket does not

Walk-forward over fourteen six-month blocks, ranking the daily top pick:

| | per trade |
|---|---|
| ungated pool | +1.695% |
| any 8-K ≤1 session | +1.088% |
| **any 8-K ≤3 sessions** | **+2.197%** |

**+0.5pp from restricting the universe** and ranking inside it. But the base
rates say something different about *owning* catalyst names:

| gate | names/session | P(\|move\|≥20%) | lift | buy-all return |
|---|---|---|---|---|
| ungated | 415 | 5.90% | — | +0.26% |
| any 8-K ≤3 | 55 | 7.10% | 1.20× | **+0.11%** |
| news 8.01/7.01 ≤3 | 28 | 7.67% | 1.30× | −0.02% |
| M&A 1.01/2.01 ≤3 | 9 | 9.63% | 1.63× | −0.23% |
| 13D activist ≤20 | 3 | 11.88% | 2.01× | +0.18% |
| **dilution 3.02 ≤3** | 2 | **20.81%** | **3.53×** | **−2.11%** |
| **cluster insider buy ≤20** | 6 | 7.24% | 1.23× | **+0.64%** |
| earnings 2.02 ≤3 | 9 | 5.45% | **0.92×** | +0.34% |
| 8-K ≤3, **excluding 3.02** | 50 | 6.00% | **1.02×** | +0.27% |

Three things fall out, and the third matters most.

**A catalyst raises the odds of a large move** — up to 3.5×. Earnings are the
exception at 0.92×: reporting results makes a stock *less* likely to move
violently than a random day.

**The strongest catalyst is a negative one.** Item 3.02, an unregistered share
issuance, is the sharpest volatility predictor anywhere in this repository at
3.53×, and has the worst return at −2.11%. It reliably produces a big move
*down*.

**Almost all the lift is that.** Excluding 3.02 collapses the 8-K effect from
1.20× to **1.02×** — indistinguishable from a random day. On this panel,
"catalysts cause big moves" is largely "dilution causes big moves down".

The only gate improving both odds and return is **cluster insider buying**:
1.23× at +0.64% against +0.26% ungated.

## Live: 2026-07-21 to 2026-08-10, unseen

The gate is rebuilt from EDGAR for **both** periods rather than reusing the
panel's columns before 2026 and something else after — 250,352 8-K filings from
the quarterly `form.idx`, mapped through the SEC's ticker file, indexed to
2026-08-24. A filing dated D is usable from session **D+1**, because 8-Ks are
routinely accepted after the close.

The ranker uses only what exists in both periods: the REM diffusion block and the
post-filing surge block, both computable from OHLCV. Trained on 158,282 gated
rows before 2026-06-17.

| arm | n | mean | vs universe | 95% CI (day-clustered) | P(≤0) |
|---|---|---|---|---|---|
| universe (control) | 13,588 | +2.30% | — | | |
| **gate basket (all gated)** | 1,800 | **+1.03%** | **−0.97pp** | **[−1.49, −0.42]** | 1.000 |
| gate + rank, k=1 | 15 | +4.04% | +1.74pp | [−10.81, +15.11] | 0.408 |
| ungated + rank, k=1 | 15 | +19.61% | +17.32pp | [−4.47, +53.68] | 0.147 |
| **gate + rank, k=5** | 75 | **+4.40%** | **+2.11pp** | [−3.04, +8.03] | 0.232 |
| ungated + rank, k=5 | 75 | +2.22% | −0.07pp | [−6.82, +8.15] | 0.538 |

**The only statistically significant result is negative.** The catalyst basket
underperformed the universe by 0.97pp with an interval clear of zero. Owning
catalyst names is worse than owning everything — which replicates the historical
buy-all figures exactly, and is the one thing fifteen sessions had enough power
to detect, because it averages 1,800 positions rather than 75.

**Everything positive is inside the noise.** Gate + rank at k=5 beat the universe
by +2.11pp and beat ungated ranking at the same k by +2.18pp, in the same
direction as the historical +0.5pp. But the interval runs from −3.04 to +8.03,
and at k=1 the ordering reverses entirely — ungated ranking returns +19.61%
against the gate's +4.04%, on one or two lucky names.

That k=1/k=5 disagreement is the same instability as the REM live test, and it
means the same thing: **fifteen sessions cannot resolve an effect of this size.**
What the window does show is that the live structure matches the historical
structure — basket bad, ranked-inside-gate good — which is weak corroboration
rather than confirmation.

Gated picks, five a session:

```
2026-07-21   -6.37%   PENG+3%  OTLK-32%  LEDS-16%  RXST+19%  FRMM-6%
2026-07-23  +12.73%   LWLG+14%  FWRD+16%  ASPI+1%  AMC+13%  STIM+20%
2026-07-29  +16.67%   USAR+34%  LPTH+38%  ONDS+39%  CDXS+7%  LMB-35%
2026-07-31  +39.19%   VENU-4%  PSIX+47%  AMIX+123%  OKLO+14%  APLD+16%
2026-08-05   +6.90%   VENU-15%  LUNR+35%  PHAT+11%  ALMU-5%  NMAD+9%
2026-08-10   -4.87%   UWMC+2%  VPG+1%  ATOM-18%  EBS+16%  APPS-25%
```

## What the gate is and is not

It is **a filter that makes ranking work better**, not a source of return on its
own. Restricting to 105 catalyst names a session out of 906 eligible gives the
model a pool where its ordering means more — and simultaneously a pool whose
average member is *worse* than the market. Both are true and they are not in
tension: the gate concentrates dispersion, and dispersion is what a ranker
monetises and a basket suffers.

## Reproducing

```
python3 scripts/catalyst_driver.py     # gate base rates and per-gate ranking
python3 scripts/gate_live_test.py      # the live test, rebuilds the gate from EDGAR
```
