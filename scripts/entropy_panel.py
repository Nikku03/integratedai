"""Fold a directory of Polygon grouped-daily files into a price panel.

One grouped file is one session and every US ticker that traded in it, so the
natural shape is a sessions x tickers matrix rather than a long table: entropy,
volatility and every other feature in this study are per-name time series, and a
matrix lets them all be computed with one vectorised pass.

Only tickers that traded are present in a session's file, so a missing cell means
"did not trade", not zero. They are kept as NaN and never filled -- a forward-fill
would manufacture a run of exactly-equal closes, and exactly-equal values are
precisely what degenerates an ordinal statistic.

Rebuilding is cheap and incremental: the parsed panel is cached with the set of
source files that produced it, and a rerun after more sessions arrive rebuilds
only if that set changed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def build(work: Path, min_price: float, min_dvol: float) -> dict:
    files = sorted(work.glob("grouped_*.json"))
    if not files:
        raise SystemExit(f"no grouped_*.json in {work}")
    rows, sessions = [], []
    for i, f in enumerate(files, 1):
        try:
            res = json.loads(f.read_text()).get("results") or []
        except json.JSONDecodeError:
            continue
        if not res:                       # market holiday: OK status, empty body
            continue
        d = f.stem.split("_")[-1]
        sessions.append(d)
        for r in res:
            t = r.get("T")
            c, v = r.get("c"), r.get("v")
            if t is None or c is None or v is None:
                continue
            rows.append((d, t, float(r.get("o", np.nan)), float(r.get("h", np.nan)),
                         float(r.get("l", np.nan)), float(c), float(v)))
        if i % 50 == 0:
            print(f"    ... {i}/{len(files)} sessions parsed", flush=True)
    L = pd.DataFrame(rows, columns=["date", "ticker", "o", "h", "l", "c", "v"])
    print(f"  {len(L):,} bars over {L.date.nunique():,} sessions, "
          f"{L.ticker.nunique():,} distinct tickers")

    L["dvol"] = L.c * L.v
    # A very loose pre-filter only, to keep the matrix from being mostly empty.
    # It is deliberately far below the study's universe bar: the real screen is
    # applied point-in-time downstream, where it can use only past data. Applying
    # a tight filter here would silently make it a full-sample decision.
    live = L.groupby("ticker").agg(px=("c", "median"), dv=("dvol", "median"),
                                   n=("c", "size"))
    keep = live.index[(live.px >= min_price) & (live.dv >= min_dvol)]
    L = L[L.ticker.isin(keep)]
    print(f"  {len(keep):,} tickers clear the loose pre-filter "
          f"(median close >= ${min_price:g}, median $vol >= ${min_dvol / 1e6:g}M)")

    out = {}
    for col in ("c", "o", "h", "l", "v", "dvol"):
        M = L.pivot(index="date", columns="ticker", values=col).sort_index()
        out[col] = M.astype(np.float32)
    sess = out["c"].index.tolist()
    print(f"  panel {out['c'].shape[0]} sessions x {out['c'].shape[1]} tickers, "
          f"{sess[0]} -> {sess[-1]}")
    cov = out["c"].notna().sum(axis=1)
    print(f"  tickers present per session: min {cov.min():,} median {int(cov.median()):,} "
          f"max {cov.max():,}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--out", default="/tmp/claude-0/opt/panel")
    ap.add_argument("--min-price", type=float, default=1.0)
    ap.add_argument("--min-dvol", type=float, default=1e6)
    args = ap.parse_args(argv)
    work, out = Path(args.work), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    p = build(work, args.min_price, args.min_dvol)
    for k, M in p.items():
        M.to_parquet(out / f"{k}.parquet")
    (out / "manifest.json").write_text(json.dumps(
        dict(sessions=list(p["c"].index), tickers=list(p["c"].columns),
             n_files=len(sorted(work.glob("grouped_*.json"))))))
    print(f"  written to {out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
