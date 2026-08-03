"""What the pre-open scan would actually have handed you, marked to the tape.

A tool that cannot be scored is a tool that cannot be wrong, so this replays
``preopen.py`` under the information available at a chosen wall-clock time and
then marks every name it listed against what the session did.

The discipline that makes it a replay and not a re-fit:

* only filings **accepted before** the cutoff are visible;
* the pre-market gap is measured from bars **before** the cutoff, so a name that
  moved between 09:00 and the bell does not leak backwards into its own score;
* the dilution flag reads registration history, which is weeks old by
  construction and cannot leak;
* entry is the **09:30 open**, the first price a resting order could touch. Not
  the pre-market print, which nobody was filled at.

The number that matters is not the WATCH list's return. It is the WATCH list's
return *minus the SKIP list's*. A filter that keeps the same names the market
was going to hand you anyway has done nothing, however good the WATCH column
looks in isolation.

One session is one observation. Nothing here is evidence of an edge and it is
not written as though it were.
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

from dilution_armed import history, label  # noqa: E402
from preopen import ADMIN_ITEMS, HIGH_VALUE_ITEMS, accepted_since, verdict  # noqa: E402


def session(client, ticker: str, cutoff) -> dict | None:
    """Pre-market as of ``cutoff``, then the regular session that followed."""
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
        "c": q.get("close"), "v": q.get("volume")}).dropna(subset=["c"])
    prev = meta.get("chartPreviousClose")
    if not prev:
        return None

    # Everything the scanner could see at the cutoff.
    pre = d[d.t <= cutoff]
    pre = pre[pre.t.dt.time < pd.Timestamp("09:30").time()]
    if pre.empty:
        return None

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

    # Everything that happened afterwards.
    reg = d[d.t.dt.time >= pd.Timestamp("09:30").time()]
    if len(reg) < 5:
        return None
    entry = float(reg.c.iloc[0])
    last = float(reg.c.iloc[-1])
    return {
        "prev_close": float(prev),
        "pre_gap_pct": round((float(pre.c.iloc[-1]) / float(prev) - 1) * 100, 1),
        "pre_bars": int(len(pre)),
        "adv20_m": round(adv / 1e6, 2) if np.isfinite(adv) else 0.0,
        "entry": round(entry, 2),
        "last": round(last, 2),
        "ret_pct": round((last / entry - 1) * 100, 2),
        "max_up_pct": round((float(reg.c.max()) / entry - 1) * 100, 2),
        "max_dn_pct": round((float(reg.c.min()) / entry - 1) * 100, 2),
        "reg_dollar_m": round(float((reg.c * reg.v.fillna(0)).sum()) / 1e6, 1),
        "mins": int(len(reg)),
    }


def cohort(d: pd.DataFrame, name: str) -> dict:
    if d.empty:
        return {"cohort": name, "n": 0}
    return {"cohort": name, "n": len(d),
            "mean%": round(float(d.ret_pct.mean()), 2),
            "median%": round(float(d.ret_pct.median()), 2),
            "win%": round(float((d.ret_pct > 0).mean() * 100), 1),
            "best%": round(float(d.ret_pct.max()), 1),
            "worst%": round(float(d.ret_pct.min()), 1),
            "mean_maxup%": round(float(d.max_up_pct.mean()), 2),
            "mean_maxdn%": round(float(d.max_dn_pct.mean()), 2)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--user-agent", required=True)
    ap.add_argument("--cutoff", default=None,
                    help="YYYY-MM-DDTHH:MM ET; the moment the scan is imagined "
                         "to run. Default 09:00 today.")
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args(argv)
    root = Path(args.root)

    from iai.core.config import Config
    from iai.core.http import HttpClient
    cfg = Config.load()
    sec = HttpClient(cfg.data.cache_dir, args.user_agent, rate_per_sec=9.0,
                     ttl_hours=0.5, max_retries=5)
    yah = HttpClient(cfg.data.cache_dir, args.user_agent, rate_per_sec=12.0,
                     ttl_hours=0.02, max_retries=3)

    now = pd.Timestamp.now(tz="America/New_York")
    cutoff = (pd.Timestamp(args.cutoff, tz="America/New_York") if args.cutoff
              else now.normalize() + pd.Timedelta(hours=9))
    since = cutoff.normalize() - pd.Timedelta(days=1) + pd.Timedelta(hours=16)
    print(f"scan imagined at {cutoff:%Y-%m-%d %H:%M} ET; "
          f"filings since {since:%m-%d %H:%M} ET; marked at {now:%H:%M} ET\n",
          flush=True)

    pool = pd.read_parquet(root / "candidate_pool.parquet")
    pool["cik"] = pool["cik"].astype(str).str.zfill(10)

    fil = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(accepted_since, sec, r.ticker, r.cik, since)
                for r in pool.itertuples()]
        for fu in as_completed(futs):
            try:
                fil.extend(fu.result())
            except Exception:                                   # noqa: BLE001
                continue
    f = pd.DataFrame(fil)
    f = f[f.et <= cutoff].copy()
    print(f"{len(f)} filings visible at the cutoff, {f.ticker.nunique()} names",
          flush=True)

    f["items_set"] = f["items"].apply(
        lambda s: {x.strip() for x in str(s).split(",") if x.strip()})
    f["high_value"] = f.items_set.apply(lambda s: bool(s & HIGH_VALUE_ITEMS))
    f["admin_only"] = f.items_set.apply(lambda s: bool(s) and not (s - ADMIN_ITEMS))
    f = (f.sort_values(["high_value", "et"], ascending=[False, False])
           .drop_duplicates("ticker", keep="first"))

    tape = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(session, yah, t, cutoff): t for t in sorted(f.ticker)}
        for fu in as_completed(futs):
            try:
                v = fu.result()
            except Exception:                                   # noqa: BLE001
                v = None
            if v:
                tape[futs[fu]] = v
    f = f[f.ticker.isin(tape)].copy()
    for c in ("pre_gap_pct", "pre_bars", "adv20_m", "entry", "last", "ret_pct",
              "max_up_pct", "max_dn_pct", "reg_dollar_m", "mins"):
        f[c] = f.ticker.map(lambda t, c=c: tape[t][c])
    f = f[f.pre_bars >= 5]

    arm = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(history, sec, r.ticker, r.cik, cutoff): r.ticker
                for r in f.itertuples()}
        for fu in as_completed(futs):
            try:
                arm[futs[fu]] = fu.result()
            except Exception:                                   # noqa: BLE001
                continue
    f["armed_score"] = f.ticker.map(lambda t: arm.get(t, {}).get("armed_score", 0))
    f["dilution"] = f.armed_score.map(label)

    rows = f.to_dict("records")
    for r in rows:
        r["call"], r["because"] = verdict(r)
    o = pd.DataFrame(rows)

    w = o[o.call == "WATCH"].sort_values("ret_pct", ascending=False)
    s = o[o.call == "SKIP"]
    print(f"\nWATCH {len(w)}   SKIP {len(s)}\n")
    print("=" * 78)
    print("THE WATCH LIST, ENTERED AT THE 09:30 OPEN")
    print("=" * 78)
    show = w[["ticker", "et", "items", "pre_gap_pct", "entry", "last",
              "ret_pct", "max_up_pct", "max_dn_pct", "reg_dollar_m"]].copy()
    show["et"] = show.et.dt.strftime("%H:%M")
    print(show.rename(columns={"pre_gap_pct": "gap%", "ret_pct": "ret%",
                               "max_up_pct": "maxUp%", "max_dn_pct": "maxDn%",
                               "reg_dollar_m": "$m"}).to_string(index=False))

    print("\n" + "=" * 78)
    print("DID THE FILTER DO ANYTHING?  equal weight, entered at the open")
    print("=" * 78)
    c = pd.DataFrame([cohort(w, "WATCH"), cohort(s, "SKIP"), cohort(o, "ALL")])
    print(c.to_string(index=False))
    if len(w) and len(s):
        d = float(w.ret_pct.mean() - s.ret_pct.mean())
        rng = np.random.default_rng(11)
        wv, sv = w.ret_pct.to_numpy(), s.ret_pct.to_numpy()
        boot = np.array([rng.choice(wv, len(wv), True).mean()
                         - rng.choice(sv, len(sv), True).mean()
                         for _ in range(20000)])
        lo, hi = np.percentile(boot, [2.5, 97.5])
        print(f"\nWATCH - SKIP = {d:+.2f}pp   bootstrap 95% CI "
              f"[{lo:+.2f}, {hi:+.2f}]   P(<=0) = {(boot <= 0).mean():.3f}")
        print("One session. A CI computed on n=1 day describes this day only "
              "and forecasts nothing.")

    for r in [cohort(s[s.armed_score >= 3], "  of which shelf-live"),
              cohort(s[s.pre_gap_pct.abs() >= 20], "  of which already gapped")]:
        if r["n"]:
            print(f"{r['cohort']:28s} n={r['n']:3d}  mean {r['mean%']:+6.2f}%  "
                  f"median {r['median%']:+6.2f}%")

    o.to_parquet(root / f"preopen_replay_{cutoff:%Y%m%d_%H%M}.parquet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
