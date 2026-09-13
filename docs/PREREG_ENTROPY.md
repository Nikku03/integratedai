# Pre-registration: price-path entropy as a tradeable state

Committed before any entropy number is computed on any price series. Two years of
daily bars were still downloading when this was written.

## The idea, and the one way it can be trivially wrong

Treat a stock's recent price path as a thermodynamic state. **Entropy** is how
disordered that path is; **information** — earnings, volume shocks, the ambient
market regime — is the matter that perturbs it. A state far below its normal
entropy is improbable and unstable, and should relax toward disorder. A state
above normal entropy is already at equilibrium and carries no exploitable
structure.

The measure is **permutation entropy** (Bandt & Pompe, 2002). For embedding
dimension `m`, every window of `m` consecutive returns is replaced by the *rank
ordering* of its values — one of `m!` symbols — and PE is the Shannon entropy of
that symbol histogram, normalised by `log(m!)` so it lands in [0, 1].

The reason for choosing it over any binned-return entropy is a single property:
**it is ordinal, so it is invariant to every monotonic transform of the series.**
Doubling every return leaves PE unchanged. Volatility triples. PE therefore
measures something volatility mathematically cannot.

That is the theory. The trivial way for this to be worthless is that PE and
volatility, while distinct in principle, move together in real price data — in
which case this repository would be re-testing a volatility signal under a new
name. So that is **gate one**, run before any return is looked at, and it can
kill the study on its own.

## Fixed parameters — set now, not after

| parameter | value | why this one |
|---|---|---|
| embedding dimension `m` | **3** | 6 patterns over a 60-day window is ~10 observations per symbol; `m=4` gives 24 patterns and a sparse histogram |
| entropy window `W` | **60 sessions** | one quarter |
| normalisation window | **252 sessions** | one year, for the z-score |
| ties | broken by index order | the standard Bandt-Pompe convention |
| horizons | **1, 5, 20 sessions** forward | all three reported, none chosen after |
| universe | close ≥ $5, 60-day median dollar volume ≥ $20M | the same liquidity bar as the rest of this repo |
| cost | **5 bp round trip** in the underlying | one crossing, not four — the reason for working in the underlying at all |

`m = 4` and `m = 5`, and `W = 20` and `W = 120`, will be reported as a robustness
grid. They are **robustness, not candidates**: `m = 3, W = 60` is the registered
specification and stays the headline whatever the grid says.

## The state

Two numbers per name per session, both computed only from data strictly at or
before that session's close.

**`pe_z`** — permutation entropy over the last 60 daily returns, minus that
name's own mean PE over the prior 252 sessions, divided by its own standard
deviation. Above normal entropy is positive; below normal is negative.

**`ord_drift`** — among the same windows, the fraction that are monotonically
increasing minus the fraction monotonically decreasing. Also ordinal, also
scale-free. It says *which* ordered state a low-entropy name is in: trending, or
oscillating. Entropy alone cannot distinguish a steady climb from a steady fall.

**The matter** — three perturbing quantities, each a z-score on its own history:
volume (`vol_z`), realised volatility (`rv_z`), and the ambient market entropy
(`mkt_pe_z`, computed on an equal-weighted index of the universe). Plus a binary
flag for an 8-K filed inside the window, reusing the EDGAR pipeline already here.

## Hypotheses

**H0 — orthogonality. The gate.** Cross-sectional |corr(`pe_z`, `rv_z`)| < 0.7,
and the entropy effect in H1 survives a double sort within volatility quintiles.
**If H0 fails the study stops and is reported as failed.** A signal that
disappears inside volatility buckets is volatility.

**H1 — the state predicts.** Forward returns differ across `pe_z` deciles by more
than day-clustered sampling error, at one or more of the three horizons.

**H2 — direction comes from the ordering.** Within the low-entropy tail, sorting
on `ord_drift` separates continuation from reversal. Entropy says *how much* is
coming; the ordering says *which way*.

**H3 — it survives friction.** The decile long-short clears 5 bp round trip. This
is the test every options structure in this repository failed, and it is the
reason for moving to the underlying: one crossing at basis points, not four
crossings at 5% of a premium.

**H4 — learned beats hand-made, or it does not.** A neural network on the full
feature set, trained strictly walk-forward, is compared against two baselines:
volatility features alone, and the H1 decile rule. **If the entropy features do
not beat the volatility-only baseline out of sample, the answer is that they
carry nothing, and that is the finding.**

## Discipline

* **No lookahead.** Every feature at session `t` uses returns through `t` only;
  every label is `t+1` onward. Point-in-time, as with the filings work.
* **Walk-forward only.** Train on months 1..k, test on k+1, roll forward. No
  shuffled split — a shuffled split on overlapping windows leaks by construction
  and would manufacture any result asked of it.
* **Day-clustered bootstrap** for every interval. Names on one session share that
  session's market move, and treating them as independent understates the error
  by a factor of several.
* **Costs from the start**, not added at the end after a number looks good.
* **The grid is reported whole.** Every `(m, W, horizon)` cell gets published,
  not the best one. Fifteen cells at 5% will hand back a "discovery" by
  construction; the registered cell is the test and the rest is context.

## What would make this different from everything before it

Every prior test in this repository priced a *view about an event* through an
options contract, and each one died on the same arithmetic: the premium was set
at the level that pays for the accuracy available against it, and four crossings
consumed what was left. This tests a *state of the price path itself*, expressed
in the underlying, where friction is basis points. If it fails, it should fail
for a new reason. If it fails for the old reason — an edge smaller than the
friction — that is worth knowing too, because it would say the friction was never
the binding constraint.
