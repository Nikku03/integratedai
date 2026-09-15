# Result: the twist is real, smaller than measured, and does not propagate

Pre-registered in `docs/PREREG_LOOP.md`. Built with `loop_events.py`,
`loop_features.py`, `loop_screen.py`, `loop_report.py`.

**8,091 scheduled earnings releases** over 293 sessions and 1,802 names,
2025-06-16 → 2026-09-10 — 69× the original 118 events.

## Pipeline validation first

Against the original 187 events: **gap correlation 1.0000, maximum absolute
difference 0.00000**; `run_z` correlation 0.9933. The larger pipeline reproduces
the smaller one exactly. Any disagreement below is about the data, not the code.

## H1 — replication: fails as registered, survives in one half of the screen

| universe | accuracy | n | P |
|---|---|---|---|
| **broad, as registered** | **50.68%** | 4,917 | 0.35 |
| original's screen, out of sample | 55.28% | 445 | 0.029 |
| **P/S ≥ 8 alone, out of sample** | **55.49%** | 656 | **0.0055** |
| market-cap band alone, out of sample | 50.66% | 2,651 | 0.51 |

The registered hypothesis **fails**: on the broad universe the reversal is
chance, and it is chance on 4,917 events, which is not a power problem.

But the effect is not gone — it is **conditional, and on the half of the screen
nobody singled out**. The market-cap band ($300M–$20B) does nothing at all:
50.66% on 2,651 events. Price-to-sales ≥ 8× carries the entire result and clears
the Bonferroni threshold on its own.

Run the same 20 sessions as the original both ways and the point is stark:
**50.83% unscreened (840 events) against 61.86% screened (118).**

**The shrinkage is real.** 61.9% in the discovery window → **55.5%** out of
sample. Roughly half the apparent edge was the window.

## H2 — the dollar edge: still does not clear zero

| | edge per event | day-clustered 95% CI |
|---|---|---|
| original claim | +1.376% | [−0.59, +2.88] |
| P/S ≥ 8, out of sample | +0.515% | **[−0.16, +1.20]** |

The sign is significant (P = 0.0055). The **money is not.** That was the open
question in the audit and it remains open, now at a third of the original
magnitude with a tighter interval that still contains zero.

## H3 — propagation: refuted

The Möbius prediction was that the twist should not stop at the filer's edge.
Tested where the twist actually exists — P/S ≥ 8, out of sample:

| signal | accuracy | n | P |
|---|---|---|---|
| the filer's own run | 55.32% | 649 | 0.0076 |
| peers' drift | 52.22% | 540 | 0.32 |
| peers who already reported | 51.31% | 267 | 0.71 |
| peers' drift, residualised on the filer's own | **51.97%** | 533 | 0.39 |
| peers' gaps, residualised on the filer's own | **51.12%** | 268 | 0.76 |

Peer drift correlates +0.583 with the filer's own — so the neighbours look
informative until you remove what the filer already told you, and then there is
nothing left. Neighbours who had **already reported** carry less still.

**The twist is local.** It exists at the name and stops there. The loop picture
predicted otherwise, was tested, and was wrong.

## H4 — the seam: holds

Every signal sits at chance on the session after the gap: 49.89%, 49.71%, 46.50%.
Whatever exists, exists in one overnight print.

## The remnant, and why it is hard to bank

Among the events that survive, **57% are shorts** — and the short arm is the weak
one:

| arm | mean edge |
|---|---|
| long (ran down → buy) | **+1.138%** |
| short (ran up → sell) | +0.327% |

The majority of the trades sit in the arm with a third of the edge **and** the
arm that pays borrow, which is still unmeasured. The long arm is stronger and
free of that cost, but this is a two-cell post-hoc split and should be treated as
a lead, not a result.

## Multiple comparisons, stated plainly

The cap × P/S grid contains eleven populated cells running from 41.9% to 64.4%.
That spread is what noise plus one modest real effect looks like, and the
best-looking cell (64.4% on n=45) should be ignored. The **P/S ≥ 8** result is
quoted because it is half of a screen fixed before this test, not the best cell
found in it. Even so, decomposing that screen after the fact is a post-hoc step,
and 55.5% is the honest number rather than anything larger.

## Where this leaves the project

* **Withdrawn:** the reversal as a general property of scheduled earnings. On the
  broad universe it is 50.7% on 4,917 events.
* **Withdrawn:** the market-cap band as any part of the mechanism.
* **Withdrawn:** the loop/propagation prediction, on its own pre-registered test.
* **Surviving, weakened:** a reversal in **expensive** stocks — P/S ≥ 8 — at
  55.5%, P = 0.0055, out of sample on 656 events. Direction real; dollars not yet.
* **Still unmeasured:** borrow cost on the short arm, which carries the majority
  of the trades and the minority of the edge.

The honest summary is that two years of data cut the headline roughly in half,
moved the mechanism from company size to valuation, and refuted the one new
prediction the framing generated.
