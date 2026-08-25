"""The REM layer: a fast closed-form solver for the forward return distribution.

The universal REM idea is that a known piece of mathematics answers most of the
question cheaply, a shared representation is computed once and reused across
many queries, and a network is left to learn only the systematic error. This
module is the first two of those three.

What the known mathematics is here
----------------------------------
A price under geometric Brownian motion has log-returns

    log(S_T / S_0) ~ Normal(mu * T, sigma^2 * T)

which gives closed forms for everything this project asks of a forward window:
the expected return, any quantile, the probability of finishing up, and — via
the reflection principle — the probability of *touching* a barrier at any point
inside the window:

    P( max_{t<=T} X_t >= b )
        = Phi( (mu T - b) / (sigma sqrt T) )
        + exp(2 mu b / sigma^2) * Phi( (-b - mu T) / (sigma sqrt T) )

That last one matters because this project's labels are excursion-based. It is
exact for Brownian motion, it costs two normal CDF evaluations, and it is
*systematically wrong* for real equities in ways that are well known: returns
have fat tails, volatility clusters, and micro-caps gap overnight rather than
diffusing. Those errors are the residual the network is there to learn.

The shared representation
-------------------------
    Phi_S = ( mu_hat, sigma_hat )

is estimated once per (ticker, date) from the trailing window. Every query then
reuses it:

    Y^REM_j = R(Phi_S, q_j)   for q_j in {E[r], q25, q50, q75, q90,
                                          P(up), P(touch +20%), P(touch -20%), ...}

Ten answers, one estimation. That is the computational advantage the design is
built around, and here it is real: the volatility estimate is the expensive part
and it is amortised across every question asked of the same row.

What is deliberately left out
-----------------------------
Everything that makes the diffusion wrong. Gaps, skew, kurtosis, volume shocks,
filing events and liquidity all get handed to the network as ``F_local`` rather
than being smuggled into the solver, because the whole point is to measure what
the physics misses.
"""

from __future__ import annotations

import numpy as np

SQRT2 = np.sqrt(2.0)


def norm_cdf(x: np.ndarray) -> np.ndarray:
    """Standard normal CDF via the error function, vectorised."""
    from scipy.special import erf
    return 0.5 * (1.0 + erf(x / SQRT2))


def _roll_sum(x: np.ndarray, tick: np.ndarray, window: int) -> np.ndarray:
    """Trailing sum over `window` rows, reset at each ticker boundary."""
    cs = np.concatenate([[0.0], np.cumsum(np.nan_to_num(x, nan=0.0))])
    n = len(x)
    idx = np.arange(n)
    start = np.zeros(n, dtype=np.int64)
    change = np.flatnonzero(np.r_[True, tick[1:] != tick[:-1]])
    start[change] = change
    start = np.maximum.accumulate(start)
    lo = np.maximum(idx - window + 1, start)
    return cs[idx + 1] - cs[lo]


def _roll_count(tick: np.ndarray, window: int) -> np.ndarray:
    n = len(tick)
    idx = np.arange(n)
    start = np.zeros(n, dtype=np.int64)
    change = np.flatnonzero(np.r_[True, tick[1:] != tick[:-1]])
    start[change] = change
    start = np.maximum.accumulate(start)
    return (idx - np.maximum(idx - window + 1, start) + 1).astype(float)


def compile_shared(prices, window: int = 60, ewma_lam: float = 0.94):
    """``Phi_S`` — the per-row diffusion state, estimated once.

    Returns ``(mu, sigma)`` in log-return-per-session units. Volatility is the
    blend of a plain trailing estimate and an exponentially weighted one, which
    is the standard concession to volatility clustering and is still part of the
    *solver* rather than the correction: it is a better estimate of the same
    parameter, not an extra input.
    """
    c = prices["close"].to_numpy(float)
    tick = prices["ticker"].to_numpy()
    same = np.r_[False, tick[1:] == tick[:-1]]
    prev = np.r_[np.nan, c[:-1]]
    with np.errstate(divide="ignore", invalid="ignore"):
        lr = np.where(same & (prev > 0) & (c > 0), np.log(c / prev), np.nan)
    lr = np.clip(lr, -1.5, 1.5)

    n = _roll_count(tick, window)
    s1 = _roll_sum(lr, tick, window)
    s2 = _roll_sum(lr * lr, tick, window)
    mu = np.where(n > 5, s1 / n, 0.0)
    var = np.where(n > 5, np.maximum(s2 / n - mu * mu, 0.0), np.nan)

    # exponentially weighted variance, computed per ticker in one pass
    ew = np.full(len(lr), np.nan)
    acc = np.nan
    for i in range(len(lr)):
        if not same[i]:
            acc = np.nan
        v = lr[i]
        if np.isfinite(v):
            acc = v * v if not np.isfinite(acc) else ewma_lam * acc + (1 - ewma_lam) * v * v
        ew[i] = acc
    sig = np.sqrt(np.where(np.isfinite(ew), 0.5 * var + 0.5 * ew, var))
    sig = np.where(np.isfinite(sig) & (sig > 1e-5), sig, np.nan)
    return np.nan_to_num(mu, nan=0.0), sig


def touch_up(b: float, mu: np.ndarray, sig: np.ndarray, T: float) -> np.ndarray:
    """P(max of the log-path reaches +b within T) — the reflection principle."""
    s = sig * np.sqrt(T)
    a = norm_cdf((mu * T - b) / s)
    expo = np.clip(2.0 * mu * b / np.maximum(sig ** 2, 1e-10), -50, 50)
    return np.clip(a + np.exp(expo) * norm_cdf((-b - mu * T) / s), 0.0, 1.0)


def touch_dn(b: float, mu: np.ndarray, sig: np.ndarray, T: float) -> np.ndarray:
    """P(min of the log-path reaches -b within T), by symmetry."""
    return touch_up(b, -mu, sig, T)


#: The queries answered from one shared Phi_S. Adding a query costs two normal
#: CDFs; re-estimating sigma for each would cost a pass over the panel.
QUERIES = ("mu", "sigma", "exp_ret", "q10", "q25", "q50", "q75", "q90",
           "p_up", "p_touch_up20", "p_touch_dn20", "p_touch_up50",
           "z_up20", "z_dn20", "sig_h")


def infer(mu: np.ndarray, sig: np.ndarray, horizon: int = 10,
          barrier: float = 0.20):
    """``R(Phi_S, q)`` for every query — the fast approximate answers.

    ``Y_REM`` is the solver's best point answer to "what is the forward return",
    which under a lognormal is the median, ``q50``. Using ``q75`` here instead
    would hand the network a residual with a large systematic offset and make
    the comparison against a direct model unfair; every quantile is still in
    ``F_REM``, so nothing is lost.
    """
    T = float(horizon)
    sh = sig * np.sqrt(T)
    b = np.log1p(barrier)
    z = {"mu": mu, "sigma": sig, "sig_h": sh,
         "exp_ret": np.exp(mu * T + 0.5 * sh ** 2) - 1.0,
         "p_up": norm_cdf(mu * T / sh),
         "p_touch_up20": touch_up(b, mu, sig, T),
         "p_touch_dn20": touch_dn(b, mu, sig, T),
         "p_touch_up50": touch_up(np.log(1.5), mu, sig, T),
         "z_up20": (b - mu * T) / sh,
         "z_dn20": (-b - mu * T) / sh}
    for name, q in (("q10", -1.2816), ("q25", -0.6745), ("q50", 0.0),
                    ("q75", 0.6745), ("q90", 1.2816)):
        z[name] = np.exp(mu * T + q * sh) - 1.0
    F = np.column_stack([z[k] for k in QUERIES]).astype(np.float32)
    return z["q50"].astype(np.float32), F, list(QUERIES)


def local_features(prices, window: int = 60):
    """``F_local`` — the high-resolution structure the diffusion compressed away.

    Every column here is something a Gaussian diffusion cannot represent: the
    split between overnight gaps and intraday drift, the third and fourth
    moments, the largest single-session jump, volume shocks and the fraction of
    sessions that did not trade at all.
    """
    o = prices["open"].to_numpy(float)
    c = prices["close"].to_numpy(float)
    v = np.nan_to_num(prices["volume"].to_numpy(float), nan=0.0)
    tick = prices["ticker"].to_numpy()
    same = np.r_[False, tick[1:] == tick[:-1]]
    prev = np.r_[np.nan, c[:-1]]
    with np.errstate(divide="ignore", invalid="ignore"):
        lr = np.where(same & (prev > 0) & (c > 0), np.log(c / prev), np.nan)
        gap = np.where(same & (prev > 0) & (o > 0), np.log(o / prev), np.nan)
    lr = np.clip(lr, -1.5, 1.5)
    gap = np.clip(gap, -1.5, 1.5)

    n = _roll_count(tick, window)
    m1 = _roll_sum(lr, tick, window) / n
    m2 = _roll_sum((lr - 0.0) ** 2, tick, window) / n
    sd = np.sqrt(np.maximum(m2 - m1 * m1, 1e-12))
    zc = (lr - m1) / sd
    skew = _roll_sum(np.nan_to_num(zc ** 3, nan=0.0), tick, window) / n
    kurt = _roll_sum(np.nan_to_num(zc ** 4, nan=0.0), tick, window) / n
    gvar = _roll_sum(np.nan_to_num(gap ** 2, nan=0.0), tick, window) / n
    gap_share = np.where(m2 > 1e-12, gvar / m2, 0.0)
    jump = _roll_sum((np.abs(np.nan_to_num(lr, nan=0.0)) > 3.0 * sd).astype(float),
                     tick, window) / n
    dead = _roll_sum((v <= 0).astype(float), tick, window) / n
    vol_mu = _roll_sum(v, tick, window) / n
    vz = np.where(vol_mu > 0, v / vol_mu, 1.0)
    illiq = np.where(v > 0, np.abs(np.nan_to_num(lr, nan=0.0)) / np.log1p(v), 0.0)
    illiq = _roll_sum(illiq, tick, window) / n

    cols = {"loc_skew": skew, "loc_kurt": kurt, "loc_gap_share": gap_share,
            "loc_jump_rate": jump, "loc_dead_frac": dead,
            "loc_vol_z": np.clip(vz, 0, 50), "loc_illiq": illiq,
            "loc_last_lr": np.nan_to_num(lr, nan=0.0),
            "loc_last_gap": np.nan_to_num(gap, nan=0.0)}
    M = np.column_stack([np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
                         for x in cols.values()]).astype(np.float32)
    return M, list(cols)


def context_features(prices, sig: np.ndarray):
    """``F_context`` — what kind of environment this is, not what this name is."""
    import pandas as pd
    dt = pd.to_datetime(prices["date"].to_numpy())
    c = prices["close"].to_numpy(float)
    df = pd.DataFrame({"d": dt, "s": sig})
    med = df.groupby("d")["s"].transform("median").to_numpy()
    rank = df.groupby("d")["s"].rank(pct=True).to_numpy()
    cols = {"ctx_mkt_vol": np.nan_to_num(med, nan=0.0),
            "ctx_vol_rank": np.nan_to_num(rank, nan=0.5),
            "ctx_log_price": np.log10(np.maximum(c, 0.01)),
            "ctx_month": dt.month.to_numpy().astype(float),
            "ctx_year": (dt.year.to_numpy() - 2015).astype(float)}
    return np.column_stack(list(cols.values())).astype(np.float32), list(cols)


__all__ = ["QUERIES", "compile_shared", "context_features", "infer",
           "local_features", "norm_cdf", "touch_dn", "touch_up"]
