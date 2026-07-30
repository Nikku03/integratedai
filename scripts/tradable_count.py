"""How many trades can actually be taken, and does the model beat picking at random?

The question this answers is narrower and harder than "does the strategy work":

    at each week, using only information available then, how many names are
    eligible, how many can be held, and does ranking them by the model's
    expected value beat drawing the same number out of the same hat?

Everything here reads the out-of-fold predictions from the pre-registered
2015-2026 run, so no model is refitted and no threshold is re-chosen. The OOF
frame is causal by construction -- each prediction comes from a fold trained
only on data before its purge boundary -- which is what makes a random-selection
control meaningful rather than circular.

The control is the point
-----------------------
A strategy that takes 22 trades a month and loses 15bp each could be losing
because the *universe* loses, or because the *model picks badly*. Those have
opposite implications: the first says the target is wrong, the second says the
ranking is wrong. Drawing k names per week uniformly from the identical eligible
pool separates them, and 2,000 draws gives the null a shape rather than a point.

Recall is reported alongside, because "how many can we trade" has a second
reading: of the large moves that actually happened in reachable names, what
share did the ranking ever put in front of us?
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

STOP_REASONS = ("stop", "both")


def load(root: Path) -> pd.DataFrame:
    d = pd.read_parquet(root / "w2015_moonshot_oof.parquet")
    d["date"] = pd.to_datetime(d["date"])
    d["week"] = d["date"].dt.to_period("W")
    # Net of the round-trip cost the run itself charged, so model and random
    # selections are compared on identical terms.
    d["net"] = d["ret"] - d["cost_rt"]
    return d.sort_values(["date", "ticker"]).reset_index(drop=True)


def per_week_topk(d: pd.DataFrame, k: int, col: str = "ev") -> pd.DataFrame:
    return (d.sort_values(col, ascending=False)
             .groupby("week", observed=True, sort=False).head(k))


def random_draws(d: pd.DataFrame, k: int, n_draws: int, seed: int = 17) -> np.ndarray:
    """Mean net return of k names drawn uniformly per week, n_draws times.

    Draws are per week from that week's own pool, so the random arm faces the
    same calendar, the same universe and the same number of positions. The only
    difference from the model arm is which names inside each week get taken.
    """
    rng = np.random.default_rng(seed)
    groups = [g["net"].to_numpy() for _, g in d.groupby("week", observed=True)]
    groups = [g for g in groups if len(g) >= 1]
    out = np.empty(n_draws)
    for i in range(n_draws):
        picks = [rng.choice(g, min(k, len(g)), replace=False) for g in groups]
        out[i] = np.concatenate(picks).mean()
    return out


def report(root: Path, n_draws: int) -> None:
    d = load(root)
    span_yrs = (d.date.max() - d.date.min()).days / 365.25
    print(f"out-of-fold candidate rows: {len(d):,} across {d.ticker.nunique():,} "
          f"names, {d.week.nunique()} weeks, {d.date.min():%Y-%m-%d} to "
          f"{d.date.max():%Y-%m-%d} ({span_yrs:.1f} years)\n")

    pool = d.groupby("week", observed=True).size()
    print("ELIGIBLE POOL per week (already past the causal tradability screen):")
    print(f"  median {pool.median():.0f}   p10 {pool.quantile(.10):.0f}   "
          f"p90 {pool.quantile(.90):.0f}   min {pool.min()}   max {pool.max()}")
    print(f"  weeks with fewer than 5 candidates: "
          f"{int((pool < 5).sum())} of {len(pool)}")

    base = d["net"].mean()
    spike_base = d["spike"].mean()
    print(f"\nUNIVERSE BASELINE (hold every eligible candidate): "
          f"net {base * 100:+.3f}%/trade, spike rate {spike_base * 100:.1f}%")

    print(f"\n{'k/week':>7s}{'trades':>8s}{'/month':>8s}{'model net':>11s}"
          f"{'random net':>12s}{'model-random':>13s}{'p(random>=model)':>18s}"
          f"{'spike%':>8s}{'stop%':>7s}")
    rows = []
    for k in (1, 2, 3, 5, 8, 12, 20):
        sel = per_week_topk(d, k)
        n = len(sel)
        m = sel["net"].mean()
        null = random_draws(d, k, n_draws)
        p = float((null >= m).mean())
        rows.append({"k": k, "trades": n, "per_month": n / (span_yrs * 12),
                     "model_net": m, "random_net": float(null.mean()),
                     "p": p, "spike": sel["spike"].mean(),
                     "stop": sel["exit_reason"].isin(STOP_REASONS).mean()})
        print(f"{k:>7d}{n:>8d}{n / (span_yrs * 12):>8.1f}{m * 100:>10.3f}%"
              f"{null.mean() * 100:>11.3f}%{(m - null.mean()) * 100:>12.3f}pp"
              f"{p:>18.3f}{sel['spike'].mean() * 100:>7.1f}%"
              f"{sel['exit_reason'].isin(STOP_REASONS).mean() * 100:>6.1f}%")

    print("\nRECALL -- of the spikes that happened in reachable names, "
          "how many did the ranking surface?")
    tot_spikes = int(d["spike"].sum())
    print(f"  spikes in the eligible pool: {tot_spikes:,} "
          f"({spike_base * 100:.1f}% of {len(d):,} rows)")
    for k in (5, 12, 20):
        sel = per_week_topk(d, k)
        got = int(sel["spike"].sum())
        print(f"  k={k:2d}: selected {len(sel):5d} rows, caught {got:4d} spikes "
              f"= {got / tot_spikes * 100:4.1f}% recall, "
              f"{got / len(sel) * 100:4.1f}% precision "
              f"(lift {(got / len(sel)) / spike_base:.2f}x)")

    out = pd.DataFrame(rows)
    out.to_csv(root / "tradable_count.csv", index=False)
    print(f"\nwrote {root / 'tradable_count.csv'}")

    print("\nGROSS vs NET -- where the money goes at k=5:")
    sel = per_week_topk(d, 5)
    print(f"  gross ret  {sel['ret'].mean() * 100:+.3f}%/trade")
    print(f"  cost       {sel['cost_rt'].mean() * 100:-.3f}%/trade "
          f"(median {sel['cost_rt'].median() * 100:.3f}%)")
    print(f"  net        {sel['net'].mean() * 100:+.3f}%/trade")
    print(f"  the cost is {sel['cost_rt'].mean() / abs(sel['ret'].mean()):.1f}x "
          f"the gross edge" if sel['ret'].mean() != 0 else "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/store")
    ap.add_argument("--draws", type=int, default=2000)
    args = ap.parse_args(argv)
    report(Path(args.root), args.draws)
    return 0


if __name__ == "__main__":
    sys.exit(main())
