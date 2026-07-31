"""Within-window burn rank: does a relative measure survive the regime shift?

Runs the specification frozen in `docs/PREREGISTRATION_BURN_RANK.md`. Nothing here
is chosen after seeing a number.

The rank is deliberately trailing rather than within-calendar-month. Ranking a
readout against every readout of its own month would use peers that had not
happened yet; a 90-day trailing window uses only what existed. That costs the
first quarter of data to warm-up and is the difference between a causal statistic
and a backward-looking one.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

WINDOW_DAYS = 90
MIN_PEERS = 20
UP_THRESH, DN_THRESH = 0.50, -0.30


def trailing_rank(d: pd.DataFrame, col: str) -> pd.Series:
    """Percentile of ``col`` among rows in the preceding WINDOW_DAYS."""
    d = d.sort_values("et")
    t = d["et"].to_numpy()
    v = d[col].to_numpy(dtype=float)
    out = np.full(len(d), np.nan)
    win = np.timedelta64(WINDOW_DAYS, "D")
    for i in range(len(d)):
        if not np.isfinite(v[i]):
            continue
        m = (t >= t[i] - win) & (t < t[i]) & np.isfinite(v)
        peers = v[m]
        if len(peers) < MIN_PEERS:
            continue
        out[i] = float((peers < v[i]).mean())
    return pd.Series(out, index=d.index)


def spread(g: pd.DataFrame) -> float:
    """P(up) − P(down) for a cohort."""
    if not len(g):
        return np.nan
    return float(g.up.mean() - g.dn.mean())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    args = ap.parse_args(argv)
    root = Path(args.root)

    d = pd.read_parquet(root / "why_moonshot.parquet")
    d["et"] = pd.to_datetime(d["et"], utc=True)
    d["up"] = d.max_up >= UP_THRESH
    d["dn"] = d.max_dn <= DN_THRESH
    d = d[d.burn_annual.replace([np.inf, -np.inf], np.nan).notna()].copy()
    d = d.sort_values("et").reset_index(drop=True)

    d["burn_rank"] = trailing_rank(d, "burn_annual")
    r = d[d.burn_rank.notna()].copy()
    print(f"{len(d):,} readouts with burn; {len(r):,} ranked against >= "
          f"{MIN_PEERS} peers in a trailing {WINDOW_DAYS}-day window")
    if len(r) < 300:
        print("UNDERPOWERED: fewer than 300 ranked events")

    r["tercile"] = pd.cut(r.burn_rank, [-0.01, 1 / 3, 2 / 3, 1.01],
                          labels=["LOW", "MID", "HIGH"])
    print("\nTERCILES (trailing burn rank)")
    g = r.groupby("tercile", observed=True).agg(
        n=("up", "size"), p_up=("up", "mean"), p_dn=("dn", "mean"),
        med_burn=("burn_annual", "median"), med_cap=("market_cap", "median"))
    g["spread"] = (g.p_up - g.p_dn)
    g["p_up"] = (g.p_up * 100).round(1)
    g["p_dn"] = (g.p_dn * 100).round(1)
    g["spread"] = (g.spread * 100).round(1)
    g["med_burn"] = (g.med_burn / 1e6).round(1)
    g["med_cap"] = (g.med_cap / 1e6).round(0)
    print(g.to_string())

    hi, lo = r[r.tercile == "HIGH"], r[r.tercile == "LOW"]
    obs = spread(hi) - spread(lo)
    print(f"\nPRIMARY: HIGH-LOW spread = {obs * 100:+.2f}pp  "
          f"(HIGH {spread(hi) * 100:+.1f}pp, LOW {spread(lo) * 100:+.1f}pp)")

    rng = np.random.default_rng(7)
    hv = (hi.up.astype(int) - hi.dn.astype(int)).to_numpy()
    lv = (lo.up.astype(int) - lo.dn.astype(int)).to_numpy()
    boot = np.array([rng.choice(hv, len(hv), replace=True).mean()
                     - rng.choice(lv, len(lv), replace=True).mean()
                     for _ in range(20000)])
    ci = (np.percentile(boot, 2.5), np.percentile(boot, 97.5))
    print(f"  bootstrap 95% CI [{ci[0] * 100:+.2f}pp, {ci[1] * 100:+.2f}pp]   "
          f"P(spread<=0) = {(boot <= 0).mean():.4f}")
    t, p = stats.ttest_ind(hv, lv, equal_var=False)
    print(f"  Welch t={t:+.2f}  p={p:.4f}")
    primary = "PASS" if ci[0] > 0 else "FAIL"
    print(f"  PRIMARY -> {primary}")

    print("\nREGIME CRITERION: spread by quarter (needs >= 4 of 5 positive)")
    r["q"] = r.et.dt.to_period("Q")
    rows = []
    for q, sub in r.groupby("q"):
        h, l = sub[sub.tercile == "HIGH"], sub[sub.tercile == "LOW"]
        if len(h) < 10 or len(l) < 10:
            continue
        sp = spread(h) - spread(l)
        base = sub.up.mean() - sub.dn.mean()
        rows.append({"quarter": str(q), "n": len(sub), "HIGH": spread(h) * 100,
                     "LOW": spread(l) * 100, "spread": sp * 100,
                     "quarter_base": base * 100})
    qt = pd.DataFrame(rows).round(1)
    print(qt.to_string(index=False))
    npos = int((qt.spread > 0).sum())
    regime = "PASS" if npos >= 4 else "FAIL"
    print(f"  positive in {npos} of {len(qt)} quarters -> {regime}")

    if len(qt) > 2:
        rho, pv = stats.spearmanr(qt.quarter_base, qt.spread)
        print(f"  does the spread track the quarter's own base rate? "
              f"rho={rho:+.2f} p={pv:.3f}")

    print("\nSUPPORTING: monotone across terciles?")
    sp = [spread(r[r.tercile == c]) for c in ("LOW", "MID", "HIGH")]
    mono = sp[0] < sp[1] < sp[2]
    print(f"  LOW {sp[0] * 100:+.1f}pp  MID {sp[1] * 100:+.1f}pp  "
          f"HIGH {sp[2] * 100:+.1f}pp  -> {'PASS' if mono else 'FAIL'}")

    print("\nSUPPORTING: within market-cap terciles")
    r["capq"] = pd.qcut(np.log10(r.market_cap.clip(lower=1e6)), 3,
                        labels=["small", "mid", "large"])
    for cb, sub in r.groupby("capq", observed=True):
        h, l = sub[sub.tercile == "HIGH"], sub[sub.tercile == "LOW"]
        if len(h) < 15 or len(l) < 15:
            continue
        print(f"  {str(cb):6s} n={len(sub):4d}  HIGH {spread(h) * 100:+6.1f}pp   "
              f"LOW {spread(l) * 100:+6.1f}pp   spread "
              f"{(spread(h) - spread(l)) * 100:+6.1f}pp")

    r.to_parquet(root / "burn_rank.parquet")
    print(f"\nVERDICT: primary {primary}, regime {regime}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
