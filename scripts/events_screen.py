"""Screen a scheduled-event calendar to the names worth buying a straddle on.

Same two screens as the directional test -- market cap $300M-$20B and trailing
price-to-sales at or above 8.0x -- and the same point-in-time discipline: the
share count is the one filed before the release existed, the price is the close
of the last session that closed before it, and trailing revenue is what had been
filed by that moment. `options_screen._revenue` supplies the top line and carries
the five corrections documented there.

Two screens are added, both about being able to trade the thing:

* **dollar volume on the entry session.** A name has to be liquid before it can
  have a weekly option chain. This is a cheap pre-filter so that Polygon requests
  -- limited to five a minute -- are not spent on names that cannot qualify.
* **the release must not land mid-session.** A straddle can only be positioned
  before an event and closed into the gap if the event happens while the market
  is shut. An intraday release is dropped rather than approximated.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import options_screen as osc  # noqa: E402
from options_straddle import legs_for, load_bars  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--calendar", default="/tmp/claude-0/opt/cal_earnings.parquet")
    ap.add_argument("--out", default="/tmp/claude-0/opt/events.parquet")
    ap.add_argument("--min-dollar-vol", type=float, default=20e6)
    args = ap.parse_args(argv)
    work = Path(args.work)
    cache = work / "cache"
    cache.mkdir(parents=True, exist_ok=True)

    E = pd.read_parquet(args.calendar)
    bars, sessions = load_bars(work)
    n0 = len(E)

    rows = []
    for _, r in E.iterrows():
        et = pd.Timestamp(r.accepted_et)
        entry, exit_ = legs_for(sessions, et)
        if entry is None or exit_ is None:
            continue
        b = bars.get(entry, {}).get(r.ticker)
        if b is None or bars.get(exit_, {}).get(r.ticker) is None:
            continue
        rows.append(dict(r, entry=entry, exit=exit_, pre_close=b["c"],
                         dvol=b["c"] * b["v"]))
    D = pd.DataFrame(rows)
    print(f"  {n0:,} releases -> {len(D):,} held across a bell with a price both sides")

    D = D[D.dvol >= args.min_dollar_vol].reset_index(drop=True)
    print(f"  {len(D):,} trade at least ${args.min_dollar_vol / 1e6:.0f}M a day "
          f"({D.ticker.nunique()} names)")

    # Cache only. urllib's timeout is per socket operation, so a companyfacts
    # body that trickles never trips it, and this screen wedged twice -- at 600
    # and then at exactly 700 of 1,424 filers -- on a single oversized response.
    # Rather than keep fighting it, the screen runs on the filers already on
    # disk and says plainly which ones it could not see. The filers it has are
    # the ones it reached first, not a selected subset, but a reader should know
    # the coverage is partial before reading anything downstream of it.
    ciks = sorted(D.cik.unique())
    out, seen, missed = [], 0, 0
    for n, (c, g) in enumerate(D.groupby("cik"), 1):
        # One filer at a time, then dropped. Holding 1,170 parsed companyfacts
        # at once is several gigabytes and gets the process OOM-killed.
        p = cache / f"facts_{int(c)}.json"
        t = p.read_text() if p.exists() else ""
        if not t.strip():
            missed += 1
            continue
        try:
            fx = json.loads(t)
        except json.JSONDecodeError:
            missed += 1
            continue
        seen += 1
        for _, r in g.iterrows():
            when = pd.Timestamp(r.entry)       # facts must be filed before entry
            sh = float("nan")
            for tax, tag in osc.SHARE_TAGS:
                sh = osc.cc.stock(fx, tax, tag, when)
                if sh == sh and sh > 0:
                    break
            rev = osc._revenue(fx, when)
            cap = sh * r.pre_close if sh == sh else float("nan")
            if cap != cap:
                continue
            if rev != rev:
                ps, cls = float("nan"), "unmeasured"
            elif rev >= osc.MIN_MEANINGFUL_REV:
                ps, cls = cap / rev, "reported"
            elif rev > 0:
                ps, cls = cap / rev, "negligible"
            else:
                ps, cls = float("inf"), "pre-revenue"
            out.append(dict(r, shares=sh, revenue_ttm=rev, mktcap=cap,
                            ps=ps, rev_class=cls))
        del fx
        if n % 200 == 0:
            print(f"    ... {n}/{len(ciks)} filers screened", flush=True)

    print(f"  XBRL on disk for {seen:,}/{len(ciks):,} filers "
          f"({seen / max(len(ciks), 1) * 100:.0f}% coverage, {missed:,} never fetched)")
    print(f"  releases behind a filer with no facts on disk are invisible to this "
          f"screen, not rejected by it")
    S = pd.DataFrame(out)

    cap_ok = S.mktcap.between(osc.MIN_CAP, osc.MAX_CAP)
    ps_ok = S.ps.notna() & (S.ps >= osc.MIN_PS)
    print(f"\n  in the $300M-$20B band:      {cap_ok.sum():,}")
    print(f"  at price-to-sales >= 8.0x:   {ps_ok.sum():,}")
    print(f"  **both**:                    {(cap_ok & ps_ok).sum():,}")

    K = S[cap_ok & ps_ok].sort_values(["date", "dvol"], ascending=[True, False])
    K = K.drop_duplicates(subset=["ticker", "entry"]).reset_index(drop=True)
    K.to_parquet(args.out)
    print(f"  {len(K)} events written ({K.ticker.nunique()} names, "
          f"{K.date.nunique()} sessions)\n")
    print(f"  {'date':12s}{'tkr':7s}{'timing':13s}{'cap':>8s}{'P/S':>8s}{'$vol':>8s}  company")
    for _, r in K.iterrows():
        ps = f"{r.ps:>7.0f}" if r.ps > 999 else f"{r.ps:>7.1f}"
        print(f"  {r.date:12s}{r.ticker:7s}{r.timing:13s}{r.mktcap / 1e9:>7.2f}B{ps}"
              f"{r.dvol / 1e6:>7.0f}M  {r.company[:34]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
