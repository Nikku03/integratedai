"""Why the trades lost: diagnose the selection rule, not the 38 outcomes.

Reading the losing trades and writing a rule that would have avoided them is
how you fit a curve to 38 numbers. `RESULT_LLM_GATE.md` already shows what that
costs -- the narrow veto looked worth +4.9pp per trade pooled over two windows
and turned out to rest on one swap.

So this asks the same question where there is power. Every hypothesis the
losers suggest is tested on the **historical gated panel** -- roughly 160,000
rows across thirteen walk-forward blocks -- rather than on the live windows.

Three questions, in order of how much they would explain
--------------------------------------------------------
1. **Is the ranker negative?** `RESULT_CATALYST_GATE.md` records that ranking
   the gate on REM and surge alone gives −1.7pp at k=1 historically, against a
   universe of −0.04%. If that still holds with the context block added, then
   the losing trades are not bad luck: the selection rule picks losers, and
   every reading layer built on top inherits that.
2. **What does the q75 objective actually select?** A quantile model targets the
   upper tail of the conditional distribution. If the names it likes are simply
   the most volatile ones, it is a volatility sorter wearing a return label, and
   the losses are the other side of the same coin.
3. **Does anything in the context block predict return inside the gate?** Decile
   sorts, walk-forward, on every column. Not "did it separate the 38", but "does
   it separate 160,000".

Only what survives (3) is worth putting in front of the reader again.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import company_context as cc  # noqa: E402
from agreed_strategy import daily_paths  # noqa: E402
from catalyst_pipeline import surge_features  # noqa: E402
from gate_live_test import UA, cik_map, since_matrix  # noqa: E402
from llm_gate_pick import eightks_with_acc, scale_fit  # noqa: E402
from rem_solver import _roll_count, _roll_sum, compile_shared, infer  # noqa: E402

HORIZON = 10
COST = 20.0 / 1e4
#: A label spanning H sessions cannot be allowed to overlap the training set.
EMBARGO = max(14, int(np.ceil(HORIZON * 7 / 5)))


def build_panel(args):
    from iai.core.config import Config
    from iai.core.http import HttpClient
    cfg = Config.load()
    cl = HttpClient(cfg.data.cache_dir, UA, rate_per_sec=6.0, ttl_hours=24 * 365)
    root = Path(args.root)
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

    print("indexing 8-K filings", flush=True)
    f = eightks_with_acc(cl, args.from_year, 2026)
    f["ticker"] = f["cik"].map(cik_map(cl))
    f = f.dropna(subset=["ticker"])
    f = f[f.ticker.isin(set(px.ticker.unique()))]
    since = since_matrix(px, f[["ticker", "filed"]])

    c_all = px["close"].to_numpy(float)
    v_all = np.nan_to_num(px["volume"].to_numpy(float), nan=0.0)
    t_all = px["ticker"].to_numpy()
    adv = _roll_sum(c_all * v_all, t_all, 20) / np.maximum(_roll_count(t_all, 20), 1)
    mu, sig = compile_shared(px)
    yrem, Frem, _ = infer(mu, sig, HORIZON)
    SG, _ = surge_features(px, since)
    PF = cc.panel_features(px, since)
    elig = np.isfinite(sig) & (adv >= args.min_adv) & (c_all >= args.min_price)

    idx = np.flatnonzero(elig)[:: args.stride]
    paths = daily_paths(px, idx, HORIZON)
    ret = np.nanprod(1.0 + np.nan_to_num(paths, nan=0.0), axis=1) - 1.0
    full = np.isfinite(paths[:, HORIZON - 1])
    ret = np.where(np.isfinite(paths[:, 0]) & (np.abs(ret) <= 3.0), ret, np.nan)

    d = pd.DataFrame({
        "date": pd.to_datetime(px["date"].to_numpy()[idx]),
        "ticker": px["ticker"].to_numpy()[idx],
        "ret": ret, "since": since[idx],
    })
    A = np.column_stack([Frem[idx], yrem[idx].reshape(-1, 1), SG[idx]]).astype(np.float32)
    X = PF[idx].astype(np.float32)
    gated = (d["since"].to_numpy() >= 1) & (d["since"].to_numpy() <= args.gate_days)
    ok = np.isfinite(d["ret"].to_numpy()) & full & gated
    d, A, X = d[ok].reset_index(drop=True), A[ok], X[ok]
    print(f"  gated, labelled rows: {len(d):,} over "
          f"{d.date.min():%Y-%m} to {d.date.max():%Y-%m}", flush=True)
    return d, A, X


def blocks(dates: pd.Series, months: int = 6):
    """Walk-forward test blocks with a training set that stops before the embargo."""
    lo, hi = dates.min(), dates.max()
    edges = pd.date_range(lo, hi + pd.DateOffset(months=months), freq=f"{months}MS")
    for a, b in zip(edges, edges[1:]):
        te = (dates >= a) & (dates < b)
        tr = dates < (a - pd.Timedelta(days=EMBARGO))
        if te.sum() > 500 and tr.sum() > 20_000:
            yield a, tr.to_numpy(), te.to_numpy()


def q75_scores(A, X, ret, tr, te, use_ctx: bool, seed: int = 0):
    from sklearn.ensemble import HistGradientBoostingRegressor
    M = np.column_stack([A, X]) if use_ctx else A
    Xtr = M[tr]
    if len(Xtr) > 250_000:
        keep = np.linspace(0, len(Xtr) - 1, 250_000).astype(int)
        Xtr, ytr = Xtr[keep], ret[tr][keep]
    else:
        ytr = ret[tr]
    med, sc = scale_fit(Xtr)
    mo = HistGradientBoostingRegressor(loss="quantile", quantile=0.75, max_iter=250,
                                       learning_rate=0.05, max_depth=6,
                                       random_state=seed)
    mo.fit(np.clip((Xtr - med) / sc, -5, 5), ytr)
    return mo.predict(np.clip((M[te] - med) / sc, -5, 5))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--recent", default="/root/.iai/wide2015/recent_prices.parquet")
    ap.add_argument("--from-year", type=int, default=2018)
    ap.add_argument("--gate-days", type=int, default=3)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--min-adv", type=float, default=1e6)
    ap.add_argument("--min-price", type=float, default=1.0)
    args = ap.parse_args(argv)

    d, A, X = build_panel(args)
    ret = d["ret"].to_numpy()
    dates = d["date"]

    print("\n" + "=" * 92)
    print("1. IS THE RANKER NEGATIVE?  walk-forward, ranked inside the gate")
    print("=" * 92)
    rows = []
    for a, tr, te in blocks(dates):
        for tag, ctx in (("REM+surge", False), ("+context", True)):
            p = q75_scores(A, X, ret, tr, te, ctx)
            sub = d[te].copy()
            sub["p"] = p
            k1 = sub.sort_values("p", ascending=False).groupby("date").head(1)
            k3 = sub.sort_values("p", ascending=False).groupby("date").head(3)
            rows.append({"block": a, "arm": tag, "pool": sub.ret.mean(),
                         "k1": k1.ret.mean(), "k3": k3.ret.mean(),
                         "n": len(sub), "days": sub.date.nunique()})
        print(f"  {a:%Y-%m} done ({rows[-1]['days']} sessions)", flush=True)
    R = pd.DataFrame(rows)
    print()
    for tag in ("REM+surge", "+context"):
        s = R[R.arm == tag]
        w = np.average
        print(f"  {tag:11s} gated pool {w(s.pool, weights=s.n) * 100 - COST * 100:+6.2f}%   "
              f"k=1 {w(s.k1, weights=s.days) * 100 - COST * 100:+6.2f}%   "
              f"k=3 {w(s.k3, weights=s.days) * 100 - COST * 100:+6.2f}%   "
              f"blocks where k=1 beat the pool: "
              f"{int((s.k1.to_numpy() > s.pool.to_numpy()).sum())}/{len(s)}")

    print("\n" + "=" * 92)
    print("2. WHAT DOES THE q75 OBJECTIVE SELECT?  top decile vs rest, by block")
    print("=" * 92)
    keep = []
    for a, tr, te in blocks(dates):
        p = q75_scores(A, X, ret, tr, te, True)
        sub = d[te].copy()
        sub["p"] = p
        for i, c in enumerate(cc.PANEL_COLS):
            sub[c] = X[te][:, i]
        sub["top"] = sub.p >= sub.p.quantile(0.90)
        keep.append(sub)
    S = pd.concat(keep, ignore_index=True)
    print(f"  {'feature':16s}{'top decile':>14s}{'rest':>12s}{'ratio':>9s}")
    for c in cc.PANEL_COLS:
        t, r = S[S.top][c].median(), S[~S.top][c].median()
        if not np.isfinite(t) or not np.isfinite(r):
            continue
        print(f"  {c:16s}{t:>14.3f}{r:>12.3f}"
              + (f"{t / r:>9.2f}" if abs(r) > 1e-9 else f"{'-':>9s}"))
    print(f"\n  realised |return| top decile {S[S.top].ret.abs().mean() * 100:.2f}%  "
          f"vs rest {S[~S.top].ret.abs().mean() * 100:.2f}%   "
          f"-> dispersion ratio {S[S.top].ret.abs().mean() / S[~S.top].ret.abs().mean():.2f}x")
    print(f"  realised  return  top decile {S[S.top].ret.mean() * 100:+.2f}%  "
          f"vs rest {S[~S.top].ret.mean() * 100:+.2f}%")

    print("\n" + "=" * 92)
    print("3. DOES ANY CONTEXT COLUMN PREDICT RETURN INSIDE THE GATE?")
    print("=" * 92)
    print(f"  {'feature':16s}{'D1':>9s}{'D5':>9s}{'D10':>9s}{'D10-D1':>10s}{'monotone':>10s}"
          f"{'|ret| D10/D1':>14s}")
    for c in cc.PANEL_COLS:
        v = S[c].to_numpy()
        if np.isfinite(v).sum() < 1000 or len(np.unique(v[np.isfinite(v)])) < 20:
            continue
        q = pd.qcut(pd.Series(v), 10, labels=False, duplicates="drop")
        g = S.assign(dec=q).dropna(subset=["dec"]).groupby("dec")["ret"]
        m = g.mean() * 100
        a_ = S.assign(dec=q).dropna(subset=["dec"]).groupby("dec")["ret"].apply(
            lambda x: x.abs().mean())
        if len(m) < 10:
            continue
        sp = np.corrcoef(np.arange(len(m)), m.to_numpy())[0, 1]
        print(f"  {c:16s}{m.iloc[0]:>+8.2f}%{m.iloc[len(m) // 2]:>+8.2f}%{m.iloc[-1]:>+8.2f}%"
              f"{m.iloc[-1] - m.iloc[0]:>+9.2f}pp{sp:>10.2f}"
              f"{a_.iloc[-1] / a_.iloc[0]:>14.2f}x")
    print("\n  'monotone' is the correlation between decile index and mean return:")
    print("  near zero means the sort carries no direction, whatever the endpoints do.")

    print("\n" + "=" * 92)
    print("4. THE CORRECTION THAT FOLLOWS: SIZE, NOT SELECTION")
    print("=" * 92)
    print("  Volatility sorts realised |return| 4.9x and mean return not at all, so it")
    print("  is a magnitude signal with no direction in it. Equal-dollar sizing throws")
    print("  that away and lets the widest names set the drawdown. These variants keep")
    print("  the same picks and change only the weights.\n")
    print("  mean log(1+r) is the statistic that matters: it is what compounds, and it")
    print("  is what a fat loser destroys. Arithmetic mean can be positive while it is")
    print("  negative, and then the book shrinks anyway.\n")
    print(f"  {'book':34s}{'trades':>8s}{'mean':>9s}{'median':>9s}{'sd':>8s}"
          f"{'mean log':>10s}{'-> per trade':>13s}{'worst':>9s}")

    def report(name, rows, w=None):
        r = np.clip(np.asarray(rows, float), -0.99, None)
        if w is None:
            w = np.ones_like(r)
        w = np.asarray(w, float)
        w = w / w.mean()
        lg = np.log1p(r) * w
        g = np.exp(lg.mean()) - 1.0
        print(f"  {name:34s}{len(r):>8d}{(r * w).mean() * 100:>+8.2f}%"
              f"{np.median(r * w) * 100:>+8.2f}%{(r * w).std() * 100:>7.1f}%"
              f"{lg.mean():>+10.4f}{g * 100:>+12.2f}%{(r * w).min() * 100:>+8.1f}%")

    allsub = []
    for a, tr, te in blocks(dates):
        p_ = q75_scores(A, X, ret, tr, te, True)
        sub = d[te].copy()
        sub["p"] = p_
        sub["vol"] = X[te][:, list(cc.PANEL_COLS).index("ctx_vol20")]
        allsub.append(sub)
    S2 = pd.concat(allsub, ignore_index=True)
    S2["net"] = S2.ret - COST

    for k in (1, 3, 5, 10):
        sel = S2.sort_values("p", ascending=False).groupby("date").head(k)
        report(f"k={k}, equal dollars", sel.net.to_numpy())

    sel5 = S2.sort_values("p", ascending=False).groupby("date").head(5).copy()
    v = sel5["vol"].to_numpy()
    v = np.where(np.isfinite(v) & (v > 0.05), v, np.nanmedian(v))
    # inverse-volatility weights, capped so one quiet name cannot dominate
    iw = np.clip((np.nanmedian(v) / v), 0.25, 4.0)
    report("k=5, inverse-volatility sized", sel5.net.to_numpy(), iw)

    cut = S2.groupby("date")["vol"].transform(lambda x: x.quantile(0.80))
    calm = S2[S2.vol <= cut]
    sel5c = calm.sort_values("p", ascending=False).groupby("date").head(5)
    report("k=5, drop top vol quintile", sel5c.net.to_numpy())

    print("\n  The comparison that matters is the last column against k=1: whether")
    print("  changing only the weights turns a shrinking book into a growing one.")
    print("  The inverse-volatility row weights per-trade returns rather than")
    print("  simulating a book, so read it as an indication; the vol-quintile row")
    print("  is an unweighted subset and is exact.")

    print("\n" + "=" * 92)
    print("5. THE OBJECTIVE ITSELF: q75 OF r  vs  MEAN OF log(1+r)")
    print("=" * 92)
    print("  If the book shrinks while the average trade is profitable, the model is")
    print("  optimising the wrong number. A q75 quantile of the return targets the")
    print("  upper tail, which is exactly the part that does not compound. Training")
    print("  the same features on log(1+r) targets growth directly.\n")
    print(f"  {'objective':34s}{'trades':>8s}{'mean':>9s}{'median':>9s}{'sd':>8s}"
          f"{'mean log':>10s}{'-> per trade':>13s}{'win':>7s}")

    from sklearn.ensemble import HistGradientBoostingRegressor

    def fit_predict(loss, y, tr, te, **kw):
        M = np.column_stack([A, X])
        Xtr, ytr = M[tr], y[tr]
        if len(Xtr) > 250_000:
            keep = np.linspace(0, len(Xtr) - 1, 250_000).astype(int)
            Xtr, ytr = Xtr[keep], ytr[keep]
        med, sc = scale_fit(Xtr)
        mo = HistGradientBoostingRegressor(loss=loss, max_iter=250, learning_rate=0.05,
                                           max_depth=6, random_state=0, **kw)
        mo.fit(np.clip((Xtr - med) / sc, -5, 5), ytr)
        return mo.predict(np.clip((M[te] - med) / sc, -5, 5))

    logret = np.log1p(np.clip(ret, -0.99, None))
    variants = {
        "q75 of r (incumbent)": ("quantile", ret, {"quantile": 0.75}),
        "mean of log(1+r)": ("squared_error", logret, {}),
        "median of log(1+r)": ("absolute_error", logret, {}),
        "mean of r": ("squared_error", ret, {}),
    }
    out = {k: [] for k in variants}
    for a, tr, te in blocks(dates):
        for name, (loss, y, kw) in variants.items():
            p_ = fit_predict(loss, y, tr, te, **kw)
            sub = d[te].copy()
            sub["p"] = p_
            sub["net"] = sub.ret - COST
            out[name].append(sub.sort_values("p", ascending=False)
                                .groupby("date").head(1).net.to_numpy())
    for name in variants:
        r = np.clip(np.concatenate(out[name]), -0.99, None)
        lg = np.log1p(r)
        print(f"  {name:34s}{len(r):>8d}{r.mean() * 100:>+8.2f}%{np.median(r) * 100:>+8.2f}%"
              f"{r.std() * 100:>7.1f}%{lg.mean():>+10.4f}{(np.exp(lg.mean()) - 1) * 100:>+12.2f}%"
              f"{(r > 0).mean() * 100:>6.1f}%")
    print("\n  A positive number in the second-to-last column would be the first")
    print("  configuration here that grows a compounded account. A negative one")
    print("  across every objective means the objective is not the problem.")

    print("\n" + "=" * 92)
    print("6. BOTH CORRECTIONS TOGETHER")
    print("=" * 92)
    print("  Sections 4 and 5 each found one lever that halves the drag: drop the")
    print("  most volatile quintile before ranking, and train on log(1+r) instead of")
    print("  a q75 quantile. Neither reaches zero alone. This is the pair, and it is")
    print("  the last configuration worth trying before concluding the book cannot")
    print("  be compounded at all.\n")
    print(f"  {'configuration':38s}{'trades':>8s}{'mean':>9s}{'median':>9s}{'sd':>8s}"
          f"{'mean log':>10s}{'-> per trade':>13s}{'win':>7s}")
    vi = list(cc.PANEL_COLS).index("ctx_vol20")
    combos = []
    for a, tr, te in blocks(dates):
        p_ = fit_predict("squared_error", logret, tr, te)
        sub = d[te].copy()
        sub["p"] = p_
        sub["vol"] = X[te][:, vi]
        sub["net"] = sub.ret - COST
        combos.append(sub)
    S3 = pd.concat(combos, ignore_index=True)
    cut = S3.groupby("date")["vol"].transform(lambda x: x.quantile(0.80))
    for name, frame, k in (("log objective, k=1, all names", S3, 1),
                           ("log objective, k=1, calm 80%", S3[S3.vol <= cut], 1),
                           ("log objective, k=5, calm 80%", S3[S3.vol <= cut], 5),
                           ("log objective, k=10, calm 80%", S3[S3.vol <= cut], 10)):
        sel = frame.sort_values("p", ascending=False).groupby("date").head(k)
        r = np.clip(sel.net.to_numpy(), -0.99, None)
        lg = np.log1p(r)
        print(f"  {name:38s}{len(r):>8d}{r.mean() * 100:>+8.2f}%{np.median(r) * 100:>+8.2f}%"
              f"{r.std() * 100:>7.1f}%{lg.mean():>+10.4f}{(np.exp(lg.mean()) - 1) * 100:>+12.2f}%"
              f"{(r > 0).mean() * 100:>6.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
