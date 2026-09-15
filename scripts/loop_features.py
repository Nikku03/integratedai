"""The three signals, all measured to the last close before acceptance.

``run_z`` is computed for the whole panel at once rather than per event, because
the peer signals need every name's run at the filer's entry session, not just the
filer's. Same definition as the original test: a five-session return divided by
that name's own five-session volatility, built from a trailing twenty-session
standard deviation.

Peers are the same four-digit SIC code among names that themselves report and
clear the liquidity bar, the filer excluded, minimum five or the event is
dropped. ``peer_gap`` uses only peers that had **already reported** in the ten
sessions before the filer's entry -- news that has landed on a neighbouring arc
and is public, not news arriving at the same moment.

No forward information enters any feature: run windows end at the entry close,
and a peer's gap is included only if that peer's own exit session is at or before
the filer's entry session.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RUN, VOL, MIN_PEERS, PEER_LOOKBACK = 5, 20, 5, 10


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", default="/tmp/claude-0/opt/loop_events.parquet")
    ap.add_argument("--panel", default="/tmp/claude-0/opt/panel")
    ap.add_argument("--out", default="/tmp/claude-0/opt/loop_features.parquet")
    args = ap.parse_args(argv)
    pan = Path(args.panel)

    C = pd.read_parquet(pan / "c.parquet")
    O = pd.read_parquet(pan / "o.parquet")
    E = pd.read_parquet(args.events)
    sess = C.index.tolist()
    pos = {s: i for i, s in enumerate(sess)}
    col = {t: i for i, t in enumerate(C.columns)}
    cv, ov = C.to_numpy(np.float64), O.to_numpy(np.float64)

    lr = np.diff(np.log(cv), axis=0)
    lr = np.vstack([np.full((1, cv.shape[1]), np.nan), lr])
    sd = pd.DataFrame(lr).rolling(VOL, min_periods=VOL).std().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        r5 = cv / np.roll(cv, RUN, axis=0) - 1.0
        r5[:RUN] = np.nan
        RZ = r5 / (sd * np.sqrt(RUN))              # run in units of own vol
    print(f"  run_z panel {RZ.shape[0]} sessions x {RZ.shape[1]:,} tickers, "
          f"{np.isfinite(RZ).sum():,} finite")

    # peer index: SIC -> the column positions of the names that report in it
    sic_of = E.drop_duplicates("ticker").set_index("ticker").sic.to_dict()
    by_sic = {}
    for t, s in sic_of.items():
        j = col.get(t)
        if j is not None and s:
            by_sic.setdefault(s, []).append(j)

    # every peer's own gap, keyed by (column, its exit session index)
    gp = {}
    for r in E.itertuples():
        i, j = pos.get(r.exit), col.get(r.ticker)
        e = pos.get(r.entry)
        if i is None or j is None or e is None:
            continue
        g = ov[i, j] / cv[e, j] - 1.0
        if np.isfinite(g):
            gp.setdefault(j, []).append((i, float(g)))

    rows = []
    for r in E.itertuples():
        e, x, j = pos.get(r.entry), pos.get(r.exit), col.get(r.ticker)
        if e is None or x is None or j is None:
            continue
        own = RZ[e, j]
        gap = ov[x, j] / cv[e, j] - 1.0
        day = cv[x, j] / ov[x, j] - 1.0
        if not (np.isfinite(own) and np.isfinite(gap)):
            continue
        peers = [p for p in by_sic.get(r.sic, []) if p != j]
        pz = RZ[e, peers] if peers else np.array([])
        pz = pz[np.isfinite(pz)]
        pg = [g for p in peers for (i, g) in gp.get(p, [])
              if e - PEER_LOOKBACK <= i <= e]        # already reported, public
        rows.append(dict(
            date=r.date, ticker=r.ticker, entry=r.entry, exit=r.exit, sic=r.sic,
            sic_desc=r.sic_desc, timing=r.timing, company=r.company,
            own_run_z=float(own), gap=float(gap),
            day_ret=float(day) if np.isfinite(day) else np.nan,
            peer_run_z=float(pz.mean()) if len(pz) >= MIN_PEERS else np.nan,
            n_peer_run=int(len(pz)),
            peer_gap=float(np.mean(pg)) if len(pg) >= MIN_PEERS else np.nan,
            n_peer_gap=int(len(pg)),
            vol20=float(sd[e, j] * np.sqrt(252)) if np.isfinite(sd[e, j]) else np.nan))
    F = pd.DataFrame(rows)
    F.to_parquet(args.out)
    print(f"  {len(F):,} events with own_run_z and a gap")
    print(f"    with peer_run_z (>= {MIN_PEERS} peers): {F.peer_run_z.notna().sum():,}"
          f"   median peers {F.n_peer_run.median():.0f}")
    print(f"    with peer_gap   (>= {MIN_PEERS} prior): {F.peer_gap.notna().sum():,}"
          f"   median priors {F.n_peer_gap.median():.0f}")
    print(f"  mean |gap| {F.gap.abs().mean() * 100:.2f}%  median "
          f"{F.gap.abs().median() * 100:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
