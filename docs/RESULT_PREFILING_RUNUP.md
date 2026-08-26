# The pre-filing run-up: right about the pool, wrong about the book

**The proposal.** If the price jumps *before* a disclosure and no announcement
explains the jump, the information is either already out or the event is so
routine everyone expects it. Either way the filing is not news by the time it
can be traded. Avoid those.

Tested on **160,920 gated rows, 2018-01 → 2026-08**. The answer splits cleanly,
and not along the line the proposal drew.

## The measurement is genuinely new

`ctx_mom20` — the momentum feature already in the model — runs to the session
before **entry**, which on a D+1 gate already contains the filing day and its
reaction. It cannot separate "the market moved because it read the news" from
"the market moved before there was any news to read".

`prefiling_features` measures the twenty sessions ending the day **before the
filing exists**, plus `gap_prev`, the sessions since the issuer's previous 8-K.

```
corr(pre_run20, ctx_mom20)      +0.695     related but not the same thing
corr(pre_run20, filing_day_ret) -0.005     independent of the disclosure reaction
corr(pre_run20, ctx_volratio)   +0.001     independent of the volume surge test
```

## The run-up half is right — on the median, not the mean

| decile | run-up | mean | median | win |
|---|---|---|---|---|
| D1 | −25.5% | −0.34% | −0.88% | 46.9% |
| D5 | −0.5% | −0.13% | −0.07% | 49.4% |
| D8 | +9.0% | −0.17% | −0.29% | 48.0% |
| D9 | +15.2% | −0.04% | −0.38% | 47.9% |
| **D10** | **+34.0%** | −0.25% | **−1.48%** | **44.7%** |

D10−D1 on the mean is **+0.08pp** — nothing. But the *median* falls monotonically
across the top four deciles and the win rate with it. After a big pre-filing
run-up the typical trade is much worse; the mean hides it behind a fat right
tail. Given that `RESULT_LOSS_AUTOPSY.md` shows the book's problem is a negative
*geometric* mean, the median is the number that matters.

## The "nothing announced" half runs backwards

| cell | rows | mean | median | win | compounds |
|---|---|---|---|---|---|
| the whole gate | 160,920 | −0.09% | −0.20% | 48.5% | −0.92% |
| **ran up AND quiet** ← the proposal's target | 12,164 | −0.14% | −0.37% | 48.2% | −1.10% |
| ran up AND something announced | 20,854 | **−0.35%** | −0.73% | 46.4% | −1.81% |
| **flat AND quiet** | 53,828 | **+0.15%** | −0.04% | 49.7% | **−0.42%** |
| flat AND something announced | 74,074 | −0.18% | −0.25% | 48.3% | −0.99% |

Among names that ran up, the ones **with** a prior announcement did *worse*
(−0.35%) than the unexplained ones (−0.14%) — the opposite of the prediction.
As a veto the rule is worth **−0.06pp, 95% CI [−0.33, +0.24], P(no worse) =
0.347.** Nothing.

## The inverted form is the strongest filter in this repository

The same table makes the positive version the best cell in it: keep only names
that had **not** moved and had announced **nothing**, then filed. Maximum
surprise rather than minimum.

| kept set | rows | mean | median | win | compounds |
|---|---|---|---|---|---|
| everything | 160,920 | −0.09% | −0.20% | 48.5% | −0.92% |
| **flat and quiet** | 53,828 | **+0.15%** | −0.04% | 49.7% | **−0.42%** |
| **flat and quiet, no volume surge** | 41,406 | **+0.17%** | **+0.01%** | **50.1%** | **−0.37%** |

**+0.36pp against the rest, 95% CI [+0.19, +0.53], P(no better) = 0.000**,
day-clustered over 160,920 rows. It more than halves the compounding drag,
takes the median positive and the win rate across 50% — the first subset here
to do either.

## But it improves the pool and wrecks the pick

A book does not buy the average row. Ranking walk-forward *inside* each pool:

| arm | blocks | train rows | pool | **k=1 mean** | k=1 median | compounds |
|---|---|---|---|---|---|---|
| full gate | 15 | 88,672 | −0.01% | **+0.82%** | −2.28% | −1.72% |
| surprise-only | 15 | 28,974 | **+0.19%** | **−0.37%** | −2.42% | −1.98% |

The filter does exactly what the pool tables promised — **+0.20pp on the pool** —
and then the model's top pick goes from +0.82% to −0.37%. Two reasons, both
mechanical:

1. The training set drops from 88,672 rows to 28,974.
2. The ranker earns its +0.83pp over the pool by finding dispersion, and this
   filter removes precisely the wide names it feeds on.

This is `RESULT_CATALYST_GATE.md`'s finding in a mirror: *the gate concentrates
dispersion, which a ranker monetises and a basket suffers.* The surprise filter
**removes** dispersion — which a basket enjoys and a ranker suffers.

The live window agrees, for once. Window C k=1 with the filter on: **−2.92%
against +4.05%**, $40 → $19.98 against $56.89. Fifteen trades prove nothing
alone, but they point the same way as 160,920 rows, which is more than any other
live/panel pair in this work has managed.

## What shipped

* `prefiling_features` — `pre_run20`, `pre_run5`, `pre_volratio`, `gap_prev`,
  `filing_day_ret` — added to the ranker's inputs **always on**, so the model
  can use the information without being forced to obey a hard rule.
* `--surprise-only` on `llm_gate_pick.py`, implementing the hard filter,
  **off by default**, because it costs 1.2pp at k=1.

The rule is a good one for **owning a basket** of catalyst names and a bad one
for **picking one**. Which of those you are doing decides whether to switch it
on.

## Reproducing

```
python3 scripts/prefiling_runup.py
python3 scripts/llm_gate_pick.py --build --offset 30 --surprise-only --out ...
```
