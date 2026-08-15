"""Ramanujan's partition and pi formulae, and the honest way to point them at a tape.

The request was to use the partition formula to predict fluctuation and
direction, and the pi formula to locate the tipping point. Taken literally that
cannot work, and it is worth being exact about why before building anything:
**p(n) and π are constants.** p(200) is 3,972,999,029,388 today, was that
yesterday, and will be that for AAPL, for a biotech, and for a stock that is
about to gap 40%. A number that does not vary with the input carries no
information about the input. Any apparent signal from keying trades to
partition congruences or to digits of π is numerology, and this repository has
spent long enough killing weaker claims than that.

But the intuition underneath is not silly, and it has a real home.

Why the word "partition" is the same word in both fields
--------------------------------------------------------
The generating function Ramanujan and Hardy worked with is

    sum_n p(n) q^n  =  prod_k 1 / (1 - q^k)

and that product is *exactly* the partition function of a gas of bosons with
energies 1, 2, 3, ... The name is not a coincidence and neither is the
mathematics. Statistical mechanics inherits from it a rigorous, non-mystical
notion of a **tipping point**: a phase transition, detected by the specific heat

    C(beta) = beta^2 ( <E^2> - <E>^2 )

diverging or peaking at a critical beta. Systems near criticality show large
susceptibility to small shocks -- which is a precise version of "the price is
about to shoot up or down from here".

So the construction below keeps the mathematics and drops the numerology:

1. **The Hardy-Ramanujan asymptotic supplies a scale.**
   log p(n) ~ pi * sqrt(2n/3) - log(4 n sqrt3). This is the entropy of the ways
   a total of n quanta can be split into parts. Applied to a move of n ATR
   units, it measures how many ways that move could have been assembled.
   **Note what this makes it: a strictly increasing function of n.** A
   gradient-boosted tree is invariant to monotone transforms of a single
   feature, so on its own this can add nothing to a model that already has
   volatility. That is a prediction, stated before the test, not an excuse
   after it.

2. **Restricted partitions add something the asymptotic does not.**
   p(n, k) -- partitions of n into at most k parts -- asks how many ways the
   move could have been distributed across k sessions. A move delivered in one
   gap is combinatorially rare; the same move ground out over twenty sessions is
   common. That ratio is *not* a function of magnitude alone.

3. **The statistical-mechanics partition function supplies the tipping point.**
   Built over the trailing return distribution rather than over integers, its
   specific heat peaks where the distribution is closest to bimodal -- where the
   name is poised between two regimes. This is the only part of the
   construction that is not a re-encoding of volatility, and so the only part
   with a real chance.

4. **Ramanujan's 1/pi series contributes a method, not a constant.**
   Its famous property is that it gains about eight digits per term. What
   transplants is the *idea*: estimate a limit from very few terms, and treat
   failure to converge as the signal. Shanks extrapolation on the recent path
   estimates where the price is heading; when successive extrapolants refuse to
   settle, the series is not converging and the level is not stable.

Everything here is then handed to the same walk-forward harness that every
other idea in this repository went through, and it is allowed to fail.
"""

from __future__ import annotations

from decimal import Decimal, getcontext
from functools import lru_cache
from math import exp, log, pi, sqrt

import numpy as np

# ---------------------------------------------------------------- the number theory


#: Cache of p(0..N), extended on demand. Filled bottom-up rather than by
#: recursion: the pentagonal recurrence reaches back to p(n - k(3k-1)/2) for
#: every k, so a recursive implementation is O(n) frames deep and dies with a
#: RecursionError somewhere past n = 500, which is well inside the range a
#: move-in-ATR-units can reach.
_P: list[int] = [1]


def _extend(n: int) -> None:
    while len(_P) <= n:
        m = len(_P)
        total, k = 0, 1
        while True:
            g1 = k * (3 * k - 1) // 2
            g2 = k * (3 * k + 1) // 2
            if g1 > m and g2 > m:
                break
            sign = -1 if k % 2 == 0 else 1
            if g1 <= m:
                total += sign * _P[m - g1]
            if g2 <= m:
                total += sign * _P[m - g2]
            k += 1
        _P.append(total)


def partitions(n: int) -> int:
    """p(n), exactly, by Euler's pentagonal number theorem.

    p(n) = sum_k (-1)^(k+1) [ p(n - k(3k-1)/2) + p(n - k(3k+1)/2) ]

    Exact arithmetic, because the point of having Ramanujan's asymptotic is to
    compare it against the truth rather than to assume it.
    """
    if n < 0:
        return 0
    _extend(n)
    return _P[n]


def hardy_ramanujan(n: int | float) -> float:
    """The 1918 asymptotic: p(n) ~ exp(pi sqrt(2n/3)) / (4 n sqrt 3)."""
    if n <= 0:
        return 1.0
    return exp(pi * sqrt(2.0 * n / 3.0)) / (4.0 * n * sqrt(3.0))


def log_hardy_ramanujan(n: float) -> float:
    """log of the above, which is the entropy and the only form worth using.

    p(500) already overflows a float; its logarithm is 55.9 and behaves.
    """
    if n <= 0:
        return 0.0
    return pi * sqrt(2.0 * n / 3.0) - log(4.0 * n * sqrt(3.0))


def restricted_partitions(n: int, k: int) -> int:
    """p(n, k): partitions of n into at most k parts.

    The recurrence is p(n,k) = p(n-k, k) + p(n, k-1), filled bottom-up. This is
    the piece that is not a function of magnitude alone -- it asks how the move
    was *distributed*, not only how big it was.
    """
    if n < 0 or k <= 0:
        return 0
    if n == 0:
        return 1
    tab = [1] + [0] * n
    for part in range(1, k + 1):
        for tot in range(part, n + 1):
            tab[tot] += tab[tot - part]
    return tab[n]


def ramanujan_pi(terms: int = 3) -> Decimal:
    """1/pi = (2 sqrt2 / 9801) sum_k (4k)! (1103 + 26390k) / ((k!)^4 396^(4k)).

    Ramanujan gave this in 1914 without proof; it was not proven until Borwein
    and Borwein in 1987. Each term adds roughly eight correct digits, which is
    the property being borrowed elsewhere in this module.
    """
    getcontext().prec = 60
    total = Decimal(0)
    for k in range(terms):
        num = Decimal(_factorial(4 * k)) * Decimal(1103 + 26390 * k)
        den = Decimal(_factorial(k)) ** 4 * Decimal(396) ** (4 * k)
        total += num / den
    inv = (Decimal(2) * Decimal(2).sqrt() / Decimal(9801)) * total
    return 1 / inv


@lru_cache(maxsize=None)
def _factorial(n: int) -> int:
    out = 1
    for i in range(2, n + 1):
        out *= i
    return out


def congruences(n: int) -> tuple[int, int, int]:
    """Ramanujan's three congruences, as residues.

    p(5n+4) = 0 mod 5, p(7n+5) = 0 mod 7, p(11n+6) = 0 mod 11. Included because
    they were asked for and because they are beautiful. They are *not* used as
    features: a residue class of an index carries no information about a price,
    and pretending otherwise is the exact failure mode this module exists to
    avoid.
    """
    p = partitions(n)
    return p % 5, p % 7, p % 11


# ------------------------------------------------------------------- the transplant


def shanks(seq: np.ndarray) -> float:
    """Shanks transform of the last three terms of a sequence.

    S(A) = (A2 A0 - A1^2) / (A2 - 2 A1 + A0). This is the same accelerated-
    convergence idea that makes Ramanujan's series useful from three terms: it
    estimates the limit of a sequence from its recent behaviour. Applied to a
    price path it estimates where the path is heading; a denominator near zero
    means the sequence is not converging, which is the interesting case.
    """
    if len(seq) < 3:
        return float("nan")
    a0, a1, a2 = seq[-3], seq[-2], seq[-1]
    den = a2 - 2.0 * a1 + a0
    if abs(den) < 1e-12:
        return float("nan")
    return float((a2 * a0 - a1 * a1) / den)


def rolling_moments(r: np.ndarray, tick: np.ndarray, window: int, beta: float):
    """Boltzmann-weighted mean and variance of trailing returns, per row.

    Z = sum exp(-beta r), <E> = sum r exp(-beta r) / Z, and the variance follows.
    Computed as three rolling sums so the whole panel costs one pass per beta
    rather than one pass per row.

    Ticker boundaries are respected by zeroing the accumulator whenever the
    symbol changes -- the same discipline the price walk needs, and for the same
    reason: the panel is one contiguous block and a window that runs off the end
    of one name lands in the next.
    """
    w = np.exp(-beta * np.clip(r, -1.0, 1.0))
    w = np.nan_to_num(w, nan=0.0, posinf=0.0, neginf=0.0)
    rr = np.nan_to_num(r, nan=0.0)
    a = _roll(w, tick, window)
    b = _roll(w * rr, tick, window)
    c = _roll(w * rr * rr, tick, window)
    z = np.where(a > 1e-12, a, np.nan)
    mean = b / z
    var = np.maximum(c / z - mean * mean, 0.0)
    return z, mean, var


def _roll(x: np.ndarray, tick: np.ndarray, window: int) -> np.ndarray:
    """Trailing sum over `window` rows, reset at every ticker boundary."""
    cs = np.concatenate([[0.0], np.cumsum(np.nan_to_num(x, nan=0.0))])
    n = len(x)
    idx = np.arange(n)
    # first row index of each ticker's block
    start = np.zeros(n, dtype=np.int64)
    change = np.flatnonzero(np.r_[True, tick[1:] != tick[:-1]])
    start[change] = change
    start = np.maximum.accumulate(start)
    lo = np.maximum(idx - window + 1, start)
    return cs[idx + 1] - cs[lo]


def self_test() -> None:
    """Show the formulae are implemented correctly, not merely invoked."""
    known = {1: 1, 5: 7, 10: 42, 50: 204226, 100: 190569292,
             200: 3972999029388}
    print("Euler pentagonal recurrence against known values of p(n):")
    for n, want in known.items():
        got = partitions(n)
        print(f"  p({n:>3d}) = {got:>16,}   {'OK' if got == want else 'WRONG'}")

    print("\nHardy-Ramanujan asymptotic against the exact value:")
    print(f"  {'n':>5s} {'exact':>18s} {'asymptotic':>18s} {'rel err':>9s}")
    for n in (10, 50, 100, 500, 1000):
        ex = partitions(n)
        ap = hardy_ramanujan(n)
        print(f"  {n:>5d} {ex:>18,} {ap:>18,.0f} {abs(ap - ex) / ex:>8.4%}")

    print("\nRamanujan's congruences (should be 0 in the marked column):")
    for n in range(4, 30, 7):
        r5, r7, r11 = congruences(n)
        mark5 = " <- p(5k+4)" if n % 5 == 4 else ""
        print(f"  p({n:>2d}) mod 5 = {r5}, mod 7 = {r7}, mod 11 = {r11}{mark5}")

    print("\nRamanujan's 1/pi series, ~8 digits a term:")
    true_pi = Decimal("3.14159265358979323846264338327950288419716939937510")
    for t in (1, 2, 3, 4):
        est = ramanujan_pi(t)
        err = abs(est - true_pi)
        digits = 0 if err == 0 else max(0, int(-err.log10()))
        print(f"  {t} term(s): {str(est)[:32]}   ~{digits} correct digits")

    print("\nRestricted partitions p(n, k) -- how a move of n splits over k sessions:")
    for n, k in ((20, 1), (20, 2), (20, 5), (20, 10), (20, 20)):
        print(f"  p({n}, at most {k:>2d} parts) = {restricted_partitions(n, k):>6,}")
    print("  (a move delivered in one jump is combinatorially rare; ground out")
    print("   over many sessions it is common -- that ratio is not magnitude)")


if __name__ == "__main__":
    self_test()
