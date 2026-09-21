"""Score tonight's scheduled filers against the one finding that survived.

The surviving result is narrow and weak, and this script exists to apply it
without dressing it up: a five-session run into the last close, in units of the
name's own volatility, on names that are liquid and expensive (trailing
price-to-sales at or above 8.0x). Run up, expect a gap down; run down, expect a
gap up; inside +/-0.5 sigma, nothing.

Measured out of sample on 656 events it is right 55.5% of the time, P = 0.0055,
with a mean edge of +0.5% per event whose day-clustered interval still touches
zero. It is a direction, not a profit, and the borrow cost on the short arm has
never been measured.

The entry price for an after-close release is that same session's close, which
has not happened while the market is open. Every ``run_z`` here is therefore
computed to the **previous** close and will move before it is actionable.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import options_screen as osc  # noqa: E402

RUN, VOL, GATE = 5, 20, 0.5


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", required=True, help="comma separated")
    ap.add_argument("--panel", default="/tmp/claude-0/opt/panel")
    ap.add_argument("--cache", default="/tmp/claude-0/opt/cache")
    ap.add_argument("--min-dvol", type=float, default=20e6)
    args = ap.parse_args(argv)
    cache = Path(args.cache)
    pan = Path(args.panel)

    C = pd.read_parquet(pan / "c.parquet")
    D = pd.read_parquet(pan / "dvol.parquet")
    asof = C.index[-1]
    print(f"  prices through {asof} (the entry close has not happened yet)\n")

    ct = json.loads((cache / "company_tickers.json").read_text())
    tk2cik = {v["ticker"]: int(v["cik_str"]) for v in ct.values()}

    rows = []
    for t in [x.strip().upper() for x in args.tickers.split(",") if x.strip()]:
        if t not in C.columns:
            rows.append(dict(ticker=t, note="not in the US tape / too illiquid to appear"))
            continue
        c = C[t].dropna()
        if len(c) < VOL + RUN + 1:
            rows.append(dict(ticker=t, note="too little price history"))
            continue
        lr = np.diff(np.log(c.to_numpy()))
        sd = float(np.std(lr[-VOL:], ddof=1))
        r5 = float(c.iloc[-1] / c.iloc[-1 - RUN] - 1)
        rz = r5 / (sd * np.sqrt(RUN)) if sd > 0 else np.nan
        dv = float(D[t].dropna().iloc[-60:].median())

        cik = tk2cik.get(t)
        cap = ps = float("nan")
        cls = "no CIK"
        if cik:
            f = cache / f"facts_{cik}.json"
            if not f.exists():
                r = subprocess.run(
                    ["curl", "-sS", "--compressed", "--max-time", "40",
                     "-H", f"User-Agent: {osc.UA}", osc.FACTS.format(cik)],
                    capture_output=True, text=True)
                if r.returncode == 0 and r.stdout.strip():
                    f.write_text(r.stdout)
            try:
                fx = json.loads(f.read_text()) if f.exists() and f.read_text().strip() else None
            except json.JSONDecodeError:
                fx = None
            # A foreign private issuer files IFRS and reports on 6-K/20-F, never
            # on an 8-K item 2.02. The 55.5% was measured only on item-2.02
            # filers, so these are outside the universe entirely -- not merely
            # unscreenable. Saying "revenue unmeasurable" would blame the screen
            # for what is really a different kind of company.
            if fx and "facts" in fx and "us-gaap" not in fx["facts"]:
                rows.append(dict(ticker=t, close=float(c.iloc[-1]), run5=r5,
                                 run_z=rz, vol_ann=sd * np.sqrt(252), dvol=dv,
                                 mktcap=float("nan"), ps=float("nan"),
                                 rev_class="IFRS filer", note="",
                                 foreign=True))
                continue
            if fx and "facts" in fx:
                when = pd.Timestamp(asof)
                sh = float("nan")
                for tax, tag in osc.SHARE_TAGS:
                    sh = osc.cc.stock(fx, tax, tag, when)
                    if sh == sh and sh > 0:
                        break
                rev = osc._revenue(fx, when)
                if sh == sh:
                    cap = sh * float(c.iloc[-1])
                    if rev != rev:
                        ps, cls = float("nan"), "revenue unmeasurable"
                    elif rev > 0:
                        ps, cls = cap / rev, "reported"
                    else:
                        ps, cls = float("inf"), "pre-revenue"
                else:
                    cls = "no share count filed"
            else:
                cls = "no XBRL on file"
        rows.append(dict(ticker=t, close=float(c.iloc[-1]), run5=r5, run_z=rz,
                         vol_ann=sd * np.sqrt(252), dvol=dv, mktcap=cap, ps=ps,
                         rev_class=cls, note="", foreign=False))

    R = pd.DataFrame(rows)
    live = R[R.note == ""].copy() if "note" in R else R
    print(f"  {'tkr':7s}{'close':>9s}{'5d run':>9s}{'run_z':>8s}{'vol':>7s}"
          f"{'$vol':>9s}{'cap':>9s}{'P/S':>9s}  revenue")
    for _, r in R.iterrows():
        if r.get("note"):
            print(f"  {r.ticker:7s}  -- {r.note}")
            continue
        ps = ("    inf" if r.ps == np.inf else "    n/a" if r.ps != r.ps
              else f"{r.ps:>7.0f}" if r.ps > 999 else f"{r.ps:>7.1f}")
        cap = "    n/a" if r.mktcap != r.mktcap else f"{r.mktcap/1e9:>6.2f}B"
        print(f"  {r.ticker:7s}{r.close:>9.2f}{r.run5*100:>+8.1f}%{r.run_z:>+8.2f}"
              f"{r.vol_ann*100:>6.0f}%{r.dvol/1e6:>8.0f}M{cap:>9s}{ps:>9s}  {r.rev_class}")

    print(f"\n  {'tkr':7s}{'liquid?':>10s}{'P/S >= 8?':>11s}{'|run_z|>0.5?':>14s}   verdict")
    for _, r in live.iterrows():
        lq = r.dvol >= args.min_dvol
        rich = (r.ps >= osc.MIN_PS) if r.ps == r.ps else False
        sig = abs(r.run_z) > GATE if r.run_z == r.run_z else False
        if r.get("foreign"):
            v = "OUT OF UNIVERSE: files 6-K/20-F, never an 8-K item 2.02"
            print(f"  {r.ticker:7s}{'yes' if lq else 'no':>10s}{'n/a':>11s}"
                  f"{'yes' if sig else 'no':>14s}   {v}")
            continue
        if lq and rich and sig:
            v = f"SIGNAL -> {'short (ran up)' if r.run_z > 0 else 'long (ran down)'}"
        elif not lq:
            v = "no trade: too illiquid"
        elif not rich:
            v = "no trade: outside the P/S >= 8 universe where the effect exists"
        else:
            v = "no trade: run inside +/-0.5 sigma"
        print(f"  {r.ticker:7s}{'yes' if lq else 'no':>10s}{'yes' if rich else 'no':>11s}"
              f"{'yes' if sig else 'no':>14s}   {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
