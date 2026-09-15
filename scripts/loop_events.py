"""Every scheduled earnings release over the panel's span, point-in-time.

Same shape as ``window_events.py`` but over two years instead of one window, so
the ordering that keeps the expensive step small matters more, not less. The
daily index gives filings and CIKs but no item codes and no timestamp; those live
in a per-company submissions document. So the cheap filters run first -- map CIK
to ticker, join to the tape, drop anything that cannot carry a liquid trade --
and only what survives costs a request.

Liquidity is measured **as of the session before the filing**, from a trailing
60-session median. A full-sample screen would quietly decide today which names
were tradeable two years ago.

``acceptanceDateTime`` is stamped UTC despite the trailing Z. Read as Eastern it
puts the 8-K clusters at 11:00-13:00 and 20:00-22:00 local, which is nobody's
filing pattern; converted from UTC it lands at 07:00-09:00 and 16:00-18:00,
which is exactly it.
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

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from options_straddle import legs_for  # noqa: E402

UA = "Naresh Chhillar chhillarnaresh03@gmail.com"
SUBS = "https://data.sec.gov/submissions/CIK{:010d}.json"
ROW = re.compile(r"^(?P<form>\S+(?:\s\S+)*?)\s{2,}(?P<comp>.+?)\s{2,}"
                 r"(?P<cik>\d{1,10})\s+(?P<date>\d{8})\s+(?P<file>edgar/data/\S+)\s*$")
LIQ_WIN = 60


def curl_json(url: str, dest: Path) -> dict | None:
    if dest.exists():
        t = dest.read_text()
        return json.loads(t) if t.strip() else None
    r = subprocess.run(["curl", "-sS", "--compressed", "--max-time", "40",
                        "-H", f"User-Agent: {UA}", url], capture_output=True, text=True)
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
    ap.add_argument("--panel", default="/tmp/claude-0/opt/panel")
    ap.add_argument("--out", default="/tmp/claude-0/opt/loop_events.parquet")
    ap.add_argument("--min-price", type=float, default=5.0)
    ap.add_argument("--min-dvol", type=float, default=20e6)
    args = ap.parse_args(argv)
    work, pan = Path(args.work), Path(args.panel)
    cache = work / "cache"
    cache.mkdir(parents=True, exist_ok=True)

    C = pd.read_parquet(pan / "c.parquet")
    D = pd.read_parquet(pan / "dvol.parquet")
    sessions = C.index.tolist()
    # point-in-time liquidity: what was true at the close before the filing
    liq = (D.rolling(LIQ_WIN, min_periods=40).median() >= args.min_dvol) & (C >= args.min_price)
    print(f"  panel {len(sessions)} sessions {sessions[0]} -> {sessions[-1]}, "
          f"{C.shape[1]:,} tickers")

    rows = []
    for p in sorted(work.glob("form.*.idx")):
        d = p.stem.split(".")[-1]
        day = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        if day < sessions[0] or day > sessions[-1]:
            continue
        for ln in p.read_text(errors="ignore").splitlines():
            if not ln.startswith("8-K"):
                continue
            m = ROW.match(ln.rstrip())
            if not m or m.group("form") != "8-K":
                continue
            g = m.groupdict()
            rows.append((int(g["cik"]), g["comp"], day,
                         g["file"].rsplit("/", 1)[-1].replace(".txt", "")))
    F = pd.DataFrame(rows, columns=["cik", "company", "date", "acc"])
    print(f"  {len(F):,} 8-K filings over {F.date.nunique():,} sessions, "
          f"{F.cik.nunique():,} filers")

    ct = curl_json("https://www.sec.gov/files/company_tickers.json",
                   cache / "company_tickers.json") or {}
    cik2tk = collections.defaultdict(list)
    for v in ct.values():
        cik2tk[int(v["cik_str"])].append(v["ticker"])

    pos = {s: i for i, s in enumerate(sessions)}
    cols = {t: i for i, t in enumerate(C.columns)}
    LQ = liq.to_numpy()
    keep = []
    for cik, comp, day, acc in F.itertuples(index=False):
        i = pos.get(day)
        if not i:
            continue
        for t in cik2tk.get(cik, []):
            j = cols.get(t)
            if j is not None and LQ[i - 1, j]:
                keep.append((cik, comp, day, acc, t))
                break
    K = pd.DataFrame(keep, columns=["cik", "company", "date", "acc", "ticker"])
    print(f"  {len(K):,} on a ticker liquid at the prior close "
          f"({K.ticker.nunique():,} names, {K.cik.nunique():,} filers)")

    ciks = sorted(K.cik.unique())
    have = sum((cache / f"subs_{c}.json").exists() for c in ciks)
    print(f"  submissions: {have:,}/{len(ciks):,} already cached, "
          f"fetching {len(ciks) - have:,}", flush=True)

    def one(c):
        return c, curl_json(SUBS.format(int(c)), cache / f"subs_{int(c)}.json")

    subs = {}
    with ThreadPoolExecutor(6) as ex:
        for n, (c, d) in enumerate(ex.map(one, ciks), 1):
            if d:
                subs[c] = dict(
                    sic=str(d.get("sic") or ""),
                    sicd=(d.get("sicDescription") or "")[:48],
                    idx={a: i for i, a in enumerate(d["filings"]["recent"]["accessionNumber"])},
                    items=d["filings"]["recent"]["items"],
                    acc_dt=d["filings"]["recent"]["acceptanceDateTime"])
            if n % 500 == 0:
                print(f"    ... {n}/{len(ciks)} filers", flush=True)
    print(f"  metadata for {len(subs):,}/{len(ciks):,} filers")

    out = []
    for cik, comp, day, acc, tk in K.itertuples(index=False):
        s = subs.get(cik)
        if not s:
            continue
        i = s["idx"].get(acc)
        if i is None:
            continue
        items = str(s["items"][i] or "")
        if not any(x.strip() == "2.02" for x in items.split(",")):
            continue
        et = pd.Timestamp(s["acc_dt"][i]).tz_convert("America/New_York")
        entry, exit_ = legs_for(sessions, et)
        if entry is None or exit_ is None:
            continue
        mins = et.hour * 60 + et.minute
        out.append(dict(date=day, ticker=tk, cik=int(cik), acc=acc, company=comp,
                        sic=s["sic"], sic_desc=s["sicd"], items=items,
                        accepted_et=et.isoformat(), entry=entry, exit=exit_,
                        timing="pre-open" if mins < 570 else "after-close"))
    E = pd.DataFrame(out).drop_duplicates(subset=["ticker", "acc"])
    E = E.sort_values(["entry", "ticker"]).reset_index(drop=True)
    E.to_parquet(args.out)
    print(f"\n  {len(E):,} item-2.02 releases held across a bell")
    print(f"  {E.ticker.nunique():,} names, {E.entry.nunique():,} entry sessions, "
          f"{E.sic.nunique():,} SIC codes")
    print(f"  timing: {E.timing.value_counts().to_dict()}")
    print(f"  span {E.entry.min()} -> {E.entry.max()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
