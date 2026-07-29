"""Propagation study: what moves the price first, by how much, and what is left.

Answers, on real intraday data:
  - How much of a catalyst's move happens before you could possibly act?
  - How much is left in the "retail wave" the next session?
  - Which event kinds lead, and which merely confirm?

    python scripts/cascade_study.py
"""

from __future__ import annotations

import argparse
import ast
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

from iai.cascade import (  # noqa: E402
    LEG_DEFINITIONS,
    analyse_cascade,
    arrival_split,
    lead_lag,
)
from iai.core.config import Config  # noqa: E402
from iai.diagnostics import benjamini_hochberg  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-events", type=int, default=30)
    args = ap.parse_args()

    cfg = Config.short_horizon()
    cfg.ensure_dirs()
    store = cfg.data.store_dir

    intra = pd.read_parquet(store / "sm_intraday_1h.parquet")
    events = pd.read_parquet(store / "sm_events.parquet")
    events["payload"] = events["payload"].map(
        lambda s: ast.literal_eval(s) if isinstance(s, str) else s
    )
    events["available_ts"] = pd.to_datetime(events["available_ts"], utc=True)

    # Intraday history is ~2 years; clip events to the covered window or the
    # cascade silently drops most of them.
    lo, hi = intra["ts"].min(), intra["ts"].max()
    ev = events[(events["available_ts"] >= lo) & (events["available_ts"] <= hi)]

    pd.set_option("display.width", 260)
    print("=" * 100)
    print("PROPAGATION STUDY -- 1h bars incl. pre/post market")
    print("=" * 100)
    print(f"intraday : {len(intra):,} bars, {intra['ticker'].nunique()} tickers")
    print(f"           {lo:%Y-%m-%d} .. {hi:%Y-%m-%d}")
    print(f"events   : {len(ev):,} in the covered window (of {len(events):,} total)")
    print()
    print("Leg definitions (in 1h bars from the event bar):")
    for name, (a, b) in LEG_DEFINITIONS.items():
        print(f"  {name:<24} bars {a}..{b}")
    print()

    res = analyse_cascade(ev, intra, min_events=args.min_events)
    if res.by_kind.empty:
        print("no event kind had enough coverage")
        return 0

    cols = ["kind", "n", "leg0_immediate", "leg1_rest_of_session", "leg2_next_session",
            "leg3_days_2_5", "total", "capturable", "capturable_share",
            "capturable_t", "leg2_vol_ratio"]
    tbl = res.by_kind[cols].copy()
    tbl["survives_fdr"] = benjamini_hochberg(res.by_kind["capturable_p"].to_numpy(), fdr=0.10)

    print("MOVE DECOMPOSITION BY EVENT KIND (abnormal returns)")
    print("-" * 100)
    print(tbl.to_string(index=False))
    print()
    print(f"kinds whose CAPTURABLE part survives FDR: {int(tbl['survives_fdr'].sum())} of {len(tbl)}")
    print()

    print("THE NATURAL EXPERIMENT -- cascade shape by when the news landed")
    print("-" * 100)
    print("After-hours news cannot move price until the next session, so its whole")
    print("cascade is visible. Intraday news reprices instantly. If both arms show a")
    print("similar capturable share, the second leg is a real behavioural wave.")
    print()
    print(arrival_split(res.per_event).to_string(index=False))
    print()

    for kind in ["8-K.2.02", "8-K.1.01", "insider.buy", "flow.volume_surge"]:
        sub = arrival_split(res.per_event, kind=kind)
        if not sub.empty and sub["n"].sum() >= args.min_events:
            print(f"  -- {kind} --")
            print("  " + sub.to_string(index=False).replace("\n", "\n  "))
            print()

    print("LEAD-LAG: when two kinds land together, which is first?")
    print("-" * 100)
    pairs = [
        ("8-K.2.02", "flow.volume_surge"),
        ("8-K.1.01", "flow.volume_surge"),
        ("insider.buy", "flow.volume_surge"),
        ("8-K.1.01", "news.attention_spike"),
        ("8-K.2.02", "news.attention_spike"),
        ("flow.volume_surge", "news.attention_spike"),
        ("8-K.1.01", "insider.buy"),
        ("stake.activist_amend", "flow.volume_surge"),
    ]
    ll = lead_lag(ev, pairs=pairs, window_hours=96)
    if ll.empty:
        print("  no pair had enough co-occurrences")
    else:
        print("  pct_b_after_a > 0.5 means the first column LEADS.")
        print()
        print(ll.to_string(index=False))

    res.per_event.to_parquet(store / "cascade_per_event.parquet")
    tbl.to_csv(store / "cascade_by_kind.csv", index=False)
    print(f"\nwrote {store / 'cascade_by_kind.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
