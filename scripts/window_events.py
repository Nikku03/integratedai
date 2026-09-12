"""Every 8-K in a date window, with its item codes and the moment it went public.

Built in the order that keeps the expensive step small. The daily index gives
filings and CIKs but no item codes and no timestamp; those live in a per-company
submissions document, and fetching one for each of ~2,300 filers is both slow and
the step that has stalled this pipeline twice. So the cheap filters run first:
map CIK to ticker, join to the tape, and drop anything that does not trade enough
to carry a weekly option chain. What survives is a few hundred filers, not a few
thousand.

Every fetch goes through curl with ``--max-time``. urllib's timeout is per socket
operation, so a response that trickles never trips it -- that is what wedged the
fundamentals screen at exactly 700 of 1,424 filers.

``acceptanceDateTime`` is stamped UTC despite its trailing Z. Read as Eastern it
puts the 8-K clusters at 11:00-13:00 and 20:00-22:00 local, which is nobody's
filing pattern; converted from UTC it puts them at 07:00-09:00 and 16:00-18:00,
which is exactly the pattern.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from options_straddle import legs_for, load_bars  # noqa: E402

UA = "Naresh Chhillar chhillarnaresh03@gmail.com"
SUBS = "https://data.sec.gov/submissions/CIK{:010d}.json"
ROW = re.compile(r"^(?P<form>\S+(?:\s\S+)*?)\s{2,}(?P<comp>.+?)\s{2,}"
                 r"(?P<cik>\d{1,10})\s+(?P<date>\d{8})\s+(?P<file>edgar/data/\S+)\s*$")


def curl_json(url: str, dest: Path) -> dict | None:
    if dest.exists():
        t = dest.read_text()
        return json.loads(t) if t.strip() else None
    r = subprocess.run(["curl", "-sS", "--compressed", "--max-time", "40",
                        "-H", f"User-Agent: {UA}", url],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    dest.write_text(r.stdout)
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--dates", required=True, help="comma-separated YYYYMMDD")
    ap.add_argument("--min-dollar-vol", type=float, default=20e6)
    ap.add_argument("--exclude", default="", help="tickers to drop, comma separated")
    ap.add_argument("--out", default="/tmp/claude-0/opt/win_events.parquet")
    args = ap.parse_args(argv)
    work = Path(args.work)
    cache = work / "cache"
    cache.mkdir(parents=True, exist_ok=True)

    rows = []
    for d in args.dates.split(","):
        p = work / f"form.{d}.idx"
        if not p.exists():
            print(f"  missing index for {d}")
            continue
        for ln in p.read_text(errors="ignore").splitlines():
            if not ln.startswith("8-K"):
                continue
            m = ROW.match(ln.rstrip())
            if not m or m.group("form") != "8-K":
                continue
            g = m.groupdict()
            rows.append(dict(cik=int(g["cik"]), company=g["comp"], date=g["date"],
                             acc=g["file"].rsplit("/", 1)[-1].replace(".txt", "")))
    F = pd.DataFrame(rows)
    print(f"  {len(F):,} 8-K filings over {F.date.nunique()} sessions, "
          f"{F.cik.nunique():,} filers")

    ct = curl_json("https://www.sec.gov/files/company_tickers.json",
                   cache / "company_tickers.json") or {}
    cik2tk = collections.defaultdict(list)
    for v in ct.values():
        cik2tk[int(v["cik_str"])].append(v["ticker"])

    bars, sessions = load_bars(work)
    drop = {t.strip().upper() for t in args.exclude.split(",") if t.strip()}

    keep = []
    for _, r in F.iterrows():
        day = f"{r.date[:4]}-{r.date[4:6]}-{r.date[6:]}"
        prior = [s for s in sessions if s < day]
        if not prior:
            continue
        for t in cik2tk.get(r.cik, []):
            b = bars.get(prior[-1], {}).get(t)
            if b is None:
                continue
            dv = b["c"] * b["v"]
            if dv < args.min_dollar_vol or t in drop:
                continue
            keep.append(dict(r, ticker=t, dvol=dv, prev_close=b["c"]))
            break
    K = pd.DataFrame(keep)
    print(f"  {len(K):,} have a ticker trading at least "
          f"${args.min_dollar_vol / 1e6:.0f}M/day ({K.ticker.nunique():,} names)")
    if drop:
        print(f"  excluded by name: {', '.join(sorted(drop))}")

    ciks = sorted(K.cik.unique())
    def one(c):
        return c, curl_json(SUBS.format(int(c)), cache / f"subs_{int(c)}.json")
    subs = {}
    with ThreadPoolExecutor(5) as ex:
        for i, (c, d) in enumerate(ex.map(one, ciks), 1):
            if d:
                subs[c] = d
            if i % 100 == 0:
                print(f"    ... {i}/{len(ciks)} submissions", flush=True)
    print(f"  metadata for {len(subs):,}/{len(ciks):,} filers")

    out = []
    for _, r in K.iterrows():
        d = subs.get(r.cik)
        if not d:
            continue
        rec = d["filings"]["recent"]
        idx = {a: i for i, a in enumerate(rec["accessionNumber"])}
        i = idx.get(r.acc)
        if i is None:
            continue
        et = pd.Timestamp(rec["acceptanceDateTime"][i]).tz_convert("America/New_York")
        day = f"{r.date[:4]}-{r.date[4:6]}-{r.date[6:]}"
        entry, exit_ = legs_for(sessions, et)
        out.append(dict(date=day, ticker=r.ticker, cik=int(r.cik), acc=r.acc,
                        company=r.company, items=rec["items"][i],
                        doc=rec["primaryDocument"][i], accepted_et=et.isoformat(),
                        timing=("pre-open" if et.hour * 60 + et.minute < 570
                                else "after-close" if et.hour * 60 + et.minute >= 960
                                else "intraday"),
                        entry=entry, exit=exit_, dvol=r.dvol,
                        prev_close=r.prev_close))
    E = pd.DataFrame(out).drop_duplicates(subset=["ticker", "acc"])
    E = E[E.entry.notna() & E.exit.notna()].reset_index(drop=True)
    E.to_parquet(args.out)
    print(f"\n  {len(E):,} events held across a bell, {E.ticker.nunique():,} names")
    print(f"  timing: {E.timing.value_counts().to_dict()}")
    top = collections.Counter()
    for s in E["items"]:
        for it in str(s).split(","):
            if it.strip():
                top[it.strip()] += 1
    print(f"  most common items: {dict(top.most_common(10))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
