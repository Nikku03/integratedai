"""Pre-filing tape context for the screened names, and the selection rule.

Everything here is measured **strictly before the filing exists**, so that the
choice of what to trade cannot be contaminated by how the trade turned out.
The last session used is the one before the 8-K's acceptance timestamp, never
the filing session itself.

Three measurements, each tied to a result already established in this
repository rather than invented for this test:

``pre_run20`` / ``pre_run5``
    The run-up into the filing. `RESULT_PREFILING_RUNUP.md` found that the
    top decile of twenty-day pre-filing run-up has a median trade of −1.48%
    against −0.88% in the bottom decile, with the win rate falling across the
    top four deciles. The mean says nothing; the median says a great deal.

``gap_prev``
    Sessions since the issuer's previous 8-K. Combined with a flat run-up this
    is the "flat and quiet" cell — no move, nothing announced, then a filing —
    which returned **+0.36pp against the rest, 95% CI [+0.19, +0.53],
    P = 0.000** over 160,920 rows. It is the strongest pool filter in this work.

``vol20``
    Realised volatility. For the equity book this was something to avoid: it
    sorted realised |return| by 4.94x and mean return not at all, so dropping
    the top quintile cut the compounding drag from −1.77% to −0.75%. **For a
    long option position the sign flips.** Dispersion with no direction is
    what a long straddle is for, and it is why the same measurement that had
    to be screened out of the equity book is screened *in* here.

The user's own rule -- if a name jumped before the disclosure and nothing was
announced, the information is already out -- is implemented as ``already_out``.
It is applied as a **down-weight, not a veto**, because tested as a veto on
160,920 rows it was worth −0.06pp with a confidence interval spanning zero.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

#: A name whose stock does not trade this much cannot have an option chain worth
#: quoting. Verified against Polygon per name before anything is traded.
MIN_DOLLAR_VOL = 25e6


def load_px(work: Path) -> pd.DataFrame:
    rows = []
    for p in sorted(work.glob("grouped_*.json")):
        d = json.loads(p.read_text())
        day = p.stem.split("_")[-1]
        for r in d.get("results") or []:
            rows.append((day, r["T"], r["c"], r["v"], r["o"], r["h"], r["l"]))
    px = pd.DataFrame(rows, columns=["date", "ticker", "close", "vol",
                                     "open", "high", "low"])
    return px.sort_values(["ticker", "date"]).reset_index(drop=True)


def features(J: pd.DataFrame, px: pd.DataFrame, eightk: list[dict]) -> pd.DataFrame:
    sessions = sorted(px.date.unique())
    by = {t: g.reset_index(drop=True) for t, g in px.groupby("ticker")}

    prior: dict[tuple[str, str], list[str]] = {}
    for f in eightk:
        d = f"{f['date'][:4]}-{f['date'][4:6]}-{f['date'][6:]}"
        prior.setdefault(f["cik"], []).append(d)

    out = []
    for _, r in J.iterrows():
        g = by.get(r.ticker)
        if g is None:
            continue
        # the last session that had closed before the filing was accepted
        et = pd.Timestamp(r.accepted).tz_convert("America/New_York")
        same_day_tradeable = et.hour * 60 + et.minute < 960      # before 16:00 ET
        last = r.date if not same_day_tradeable else None
        cut = [s for s in sessions if s < r.date] if same_day_tradeable else \
              [s for s in sessions if s <= r.date]
        if not cut:
            continue
        j = g.index[g.date == cut[-1]]
        if not len(j):
            continue
        j = int(j[0])
        c = g.close.to_numpy()
        v = g.vol.to_numpy()

        def run(n):
            k = j - n
            return float(c[j] / c[k] - 1) if k >= 0 and c[k] > 0 else np.nan

        w = c[max(0, j - 20):j + 1]
        lr = np.diff(np.log(w)) if len(w) > 2 else np.array([np.nan])
        vol20 = float(np.nanstd(lr) * np.sqrt(252))
        vr = (float(v[j] / np.median(v[max(0, j - 20):j]))
              if j >= 5 and np.median(v[max(0, j - 20):j]) > 0 else np.nan)

        past = sorted(d for d in prior.get(r.cik, []) if d < r.date)
        gap = ((pd.Timestamp(r.date) - pd.Timestamp(past[-1])).days
               if past else 999)

        out.append(dict(r, entry_session=None, last_pre=cut[-1],
                        same_day=same_day_tradeable,
                        pre_run20=run(20), pre_run5=run(5), pre_run1=run(1),
                        vol20=vol20, pre_volratio=vr, gap_prev=gap))
    return pd.DataFrame(out)


def select(F: pd.DataFrame, judge: dict) -> pd.DataFrame:
    """Score every screened name on a rule fixed before any outcome is known."""
    F = F.copy()
    F["judge"] = [judge.get(f"{r.date}:{r.ticker}", {}).get("judge", 0)
                  for _, r in F.iterrows()]
    F["thesis"] = [judge.get(f"{r.date}:{r.ticker}", {}).get("thesis", "")
                   for _, r in F.iterrows()]

    # only negative readings have held up: judge -2 returned -11.33% at an 18.2%
    # win rate across four windows, while judge +1 returned -4.50% and +2
    # -2.28%. Conviction in a negative call is therefore worth more than the
    # same magnitude of conviction in a positive one.
    conv = F.judge.abs() * np.where(F.judge < 0, 1.5, 1.0)

    med_run = F.groupby("date")["pre_run20"].transform(
        lambda x: x.abs().median())
    quiet = (F.pre_run20.abs() <= med_run) & (F.gap_prev >= 30)
    F["flat_and_quiet"] = quiet

    # the user's rule, as a down-weight rather than a veto
    F["already_out"] = (F.pre_run5.abs() > 0.10) & (F.gap_prev >= 5)

    med_vol = F.groupby("date")["vol20"].transform("median")
    F["dispersion"] = F.vol20 / med_vol

    F["score"] = (conv
                  * np.where(quiet, 1.0, 0.6)
                  * np.where(F.already_out, 0.5, 1.0)
                  * np.clip(F.dispersion, 0.5, 2.0)
                  * np.where(F.dvol >= MIN_DOLLAR_VOL, 1.0, 0.0))
    return F.sort_values(["date", "score"], ascending=[True, False])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--judge", default="data/options_w1_labels.json")
    args = ap.parse_args(argv)
    work = Path(args.work)

    J = pd.read_parquet(work / "shortlist.parquet")
    px = load_px(work)
    eightk = json.load(open(work / "eightk.json"))
    F = features(J, px, eightk)
    print(f"  {len(F)} screened name-days with tape context, "
          f"{px.date.nunique()} sessions loaded")

    jp = Path(args.judge)
    judge = json.loads(jp.read_text()) if jp.exists() else {}
    S = select(F, judge)
    S.to_parquet(work / "selected.parquet")

    for day, g in S.groupby("date"):
        print(f"\n=== {day} ===")
        print(f"  {'tkr':7s}{'judge':>6s}{'run20':>8s}{'run5':>7s}{'vol':>7s}"
              f"{'gap':>5s}{'$vol':>7s}{'quiet':>7s}{'out':>5s}{'score':>7s}  thesis")
        for _, r in g.iterrows():
            print(f"  {r.ticker:7s}{r.judge:>+6d}{r.pre_run20 * 100:>+7.1f}%"
                  f"{r.pre_run5 * 100:>+6.1f}%{r.vol20 * 100:>6.0f}%"
                  f"{min(r.gap_prev, 999):>5.0f}{r.dvol / 1e6:>6.0f}M"
                  f"{str(r.flat_and_quiet):>7s}{str(r.already_out):>5s}"
                  f"{r.score:>7.2f}  {r.thesis[:44]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
