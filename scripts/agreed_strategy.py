"""The strategy made only of the pieces that survived testing, priced as a book.

Every result so far has been quoted per trade — "+1.349% per trade", "+0.894%
excess". That is the right unit for testing a signal and the wrong unit for
answering "what would I have made". Per-trade means say nothing about how much
capital was working, how many positions overlapped, or how deep the hole got on
the way. This runs the agreed rules as an actual book with an actual equity
curve.

What is in, and why
-------------------
Only things that passed a pre-registered test:

* **q75 quantile objective.** Beat the mean-optimising control and every other
  quantile at k=1 (`RESULT_MOONSHOT_TAIL.md`). Mean objectives push away from
  lottery tickets; the payoff here is convex, so the objective has to be too.
* **Long only, buy the next open, hold ten sessions.** The direction head failed
  five independent ways, so nothing is shorted.
* **No exit rules.** All seventeen stops, targets and trails lost to holding
  (`RESULT_EXIT_RULES.md`). Every one removed more upside than downside.
* **The item 3.02 veto.** Skip any name that reported an unregistered share
  issuance in the last quarter — 15.1% disaster rate against 26.9%, the only
  checklist question of eighteen to clear Bonferroni (`RESULT_CHECKLIST.md`),
  and independently the strongest single field in the blind reading pilot at
  0.679 (`RESULT_LLM_PILOT.md`).
* **Walk-forward with a fourteen-day embargo.** A label runs ten sessions
  forward, so training rows inside that window would leak.

What is deliberately out: confidence gating (the score level carries +0.0093
rank correlation), the other seventeen checklist questions (0 of 18 replicated),
and any text feature (the regex arm tested at −0.217pp).

The accounting
--------------
`k` new positions per session, each held ten sessions, so up to `10k` overlap.
Each entry takes `1/(10k)` of equity, the rest earns nothing. Positions are
marked daily from the close so the equity curve and the drawdown are real rather
than reconstructed from trade averages. Costs are ten basis points on entry and
ten on exit, charged on the days they occur.

Cash drag is left in on purpose. On days when fewer than `k` names clear the
filters the book is not fully invested, and pretending otherwise would inflate
the return. The reported figure is what the account does, not what the signal
does.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adrnn_train import build_arrays  # noqa: E402
from moonshot_tail import MAX_TRAIN, blocks, scale_fit  # noqa: E402

HORIZON = 10
SIDE_COST = 10.0 / 1e4
QUANTILE = 0.75
TRADING_DAYS = 252.0


def daily_paths(prices: pd.DataFrame, rows: np.ndarray, horizon: int = HORIZON):
    """Per-trade daily returns, entry at the next open, exit at the last traded close.

    ``tick`` is checked on every step. The panel is one contiguous block sorted
    by (ticker, date), so a window running off the end of one ticker walks into
    the next one's prices — the bug that once produced a mean of +293% with a
    median of −4.56%.

    The exit convention is copied from ``exit_rules.walk`` rather than invented,
    because every other result in the project is quoted on it: mark out at the
    last bar inside the window that **actually traded**, scanning backwards past
    zero-volume and missing bars. Breaking forward at the first gap instead gave
    answers that differed by up to two percentage points on a minority of
    trades, which the cross-check in ``main`` caught. Untradeable days inside
    the window carry the mark unchanged — a halted name does not reprice a book.
    """
    o = prices["open"].to_numpy(float)
    c = prices["close"].to_numpy(float)
    v = np.nan_to_num(prices["volume"].to_numpy(float), nan=0.0)
    tick = prices["ticker"].to_numpy()
    n = len(o)
    out = np.full((len(rows), horizon), np.nan)
    for a, i in enumerate(rows):
        i = int(i)
        j0 = i + 1
        if j0 >= n or tick[j0] != tick[i]:
            continue
        e = o[j0]
        if not (np.isfinite(e) and e > 0):
            continue
        who = tick[j0]
        end = min(j0 + horizon - 1, n - 1)
        while end > j0 and tick[end] != who:
            end -= 1
        while end > j0 and not (np.isfinite(c[end]) and v[end] > 0):
            end -= 1
        if not np.isfinite(c[end]):
            continue
        prev = e
        for step in range(end - j0 + 1):
            j = j0 + step
            px = c[j]
            if np.isfinite(px) and px > 0 and (v[j] > 0 or j == end):
                out[a, step] = px / prev - 1.0
                prev = px
            else:
                out[a, step] = 0.0
    return out


def equity_curve(trades: pd.DataFrame, paths: np.ndarray, dates: np.ndarray,
                 k: int, horizon: int = HORIZON) -> pd.Series:
    """Daily portfolio returns from overlapping equal-weight positions."""
    cal = np.sort(np.unique(dates))
    pos = {d: i for i, d in enumerate(cal)}
    weight = 1.0 / (k * horizon)
    daily = np.zeros(len(cal))
    for a, entry in enumerate(trades.date.to_numpy()):
        start = pos[entry]
        for step in range(horizon):
            r = paths[a, step]
            if not np.isfinite(r):
                break
            # Entry fill is the open of the session after the signal, so the
            # first marked day sits one session later on the calendar.
            j = start + 1 + step
            if j >= len(cal):
                break
            if step == 0:
                r -= SIDE_COST
            if step == horizon - 1 or not np.isfinite(paths[a, min(step + 1, horizon - 1)]):
                r -= SIDE_COST
            daily[j] += weight * r
    return pd.Series(daily, index=pd.DatetimeIndex(cal))


def summarise(eq: pd.Series, trades: pd.DataFrame, label: str) -> dict:
    curve = (1.0 + eq).cumprod()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    total = float(curve.iloc[-1]) - 1.0
    cagr = float(curve.iloc[-1]) ** (1.0 / yrs) - 1.0 if yrs > 0 else np.nan
    dd = float((curve / curve.cummax() - 1.0).min())
    vol = float(eq.std() * np.sqrt(TRADING_DAYS))
    sharpe = float(eq.mean() * TRADING_DAYS / vol) if vol > 0 else np.nan
    return {"book": label, "from": eq.index[0].date(), "to": eq.index[-1].date(),
            "years": yrs, "trades": len(trades), "per_mo": len(trades) / (yrs * 12),
            "total": total, "cagr": cagr, "maxdd": dd, "vol": vol,
            "sharpe": sharpe, "curve": curve}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--stride", type=int, default=10)
    ap.add_argument("--quantile", type=float, default=QUANTILE)
    ap.add_argument("--ks", default="1,2,3,5")
    ap.add_argument("--horizon", type=int, default=HORIZON,
                    help="sessions held; 10 is the project default, 21 is a month")
    args = ap.parse_args(argv)
    root = Path(args.root)
    ks = [int(x) for x in args.ks.split(",")]
    H = args.horizon
    # A label runs H sessions forward, so the embargo has to cover it in
    # calendar time or training rows leak into the test block. Five sessions is
    # seven days, and the max() keeps the ten-session case at the fourteen days
    # every earlier result used, so those stay comparable.
    embargo = max(14, int(np.ceil(H * 7 / 5)))
    print(f"horizon {H} sessions, embargo {embargo} calendar days", flush=True)

    from sklearn.ensemble import HistGradientBoostingRegressor

    d, X, feats, idx = build_arrays(root / "adrnn_panel.parquet", args.stride)
    prices = pd.read_parquet(root / "w2015_prices.parquet",
                             columns=["date", "ticker", "open", "high", "low",
                                      "close", "volume"])
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)

    print("computing daily paths for every candidate", flush=True)
    paths_all = daily_paths(prices, idx, H)
    ret_all = np.nanprod(1.0 + np.nan_to_num(paths_all, nan=0.0), axis=1) - 1.0
    alive = np.isfinite(paths_all[:, 0])
    ret_all = np.where(alive & (np.abs(ret_all) <= 3.0), ret_all, np.nan)

    # The daily path is a new way of computing a number the project already has
    # from ``walk``. If the two disagree, one of them is wrong and every figure
    # below inherits it, so they are checked against each other rather than
    # assumed to agree.
    from exit_rules import walk as _walk
    _o = prices["open"].to_numpy(float)
    _h = prices["high"].to_numpy(float)
    _l = prices["low"].to_numpy(float)
    _c = prices["close"].to_numpy(float)
    _v = np.nan_to_num(prices["volume"].to_numpy(float), nan=0.0)
    _t = prices["ticker"].to_numpy()
    chk = np.random.default_rng(0).choice(len(idx), 3000, replace=False)
    gap = []
    for a in chk:
        r, _, _ = _walk(_o, _h, _l, _c, _v, _t, int(idx[a]) + 1, H,
                        None, None, None, None, None)
        if np.isfinite(r) and abs(r) <= 3.0 and np.isfinite(ret_all[a]):
            gap.append(abs(r - ret_all[a]))
    gap = np.array(gap)
    print(f"  cross-check against walk() on {len(gap):,} trades: "
          f"max |diff| {gap.max():.2e}, mean {gap.mean():.2e}")
    assert gap.max() < 1e-6, "daily path and walk() disagree on the return"

    veto_col = "i3.02_60d"
    vi = feats.index(veto_col)
    tab = pd.DataFrame({
        "row": idx,
        "date": pd.to_datetime(d["date"].to_numpy()[idx]),
        "ticker": d["ticker"].to_numpy()[idx],
        "ret": ret_all,
        "i302": X[idx, vi],
    })
    ok = tab.ret.notna().to_numpy()
    tab, paths_all = tab[ok].reset_index(drop=True), paths_all[ok]
    Xs = X[tab.row.to_numpy()]
    print(f"  {len(tab):,} candidates over {tab.date.nunique():,} sessions "
          f"({len(tab) / tab.date.nunique():.0f} per session)")
    print(f"  {(tab.i302 > 0).mean() * 100:.1f}% carry an item 3.02 issuance "
          f"in the trailing quarter\n", flush=True)

    # ---- score every candidate, walk-forward ---------------------------
    preds = np.full(len(tab), np.nan)
    y = tab.ret.to_numpy()
    for b0, b1 in blocks(tab.date.max()):
        tr = np.flatnonzero(tab.date < b0 - pd.Timedelta(days=embargo))
        te = np.flatnonzero((tab.date >= b0) & (tab.date < b1))
        if len(tr) < 40_000 or len(te) < 500:
            continue
        if len(tr) > MAX_TRAIN:
            tr = tr[np.linspace(0, len(tr) - 1, MAX_TRAIN).astype(int)]
        med, sc = scale_fit(Xs[tr])
        m = HistGradientBoostingRegressor(loss="quantile", quantile=args.quantile,
                                          max_iter=250, learning_rate=0.05,
                                          max_depth=6, random_state=0)
        m.fit(np.clip((Xs[tr] - med) / sc, -5, 5), y[tr])
        preds[te] = m.predict(np.clip((Xs[te] - med) / sc, -5, 5))
        print(f"  block {b0:%Y-%m}: trained on {len(tr):,}, scored {len(te):,}",
              flush=True)
    tab["pred"] = preds
    live = tab.pred.notna().to_numpy()
    tab, paths_all = tab[live].reset_index(drop=True), paths_all[live]
    print(f"\n{len(tab):,} scored candidates from {tab.date.min():%Y-%m-%d} "
          f"to {tab.date.max():%Y-%m-%d}\n", flush=True)

    all_dates = tab.date.to_numpy()
    rows = []
    curves = {}
    for k in ks:
        for veto in (True, False):
            pool = tab[tab.i302 <= 0] if veto else tab
            sel = (pool.sort_values("pred", ascending=False)
                       .groupby("date").head(k).sort_values("date"))
            p = paths_all[sel.index.to_numpy()]
            s = sel.reset_index(drop=True)
            eq = equity_curve(s, p, all_dates, k, H)
            lab = f"k={k} {'3.02 veto' if veto else 'no veto '}"
            r = summarise(eq, s, lab)
            r["per_trade"] = float(s.ret.mean()) - 2 * SIDE_COST
            r["win"] = float((s.ret - 2 * SIDE_COST > 0).mean())
            r["p20"] = float((s.ret >= 0.20).mean())
            curves[lab] = r.pop("curve")
            r["_sel"] = s
            rows.append(r)

    print("=" * 108)
    print("THE BOOK -- overlapping equal-weight positions, 20bps round trip, "
          "cash drag included")
    print("=" * 108)
    print(f"{'book':20s} {'trades':>7s} {'/mo':>5s} {'per trade':>10s} {'win':>6s} "
          f"{'P(+20%)':>8s} {'TOTAL ROI':>11s} {'CAGR':>8s} {'maxDD':>8s} "
          f"{'vol':>7s} {'Sharpe':>7s}")
    for r in rows:
        print(f"{r['book']:20s} {r['trades']:>7,d} {r['per_mo']:>5.1f} "
              f"{r['per_trade'] * 100:>+9.3f}% {r['win'] * 100:>5.1f}% "
              f"{r['p20'] * 100:>7.1f}% {r['total'] * 100:>+10.1f}% "
              f"{r['cagr'] * 100:>+7.1f}% {r['maxdd'] * 100:>7.1f}% "
              f"{r['vol'] * 100:>6.1f}% {r['sharpe']:>7.2f}")
    span = rows[0]
    print(f"\nperiod {span['from']} to {span['to']}  ({span['years']:.1f} years)")

    # ---- what the answer actually rests on -----------------------------
    # ---- what the skill is worth against no skill ----------------------
    print("\n" + "=" * 108)
    print("BENCHMARKS -- the same accounting, without the model")
    print("=" * 108)
    kb = ks[-1]
    pool = tab[tab.i302 <= 0]
    tot = []
    for seed in range(40):
        rs = np.random.default_rng(seed)
        pick = (pool.assign(u=rs.random(len(pool)))
                    .sort_values("u").groupby("date").head(kb).sort_values("date"))
        eqb = equity_curve(pick.reset_index(drop=True),
                           paths_all[pick.index.to_numpy()], all_dates, kb)
        tot.append(float((1 + eqb).prod()) - 1.0)
    tot = np.array(tot)
    lo, hi = np.percentile(tot, [5, 95])
    print(f"  random {kb} names a day, 40 draws:  median ROI {np.median(tot) * 100:+.1f}%"
          f"   5-95% [{lo * 100:+.1f}%, {hi * 100:+.1f}%]")
    own = (tab.groupby("date")["ret"].mean())
    everything = equity_curve(tab.assign(_o=1).reset_index(drop=True), paths_all,
                              all_dates, max(1, int(round(len(tab) / tab.date.nunique()))))
    print(f"  own the whole pool equally:        ROI "
          f"{(float((1 + everything).prod()) - 1) * 100:+.1f}%")
    del own
    model = next(r for r in rows if r["book"] == f"k={kb} 3.02 veto")
    beat = float((tot >= model["total"]).mean())
    print(f"  the model's k={kb} book:              ROI {model['total'] * 100:+.1f}%"
          f"   ({beat * 100:.0f}% of random draws beat it)")

    print("\n" + "=" * 108)
    print("FRAGILITY -- the same book with the winners trimmed")
    print("=" * 108)
    base = next(r for r in rows if r["book"].startswith(f"k={ks[0]} 3.02"))
    s = base["_sel"]
    net = s.ret.to_numpy() - 2 * SIDE_COST
    top = np.argsort(net)[::-1]
    for share in (0.0, 0.01, 0.02, 0.05):
        cut = int(round(share * len(net)))
        keep = net.copy()
        if cut:
            keep[top[:cut]] = np.nan
        m = np.nanmean(keep)
        print(f"  drop the best {share * 100:4.1f}% of trades ({cut:>3d} of "
              f"{len(net)}):  mean {m * 100:+7.3f}% per trade")
    for hair in (0.10, 0.25, 0.50):
        adj = net.copy()
        adj[adj > 0] *= (1 - hair)
        print(f"  haircut winners by {hair * 100:4.0f}%:                       "
              f"     mean {np.mean(adj) * 100:+7.3f}% per trade")
    contrib = np.sort(net)[::-1]
    tot = contrib.sum()
    for n in (10, 20, 40):
        if n <= len(contrib):
            print(f"  top {n:>2d} trades carry {contrib[:n].sum() / tot * 100:5.1f}% "
                  f"of the total per-trade sum")

    # ---- the number that decides whether any of this is real ------------
    print("\n" + "=" * 108)
    print("SURVIVORSHIP -- how many hidden total losses would it take?")
    print("=" * 108)
    print("  Not one of 3,662 tickers in this panel delisted in eleven years.")
    print("  RESULT_SURVIVORSHIP.md counts the real rate from the Form 25 filings:")
    print("  871 involuntary common-stock delistings in eleven years, 79 a year,")
    print("  which at the measured 6.07x pick concentration is a hazard of about")
    print(f"  {0.0047 * H / 10 * 100:.2f}% over a {H}-session hold. Mix in a fraction f of")
    print("  trades that went to -100% and find where the edge disappears.")
    for r in rows:
        if not r["book"].endswith("3.02 veto"):
            continue
        m = r["per_trade"]
        f = m / (1.0 + m) if m > 0 else np.nan
        print(f"    {r['book']:20s} per trade {m * 100:+6.3f}%  ->  breaks even at "
              f"f = {f * 100:.2f}%  (1 hidden zero per {1 / f:.0f} trades)")

    # ---- what the trades actually look like -----------------------------
    log = base["_sel"][["date", "ticker", "pred", "ret"]].copy()
    log["net"] = log.ret - 2 * SIDE_COST
    log.to_parquet(root / "agreed_trades.parquet")
    tab.drop(columns=["row"]).to_parquet(root / "agreed_scored.parquet")
    print("\n" + "=" * 108)
    print("THE TRADES -- primary book, most recent 12")
    print("=" * 108)
    for _, t in log.tail(12).iterrows():
        print(f"  buy {t.date:%Y-%m-%d} open   {t.ticker:6s}   "
              f"sell {H} sessions later   {t.net * 100:+8.2f}%")
    print("\n  the ten that carried it:")
    for _, t in log.sort_values("net", ascending=False).head(10).iterrows():
        print(f"  buy {t.date:%Y-%m-%d} open   {t.ticker:6s}   {t.net * 100:+8.2f}%")
    print("\n  the ten worst:")
    for _, t in log.sort_values("net").head(10).iterrows():
        print(f"  buy {t.date:%Y-%m-%d} open   {t.ticker:6s}   {t.net * 100:+8.2f}%")

    # ---- a month, both senses -------------------------------------------
    print("\n" + "=" * 108)
    print("MONTH BY MONTH -- how a single month behaves")
    print("=" * 108)
    for r in rows:
        if not r["book"].endswith("3.02 veto"):
            continue
        c2 = curves[r["book"]]
        st = pd.Series(np.r_[c2.iloc[0] - 1.0, c2.pct_change().dropna().to_numpy()],
                       index=c2.index)
        mo = (1 + st).resample("ME").prod() - 1
        print(f"  {r['book']:20s} months {len(mo):>3d}   "
              f"positive {int((mo > 0).sum())}/{len(mo)} ({(mo > 0).mean() * 100:.0f}%)   "
              f"median {mo.median() * 100:+6.2f}%   mean {mo.mean() * 100:+6.2f}%   "
              f"best {mo.max() * 100:+7.1f}%   worst {mo.min() * 100:+7.1f}%")
    c2 = curves[base["book"]]
    st = pd.Series(np.r_[c2.iloc[0] - 1.0, c2.pct_change().dropna().to_numpy()],
                   index=c2.index)
    mo = (1 + st).resample("ME").prod() - 1
    print(f"\n  {base['book']} by month, last 24:")
    for ts, v in mo.tail(24).items():
        n = int(((log.date.dt.year == ts.year) & (log.date.dt.month == ts.month)).sum())
        bar = ("+" if v >= 0 else "-") * min(40, int(abs(v) * 200))
        print(f"    {ts:%Y-%m}  {v * 100:+7.2f}%  ({n:>3d} trades)  {bar}")

    print("\n" + "=" * 108)
    print("ONE MONTH IN FULL -- every trade of the last complete month")
    print("=" * 108)
    last = log.date.max().to_period("M") - 1
    m1 = log[log.date.dt.to_period("M") == last]
    if len(m1):
        for _, t in m1.iterrows():
            bar = ("+" if t.net >= 0 else "-") * min(30, int(abs(t.net) * 100))
            print(f"  {t.date:%Y-%m-%d}  {t.ticker:6s} {t.net * 100:+8.2f}%  {bar}")
        print(f"\n  {len(m1)} trades, mean {m1.net.mean() * 100:+.2f}%, "
              f"{int((m1.net > 0).sum())} winners, "
              f"best {m1.net.max() * 100:+.1f}%, worst {m1.net.min() * 100:+.1f}%")
        v = float(mo.get(pd.Timestamp(last.end_time.date()), float("nan")))
        print(f"  the book returned {v * 100:+.2f}% that month")

    print("\n" + "=" * 108)
    print("YEAR BY YEAR -- the primary book")
    print("=" * 108)
    c = curves[base["book"]]
    step = pd.Series(np.r_[c.iloc[0] - 1.0, c.pct_change().dropna().to_numpy()],
                     index=c.index)
    for ts, v in ((1 + step).resample("YE").prod() - 1).items():
        n = int((s.date.dt.year == ts.year).sum())
        print(f"  {ts.year}   {v * 100:+8.1f}%   ({n:>3d} trades)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
