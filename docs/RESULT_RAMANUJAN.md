# Ramanujan's partition and pi formulae, applied and tested

The ask was to predict fluctuation and direction from the partition formula and
locate the tipping point with the pi formula. Both are implemented correctly and
both are tested against the panel. **All three pre-registered criteria fail**,
and one of them fails in a way that is worth more than a pass would have been.

## The mathematics, working

`scripts/ramanujan.py` implements the real objects, verified against known
values rather than asserted:

```
p(  1) =                1   OK        Hardy-Ramanujan vs exact:
p(  5) =                7   OK          n=10    err 14.53%
p( 50) =          204,226   OK          n=100   err  4.57%
p(100) =      190,569,292   OK          n=1000  err  1.42%
p(200) = 3,972,999,029,388  OK
```

Euler's pentagonal recurrence, the 1918 asymptotic
`p(n) ~ exp(π√(2n/3)) / (4n√3)`, restricted partitions `p(n,k)`, the three
congruences (`p(4)≡0 mod 5`, `p(11)≡0 mod 7`, `p(18)≡0` mod 5, 7 **and** 11),
and Ramanujan's 1914 series for 1/π:

```
1 term  : 3.141592730013305660  ~7 correct digits
2 terms : 3.141592653589793877  ~15 digits
3 terms : 3.141592653589793238  ~23 digits
4 terms : 3.141592653589793238  ~31 digits
```

Eight digits a term, exactly as advertised.

## Why a literal application cannot work, and what was built instead

p(n) and π are **constants**. p(200) is the same number today as yesterday, for
every ticker, including one about to gap 40%. A quantity that does not vary with
the input carries no information about the input, so trading on partition
congruences or digits of π is numerology.

The intuition underneath is not silly, and it has a real home. The generating
function Ramanujan worked with,

```
Σ p(n) qⁿ  =  Π 1/(1 − qᵏ)
```

is *exactly* the partition function of a boson gas. The word is the same word.
Statistical mechanics inherits from it a rigorous notion of a tipping point — a
phase transition, detected by the specific heat `C(β) = β²(⟨E²⟩ − ⟨E⟩²)` peaking
at a critical β, where a system becomes maximally susceptible to small shocks.
That is a precise version of "the price is about to shoot up or down from here".

So ten features were built:

| from | feature | idea |
|---|---|---|
| Hardy–Ramanujan | `ram_units`, `ram_hr_ent`, `ram_hr_err` | the trailing move in ATR quanta, and the entropy `log p(n) ≈ π√(2n/3)` of the ways it could have been assembled |
| restricted partitions | `ram_part_frac`, `ram_active_k` | `p(n,k)` — how the move was *distributed* over sessions, not just its size |
| statistical mechanics | `ram_c_max`, `ram_beta_crit`, `ram_c_ratio` | Boltzmann specific heat over the trailing return distribution; peaks where the name is poised between two regimes |
| Ramanujan's 1/π series | `ram_shanks_gap`, `ram_shanks_unstable` | the accelerated-convergence *method*: Shanks-extrapolate the path to its limit, and treat failure to converge as the signal |

## Where my prediction was wrong

I pre-registered that the partition features would be redundant with volatility,
because `log p(n) ≈ π√(2n/3)` is monotone in `n` and a tree is invariant to
monotone transforms. **That was wrong**, and the reason is worth keeping: `n` is
|move| divided by ATR, so volatility is in the *denominator* and largely cancels.

```
spearman(ram_units,      vol_20d) = +0.0712
spearman(ram_hr_ent,     vol_20d) = +0.0713
spearman(ram_part_frac,  vol_20d) = −0.0095
spearman(ram_c_ratio,    vol_20d) = +0.0106
spearman(ram_c_max,      vol_20d) = +0.8249
spearman(ram_shanks_gap, vol_20d) = +0.0013
```

Only `ram_c_max` is largely volatility. The rest are genuinely orthogonal to it —
so the features were not ruled out in advance, and the test was a real one. The
right conclusion was reached for the wrong reason, which is worth saying plainly.

## The three tests

**1. Separability — needed +0.010.**

| arm | AUC |
|---|---|
| price only | 0.5481 |
| + ramanujan | 0.5492 |
| ramanujan only | 0.5278 |

**+0.0011. FAIL.** And the ramanujan-only arm lands at 0.5278 — the same 0.53
that every exhausted feature set in this repository lands at.

**2. Ranking — needed +0.25pp, walk-forward, 14 blocks.**

```
price only   +1.005% per trade
+ ramanujan  +0.624%
delta        −0.381pp   95% CI [−1.548, +0.789]   P(≤0) = 0.7382
```

**FAIL**, and negative. Adding ten columns of number theory made the book worse,
within noise.

**3. Tipping point — the one that matters.**

Can any criticality measure beat plain volatility at flagging which names will
move 20% or more in the next ten sessions? 5.90% of candidates do.

| measure | AUC |
|---|---|
| **`vol_20d` (baseline)** | **0.8148** |
| `ram_c_max` | 0.7873 |
| `ram_c_ratio` | 0.5587 |
| `ram_hr_ent` | 0.5557 |
| `ram_part_frac` | 0.5098 |
| `ram_shanks_gap` | 0.5033 |

**FAIL, decisively.** The best Ramanujan-derived measure is *worse* than a
twenty-day standard deviation, and the theoretically best-motivated one — the
Boltzmann specific heat — is 82% correlated with volatility anyway, so it is
just a noisier version of it. The Shanks extrapolation, the direct transplant of
the π series, is a coin flip at 0.5033.

## The finding that is actually useful

Look again at that table, at the baseline rather than the challengers.

**Plain twenty-day volatility hits AUC 0.8148 at predicting which stocks will
move 20% or more.** That is not a weak number — it is the strongest single
predictor anywhere in this project, and it says the tipping point was never the
hard part. Knowing *that* a stock is about to move violently is close to solved
with one line of arithmetic.

What has never worked, across five independent attempts, is knowing **which
direction**. `RESULT_WHY_NO_UP.md`, `RESULT_DIRECTIONAL.md` and the ADRNN
direction head all landed at chance. And `RESULT_WHY_LOSERS.md` explains why the
strategy still profits: it selects *convexity*, not accuracy — fat tails in both
directions — landing at the 47th percentile of outcomes while beating random on
return.

So the search for a better tipping-point detector is a search for something we
already have. The open problem is direction, and no amount of number theory
touches it, because the information required is not in the price path.

## Reproducing

```
python3 scripts/ramanujan.py        # the formulae, self-verified
python3 scripts/ramanujan_test.py   # the three pre-registered tests, ~20 min
```
