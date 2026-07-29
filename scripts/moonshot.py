"""Moonshot study: few trades a week, hunting +10% spikes.

Trains two models (P(target first) and P(stop first)), ranks candidates by
expected value, takes the best few each week, and reports the economics net of
cost -- plus the volatility control that decides whether any of it is skill.

    python scripts/moonshot.py --trades-per-week 5
"""

from __future__ import annotations

import argparse
import ast
import logging
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from iai.backtest.costs import total_cost_bps  # noqa: E402
from iai.backtest.metrics import deflated_sharpe, performance_summary  # noqa: E402
from iai.core.config import Config  # noqa: E402
from iai.features.assembler import assemble  # noqa: E402
from iai.labels import build_spike_labels  # noqa: E402
from iai.moonshot import (  # noqa: E402
    select_per_week,
    selection_report,
    train_moonshot,
    volatility_control,
)


def simulate(selected, prices, cfg, weight):
    """Daily-marked portfolio simulation of the selected trades.

    Each position is entered at the next open, marked to the close every
    session, and exited at the first barrier touch or the time stop. Costs are
    split half on entry and half on exit rather than charged in a lump, so the
    equity curve reflects when they are actually paid.
    """
    target, stop, H = cfg.spike.target, cfg.spike.stop, cfg.spike.horizon
    byt = {t: g.reset_index(drop=True) for t, g in prices.groupby("ticker", observed=True)}
    daily: dict[pd.Timestamp, list[float]] = {}
    trades = []

    for r in selected.itertuples(index=False):
        g = byt.get(r.ticker)
        if g is None:
            continue
        i = int(np.searchsorted(g["date"].to_numpy(), np.datetime64(r.date)))
        e = i + 1
        if e + H >= len(g):
            continue
        o, hi, lo, c = (g[k].to_numpy() for k in ("open", "high", "low", "close"))
        d = g["date"].to_numpy()
        ep = o[e]
        if not np.isfinite(ep) or ep <= 0:
            continue
        U, D = ep * (1 + target), ep * (1 - stop)

        path, exit_px = [], None
        for j in range(e, min(e + H, len(g))):
            if hi[j] >= U and lo[j] <= D:
                exit_px = D          # ambiguous bar resolves against us
            elif hi[j] >= U:
                exit_px = U
            elif lo[j] <= D:
                exit_px = D
            prev = ep if j == e else c[j - 1]
            mark = exit_px if exit_px is not None else c[j]
            path.append((d[j], mark / prev - 1.0))
            if exit_px is not None:
                break
        if not path:
            continue
        cost = float(getattr(r, "cost_rt", 0.0))
        path[0] = (path[0][0], path[0][1] - cost / 2)
        path[-1] = (path[-1][0], path[-1][1] - cost / 2)
        for dt, rr in path:
            daily.setdefault(pd.Timestamp(dt), []).append(rr)
        final = exit_px if exit_px is not None else c[e + len(path) - 1]
        trades.append({"ticker": r.ticker, "entry": d[e], "days": len(path),
                       "ret": final / ep - 1.0 - cost})

    if not daily:
        return pd.DataFrame(), pd.DataFrame()
    first, last = min(daily), max(daily)
    cal = pd.DatetimeIndex([d for d in sorted(prices["date"].unique()) if first <= d <= last])
    rows = [{"date": dt, "ret": weight * sum(daily.get(dt, [])),
             "n_positions": len(daily.get(dt, []))} for dt in cal]
    eq = pd.DataFrame(rows)
    eq["equity"] = cfg.risk.capital * (1 + eq["ret"]).cumprod()
    eq["gross"] = eq["n_positions"] * weight
    return eq, pd.DataFrame(trades)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades-per-week", type=float, default=5.0)
    ap.add_argument("--target", type=float, default=0.10)
    ap.add_argument("--stop", type=float, default=0.07)
    ap.add_argument("--horizon", type=int, default=10)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--splits", type=int, default=5)
    ap.add_argument("--weight", type=float, default=0.10)
    ap.add_argument("--order-usd", type=float, default=25_000.0)
    ap.add_argument("--n-trials", type=int, default=30,
                    help="configurations tried, for the deflated Sharpe")
    ap.add_argument("--prefix", default="sm",
                    help="store filename prefix (sm = 106-name core, wide = full pool)")
    ap.add_argument("--prereg", default="docs/PREREGISTRATION_2015.md",
                    help="which pre-registration the criteria are being read from")
    ap.add_argument("--max-year-share", type=float, default=0.35,
                    help="temporal-spread cap; 0.35 over eleven years, 0.50 over four")
    ap.add_argument("--members", default=None,
                    help="members.parquet from the screen stage. Restricts every date to "
                         "the names that qualified AS OF that date. Without it the run "
                         "uses the union of all quarters, which is lookahead.")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    cfg = Config.moonshot()
    cfg.spike.target, cfg.spike.stop, cfg.spike.horizon = args.target, args.stop, args.horizon
    cfg.spike.trades_per_week = args.trades_per_week
    cfg.model.n_seeds, cfg.model.n_splits = args.seeds, args.splits
    cfg.ensure_dirs()
    store = cfg.data.store_dir

    prices = pd.read_parquet(store / f"{args.prefix}_prices.parquet")
    events = pd.read_parquet(store / f"{args.prefix}_events.parquet")
    events["payload"] = events["payload"].map(
        lambda s: ast.literal_eval(s) if isinstance(s, str) else s
    )

    # ---- point-in-time universe membership ---------------------------------
    # Restricting to the *union* of every quarter's members is not enough. A
    # name that first qualified in 2019 would still be tradable in 2015 under
    # a union filter, and the only reason it is in the file at all is a fact
    # from 2019. Applying membership per date is what makes the universe
    # point-in-time rather than merely small.
    if args.members:
        from iai.universe_builder import membership_mask

        members = pd.read_parquet(args.members)
        before = len(prices)
        mask = membership_mask(members, prices)
        prices = prices.merge(mask, on=["date", "ticker"], how="left")
        prices = prices[prices["in_universe"].fillna(False)].drop(columns=["in_universe"])
        prices = prices.reset_index(drop=True)
        keep = set(map(tuple, prices[["date", "ticker"]].to_numpy()))
        print(f"PIT universe: {len(prices):,} of {before:,} bars in-universe "
              f"({prices['ticker'].nunique():,} names ever, "
              f"{len(keep) // max(prices['date'].nunique(), 1):,} avg per day)")
        if prices.empty:
            print("no in-universe bars; check --members matches this price file")
            return 1
    else:
        print("WARNING: no --members given. Using every name in the price file for "
              "every date, which includes names that only qualified later.")

    pd.set_option("display.width", 240)
    print("=" * 100)
    print(f"MOONSHOT  +{args.target:.0%} target / -{args.stop:.0%} stop / {args.horizon}d "
          f"/ {args.trades_per_week:.0f} trades per week")
    print("=" * 100)

    panel = assemble(prices, events, cfg)
    labels = build_spike_labels(prices, cfg, target=args.target, stop=args.stop,
                                horizon=args.horizon)
    fit = train_moonshot(panel, labels, cfg)
    oof = fit.oof

    print(f"rows {len(oof):,}   universe P(spike) {oof['spike'].mean():.4f}")
    print(f"AUC  spike {fit.auc_spike:.4f}   stop {fit.auc_stop:.4f}   E[r|time] {fit.r_time:+.4f}")
    print(f"calibration: mean p {oof['p'].mean():.4f} vs realised {oof['spike'].mean():.4f}")
    print()

    px = prices.sort_values(["ticker", "date"]).copy()
    px["adj"] = px["close"] * px.get("adj_factor", 1.0)
    px["r"] = px.groupby("ticker", observed=True)["adj"].pct_change()
    px["vol21"] = px.groupby("ticker", observed=True)["r"].transform(
        lambda s: s.rolling(21, min_periods=10).std()
    )
    oof = oof.merge(px[["date", "ticker", "adv_usd", "vol21"]], on=["date", "ticker"], how="left")
    oof["cost_rt"] = 2 * total_cost_bps(
        args.order_usd, oof["adv_usd"].fillna(1e9).to_numpy(), cfg, news_day=True
    ) / 1e4

    # ---- the ablation that matters ----------------------------------------
    print("ABLATION -- ranking by P(spike) vs by expected value")
    print("-" * 100)
    ablation = {}
    for name, col in [("P(spike) only", "p"), ("expected value", "ev")]:
        s = select_per_week(oof, per_week=args.trades_per_week, rank_col=col)
        rep = selection_report(s, oof).iloc[0]
        ablation[col] = float(rep["net"])
        print(f"  {name:<16} n={rep['n']:>4.0f}  P={rep['P_spike']:.4f}  stop%={rep['pct_stop']:.3f}  "
              f"net={rep['net']:+.4f}  t={rep['net_t']:+.2f}  t_clu={rep['net_t_clustered']:+.2f}")
    print()
    print("  106 names said EV > P(spike). 341 names said the reverse. A real")
    print("  mechanism does not flip; see docs/PREREGISTRATION_2015.md criterion 4.")
    print()

    # ---- selection ladder --------------------------------------------------
    print("SELECTION LADDER")
    print("-" * 100)
    print(f"{'trades/wk':>9} {'n':>6} {'P(spike)':>9} {'lift':>6} {'gross':>9} {'cost':>7} {'net':>9} {'t':>7}")
    for tpw in [20.0, 10.0, 5.0, 3.0, 2.0, 1.0]:
        s = select_per_week(oof, per_week=tpw, rank_col="ev")
        if len(s) < 30:
            continue
        r = selection_report(s, oof).iloc[0]
        print(f"{tpw:>9.0f} {r['n']:>6.0f} {r['P_spike']:>9.4f} {r['lift']:>6.2f}x "
              f"{r['gross']:>+9.4f} {r['cost']:>7.4f} {r['net']:>+9.4f} {r['net_t']:>+7.2f}")
    print()

    sel = select_per_week(oof, per_week=args.trades_per_week, rank_col="ev")

    print("VOLATILITY CONTROL -- skill, or just a volatility tilt?")
    print("-" * 100)
    print(f"  selected median vol {sel['vol21'].median():.4f} vs universe "
          f"{oof['vol21'].median():.4f} ({sel['vol21'].median()/oof['vol21'].median():.2f}x)")
    print()
    print(volatility_control(sel, oof).to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()
    print("  lift ~1.0 in every bucket would mean no skill beyond a volatility tilt.")
    print()

    # ---- portfolio ---------------------------------------------------------
    eq, trades = simulate(sel, prices, cfg, args.weight)
    if eq.empty:
        print("no simulated trades")
        return 0
    summ = performance_summary(
        eq[["date", "equity", "n_positions", "gross"]],
        trades.assign(pnl=trades["ret"], reason="x", days_held=trades["days"]),
    ).iloc[0]
    rets = eq.set_index("date")["ret"]

    print(f"PORTFOLIO -- {args.weight:.0%} per position, daily-marked")
    print("-" * 100)
    print(f"  period            {eq['date'].min():%Y-%m-%d} .. {eq['date'].max():%Y-%m-%d}")
    print(f"  CAGR              {summ['cagr']:+.2%}")
    print(f"  volatility        {summ['vol_annual']:.2%}")
    print(f"  Sharpe            {summ['sharpe']:+.2f}   (SE {summ['sharpe_se']:.2f})")
    print(f"  deflated Sharpe   {deflated_sharpe(rets, n_trials=args.n_trials):.3f}  "
          f"({args.n_trials} configurations tried)")
    print(f"  max drawdown      {summ['max_drawdown']:.2%}")
    print(f"  worst month       {summ['worst_month']:+.2%}")
    print(f"  skew              {summ['skew']:+.2f}")
    print(f"  trades            {len(trades)}   win% {(trades['ret']>0).mean():.3f}   "
          f"avg hold {trades['days'].mean():.1f}d")
    print(f"  avg win           {trades.loc[trades['ret']>0,'ret'].mean():+.2%}")
    print(f"  avg loss          {trades.loc[trades['ret']<=0,'ret'].mean():+.2%}")
    print(f"  avg positions     {eq['n_positions'].mean():.1f}  max {eq['n_positions'].max()}")
    print(f"  avg gross         {eq['gross'].mean():.0%}")
    print()
    print("  Sharpe SE is the number to read next to Sharpe. If the SE is comparable to")
    print("  the estimate, the strategy has not been measured, only observed.")
    print()

    # ---- pre-registered criteria (docs/PREREGISTRATION.md) -----------------
    rep = selection_report(sel, oof).iloc[0]
    ctrl = volatility_control(sel, oof)
    srt = sel.reindex((sel["ret"] - sel["cost_rt"]).abs().sort_values(ascending=False).index)
    trimmed = srt.iloc[20:]
    trimmed_net = float((trimmed["ret"] - trimmed["cost_rt"]).mean())
    by_year = sel.groupby(sel["date"].dt.year).size()
    max_year_share = float(by_year.max() / by_year.sum())
    vol_ratio = float(sel["vol21"].median() / oof["vol21"].median())
    buckets_ok = int((ctrl["lift"] > 1.0).sum()) if not ctrl.empty else 0

    print(f"PRE-REGISTERED CRITERIA  ({args.prereg})")
    print("-" * 100)
    # Primary is the WEEK-CLUSTERED t. Five trades in one week are not five
    # independent observations -- they share a regime and lose together -- so
    # the naive SE overstates t by whatever the within-week correlation is.
    t_clu = rep["net_t_clustered"]
    primary = t_clu > 2.0 and rep["net"] > 0
    print(f"  PRIMARY   net/trade {rep['net']:+.4f}  t_clustered = {t_clu:+.2f}  "
          f"(naive t = {rep['net_t']:+.2f} over {rep['n_weeks']:.0f} weeks)")
    print(f"            required clustered t > 2.0   -> {'PASS' if primary else 'FAIL'}")
    c1 = buckets_ok >= 3 and vol_ratio <= 1.2
    print(f"  vol control     lift>1 in {buckets_ok}/5 buckets, selected vol {vol_ratio:.2f}x universe "
          f"-> {'PASS' if c1 else 'FAIL'}")
    c2 = trimmed_net > 0
    print(f"  outlier robust  net after dropping 20 largest = {trimmed_net:+.4f} "
          f"-> {'PASS' if c2 else 'FAIL'}")
    c3 = max_year_share <= args.max_year_share
    print(f"  temporal spread largest year holds {max_year_share:.1%} of trades "
          f"(cap {args.max_year_share:.0%}) -> {'PASS' if c3 else 'FAIL'}")
    # Criterion 4: the ablation flipped between the two prior samples. Landing
    # a third way means the mechanism is noise whatever the primary says.
    ev_wins = ablation.get("ev", 0.0) > ablation.get("p", 0.0)
    c4 = ev_wins  # 106 names said EV wins; 341 said otherwise. Agreeing with one is the bar.
    print(f"  ablation        EV {ablation.get('ev', float('nan')):+.4f} vs "
          f"P(spike) {ablation.get('p', float('nan')):+.4f} "
          f"-> {'PASS (agrees with the 106-name run)' if c4 else 'FAIL (agrees with the 341-name run)'}")
    print()
    n_secondary = sum([c1, c2, c3, c4])
    verdict = (
        f"EDGE SURVIVED - {n_secondary}/4 secondaries - paper trade at fractional size"
        if primary and n_secondary >= 3
        else "SIGNIFICANT BUT CONFOUNDED - report, do not trade" if primary
        else "NO EDGE - stop. Three samples, this one powered. See the decision rule."
    )
    print(f"  VERDICT: {verdict}")
    if not primary:
        print()
        print("  The pre-registered stopping rule applies: no fourth test. The only")
        print("  moves left would be changing the target, horizon or universe, and")
        print("  searching over those is how a wanted result gets manufactured.")

    oof.to_parquet(store / f"{args.prefix}_moonshot_oof.parquet")
    sel.to_parquet(store / f"{args.prefix}_moonshot_selected.parquet")
    print(f"\nwrote {store}/{args.prefix}_moonshot_selected.parquet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
