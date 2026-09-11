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
    Days since the issuer's previous 8-K, read from that issuer's full SEC
    submissions history. Deriving it from the three indexed sessions alone --
    the obvious shortcut -- makes every issuer that did not file twice inside
    the window look like it had been silent forever, which is how "quiet" ends
    up meaning nothing at all. Combined with a flat run-up this
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

A fifth term, added after the first run: the name must have had an **option
market before the filing existed**. The first run selected six names and only
afterwards discovered that four had no tradeable at-the-money contract -- one of
them never traded a single one. `options_liquidity.py` measures that over the
five sessions ending before the filing, and it enters here as a hard gate rather
than a weight, because an option that does not trade is not a worse trade, it is
not a trade.

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


def acceptance(ts) -> pd.Timestamp:
    """The filing's acceptance moment in Eastern Time.

    EDGAR stamps ``acceptanceDateTime`` in UTC despite the trailing Z. Read as
    Eastern it puts the two 8-K clusters at 11:00-13:00 and 20:00-22:00 local,
    which is nobody's filing pattern; converted from UTC it puts them at
    07:00-09:00 and 16:00-18:00, which is exactly the pattern.
    """
    return pd.Timestamp(ts).tz_convert("America/New_York")


def last_close_before(sessions, et: pd.Timestamp) -> str | None:
    """The last session whose 16:00 bell rang before the filing was accepted.

    This is the boundary every pre-filing measurement has to respect, and it is
    not the day the filing appears in EDGAR's index. Biohaven's partial clinical
    hold was accepted at 21:55 on 09-09 and indexed under 09-10; keying off the
    index date put 09-10 -- a session that had already traded on the news --
    inside its "pre-filing" run-up, and reported a 5-day run of -18.5% that was
    mostly the reaction itself.
    """
    d = et.date().isoformat()
    cut = d if (et.hour * 60 + et.minute) > 960 else None
    ok = [s for s in sessions if s < d] + ([cut] if cut and cut in sessions else [])
    return max(ok) if ok else None


def first_open_after(sessions, et: pd.Timestamp) -> str | None:
    """The first session whose 09:30 open came after the filing was accepted."""
    d = et.date().isoformat()
    if (et.hour * 60 + et.minute) < 570 and d in sessions:
        return d
    later = [s for s in sessions if s > d]
    return min(later) if later else None


def prior_8k(cache: Path, cik: int, before: str) -> int:
    """Days since this issuer's previous 8-K, from its whole filing history."""
    p = cache / f"subs_{cik}.json"
    if not p.exists():
        return 999
    t = p.read_text()
    if not t.strip():
        return 999
    rec = json.loads(t)["filings"]["recent"]
    past = [d for f, d in zip(rec["form"], rec["filingDate"])
            if f == "8-K" and d < before]
    if not past:
        return 999
    return int((pd.Timestamp(before) - pd.Timestamp(max(past))).days)


def features(J: pd.DataFrame, px: pd.DataFrame, cache: Path) -> pd.DataFrame:
    sessions = sorted(px.date.unique())
    by = {t: g.reset_index(drop=True) for t, g in px.groupby("ticker")}

    out = []
    for _, r in J.iterrows():
        g = by.get(r.ticker)
        if g is None:
            continue
        et = acceptance(r.accepted)
        last_pre = last_close_before(sessions, et)
        entry = first_open_after(sessions, et)
        if last_pre is None:
            continue
        j = g.index[g.date == last_pre]
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

        gap = prior_8k(cache, int(r.cik), r.date)

        out.append(dict(r, entry_session=entry, last_pre=last_pre,
                        acc_et=et.isoformat(),
                        pre_run20=run(20), pre_run5=run(5), pre_run1=run(1),
                        vol20=vol20, pre_volratio=vr, gap_prev=gap))
    return pd.DataFrame(out)


def select(F: pd.DataFrame, judge: dict, liq: pd.DataFrame | None = None) -> pd.DataFrame:
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

    if liq is not None and len(liq):
        key = liq.set_index(["date", "ticker"])
        F["opt_prevol"] = [float(key.pre_vol.get((r.date, r.ticker), 0.0))
                           for _, r in F.iterrows()]
        F["opt_ok"] = [bool(key.eligible.get((r.date, r.ticker), False))
                       for _, r in F.iterrows()]
    else:
        F["opt_prevol"] = np.nan
        F["opt_ok"] = True

    F["score"] = (conv
                  * np.where(quiet, 1.0, 0.6)
                  * np.where(F.already_out, 0.5, 1.0)
                  * np.clip(F.dispersion, 0.5, 2.0)
                  * np.where(F.dvol >= MIN_DOLLAR_VOL, 1.0, 0.0)
                  * np.where(F.opt_ok, 1.0, 0.0))
    return F.sort_values(["date", "score"], ascending=[True, False])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--judge", default="data/options_w1_labels.json")
    ap.add_argument("--no-gate", action="store_true",
                    help="score without the option-liquidity gate, to build the "
                         "candidate list the gate is then measured on")
    args = ap.parse_args(argv)
    work = Path(args.work)

    J = pd.read_parquet(work / "shortlist.parquet")
    px = load_px(work)
    F = features(J, px, work / "cache")
    print(f"  {len(F)} screened name-days with tape context, "
          f"{px.date.nunique()} sessions loaded")

    jp = Path(args.judge)
    judge = json.loads(jp.read_text()) if jp.exists() else {}
    lp = work / "optliq.parquet"
    liq = pd.read_parquet(lp) if lp.exists() and not args.no_gate else None
    if liq is None:
        print("  ** no option-liquidity file: the gate is NOT applied **")
    S = select(F, judge, liq)
    S.to_parquet(work / "selected.parquet")

    for day, g in S.groupby("date"):
        print(f"\n=== {day} ===")
        print(f"  {'tkr':7s}{'judge':>6s}{'run20':>8s}{'run5':>7s}{'vol':>7s}"
              f"{'gap':>5s}{'$vol':>7s}{'quiet':>7s}{'out':>5s}{'optvol':>7s}"
              f"{'score':>7s}  thesis")
        for _, r in g.iterrows():
            ov = ("   --" if r.opt_prevol != r.opt_prevol
                  else f"{r.opt_prevol:>5,.0f}")
            print(f"  {r.ticker:7s}{r.judge:>+6d}{r.pre_run20 * 100:>+7.1f}%"
                  f"{r.pre_run5 * 100:>+6.1f}%{r.vol20 * 100:>6.0f}%"
                  f"{min(r.gap_prev, 999):>5.0f}{r.dvol / 1e6:>6.0f}M"
                  f"{str(r.flat_and_quiet):>7s}{str(r.already_out):>5s}"
                  f"{ov:>7s}{r.score:>7.2f}  {r.thesis[:34]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
