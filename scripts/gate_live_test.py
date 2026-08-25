"""Test the catalyst gate alone on unseen 2026 data.

`catalyst_pipeline.py` found one thing that worked and several that did not.
Ranking inside a universe restricted to names with a recent 8-K returned +2.197%
per trade against +1.695% ungated, while every block layered on top — volume
surge, Markov crowd state, REM correction — made it worse. So this tests the
part that earned it, and nothing else.

The gate is rebuilt from EDGAR rather than reused
-------------------------------------------------
The panel's 8-K columns stop at 2025-12-31, so a live test needs filings the
panel never had. Both periods are therefore built from the same source: the
quarterly ``form.idx``, parsed for 8-K rows, mapped to tickers through the SEC's
current ``company_tickers.json``. One gate definition across training and test,
rather than the panel's columns before 2026 and something else after — which
would confound a change in the gate with a change in the market.

A filing dated D is treated as usable from session **D+1**. 8-Ks are frequently
accepted after the close, and a same-day gate would be trading on information the
tape had not seen.

Three arms, because "the gate" means two different things
---------------------------------------------------------
* **universe** — every eligible name. The control.
* **gate basket** — every gated name, equally weighted. This asks whether simply
  owning catalyst names beats owning everything. Historically it did *not*: the
  buy-all return inside the 8-K gate was +0.11% against +0.26% ungated.
* **gate + ranking** — top k inside the gate, scored by a model trained on
  historical gated rows. This is where the +2.197% came from, so this is the arm
  under test.

The ranker uses only features computable from OHLCV in both periods — the REM
diffusion block and the post-filing surge block. The panel's fundamentals,
insider and government columns do not exist for 2026 without a refetch, and
training on features the test cannot have would be a broken comparison rather
than a hard one.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agreed_strategy import daily_paths  # noqa: E402
from catalyst_pipeline import surge_features  # noqa: E402
from moonshot_tail import scale_fit  # noqa: E402
from rem_solver import _roll_count, _roll_sum, compile_shared, infer  # noqa: E402

HORIZON = 10
COST = 20.0 / 1e4
ROW = re.compile(r"^(\S+)\s+(.+?)\s\s+(\d+)\s+(\d{4}-\d{2}-\d{2})\s+(\S+)\s*$")
UA = "integratedai research chhillarnaresh03@gmail.com"


def eightks(client, y0: int, y1: int) -> pd.DataFrame:
    """Every 8-K in the quarterly indexes, as (cik, filed)."""
    out = []
    for y in range(y0, y1 + 1):
        for q in (1, 2, 3, 4):
            b = client.get_bytes(
                f"https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.idx")
            if not b:
                continue
            n = 0
            for line in b.decode("latin-1", errors="ignore").splitlines():
                if not line.startswith("8-K"):
                    continue
                m = ROW.match(line)
                if m and m.group(1).strip() == "8-K":
                    out.append((int(m.group(3)), m.group(4)))
                    n += 1
            print(f"    {y}Q{q}: {n:,}", flush=True)
    d = pd.DataFrame(out, columns=["cik", "filed"])
    d["filed"] = pd.to_datetime(d["filed"])
    return d.drop_duplicates()


def cik_map(client) -> dict:
    blob = client.get("https://www.sec.gov/files/company_tickers.json")
    if not blob:
        return {}
    return {int(v["cik_str"]): str(v["ticker"]).upper()
            for v in blob.values() if v.get("ticker")}


def since_matrix(px: pd.DataFrame, filings: pd.DataFrame) -> np.ndarray:
    """Sessions since the most recent usable 8-K, per row of the price panel."""
    sess = pd.DatetimeIndex(sorted(px.date.unique()))
    pos = {d: i for i, d in enumerate(sess)}
    # a filing dated D becomes usable on the next session
    f = filings.copy()
    j = np.searchsorted(sess.to_numpy(), f["filed"].to_numpy(), side="right")
    f = f[j < len(sess)]
    f["sidx"] = j[j < len(sess)]

    tick = px["ticker"].to_numpy()
    di = px["date"].map(pos).to_numpy()
    n = len(px)
    since = np.full(n, 9999.0)

    by = {}
    for t, s in zip(f["ticker"].to_numpy(), f["sidx"].to_numpy()):
        by.setdefault(t, []).append(s)
    for t in by:
        by[t] = np.array(sorted(set(by[t])))

    order = np.argsort(tick, kind="stable")
    start = 0
    while start < n:
        end = start
        who = tick[order[start]]
        while end < n and tick[order[end]] == who:
            end += 1
        rows = order[start:end]
        arr = by.get(who)
        if arr is not None and len(arr):
            k = np.searchsorted(arr, di[rows], side="right") - 1
            ok = k >= 0
            since[rows[ok]] = di[rows[ok]] - arr[k[ok]]
        start = end
    return since


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--recent", default="/root/.iai/wide2015/recent_prices.parquet")
    ap.add_argument("--from-year", type=int, default=2018)
    ap.add_argument("--gate-days", type=int, default=3)
    ap.add_argument("--days", type=int, default=15)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--min-adv", type=float, default=1e6)
    ap.add_argument("--min-price", type=float, default=1.0)
    args = ap.parse_args(argv)
    root = Path(args.root)

    from iai.core.config import Config
    from iai.core.http import HttpClient
    from sklearn.ensemble import HistGradientBoostingRegressor
    cfg = Config.load()
    cl = HttpClient(cfg.data.cache_dir, UA, rate_per_sec=6.0, ttl_hours=24 * 365)

    old = pd.read_parquet(root / "w2015_prices.parquet",
                          columns=["date", "ticker", "open", "high", "low",
                                   "close", "volume"])
    old["date"] = pd.to_datetime(old["date"])
    new = pd.read_parquet(args.recent)
    new["date"] = pd.to_datetime(new["date"])
    new = new[["date", "ticker", "open", "high", "low", "close", "volume"]]
    px = (pd.concat([old, new[new.date > old.date.max()]], ignore_index=True)
            .drop_duplicates(subset=["ticker", "date"], keep="last")
            .sort_values(["ticker", "date"]).reset_index(drop=True))
    print(f"prices: {len(px):,} bars to {px.date.max():%Y-%m-%d}", flush=True)

    print(f"\nparsing 8-K filings from {args.from_year}", flush=True)
    f = eightks(cl, args.from_year, 2026)
    m = cik_map(cl)
    f["ticker"] = f["cik"].map(m)
    f = f.dropna(subset=["ticker"])
    uni = set(px.ticker.unique())
    f = f[f.ticker.isin(uni)]
    print(f"  {len(f):,} 8-K filings mapped into the {len(uni):,}-ticker universe "
          f"({f.ticker.nunique():,} distinct)", flush=True)
    print(f"  latest filing indexed: {f.filed.max():%Y-%m-%d}", flush=True)

    since = since_matrix(px, f)
    print(f"  rows with an 8-K within {args.gate_days} sessions: "
          f"{(since <= args.gate_days).mean() * 100:.1f}%", flush=True)

    # ---- eligibility, REM and surge -------------------------------------
    c_all = px["close"].to_numpy(float)
    v_all = np.nan_to_num(px["volume"].to_numpy(float), nan=0.0)
    t_all = px["ticker"].to_numpy()
    adv = _roll_sum(c_all * v_all, t_all, 20) / np.maximum(_roll_count(t_all, 20), 1)
    mu, sig = compile_shared(px)
    yrem, Frem, _ = infer(mu, sig, HORIZON)
    SG, _ = surge_features(px, since)
    elig = (np.isfinite(sig) & (adv >= args.min_adv) & (c_all >= args.min_price))
    print(f"  eligible bars: {int(elig.sum()):,}", flush=True)

    idx = np.flatnonzero(elig)[:: args.stride]
    paths = daily_paths(px, idx, HORIZON)
    ret = np.nanprod(1.0 + np.nan_to_num(paths, nan=0.0), axis=1) - 1.0
    full = np.isfinite(paths[:, HORIZON - 1])
    ret = np.where(np.isfinite(paths[:, 0]) & (np.abs(ret) <= 3.0), ret, np.nan)

    dates = pd.Series(pd.to_datetime(px["date"].to_numpy()[idx]))
    tick = px["ticker"].to_numpy()[idx]
    A = np.column_stack([Frem[idx], yrem[idx].reshape(-1, 1), SG[idx]]).astype(np.float32)
    gated = (since[idx] >= 1) & (since[idx] <= args.gate_days)

    sess = pd.DatetimeIndex(sorted(px.date.unique()))
    scored_end = sess[-(HORIZON + 1)]
    win = sess[sess <= scored_end][-args.days:]
    print(f"\nSCORED window {win[0]:%Y-%m-%d} .. {win[-1]:%Y-%m-%d} "
          f"({len(win)} sessions)", flush=True)

    cutoff = win[0] - pd.Timedelta(days=HORIZON * 2 + 14)
    tr = np.flatnonzero((dates < cutoff).to_numpy() & np.isfinite(ret) & gated)
    if len(tr) > 250_000:
        tr = tr[np.linspace(0, len(tr) - 1, 250_000).astype(int)]
    print(f"training the in-gate ranker on {len(tr):,} gated rows "
          f"before {cutoff:%Y-%m-%d}", flush=True)
    med, sc = scale_fit(A[tr])
    mo = HistGradientBoostingRegressor(loss="quantile", quantile=0.75,
                                       max_iter=250, learning_rate=0.05,
                                       max_depth=6, random_state=0)
    mo.fit(np.clip((A[tr] - med) / sc, -5, 5), ret[tr])

    inwin = dates.isin(win).to_numpy() & full & np.isfinite(ret)
    t = pd.DataFrame({"date": dates[inwin].to_numpy(), "ticker": tick[inwin],
                      "ret": ret[inwin], "gated": gated[inwin],
                      "p": mo.predict(np.clip((A[inwin] - med) / sc, -5, 5))})
    print(f"  {len(t):,} scorable candidates, {int(t.gated.sum()):,} gated "
          f"({t.gated.mean() * 100:.1f}%), "
          f"{t[t.gated].groupby('date').size().median():.0f} gated names/session\n",
          flush=True)

    uni_day = t.groupby("date").ret.mean()
    rows_out = []

    def report(name, sel):
        if not len(sel):
            return
        day = sel.groupby("date").ret.mean()
        common = day.index.intersection(uni_day.index)
        ex = (day.loc[common] - uni_day.loc[common]).to_numpy()
        rng = np.random.default_rng(61)
        bs = np.array([rng.choice(ex, len(ex), True).mean() for _ in range(20000)])
        lo, hi = np.percentile(bs, [2.5, 97.5])
        rows_out.append((name, len(sel), sel.ret.mean() * 100 - COST * 100,
                         ex.mean() * 100, lo * 100, hi * 100, (bs <= 0).mean()))

    report("universe (control)", t)
    report("gate basket (all gated)", t[t.gated])
    for k in (1, 5):
        report(f"gate + rank, k={k}",
               t[t.gated].sort_values("p", ascending=False).groupby("date").head(k))
        report(f"UNGATED + rank, k={k}",
               t.sort_values("p", ascending=False).groupby("date").head(k))

    print("=" * 104)
    print("THE GATE ALONE, ON UNSEEN DATA")
    print("=" * 104)
    print(f"  {'arm':26s} {'n':>6s} {'mean ret':>10s} {'vs universe':>12s} "
          f"{'95% CI (day-clustered)':>26s} {'P(<=0)':>8s}")
    for nm, n, mr, ex, lo, hi, p in rows_out:
        flag = "  PASS" if lo > 0 else ""
        print(f"  {nm:26s} {n:>6,} {mr:>+9.2f}% {ex:>+11.2f}pp "
              f"  [{lo:>+6.2f}, {hi:>+6.2f}]pp {p:>8.3f}{flag}")

    g = t[t.gated].sort_values("p", ascending=False).groupby("date").head(5)
    print(f"\n  gated k=5 picks, session by session:")
    for dte, grp in g.groupby("date"):
        names = "  ".join(f"{r.ticker}{r.ret * 100:+.0f}%" for _, r in grp.iterrows())
        print(f"    {dte:%Y-%m-%d}  {grp.ret.mean() * 100:>+7.2f}%   {names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
