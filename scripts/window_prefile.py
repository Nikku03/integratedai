"""Has the market already moved on this filing before it was filed?

The rule being implemented: if a stock has already jumped in the days before a
disclosure and nothing was announced to explain it, then the information is
either already out or the event is routine enough that everyone expects it.
Either way the filing is not news by the time it can be traded.

Everything here stops at the last session that CLOSED BEFORE the filing was
accepted. Not the session before the index date -- the index date is when EDGAR
disseminated the filing, which can be the morning after acceptance, and keying
off it silently pulls the reaction session into the "pre-filing" window. That
error turned Biohaven's genuine surprise into an apparent leak: its five-day
run-up read -18.5% when the honest figure was -4.7%.

What is measured
----------------
``pre_run5`` / ``pre_run4`` / ``pre_run1``
    Return over the sessions ending at that last pre-filing close.
``pre_volratio``
    That session's volume against its own 20-session median. Volume arriving
    before a filing is the cleanest sign the market is positioning for it.
``vol20``
    Realised volatility, which sets how large a run has to be before it means
    anything. A 10% move in a 30%-volatility name is an event; in a
    120%-volatility name it is a Tuesday.
``run_z``
    The five-session run expressed in units of that name's own volatility, so
    names of different temperament can be compared.
``gap_prev``
    Days since the issuer's previous 8-K, from its full filing history. A run
    with a recent filing behind it has an explanation; a run with nothing behind
    it is the case the rule is about.

``already_priced`` is the flag: a move of more than one standard deviation over
five sessions **or** more than one and a half over the single session before the
filing, with no 8-K in the preceding two weeks to explain it. The one-session
test matters and was added after looking at the pre-filing data alone: Twist rose
**22.6% on the day before** its 8-K, which is 3.3 standard deviations of its own
daily move and unmistakably the market already positioning -- and the five-day
window diluted it to +13.7% and 0.9 standard deviations, below any sensible
threshold. The refinement used no outcome data of any kind. Note that the earlier panel test of this rule
as a hard veto found it worth -0.06pp with an interval spanning zero, so it is
recorded here as a measurement to test, not as a filter to trust.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from options_straddle import load_bars  # noqa: E402


def prior_8k(cache: Path, cik: int, before: str) -> int:
    p = cache / f"subs_{cik}.json"
    if not p.exists() or not p.read_text().strip():
        return 999
    rec = json.loads(p.read_text())["filings"]["recent"]
    past = [d for f, d in zip(rec["form"], rec["filingDate"])
            if f == "8-K" and d < before]
    return int((pd.Timestamp(before) - pd.Timestamp(max(past))).days) if past else 999


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--events", default="/tmp/claude-0/opt/win_screened.parquet")
    ap.add_argument("--out", default="/tmp/claude-0/opt/win_prefile.parquet")
    args = ap.parse_args(argv)
    work = Path(args.work)
    bars, sessions = load_bars(work)
    E = pd.read_parquet(args.events)

    px = {}
    for d in sessions:
        for t, b in bars[d].items():
            px.setdefault(t, []).append((d, b))

    rows = []
    for _, r in E.iterrows():
        et = pd.Timestamp(r.accepted_et)
        d = et.date().isoformat()
        # the last bell that rang before the filing was accepted
        last_pre = ([s for s in sessions if s < d]
                    + ([d] if (et.hour * 60 + et.minute) > 960 and d in sessions else []))
        if not last_pre:
            continue
        lp = max(last_pre)
        ser = px.get(r.ticker, [])
        days = [x[0] for x in ser]
        if lp not in days:
            continue
        j = days.index(lp)
        c = np.array([x[1]["c"] for x in ser], float)
        v = np.array([x[1]["v"] for x in ser], float)

        def run(n):
            k = j - n
            return float(c[j] / c[k] - 1) if k >= 0 and c[k] > 0 else np.nan

        w = c[max(0, j - 20):j + 1]
        lr = np.diff(np.log(w)) if len(w) > 2 else np.array([np.nan])
        vol20 = float(np.nanstd(lr) * np.sqrt(252))
        med = np.median(v[max(0, j - 20):j]) if j >= 5 else np.nan
        r5 = run(5)
        # a five-session run in units of this name's own five-session volatility
        sd5 = vol20 / np.sqrt(252) * np.sqrt(5) if vol20 == vol20 and vol20 > 0 else np.nan
        z = r5 / sd5 if sd5 == sd5 and sd5 > 0 else np.nan
        sd1 = vol20 / np.sqrt(252) if vol20 == vol20 and vol20 > 0 else np.nan
        r1 = run(1)
        z1 = r1 / sd1 if sd1 == sd1 and sd1 > 0 else np.nan
        gap = prior_8k(work / "cache", int(r.cik), d)
        big = ((abs(z) > 1.0 if z == z else False)
               or (abs(z1) > 1.5 if z1 == z1 else False))
        unexplained = big and gap >= 14
        rows.append(dict(
            date=r.date, ticker=r.ticker, cik=int(r.cik), acc=r.acc,
            accepted_et=r.accepted_et, timing=r.timing, entry=r.entry, exit=r.exit,
            items=r["items"], company=r.company, mktcap=r.mktcap, ps=r.ps,
            dvol=r.dvol, last_pre=lp, spot=float(c[j]),
            pre_run5=r5, pre_run4=run(4), pre_run1=run(1),
            pre_volratio=float(v[j] / med) if med == med and med > 0 else np.nan,
            vol20=vol20, run_z=z, run_z1=z1, gap_prev=gap,
            already_priced=bool(unexplained),
        ))

    P = pd.DataFrame(rows)
    P.to_parquet(args.out)
    print(f"  {len(P)} events with pre-filing tape context "
          f"(all measured to the last close before acceptance)\n")
    print(f"  already-priced flag set on {int(P.already_priced.sum())} of {len(P)}")
    print(f"  median |5-session run| {P.pre_run5.abs().median() * 100:.1f}%   "
          f"median realised vol {P.vol20.median() * 100:.0f}%\n")
    print(f"  {'date':12s}{'tkr':7s}{'run5':>8s}{'run1':>8s}{'z5':>7s}{'z1':>7s}{'vol':>6s}"
          f"{'volx':>6s}{'gap':>5s}{'priced?':>9s}  items")
    for _, r in P.sort_values(["date", "ticker"]).iterrows():
        z = "  n/a" if r.run_z != r.run_z else f"{r.run_z:>+6.1f}"
        z1 = "  n/a" if r.run_z1 != r.run_z1 else f"{r.run_z1:>+6.1f}"
        vx = "  n/a" if r.pre_volratio != r.pre_volratio else f"{r.pre_volratio:>5.1f}"
        print(f"  {r.date:12s}{r.ticker:7s}{r.pre_run5 * 100:>+7.1f}%{r.pre_run1 * 100:>+7.1f}%"
              f"{z}{z1}{r.vol20 * 100:>5.0f}%{vx}{min(r.gap_prev, 999):>5.0f}"
              f"{('ALREADY' if r.already_priced else '-'):>9s}  {str(r['items'])[:22]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
