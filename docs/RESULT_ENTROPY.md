# Result: the entropy study fails at the gate, and the gate was the wrong one

Pre-registered in `docs/PREREG_ENTROPY.md`. **No forward return was examined.**
The study stops where the pre-registration said it would stop, for a reason the
pre-registration did not anticipate.

Run with `scripts/entropy_gate.py` on 2,358 names × 350 sessions.

## What was registered, and what happened

The registered gate (H0) was: *is permutation entropy just volatility in a
costume?* Threshold |corr(pe_z, rv_z)| < 0.7.

**It passes. corr = +0.07** — ten times inside the threshold.

And the study is dead anyway, because H0 cannot ask the question that mattered.

## The measurement that kills it

PE over 60 returns at m=3 is a multinomial estimate: 58 ordinal patterns spread
over 6 bins, about 10 counts per bin. An estimator like that has a standard
deviation of its own. The null is each name's own returns permuted — preserving
its distribution and its exact ties, destroying only the ordering.

| m=3, W=60 | value |
|---|---|
| real cross-sectional sd of PE | 0.013509 |
| shuffle-null sd | 0.014024 |
| **ratio** | **0.963** |

The real cross-section of permutation entropy across 2,358 US equities is
**narrower than pure sampling noise.** There is no state to sort on. `pe_z` would
have been dividing noise by noise.

Two more, with realised volatility computed the identical way as a positive
control:

| | PE | realised vol |
|---|---|---|
| split-half reliability | **+0.009** | +0.792 |
| non-overlapping persistence | **−0.028** | +0.867 |

The control comes back at +0.79 and +0.87 on the same rows, same code, same
windows. So the diagnostics work. Permutation entropy at a 60-day window is
simply not a property of the name — it is a fresh draw of estimation error each
time it is computed.

## The lesson: I guarded against the wrong failure

H0 asked whether PE carries the *same* information as volatility. The real
question was whether it carries *any*. Those are different, and only one of them
can kill a study.

**A pure-noise feature passes an orthogonality test trivially.** Orthogonality is
evidence of no shared information; it is never evidence of orthogonal
information. The pre-registration called H0 "gate one … it can kill the study on
its own", and that was wrong: H0 is diagnostic, never confirmatory.

The gate that should have been registered — and is now, in code — is: *does the
estimator's dispersion exceed its own sampling noise, is it reliable within a
window, and is it persistent across windows?* All three run on features alone,
with no forward return in memory.

## The one thing that survives

Signal share of cross-sectional variance, by window:

| window | ratio to noise | signal share |
|---|---|---|
| W = 60 (registered) | 0.959 | **0.0%** |
| W = 120 | 0.973 | 0.0% |
| W = 250 | 1.141 | **23.2%** |

PE is not inherently empty. It is empty **at a 60-day window**, where the
estimator cannot resolve anything. At 250 sessions roughly a quarter of the
dispersion is real.

That is the honest surviving lead, and the data budget does not currently support
testing it. W=250 costs 251 sessions of burn-in; ten independent time blocks at a
20-day horizon need roughly 2,950 sessions — about twelve years. Polygon's free
tier caps at two. **Reporting this as untested rather than testing it badly.**

## A note on the published literature

Stratifying by exact-tie rate locates where PE's apparent signal actually lives:
the most tie-prone names in this universe are TFLO, GSY, BIL, MINT, SHV, BILS —
every one a par-pinned short-duration fixed-income ETF whose price repeats
exactly, and all of them clear the $5 / $20M liquidity bar.

PE at a short window is a **stale-price detector**. That is consistent with the
best-known finance result in this family — Zunino et al. (2010) separating
developed from emerging equity indices — and with its two subsequent replication
failures. Emerging and illiquid indices have discretised, repeating prices;
liquid US equities do not.

This is also the Corwin-Schultz degeneracy in a new costume: that estimator
failed earlier in this work because `high == low` on single-print bars. Here a
flat window encodes as PE = 0.0 — maximally confident and maximally wrong.

## Status

* The registered specification (m=3, W=60) is **closed**, at the gate, with no
  forward return examined.
* `scripts/entropy_gate.py` is kept: any future feature in this repository should
  clear it before a backtest is written, and it costs seconds to run.
* The long-window variant is **open and untested**, pending roughly a decade of
  daily history this session does not have.
