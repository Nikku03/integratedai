# Pre-registration: does the twist propagate around the loop?

Committed before any event outside the original 118 is assembled or scored.

## The claim being tested

If a company is not a ticker but a loop — suppliers, customers, competitors, all
on one surface — then the pre-earnings reversal measured on one name should not
stop at that name's edge. Information sitting on the far arc should be visible in
the neighbours before it reaches the filer.

That is a real, falsifiable prediction, and it is the only thing the Möbius
framing has produced that the data has not already told us. It is tested here and
nowhere else; the analogy is not permitted to interpret the result afterwards.

## Three signals, one set of events

Every signal is measured to the **last close before acceptance** and predicts the
**overnight gap** into the first session that opens after.

**S1 — `own_run_z`.** The filer's own five-session return in units of its own
volatility. Run up → expect a gap down. This is the 61.9% effect, and re-running
it on a much larger sample is the single most important number this test
produces: the original was one 18-session window.

**S2 — `peer_run_z`.** The mean `run_z` of the filer's peers over the same
window, peers excluded of the filer itself. Tests whether the neighbours' price
paths carry information about the filer.

**S3 — `peer_gap`.** The mean signed gap of peers who **already reported** in the
ten sessions before the filer's entry. This is the actual loop test: news that
has already landed on a neighbouring arc, propagating to one that has not yet
turned into view.

**Peers** are the same four-digit SIC code, drawn from EDGAR company metadata,
restricted to the liquid universe, minimum five peers or the event is dropped.

## Registered directions

| signal | registered direction | basis |
|---|---|---|
| S1 | **reversal** — run up, gap down | the 61.9% measurement |
| S2 | **reversal** — peers ran up, filer gaps down | same mechanism, if it propagates |
| S3 | **momentum** — peers gapped up, filer gaps up | Foster (1981) information transfer: a common demand shock moves an industry together |

S3's direction is genuinely uncertain. Momentum is registered because the
information-transfer literature finds common-shock effects dominate share-shift
effects on average. **A significant result in the opposite direction is a
share-shift finding and will be reported as such, explicitly labelled as against
the registered direction**, not quietly re-described as a success.

## The test that actually matters for S2 and S3

Peers co-move with the filer by construction. A naive test would show `peer_run_z`
"predicting" the gap purely as a noisy copy of `own_run_z`, and that is not
propagation — it is correlation.

So the registered test is **incremental**: within quintiles of `own_run_z`, does
the peer signal still separate outcomes? Reported alongside a joint fit carrying
both. **If the peer signal adds nothing once the filer's own run is known, the
prediction is refuted** — the twist stops at the name's edge.

## Fixed now

* **Universe.** Close ≥ $5, trailing 60-session median dollar volume ≥ $20M as of
  the entry session — point-in-time, never full-sample.
* **Events.** 8-K item 2.02 only. Held across a bell; an intraday release is
  dropped, not approximated.
* **Signal gate.** |z| > 0.5, the same threshold as the original test.
* **Horizons.** The overnight gap is primary. The following session (`day_ret`)
  is reported because the original measured 49.2% there and it should stay near
  a coin flip.
* **Statistics.** Day-clustered bootstrap on every interval — events on one
  session share that session's tape. 3 signals × 2 horizons = **6 cells**;
  Bonferroni threshold **0.05 / 6 = 0.0083**, and the whole grid is published.
* **Costs.** Reported in the underlying, one crossing each way. Borrow cost on
  the short leg is **not** modelled and is named as the open hole, because most
  of these trades are shorts and nobody here has measured it.

## Hypotheses

**H1 — replication.** `own_run_z` clears 50% out of sample at the Bonferroni
threshold. *This is the one that decides whether anything here is real.* The
original 118 events were one window, one regime, one screen.

**H2 — the dollar edge.** The mean signed return per event clears zero on a
day-clustered interval. The original was +1.38% with [−0.59, +2.88] — direction
solid, profit unresolved. A larger sample either tightens it or kills it.

**H3 — propagation.** S2 or S3 carries information about the filer's gap
**beyond** what the filer's own run already says.

**H4 — the seam.** Every effect is far weaker on `day_ret` than on the gap. The
twist is at one place on the loop and cannot be harvested twice.

## What refutes the whole idea

If H1 fails, the 61.9% was a window artifact and everything downstream of it goes
with it — including the reason for running this test at all. That outcome is more
likely than it feels, and it is reported first whatever it says.

If H1 holds and H3 fails, the reversal is real and **local**. The loop picture is
then decoration, and this document is the record of it being tested and dropped.
