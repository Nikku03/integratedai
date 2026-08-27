# Pre-registration: window D, everything learned, tested forward

Committed **before** `--build` runs on window D and before any outcome for it is
computed. The git timestamp is the evidence.

## Window

Offset 45: **2026-05-14 → 2026-06-04**. No overlap with A (07-21→08-10),
B (06-29→07-20) or C (06-05→06-26). No result document reports outcomes for it.

**Caveat, stated in advance.** The reader's knowledge cutoff is May 2026, so
this window brushes it in a way A, B and C did not. Labels resolve ten sessions
forward, into June, but the mid-May filings themselves may be recallable. Window
D is therefore weaker evidence than C on the reading arms specifically. The
model arms are unaffected — the ranker has no knowledge cutoff.

## What changed, and why each change is entitled to be here

Every item below was measured on ~160,000 gated rows across fifteen
walk-forward blocks, not on the live windows.

| change | evidence | source |
|---|---|---|
| context columns in the ranker | k=1 −1.30% → +0.75%, 8/15 blocks | `RESULT_LOSS_AUTOPSY.md` §1 |
| pre-filing columns in the ranker | independent of the filing-day move (corr −0.005) | `RESULT_PREFILING_RUNUP.md` |
| **objective: log(1+r), not q75** | mean +0.75% → +1.53%, drag −1.77% → −0.82% | `RESULT_LOSS_AUTOPSY.md` §5 |
| **drop the top volatility quintile** | drag −1.77% → −0.75%, sd 23.1% → 17.0% | `RESULT_LOSS_AUTOPSY.md` §4 |
| **book at k=5, not k=1** | log+calm at k=5 is the best measured: drag −0.33% | `RESULT_LOSS_AUTOPSY.md` §6 |

Deliberately **not** changed: `--surprise-only` stays off. It adds +0.20pp to
the pool and costs 1.2pp at k=1 (`RESULT_PREFILING_RUNUP.md` §6).

## Hypotheses

1. **Primary.** The learned book — log objective, calm screen, k=5 — has a
   higher **mean log(1+r)** per trade than the incumbent q75 k=1 control on the
   same window. Predicted direction only: the panel says −0.33% against −1.77%,
   so the prediction is **less negative, not positive**. Claiming it will make
   money would not be supported by anything measured.
2. **Secondary.** The learned book's median trade beats the incumbent's. The
   panel gap is −0.25% against −1.76%.
3. **Fourth test of the veto.** `veto −2 only` beats its own control. It has now
   won in A, B and C; C was its first pre-registered win and rested on a single
   swap.
4. **Expected to fail.** The reader's directional judgement is worthless.
   Pooled over three windows the Spearman correlation is +0.061 and the
   positive-minus-negative spread is −0.10pp. Recorded so that confirming it is
   not presented as a discovery.

## Rules fixed in advance

* All 45 shortlist filings judged on direction (−2…+2) and materiality (0…3)
  from the filing and context block only, before `--score` runs.
* Costs 20bp, horizon 10 sessions, exactly as in A, B and C.
* The book arms (k=1/3/5) come from `book.parquet`, written at build time and
  requiring no reading, so they cannot be influenced by the judgements.
* Fifteen sessions cannot establish an effect. A win here means the
  configuration survives to a fifth window; it does not mean it works.
