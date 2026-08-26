"""Skip filings the price already moved on, with nothing announced to explain it.

The proposal: if a stock jumps **before** a disclosure and no announcement
accounts for the jump, then either the information is already out -- leaked,
guessed, or traded on by someone who knew -- or the event is so routine that
everybody expects it. Either way the filing is not new information by the time
it can be traded, and the D+1 entry is buying an echo.

This is a different claim from the one already tested in
`RESULT_MISS_PATTERN.md`. That measured `ctx_mom20`, momentum up to the session
before **entry**, which on a D+1 gate already contains the filing day and its
reaction -- so it mixes "the market moved because it read the news" with "the
market moved before there was any news to read". `prefiling_features` separates
them: the run-up window ends the day *before* the filing exists, and `gap_prev`
says whether any other 8-K landed during it.

Four cells
----------
The interesting comparison is not run-up versus no run-up. It is:

* **ran up, nothing announced** -- the proposal's target. Unexplained move.
* **ran up, something announced** -- the move has a disclosed cause, so it is
  ordinary post-news drift rather than leakage.
* **flat, nothing announced** -- the base case.
* **flat, something announced** -- news that did not move the price.

If the proposal is right, the first cell is materially worse than the others,
and the difference is bigger than the crude "did the filing surge volume" test
already found (about -0.5pp).
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
import loss_autopsy as la  # noqa: E402
from agreed_strategy import daily_paths  # noqa: E402
from gate_live_test import UA, cik_map, since_matrix  # noqa: E402
from llm_gate_pick import eightks_with_acc  # noqa: E402
from rem_solver import _roll_count, _roll_sum, compile_shared  # noqa: E402


def build(args):
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

    c = px["close"].to_numpy(float)
    v = np.nan_to_num(px["volume"].to_numpy(float), nan=0.0)
    t = px["ticker"].to_numpy()
    adv = _roll_sum(c * v, t, 20) / np.maximum(_roll_count(t, 20), 1)
    _, sig = compile_shared(px)
    PF = cc.panel_features(px, since)
    QF = cc.prefiling_features(px, since)
    elig = np.isfinite(sig) & (adv >= args.min_adv) & (c >= args.min_price)

    idx = np.flatnonzero(elig)[:: args.stride]
    paths = daily_paths(px, idx, la.HORIZON)
    ret = np.nanprod(1.0 + np.nan_to_num(paths, nan=0.0), axis=1) - 1.0
    full = np.isfinite(paths[:, la.HORIZON - 1])
    ret = np.where(np.isfinite(paths[:, 0]) & (np.abs(ret) <= 3.0), ret, np.nan)

    S = pd.DataFrame({"date": pd.to_datetime(px["date"].to_numpy()[idx]),
                      "ticker": t[idx], "ret": ret, "since": since[idx]})
    for i, col in enumerate(cc.PANEL_COLS):
        S[col] = PF[idx][:, i]
    for i, col in enumerate(cc.PREFILE_COLS):
        S[col] = QF[idx][:, i]
    gated = (S["since"].to_numpy() >= 1) & (S["since"].to_numpy() <= args.gate_days)
    ok = np.isfinite(S["ret"].to_numpy()) & full & gated
    S = S[ok].reset_index(drop=True)
    S["net"] = S.ret - la.COST
    return S


def show(tag, s):
    if not len(s):
        print(f"  {tag:46s}{'—':>9s}")
        return
    lg = np.log1p(np.clip(s.net.to_numpy(), -0.99, None))
    print(f"  {tag:46s}{len(s):>9,d}{s.net.mean() * 100:>+9.2f}%"
          f"{s.net.median() * 100:>+9.2f}%{(s.net > 0).mean() * 100:>7.1f}%"
          f"{np.exp(lg.mean()) * 100 - 100:>11.2f}%")


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
    ap.add_argument("--quiet-gap", type=int, default=20,
                    help="sessions since the previous 8-K for the run-up to count "
                         "as unexplained")
    args = ap.parse_args(argv)

    S = build(args)
    S = S.dropna(subset=["pre_run20", "gap_prev", "filing_day_ret"])
    print(f"  gated rows with a pre-filing window: {len(S):,} "
          f"({S.date.min():%Y-%m} to {S.date.max():%Y-%m})")

    print("\n" + "=" * 92)
    print("0. IS THE PRE-FILING RUN-UP EVEN A DIFFERENT THING FROM ctx_mom20?")
    print("=" * 92)
    cr = S[["pre_run20", "ctx_mom20", "filing_day_ret", "ctx_volratio"]].corr().iloc[0]
    print(f"  corr(pre_run20, ctx_mom20)      {cr['ctx_mom20']:+.3f}   "
          "-- if this were ~1 the test would be redundant")
    print(f"  corr(pre_run20, filing_day_ret) {cr['filing_day_ret']:+.3f}")
    print(f"  corr(pre_run20, ctx_volratio)   {cr['ctx_volratio']:+.3f}")
    print(f"  median pre_run20 {S.pre_run20.median() * 100:+.2f}%   "
          f"90th pct {S.pre_run20.quantile(0.90) * 100:+.1f}%   "
          f"median gap to previous 8-K {S.gap_prev.median():.0f} sessions")

    print("\n" + "=" * 92)
    print("1. RETURN BY PRE-FILING RUN-UP, DECILES")
    print("=" * 92)
    q = pd.qcut(S.pre_run20, 10, labels=False, duplicates="drop")
    g = S.assign(dec=q).groupby("dec")
    print(f"  {'decile':10s}{'run-up':>10s}{'n':>9s}{'mean':>9s}{'median':>9s}{'win':>7s}")
    for k, sub in g:
        print(f"  {f'D{int(k)+1}':10s}{sub.pre_run20.median() * 100:>+9.1f}%{len(sub):>9,d}"
              f"{sub.net.mean() * 100:>+8.2f}%{sub.net.median() * 100:>+8.2f}%"
              f"{(sub.net > 0).mean() * 100:>6.1f}%")
    m = g.net.mean()
    print(f"  D10-D1 {(m.iloc[-1] - m.iloc[0]) * 100:+.2f}pp   "
          f"monotone {np.corrcoef(np.arange(len(m)), m.to_numpy())[0, 1]:+.2f}")

    print("\n" + "=" * 92)
    print("2. THE PROPOSAL: RAN UP, AND NOTHING WAS ANNOUNCED")
    print("=" * 92)
    hi = S.groupby("date")["pre_run20"].transform(lambda x: x.quantile(0.80))
    ran = S.pre_run20 >= hi
    quiet = S.gap_prev > args.quiet_gap
    print(f"  'ran up'   = top quintile of pre-filing 20-session return that day")
    print(f"  'quiet'    = no other 8-K in the {args.quiet_gap} sessions before the filing\n")
    print(f"  {'cell':46s}{'rows':>9s}{'mean':>9s}{'median':>9s}{'win':>7s}{'compounds':>11s}")
    show("the whole gate", S)
    show("ran up  AND quiet  <- the proposal's target", S[ran & quiet])
    show("ran up  AND something announced", S[ran & ~quiet])
    show("flat    AND quiet", S[~ran & quiet])
    show("flat    AND something announced", S[~ran & ~quiet])
    a, b = S[ran & quiet].net, S[~(ran & quiet)].net
    print(f"\n  target cell minus everything else: {(a.mean() - b.mean()) * 100:+.2f}pp")

    print("\n" + "=" * 92)
    print("3. AS A FILTER, AND AGAINST THE ONE ALREADY KNOWN TO WORK")
    print("=" * 92)
    surge = S.ctx_volratio >= S.groupby("date")["ctx_volratio"].transform(
        lambda x: x.quantile(0.80))
    print(f"  {'kept set':46s}{'rows':>9s}{'mean':>9s}{'median':>9s}{'win':>7s}{'compounds':>11s}")
    show("everything (baseline)", S)
    show("drop: filing-day volume surge (known, ~-0.5pp)", S[~surge])
    show("drop: ran up and quiet", S[~(ran & quiet)])
    show("drop: both", S[~surge & ~(ran & quiet)])

    print("\n" + "=" * 92)
    print("4. DAY-CLUSTERED BOOTSTRAP ON THE PROPOSAL")
    print("=" * 92)
    days = sorted(S.date.unique())
    tgt = {d_: x.net.to_numpy() for d_, x in S[ran & quiet].groupby("date")}
    rest = {d_: x.net.to_numpy() for d_, x in S[~(ran & quiet)].groupby("date")}
    ta = [tgt.get(d_, np.array([])) for d_ in days]
    ra = [rest.get(d_, np.array([])) for d_ in days]
    rng = np.random.default_rng(0)
    out = []
    for _ in range(5000):
        i = rng.integers(0, len(days), len(days))
        x = np.concatenate([ta[k] for k in i])
        y = np.concatenate([ra[k] for k in i])
        if len(x) > 30 and len(y) > 30:
            out.append(x.mean() - y.mean())
    out = np.array(out)
    print(f"  difference {(a.mean() - b.mean()) * 100:+.2f}pp   "
          f"95% CI [{np.percentile(out, 2.5) * 100:+.2f}, {np.percentile(out, 97.5) * 100:+.2f}]   "
          f"P(no worse) = {(out >= 0).mean():.3f}")

    print("\n" + "=" * 92)
    print("5. THE STEELMAN: KEEP ONLY THE GENUINELY UNANTICIPATED FILINGS")
    print("=" * 92)
    print("  Section 2 shows the 'quiet' half of the proposal runs backwards -- among")
    print("  names that ran up, the ones with a prior announcement did worse, not")
    print("  better. But the same table makes the positive form of the idea the best")
    print("  cell in it: a name that had NOT moved and had announced NOTHING, then")
    print("  files. Maximum surprise rather than minimum. That is the version worth")
    print("  keeping, so it is measured as an inclusion rule rather than a veto.\n")
    print(f"  {'kept set':46s}{'rows':>9s}{'mean':>9s}{'median':>9s}{'win':>7s}{'compounds':>11s}")
    show("everything (baseline)", S)
    show("keep: flat and quiet", S[~ran & quiet])
    show("keep: flat and quiet, no volume surge", S[~ran & quiet & ~surge])
    show("keep: flat and quiet, WITH volume surge", S[~ran & quiet & surge])

    x = S[~ran & quiet].net
    y = S[~(~ran & quiet)].net
    kp = {d_: g.net.to_numpy() for d_, g in S[~ran & quiet].groupby("date")}
    op = {d_: g.net.to_numpy() for d_, g in S[~(~ran & quiet)].groupby("date")}
    ka = [kp.get(d_, np.array([])) for d_ in days]
    oa = [op.get(d_, np.array([])) for d_ in days]
    rng2 = np.random.default_rng(1)
    o2 = []
    for _ in range(5000):
        i = rng2.integers(0, len(days), len(days))
        u = np.concatenate([ka[k] for k in i])
        w = np.concatenate([oa[k] for k in i])
        if len(u) > 30 and len(w) > 30:
            o2.append(u.mean() - w.mean())
    o2 = np.array(o2)
    print(f"\n  flat-and-quiet minus the rest: {(x.mean() - y.mean()) * 100:+.2f}pp   "
          f"95% CI [{np.percentile(o2, 2.5) * 100:+.2f}, "
          f"{np.percentile(o2, 97.5) * 100:+.2f}]   "
          f"P(no better) = {(o2 <= 0).mean():.3f}")

    print("\n" + "=" * 92)
    print("6. THE QUESTION THAT DECIDES WHETHER TO SHIP IT")
    print("=" * 92)
    print("  Sections 2-5 are about the average row in a subset. A book does not")
    print("  buy the average row, it buys the model's top pick, and shrinking the")
    print("  pool also shrinks the training set. So: rank walk-forward inside the")
    print("  full gate and inside the filtered gate, and compare the picks.\n")
    feats = [c for c in cc.PANEL_COLS] + [c for c in cc.PREFILE_COLS]
    M = S[feats].to_numpy(np.float32)
    r_ = S.ret.to_numpy()
    keep_mask = (~ran & quiet).to_numpy()
    rows = []
    for a_, tr, te in la.blocks(S.date):
        for tag, sub_mask in (("full gate", np.ones(len(S), bool)),
                              ("surprise-only", keep_mask)):
            tr2, te2 = tr & sub_mask, te & sub_mask
            if tr2.sum() < 5000 or te2.sum() < 200:
                continue
            p_ = la.q75_scores(M[:, :0], M, r_, tr2, te2, True)
            g_ = S[te2].copy()
            g_["p"] = p_
            k1 = g_.sort_values("p", ascending=False).groupby("date").head(1)
            rows.append({"arm": tag, "k1": k1.ret.mean() - la.COST,
                         "pool": g_.ret.mean() - la.COST,
                         "med": k1.ret.median() - la.COST,
                         "lg": np.log1p(np.clip(k1.ret.to_numpy() - la.COST,
                                                -0.99, None)).mean(),
                         "days": k1.date.nunique(), "ntr": int(tr2.sum())})
    R = pd.DataFrame(rows)
    print(f"  {'arm':22s}{'blocks':>8s}{'train rows':>12s}{'pool':>9s}"
          f"{'k=1 mean':>11s}{'k=1 median':>12s}{'compounds':>11s}")
    for tag in ("full gate", "surprise-only"):
        t_ = R[R.arm == tag]
        if not len(t_):
            continue
        w = t_.days
        print(f"  {tag:22s}{len(t_):>8d}{int(t_.ntr.mean()):>12,d}"
              f"{np.average(t_.pool, weights=w) * 100:>+8.2f}%"
              f"{np.average(t_.k1, weights=w) * 100:>+10.2f}%"
              f"{np.average(t_.med, weights=w) * 100:>+11.2f}%"
              f"{(np.exp(np.average(t_.lg, weights=w)) - 1) * 100:>+10.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
