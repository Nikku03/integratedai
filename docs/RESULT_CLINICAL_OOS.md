# Result: the clinical-readout rule failed out of sample

Pre-registered in [`PREREGISTRATION_CLINICAL.md`](PREREGISTRATION_CLINICAL.md),
committed at `29d8fab` before the twelve-month result existed. Reported as
committed.

## Verdict

```
PRIMARY   mean/trade -2.20%   bootstrap 95% CI [-3.20%, -1.18%]
          required CI excluding zero on the POSITIVE side       -> FAIL
median    -1.12%                                                -> FAIL
quarters  2 of 5 positive                                       -> FAIL
POSITIVE beats SILENT   -2.20% vs -2.41%, Welch p=0.809         -> FAIL
sample    940 trades (>= 40 required)                           -> PASS

VERDICT: NO EDGE.
```

The July estimate was **+9.86%** per trade with a bootstrap CI of
**[+1.34%, +19.07%]** on **11 trades**. Twelve months and 940 trades give
**−2.20%** with a CI of **[−3.20%, −1.18%]**. Not shrinkage — sign reversal, with
both intervals excluding zero on opposite sides.

## The scan

**11,781 8-Ks** from biotech/pharma SIC filers, June 2025 – June 2026 →
**1,865 clinical readouts** with no toxic-financing signal → **1,540 tradable**.

| verdict | n | mean | median | win | best | worst |
|---|---|---|---|---|---|---|
| **POSITIVE** | 940 | **−2.20%** | −1.12% | 44% | +152% | −59% |
| SILENT | 403 | −2.41% | −1.43% | 42% | +66% | −50% |
| MIXED | 173 | −2.58% | −1.38% | 42% | +39% | −37% |
| **NEGATIVE** | 24 | **+1.77%** | +2.17% | 54% | +29% | −21% |

## The sentiment filter has no power at all

POSITIVE −2.20% against SILENT −2.41%: **Welch t = +0.24, p = 0.809.** The two
cohorts are indistinguishable. And the best-performing cohort is **NEGATIVE**
(+1.77%, n=24) — the readouts that say the trial *failed*.

This was the component most at risk, and it is the one that broke. The patterns
were written after seeing which eleven July names won; on 940 fresh observations
they carry nothing. **A bootstrap CI excluding zero did not save it, because the
bootstrap resamples the data and cannot resample the decision to write that
regex.**

## The "a winner cannot become a loser" property does not survive

On July minute bars, all 14 armed trades were profitable, worst +6.3%. Over twelve
months on daily bars:

| exit | n | mean | win | worst |
|---|---|---|---|---|
| trail | 545 | +4.84% | 63% | **−25.91%** |
| stall | 15 | +10.57% | 100% | +1.10% |
| time | 103 | +4.24% | 54% | −13.94% |
| **stop** | **277** | **−19.12%** | 0% | **−58.66%** |

**560 armed trades, 64% profitable, worst −25.9%.** The guarantee was an artifact
of minute bars: intraday the trail catches the dip on the way down, but a stock
that gaps through it overnight fills far below. The 277 initial stops average
−19.12% against a −15% level for the same reason.

## By quarter

| quarter | n | mean | win |
|---|---|---|---|
| 2025 Q2 | 56 | +0.51% | 54% |
| 2025 Q3 | 187 | +1.05% | 53% |
| 2025 Q4 | 213 | −1.46% | 49% |
| 2026 Q1 | 260 | −4.15% | 37% |
| 2026 Q2 | 224 | −4.02% | 38% |

Two positive quarters then three negative ones. Dropping the two largest winners
(CELC, OLMA) moves the mean from −2.20% to −2.49%, so it is not a tail artifact
either.

**$80, two slots, twelve months → $73.47 (−8.2%)**, before any transaction cost.

## What this establishes

**The July result was a false positive produced by post-hoc rule construction**,
and the pre-registration is the only reason that is now known rather than
believed. Eleven trades, a CI excluding zero, a plausible mechanism, and both
calendar halves positive — every check passed, and the rule still had no power.

**The mechanism argument was not enough.** "A positive readout re-prices a
biotech" is economically sound and was stated before the test. It is also, on 940
observations, wrong as a tradable proposition — most plausibly because the readout
is priced in the gap before the next open, which is where this entry sits.

**Three of the four cohorts lose about 2.2–2.6% and the fourth is 24 names.** The
spread across sentiment classes is smaller than the spread across quarters, which
is the signature of a classifier reading noise.

This closes the clinical-readout line. The pre-registered criteria were set in
advance, four of five failed, and the honest conclusion is that there is no edge
here to recover with a better exit or a better parser.
