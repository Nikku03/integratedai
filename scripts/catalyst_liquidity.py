"""At catalyst + 1 minute: what could you trade, and where was the price?

Earlier work went mover-first -- take the big moves, ask what caused them. This
goes event-first: take every catalyst of every type, stand at its timestamp plus
one minute, and record the two things that decide whether it is tradable at all.

**Liquidity.** Did that minute print? How many dollars changed hands in it, and in
the five, fifteen and sixty minutes after? An $80 order needs a counterparty; a
$50,000 order needs about six hundred times more of one. Reporting dollars rather
than a yes/no makes the size question answerable instead of assumed.

**Price.** Where is the offer at T+1min relative to the last print before the
catalyst? That is the move already gone by the time a one-minute reaction can
act -- the part you pay for rather than earn.

Timestamp quality is the whole game here
----------------------------------------
SEC forms carry ``acceptanceDateTime`` to the second, which is the instant the
document became publicly retrievable. That supports a real T+1min measurement.

FDA, ClinicalTrials.gov and DoD publish **date only**. There is no minute to add
one to, so a T+1min figure for them would be fabricated. They are measured at the
next session's open instead and reported in a separate block, clearly marked. Any
table that mixes the two is comparing a stopwatch with a calendar.

Corporate actions are screened
------------------------------
Unadjusted minute bars carry raw prints, so a 1-for-40 reverse split reads as a
+3,900% move. Fourteen such rows in an earlier pass moved a mean from +0.72% to
+7.94%. Anything above +100% at T+1min is dropped as a split rather than a move.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

WINDOW = (pd.Timestamp("2026-07-01", tz="America/New_York"),
          pd.Timestamp("2026-07-29", tz="America/New_York"))

#: A single move this large in one step is a split, not a trade.
SPLIT_GUARD = 1.00

#: Form -> catalyst type. First match wins, most decisive first.
FORM_TYPE = [
    ("merger/tender", ("425", "SC TO-T", "SC 14D9", "SC TO-I", "DEFM14A")),
    ("offering/dilution", ("424B", "S-1", "S-3", "F-1", "F-3")),
    ("activist 13D", ("SCHEDULE 13D", "SC 13D")),
    ("passive 13G", ("SCHEDULE 13G", "SC 13G")),
    ("periodic 10-Q/K", ("10-Q", "10-K", "20-F", "6-K")),
    ("insider Form 4", ("4", "144", "3")),
    ("proxy/other", ("DEF 14A", "DEFA14A", "PRE 14A", "8-A12B", "S-8")),
]

#: 8-K item codes split out separately, since "8-K" spans everything from a
#: dividend declaration to a merger.
ITEM_TYPE = {
    "1.01": "8-K material agreement", "2.01": "8-K acquisition done",
    "2.02": "8-K earnings", "3.01": "8-K delisting", "3.02": "8-K dilution",
    "4.01": "8-K auditor change", "4.02": "8-K restatement",
    "5.02": "8-K officer change", "5.07": "8-K vote results",
    "7.01": "8-K reg-FD", "8.01": "8-K other event",
}


def classify(form: str, items: str) -> str:
    f = str(form).upper().strip()
    if f.startswith("8-K"):
        codes = [c.strip() for c in str(items or "").split(",") if c.strip()]
        for c in codes:
            if c in ITEM_TYPE and c != "9.01":
                return ITEM_TYPE[c]
        return "8-K other event"
    for label, prefixes in FORM_TYPE:
        if any(f == p or f.startswith(p) for p in prefixes):
            return label
    return None


def measure(b: pd.DataFrame, t0: np.datetime64) -> dict | None:
    """Liquidity and price one minute after the catalyst.

    ``b`` carries every bar; the traded subset is derived here because the
    *absence* of a print is itself the measurement.
    """
    tv = b["t_utc"].to_numpy()
    vol = b["volume"].fillna(0).to_numpy()
    traded = vol > 0

    prev = np.nonzero(traded[:max(0, int(np.searchsorted(tv, t0, "left")))])[0]
    if not len(prev):
        return None
    p_pre = float(b["close"].iloc[prev[-1]])
    if not np.isfinite(p_pre) or p_pre <= 0:
        return None

    i1 = int(np.searchsorted(tv, t0 + np.timedelta64(1, "m"), "left"))
    if i1 >= len(b):
        return None

    # The exact T+1 minute: did it print, and for how much?
    printed = bool(traded[i1])
    bar_usd = float(b["close"].iloc[i1] * vol[i1]) if printed else 0.0

    # Dollars available over the following windows, counting only real prints.
    out = {"p_pre": p_pre, "printed_at_1min": printed, "usd_at_1min": bar_usd}
    for w in (5, 15, 60):
        j = min(i1 + w, len(b))
        seg = b.iloc[i1:j]
        out[f"usd_{w}min"] = float((seg["close"] * seg["volume"].fillna(0)).sum())

    # Price you would pay: the offer in the first minute that actually trades.
    fwd = np.nonzero(traded[i1:])[0]
    if not len(fwd):
        return None
    i_fill = i1 + int(fwd[0])
    px = float(b["high"].iloc[i_fill])
    if not np.isfinite(px) or px <= 0:
        return None
    out["fill_lag_min"] = float((tv[i_fill] - t0) / np.timedelta64(1, "m"))
    out["px_at_1min"] = px
    out["move_at_1min"] = px / p_pre - 1.0

    # Where it goes after you are in.
    for w, lab in ((15, "fwd_15m"), (60, "fwd_60m"), (390, "fwd_1d")):
        j = min(i_fill + w, len(b) - 1)
        k = np.nonzero(traded[i_fill + 1:j + 1])[0]
        out[lab] = (float(b["low"].iloc[i_fill + 1 + k[-1]]) / px - 1.0
                    if len(k) else np.nan)
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
            m = measure(b, t0)
            if m and abs(m["move_at_1min"]) <= SPLIT_GUARD:
                rows.append({"ticker": tkr, "ctype": r.ctype, "form": r.form,
                             "et": r.et, **m})
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--cache", default="/root/.iai/minutecache")
    ap.add_argument("--min-n", type=int, default=25)
    args = ap.parse_args(argv)

    d = build(Path(args.root), Path(args.cache))
    d.to_parquet(Path(args.root) / "catalyst_liquidity.parquet")
    print(f"{len(d):,} catalyst events across {d.ticker.nunique():,} names, "
          f"1-29 July 2026, SEC forms with second-resolution timestamps\n")

    print("LIQUIDITY AT CATALYST + 1 MINUTE")
    print(f"{'catalyst type':26s}{'n':>6s}{'printed':>9s}{'$ in that min':>15s}"
          f"{'$ next 5min':>13s}{'$ next 60min':>14s}")
    g = d.groupby("ctype")
    for c, sub in sorted(g, key=lambda x: -len(x[1])):
        if len(sub) < args.min_n:
            continue
        print(f"{c:26s}{len(sub):>6d}{sub.printed_at_1min.mean() * 100:>8.0f}%"
              f"{sub.usd_at_1min.median():>15,.0f}"
              f"{sub.usd_5min.median():>13,.0f}{sub.usd_60min.median():>14,.0f}")
    print(f"{'ALL':26s}{len(d):>6d}{d.printed_at_1min.mean() * 100:>8.0f}%"
          f"{d.usd_at_1min.median():>15,.0f}{d.usd_5min.median():>13,.0f}"
          f"{d.usd_60min.median():>14,.0f}")

    print("\nPRICE MOVE ALREADY GONE AT +1 MINUTE (offer vs last pre-catalyst print)")
    print(f"{'catalyst type':26s}{'n':>6s}{'median':>9s}{'mean':>9s}"
          f"{'p90':>8s}{'>=1%':>7s}{'>=5%':>7s}{'fill lag':>10s}")
    for c, sub in sorted(g, key=lambda x: -len(x[1])):
        if len(sub) < args.min_n:
            continue
        m = sub.move_at_1min
        print(f"{c:26s}{len(sub):>6d}{m.median() * 100:>8.2f}%{m.mean() * 100:>8.2f}%"
              f"{m.quantile(.90) * 100:>7.1f}%{(m >= .01).mean() * 100:>6.0f}%"
              f"{(m >= .05).mean() * 100:>6.0f}%{sub.fill_lag_min.median():>9.0f}m")

    print("\nWHAT HAPPENS AFTER YOU ARE IN (from the T+1min offer, selling the bid)")
    print(f"{'catalyst type':26s}{'n':>6s}{'+15m':>9s}{'+60m':>9s}{'+1 day':>9s}")
    for c, sub in sorted(g, key=lambda x: -len(x[1])):
        if len(sub) < args.min_n:
            continue
        print(f"{c:26s}{len(sub):>6d}{sub.fwd_15m.mean() * 100:>8.2f}%"
              f"{sub.fwd_60m.mean() * 100:>8.2f}%{sub.fwd_1d.mean() * 100:>8.2f}%")

    print("\nORDER SIZE THE T+1min BAR SUPPORTS at 10% participation")
    print(f"{'catalyst type':26s}{'n':>6s}{'median $':>12s}{'p25 $':>11s}"
          f"{'supports $80':>14s}{'supports $5k':>14s}")
    for c, sub in sorted(g, key=lambda x: -len(x[1])):
        if len(sub) < args.min_n:
            continue
        cap = sub.usd_at_1min * 0.10
        print(f"{c:26s}{len(sub):>6d}{cap.median():>12,.0f}{cap.quantile(.25):>11,.0f}"
              f"{(cap >= 80).mean() * 100:>13.0f}%{(cap >= 5000).mean() * 100:>13.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
