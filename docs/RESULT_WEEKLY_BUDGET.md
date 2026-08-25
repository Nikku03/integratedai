# Three trades a week — and a correction to the previous result

## First, the correction

Last time I reported the live gate test I wrote that it "matches the historical
structure — basket bad, ranked-inside-gate good." **That was wrong**, and this
run is what showed it.

The +2.197% per trade for ranking inside the catalyst gate came from
`catalyst_driver.py`, which ranks using the panel's **108 features** —
fundamentals, insider activity, government contracts, filing counts. The live
test could not use any of those, because they do not exist for 2026 without a
refetch, so it ranked on the **REM diffusion and post-filing surge blocks only**:
23 price-derived columns.

Run the *same* feature set historically and it does not produce +2.197%. It
produces this:

| rule | trades | per trade | vs universe |
|---|---|---|---|
| universe | 124,554 | −0.041% | — |
| weekly 3, causal | 545 | **−0.869%** | −0.828pp |
| weekly 3, look-ahead | 1,038 | −0.702% | −0.661pp |
| daily k=1 | 1,636 | **−1.714%** | −1.673pp |
| daily k=3 | 4,908 | −1.344% | −1.302pp |

Thirteen walk-forward blocks, ~7 years. **Every rule loses to simply owning the
eligible universe.** So the live window's +2.11pp was noise on a configuration
that historically loses 1.3pp — I had matched a live point estimate against a
historical number produced by a different model and called it corroboration. It
was not.

What stands: **gate + panel features works (+2.197%). Gate + price features alone
does not (−1.3%).** The gate is not what carried it; the panel's non-price
information was.

## What three-a-week actually does

Two versions, because "the week's best three" is not a strategy you can run — on
Monday you do not know whether Thursday will offer something better, so pooling
the week and keeping its top three uses the future to choose which days to trade.

* **Causal:** each session, trade any gated name clearing a bar set from the
  *training* score distribution, first come first served, three slots a week.
  Weeks often do not fill — 15 to 64 fills against a possible 81 per block.
* **Look-ahead:** pool the week, keep the top three. Reported only to price the
  cheat.

Two things come out of the comparison, and both are useful:

**Fewer, more selective trades is genuinely better.** Causal weekly-3 loses
0.869% per trade against daily k=1's 1.714% — an **+0.85pp improvement** across
545 versus 1,636 trades. Trading only when something clears a bar beats trading
every session, which is the first time in this project that a *restraint* rule
has helped rather than removed the tail.

**The look-ahead is worth about 0.17pp.** Causal −0.869% against look-ahead
−0.702%. Smaller than I expected — knowing which day of the week would offer the
best name is worth less than a fifth of a percentage point here. Worth knowing
before spending effort on timing.

Neither rescues a ranker that does not work. Selectivity improves a losing
strategy; it does not make it a winning one.

## The live window, and why it says nothing

2026-07-21 to 2026-08-10, four weeks:

| rule | n | mean | win | vs universe | 95% CI |
|---|---|---|---|---|---|
| universe | 13,588 | +2.30% | 56.9% | — | |
| **weekly 3, causal** | **3** | **+17.58%** | 33.3% | +28.04pp | [−7.18, +63.27] |
| weekly 3, look-ahead | 12 | −0.20% | 50.0% | −2.91pp | [−19.89, +12.65] |
| daily k=1 | 15 | +1.79% | 53.3% | −0.50pp | [−13.28, +13.21] |
| daily k=3 | 45 | +4.93% | 60.0% | +2.64pp | [−4.32, +9.81] |

The causal rule took **three trades in four weeks**, and one of them is the
entire result:

```
2026-07-28  AXTI   score +17.03   realised  +67.68%
2026-08-07  VRRM   score +15.94   realised   -5.59%
2026-08-07  ZSQR   score +15.14   realised   -8.75%
```

A 33% win rate and a +17.58% mean. That is one lottery ticket, not a result, and
the interval — −7.18 to +63.27 — says so. The look-ahead version, which had four
times as many trades to work with, returned −0.20%.

Three trades cannot be evaluated. This is the third live window in a row where
the point estimate moved by tens of percentage points on a change that should not
matter, and the honest reading of all three is the same: **fifteen sessions is
not a test.**

## What I would take from this

1. **The correction is the finding.** The catalyst gate's value depended on the
   panel's non-price features, and I attributed it to the gate. Anything built on
   price data alone — which is all a live 2026 test can currently use — loses.
2. **A weekly budget beats daily trading**, by +0.85pp per trade over 545 trades.
   That is a real, well-powered result and it is the one thing here worth keeping.
3. **The look-ahead in "best three of the week" is small**, ~0.17pp, so the
   causal implementation costs little and should always be preferred.
4. **To test any of this live properly**, the 2026 panel needs its non-price
   features rebuilt — fundamentals from SEC XBRL, insider Form 4, government
   contracts. That is a data job, not a modelling one, and it is now the blocker.

## Reproducing

```
python3 scripts/weekly_budget.py                  # both historical and live
python3 scripts/weekly_budget.py --per-week 5
```
