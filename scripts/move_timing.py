"""When does the 10/20/50% move actually happen, and can you be in it?

Everything measured so far says the price has barely moved at catalyst + 1 minute
(2-19 basis points) and that large moves nevertheless exist (856 names above 10%
in July). Both cannot be describing the same instant, so the question is *when*
the move lands -- and, more usefully, whether it lands somewhere an order placed
at T+1min can reach.

The decomposition that matters
------------------------------
Every move from the last pre-catalyst print to the moment it crosses a threshold
splits into exactly two parts:

**The gap.** From the last print before the catalyst to the *first* print after
it. Nothing trades in between by definition, so this part is unreachable. If a
filing lands at 18:40 and the stock opens 12% higher at 09:30, that 12% belongs
to nobody who was not already long.

**The continuous part.** From that first print onward, while the tape is running.
This is the only part an order can participate in.

A strategy that enters at T+1min captures the continuous part and pays for the
gap. So "when does the move happen" is really "what share of it is gap", and that
share is the ceiling on the whole idea.

Direction is reported separately throughout. A 20% move down is as much a move as
a 20% move up, and conflating them is how a crash becomes a signal.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalyst_liquidity import WINDOW, classify  # noqa: E402

THRESHOLDS = (0.10, 0.20, 0.50)
SPLIT_GUARD = 1.00

PRE_OPEN, RTH_OPEN, RTH_CLOSE, POST_CLOSE = 240, 570, 960, 1200


def session_of(ts_et: pd.Timestamp) -> str:
    m = ts_et.hour * 60 + ts_et.minute
    if RTH_OPEN <= m < RTH_CLOSE:
        return "regular"
    if PRE_OPEN <= m < RTH_OPEN:
        return "pre-market"
    if RTH_CLOSE <= m < POST_CLOSE:
        return "after-hours"
    return "closed"


def trace(b: pd.DataFrame, t0: np.datetime64, horizon_bars: int = 3900) -> dict | None:
    """Path from the catalyst forward, split into gap and continuous parts."""
    tv = b["t_utc"].to_numpy()
    traded = b["volume"].fillna(0).to_numpy() > 0

    i0 = int(np.searchsorted(tv, t0, "left"))
    prev = np.nonzero(traded[:max(0, i0)])[0]
    if not len(prev):
        return None
    p_pre = float(b["close"].iloc[prev[-1]])
    if not np.isfinite(p_pre) or p_pre <= 0:
        return None

    # First print after the catalyst -- the earliest moment anything is tradable.
    nxt = np.nonzero(traded[i0:])[0]
    if not len(nxt):
        return None
    i_first = i0 + int(nxt[0])
    p_first = float(b["high"].iloc[i_first])
    if not np.isfinite(p_first) or p_first <= 0:
        return None
    gap = p_first / p_pre - 1.0
    if abs(gap) > SPLIT_GUARD:
        return None                        # reverse split, not a move

    out = {"p_pre": p_pre, "p_first": p_first, "gap": gap,
           "gap_min": float((tv[i_first] - t0) / np.timedelta64(1, "m"))}

    last = min(i_first + horizon_bars, len(b) - 1)
    seg = b.iloc[i_first:last + 1]
    seg_traded = traded[i_first:last + 1]
    hi = seg["high"].to_numpy(dtype=float)
    lo = seg["low"].to_numpy(dtype=float)
    st = tv[i_first:last + 1]

    up = np.where(seg_traded, hi / p_pre - 1.0, -np.inf)
    dn = np.where(seg_traded, lo / p_pre - 1.0, np.inf)
    for th in THRESHOLDS:
        k = int(th * 100)
        hit = np.nonzero(up >= th)[0]
        if len(hit):
            j = int(hit[0])
            out[f"up{k}_min"] = float((st[j] - t0) / np.timedelta64(1, "m"))
            out[f"up{k}_hit"] = True
            # How much of the threshold was already banked in the gap?
            out[f"up{k}_gap_share"] = float(np.clip(gap / th, -5, 5))
            out[f"up{k}_in_gap"] = bool(gap >= th)
        else:
            out[f"up{k}_hit"] = False
            out[f"up{k}_min"] = np.nan
            out[f"up{k}_gap_share"] = np.nan
            out[f"up{k}_in_gap"] = False
        hitd = np.nonzero(dn <= -th)[0]
        out[f"dn{k}_hit"] = bool(len(hitd))
        out[f"dn{k}_min"] = (float((st[int(hitd[0])] - t0) / np.timedelta64(1, "m"))
                             if len(hitd) else np.nan)
    return out


def build(root: Path, cache: Path) -> pd.DataFrame:
    f = pd.read_parquet(root / "recent_filings.parquet")
    f["accepted"] = pd.to_datetime(f["accepted"], utc=True, format="mixed")
    f["et"] = f["accepted"].dt.tz_convert("America/New_York")
    f = f[(f.et >= WINDOW[0]) & (f.et <= WINDOW[1])].copy()
    f["ctype"] = [classify(a, b) for a, b in zip(f["form"], f.get("items", ""))]
    f = f[f["ctype"].notna()]

    rows = []
    for tkr, grp in f.groupby("ticker"):
        p = cache / f"{tkr}.parquet"
        if not p.exists():
            continue
        b = pd.read_parquet(p)
        if b.empty or "t_utc" not in b.columns:
            continue
        b = b.sort_values("t_utc").reset_index(drop=True)
        for r in grp.itertuples():
            t0 = np.datetime64(r.accepted.tz_convert("UTC").tz_localize(None))
            t = trace(b, t0)
            if t:
                rows.append({"ticker": tkr, "ctype": r.ctype, "et": r.et,
                             "session": session_of(r.et), **t})
    return pd.DataFrame(rows)


def hm(mins: float) -> str:
    if not np.isfinite(mins):
        return "-"
    if mins < 90:
        return f"{mins:.0f}m"
    if mins < 60 * 48:
        return f"{mins / 60:.1f}h"
    return f"{mins / 1440:.1f}d"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--cache", default="/root/.iai/minutecache")
    args = ap.parse_args(argv)

    d = build(Path(args.root), Path(args.cache))
    d.to_parquet(Path(args.root) / "move_timing.parquet")
    print(f"{len(d):,} catalyst events, {d.ticker.nunique():,} names, "
          f"1-29 July 2026\n")

    print("HOW OFTEN THE MOVE HAPPENS AT ALL, AND WHEN")
    print(f"{'threshold':12s}{'reached UP':>12s}{'median lag':>13s}{'p25':>9s}"
          f"{'p75':>9s}{'reached DOWN':>14s}{'median lag':>13s}")
    for th in THRESHOLDS:
        k = int(th * 100)
        u, dnm = d[f"up{k}_hit"], d[f"dn{k}_hit"]
        lu = d.loc[u, f"up{k}_min"]
        ld = d.loc[dnm, f"dn{k}_min"]
        print(f"+{th:.0%}{'':7s}{u.mean() * 100:>11.1f}%{hm(lu.median()):>13s}"
              f"{hm(lu.quantile(.25)):>9s}{hm(lu.quantile(.75)):>9s}"
              f"{dnm.mean() * 100:>13.1f}%{hm(ld.median()):>13s}")

    print("\nTHE DECOMPOSITION -- how much of the move is in the UNTRADEABLE gap?")
    print("(gap = last print before the catalyst -> first print after it)")
    print(f"{'threshold':12s}{'n reached':>11s}{'whole move in gap':>19s}"
          f"{'median gap share':>18s}{'reachable after 1st print':>27s}")
    for th in THRESHOLDS:
        k = int(th * 100)
        s = d[d[f"up{k}_hit"]]
        if not len(s):
            continue
        ing = s[f"up{k}_in_gap"]
        print(f"+{th:.0%}{'':7s}{len(s):>11d}{ing.mean() * 100:>18.0f}%"
              f"{s[f'up{k}_gap_share'].median() * 100:>17.0f}%"
              f"{(~ing).mean() * 100:>26.0f}%")

    print("\nBY SESSION THE CATALYST LANDED IN (+10% up-move)")
    print(f"{'session':14s}{'n':>7s}{'reached +10%':>14s}{'median lag':>13s}"
          f"{'in gap':>9s}{'median gap size':>17s}")
    for s in ("regular", "pre-market", "after-hours", "closed"):
        g = d[d.session == s]
        if len(g) < 20:
            continue
        h = g[g.up10_hit]
        print(f"{s:14s}{len(g):>7d}{g.up10_hit.mean() * 100:>13.1f}%"
              f"{hm(h.up10_min.median()):>13s}{h.up10_in_gap.mean() * 100:>8.0f}%"
              f"{g.gap.median() * 100:>16.2f}%")

    print("\nTHE GAP ITSELF, by session (this is what you cannot trade)")
    print(f"{'session':14s}{'n':>7s}{'median':>9s}{'mean':>9s}{'p90':>9s}"
          f"{'|gap|>=5%':>11s}{'time to 1st print':>19s}")
    for s in ("regular", "pre-market", "after-hours", "closed"):
        g = d[d.session == s]
        if len(g) < 20:
            continue
        print(f"{s:14s}{len(g):>7d}{g.gap.median() * 100:>8.2f}%"
              f"{g.gap.mean() * 100:>8.2f}%{g.gap.quantile(.90) * 100:>8.2f}%"
              f"{(g.gap.abs() >= .05).mean() * 100:>10.0f}%"
              f"{hm(g.gap_min.median()):>19s}")

    print("\nBY CATALYST TYPE -- share reaching +10%, and how much was gap")
    print(f"{'catalyst type':26s}{'n':>6s}{'reach +10%':>12s}{'median lag':>13s}"
          f"{'in gap':>9s}")
    for c, sub in sorted(d.groupby("ctype"), key=lambda x: -len(x[1])):
        if len(sub) < 40:
            continue
        h = sub[sub.up10_hit]
        print(f"{c:26s}{len(sub):>6d}{sub.up10_hit.mean() * 100:>11.1f}%"
              f"{hm(h.up10_min.median()) if len(h) else '-':>13s}"
              f"{(h.up10_in_gap.mean() * 100 if len(h) else 0):>8.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
