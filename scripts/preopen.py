"""Pre-open scanner: the ranked list you act on at 09:30, not at lunchtime.

Why this exists
---------------
On 3 Aug 2026 all 94 8-K filings of the day were accepted before the 09:30
open -- the last at 08:57 ET -- and the four largest gap-ups gave back
everything after it:

    ATKR  +28.0% gap ->  +0.1% from the open
    BOW   +10.3% gap ->  -0.1% from the open
    ALGT   +5.8% gap ->  -0.7% from the open
    CNH   +12.9% gap ->  -4.3% from the open

That is the whole problem in one session. The information is public between
roughly 02:00 and 09:00 ET, the opening auction prices it, and by mid-session
there is nothing left to trade and no volume to trade it with. A scan run at
14:00 is archaeology.

So this runs *before* the bell. It answers one question per name -- is this
worth an order at 09:30 -- and it refuses to answer the question it cannot:
which way the stock goes. Every direction test in this project has failed, so
nothing here scores sentiment or predicts a move. It ranks on things that are
knowable in advance and were shown to matter:

1. **Could the filing carry a defined payoff?** Only the item codes are used
   here -- a material agreement or a completed acquisition outranks an officer
   change. Whether the payoff is actually defined still needs a human to open
   the exhibit, which is what the WATCH list is for.
2. **Will the company sell stock into it?** ``dilution_armed`` reads the
   registration record. An effective shelf caps good news without capping bad.
3. **Can it be filled?** Pre-market dollar volume does not exist -- Yahoo
   returns extended-hours bars with a null volume field -- so depth is taken
   from how many pre-market minutes actually printed, plus the name's prior
   twenty-session dollar volume.
4. **Has it already been paid?** A name that gapped 28% pre-market has
   delivered its move to whoever held it overnight, not to you.

The output is deliberately a shortlist with reasons attached, not a signal.
The last column is the one that matters: what would have to be true for the
trade to work.

Known limitation: the dilution flag answers "if I hold this through the news,
do I keep the upside", and that is not the same question as "does it bounce
today". On 3 Aug it skipped TWST for a live shelf, and TWST gapped -12.1% then
ran +14.6% off the open. The filter is not wrong -- it is answering the
question it was built for -- but it should not be read as a same-session call.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dilution_armed import ARMED, history, label  # noqa: E402

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"

#: Items that can carry a defined payoff. 1.01 is a material agreement, 2.01 a
#: completed acquisition, 8.01 the catch-all companies use for merger and
#: regulatory news. 7.01 is Reg FD, which is where most press releases land.
HIGH_VALUE_ITEMS = {"1.01", "2.01", "8.01", "7.01", "2.02"}

#: Items that are almost always administrative. 5.02 is an officer or director
#: change; on 3 Aug it accounted for a third of the day's filings and not one
#: of them moved a stock more than noise.
ADMIN_ITEMS = {"5.02", "5.03", "5.07", "3.01"}


def accepted_since(client, ticker: str, cik: str, since) -> list[dict]:
    """8-Ks accepted after ``since``.

    ``acceptanceDateTime`` is UTC and carries a ``Z`` suffix, so pandas parses
    the offset directly. Do not re-localize it -- reading it as Eastern shifts
    every filing four hours and moves the post-close spike into the evening.
    """
    blob = client.get(SUBMISSIONS.format(cik=cik))
    if not blob:
        return []
    rec = blob.get("filings", {}).get("recent", {})
    forms = rec.get("form", [])
    out = []
    for i, form in enumerate(forms[:20]):
        if not str(form).startswith("8-K"):
            continue
        raw = rec.get("acceptanceDateTime", [None] * len(forms))[i]
        if not raw:
            continue
        et = pd.Timestamp(raw).tz_convert("America/New_York")
        if et < since:
            continue
        out.append({"ticker": ticker, "cik": cik,
                    "sic": str(blob.get("sic", "")).strip(), "et": et,
                    "items": rec.get("items", [""] * len(forms))[i] or "",
                    "accession": rec.get("accessionNumber", [""] * len(forms))[i],
                    "doc": rec.get("primaryDocument", [""] * len(forms))[i]})
    return out


def premarket(client, ticker: str) -> dict | None:
    """Pre-market tape, plus the prior depth that says whether 09:30 will fill.

    Yahoo returns extended-hours 1-minute bars with a **null volume** field --
    254 pre-market bars for ATKR on 3 Aug, every one of them zero. So dollar
    volume cannot be measured before the bell and any gate built on it silently
    passes nothing. Two things that *are* knowable stand in for it:

    ``pre_bars``  how many minutes actually printed since 04:00. A name trading
                  continuously has someone on the other side; one with a handful
                  of prints does not. On 3 Aug this ranked ATKR 254, AUTL 86,
                  RCKT 39 against realised day volumes of $538m, $22m and $7m.
    ``adv20_m``   the last twenty sessions' median dollar volume, which is the
                  name's normal depth and is fixed before the open.
    """
    from iai.sources.prices import BROWSER_UA, YAHOO_CHART
    blob = client.get(YAHOO_CHART.format(symbol=ticker),
                      params={"range": "1d", "interval": "1m",
                              "includePrePost": "true"},
                      headers={"User-Agent": BROWSER_UA})
    res = (blob or {}).get("chart", {}).get("result")
    if not res:
        return None
    r = res[0]
    meta, q = r.get("meta", {}), r["indicators"]["quote"][0]
    ts = r.get("timestamp") or []
    if not ts:
        return None
    d = pd.DataFrame({
        "t": pd.to_datetime(ts, unit="s", utc=True).tz_convert("America/New_York"),
        "c": q.get("close")}).dropna(subset=["c"])
    prev = meta.get("chartPreviousClose")
    pre = d[d.t.dt.time < pd.Timestamp("09:30").time()]
    if not prev or pre.empty:
        return None
    last = float(pre.c.iloc[-1])

    day = client.get(YAHOO_CHART.format(symbol=ticker),
                     params={"range": "3mo", "interval": "1d",
                             "includePrePost": "false"},
                     headers={"User-Agent": BROWSER_UA})
    adv = np.nan
    dres = (day or {}).get("chart", {}).get("result")
    if dres:
        dq = dres[0]["indicators"]["quote"][0]
        b = pd.DataFrame({"c": dq.get("close"), "v": dq.get("volume")}).dropna()
        if len(b) > 21:
            adv = float((b.c * b.v).iloc[-21:-1].median())

    return {"prev_close": round(float(prev), 2), "pre_last": round(last, 2),
            "pre_gap_pct": round((last / float(prev) - 1) * 100, 1),
            "pre_bars": int(len(pre)),
            "adv20_m": round(adv / 1e6, 2) if np.isfinite(adv) else 0.0}


def verdict(row: dict) -> tuple[str, str]:
    """What would have to be true for this to work. Never a direction."""
    if row["armed_score"] >= 3:
        return "SKIP", "shelf live -- good news gets sold into an offering"
    if row["pre_bars"] < 15 or row["adv20_m"] < 1.0:
        return "SKIP", "too thin to fill at the open"
    if abs(row["pre_gap_pct"]) >= 20:
        return "SKIP", "already gapped; the move went to overnight holders"
    if row["admin_only"]:
        return "SKIP", "administrative items only"
    if row["armed_score"] == 0 and abs(row["pre_gap_pct"]) < 8:
        return "WATCH", "clear of dilution and not yet repriced -- read the 8-K"
    return "WATCH", "read the 8-K before the bell"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--user-agent", required=True)
    ap.add_argument("--since", default=None,
                    help="YYYY-MM-DDTHH:MM ET; default 16:00 ET yesterday")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--min-pre-bars", type=int, default=5,
                    help="pre-market minutes that printed, to be worth listing")
    args = ap.parse_args(argv)
    root = Path(args.root)

    from iai.core.config import Config
    from iai.core.http import HttpClient
    cfg = Config.load()
    sec = HttpClient(cfg.data.cache_dir, args.user_agent, rate_per_sec=9.0,
                     ttl_hours=0.25, max_retries=5)
    yah = HttpClient(cfg.data.cache_dir, args.user_agent, rate_per_sec=12.0,
                     ttl_hours=0.02, max_retries=3)

    now = pd.Timestamp.now(tz="America/New_York")
    since = (pd.Timestamp(args.since, tz="America/New_York") if args.since
             else (now.normalize() - pd.Timedelta(days=1)) + pd.Timedelta(hours=16))
    print(f"8-Ks accepted since {since:%Y-%m-%d %H:%M} ET   (now {now:%H:%M} ET)\n",
          flush=True)

    pool = pd.read_parquet(root / "candidate_pool.parquet")
    pool["cik"] = pool["cik"].astype(str).str.zfill(10)

    fil = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(accepted_since, sec, r.ticker, r.cik, since)
                for r in pool.itertuples()]
        for k, fu in enumerate(as_completed(futs), 1):
            if k % 1500 == 0:
                print(f"  {k}/{len(pool)} filers, {len(fil)} filings", flush=True)
            try:
                fil.extend(fu.result())
            except Exception:                                   # noqa: BLE001
                continue
    if not fil:
        print("nothing filed in the window")
        return 0
    f = pd.DataFrame(fil)
    print(f"{len(f)} filings, {f.ticker.nunique()} names\n", flush=True)

    # One row per name, keeping its most informative filing.
    f["items_set"] = f["items"].apply(
        lambda s: {x.strip() for x in str(s).split(",") if x.strip()})
    f["high_value"] = f.items_set.apply(lambda s: bool(s & HIGH_VALUE_ITEMS))
    f["admin_only"] = f.items_set.apply(lambda s: bool(s) and not (s - ADMIN_ITEMS))
    f = (f.sort_values(["high_value", "et"], ascending=[False, False])
           .drop_duplicates("ticker", keep="first"))

    names = sorted(f.ticker.unique())
    tape = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(premarket, yah, t): t for t in names}
        for fu in as_completed(futs):
            try:
                v = fu.result()
            except Exception:                                   # noqa: BLE001
                v = None
            if v:
                tape[futs[fu]] = v
    f = f[f.ticker.isin(tape)].copy()
    for c in ("prev_close", "pre_last", "pre_gap_pct", "pre_bars", "adv20_m"):
        f[c] = f.ticker.map(lambda t, c=c: tape[t][c])
    f = f[f.pre_bars >= args.min_pre_bars]
    if f.empty:
        print("nothing with pre-market depth")
        return 0

    arm = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(history, sec, r.ticker, r.cik, now): r.ticker
                for r in f.itertuples()}
        for fu in as_completed(futs):
            try:
                v = fu.result()
            except Exception:                                   # noqa: BLE001
                continue
            arm[futs[fu]] = v
    f["armed_score"] = f.ticker.map(lambda t: arm.get(t, {}).get("armed_score", 0))
    f["dilution"] = f.armed_score.map(label)

    rows = f.to_dict("records")
    for r in rows:
        r["call"], r["because"] = verdict(r)
    out = pd.DataFrame(rows).sort_values(
        ["call", "adv20_m"], ascending=[True, False])

    show = out[["ticker", "et", "items", "pre_gap_pct", "pre_bars", "adv20_m",
                "dilution", "call", "because"]].copy()
    show["et"] = show.et.dt.strftime("%H:%M")
    show = show.rename(columns={"pre_gap_pct": "gap%", "pre_bars": "preBar",
                                "adv20_m": "adv$m"})
    print(show.to_string(index=False))

    out.to_parquet(root / f"preopen_{now:%Y%m%d}.parquet")
    n_watch = int((out.call == "WATCH").sum())
    print(f"\n{n_watch} to read before the bell, {len(out) - n_watch} skipped")
    print("Direction is not scored here and never has been. Read the filing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
