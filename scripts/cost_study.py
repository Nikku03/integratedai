"""Where does the edge exceed the cost of harvesting it?

The blocking result from the last run was arithmetic, not modelling: the top 1%
of signals earned +21bp gross over 8 days while round-trip cost on this universe
ran ~48bp. This script finds the conditions, if any, under which that inequality
flips -- by liquidity, by market cap, by holding period, and by how selective
the signal gate is.

    python scripts/cost_study.py
"""

from __future__ import annotations

import argparse
import ast
import logging
import sys
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

from iai.backtest.costs import total_cost_bps  # noqa: E402
from iai.core.config import Config  # noqa: E402
from iai.features.assembler import assemble  # noqa: E402
from iai.labels import build_labels  # noqa: E402
from iai.model.ensemble import assign_payoffs  # noqa: E402
from iai.model.train import make_dataset, walk_forward  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--splits", type=int, default=5)
    ap.add_argument("--order-usd", type=float, default=25_000.0,
                    help="assumed order size; impact is order/ADV so this matters")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    cfg = Config.short_horizon()
    cfg.model.n_seeds, cfg.model.n_splits = args.seeds, args.splits
    cfg.ensure_dirs()
    store = cfg.data.store_dir

    prices = pd.read_parquet(store / "sm_prices.parquet")
    events = pd.read_parquet(store / "sm_events.parquet")
    events["payload"] = events["payload"].map(
        lambda s: ast.literal_eval(s) if isinstance(s, str) else s
    )
    caps = pd.read_parquet(store / "sm_caps.parquet")

    panel = assemble(prices, events, cfg)
    labels = build_labels(prices, cfg)
    X, y, meta = make_dataset(panel, labels, cfg)
    fit = walk_forward(X, y, meta, cfg, permutation_repeats=0)

    sig = fit.oof.merge(
        meta[["date", "ticker", "barrier_up", "barrier_dn"]], on=["date", "ticker"], how="left"
    )
    sig = assign_payoffs(sig, fit.payoff_table)
    # Attach liquidity and cap, both point-in-time.
    sig = sig.merge(prices[["date", "ticker", "adv_usd", "close"]], on=["date", "ticker"], how="left")
    sig = sig.merge(caps[["date", "ticker", "market_cap", "cap_band"]], on=["date", "ticker"], how="left")
    sig = sig.dropna(subset=["adv_usd", "ret"])

    # One-way cost for the assumed order, then double it for the round trip.
    sig["cost_bps_1way"] = total_cost_bps(args.order_usd, sig["adv_usd"].to_numpy(), cfg, news_day=True)
    sig["cost_rt"] = 2 * sig["cost_bps_1way"] / 1e4

    pd.set_option("display.width", 240)
    print("=" * 96)
    print("COST STUDY -- when does the edge beat the bill?")
    print("=" * 96)
    print(f"signals: {len(sig):,}   pooled AUC {fit.auc:.4f}   order size ${args.order_usd:,.0f}")
    print()

    # ---- 1. selectivity ---------------------------------------------------
    print("1. SELECTIVITY: gross edge vs round-trip cost, by prediction percentile")
    print("-" * 96)
    rows = []
    for q in [0.0, 0.5, 0.8, 0.9, 0.95, 0.99, 0.995]:
        thr = sig["p"].quantile(q)
        top = sig[sig["p"] >= thr]
        if len(top) < 50:
            continue
        rows.append({
            "pct": f"top {100*(1-q):.1f}%",
            "n": len(top),
            "hit_rate": top["y"].mean(),
            "gross_ret": top["ret"].mean(),
            "cost_rt": top["cost_rt"].mean(),
            "net_ret": top["ret"].mean() - top["cost_rt"].mean(),
        })
    sel = pd.DataFrame(rows)
    print(sel.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()

    # ---- 2. liquidity -----------------------------------------------------
    print("2. LIQUIDITY: the same, split by ADV decile (top 10% of signals only)")
    print("-" * 96)
    top = sig[sig["p"] >= sig["p"].quantile(0.90)].copy()
    top["adv_decile"] = pd.qcut(top["adv_usd"].rank(method="first"), 10, labels=False)
    liq = top.groupby("adv_decile", observed=True).agg(
        n=("ret", "size"),
        median_adv=("adv_usd", "median"),
        gross_ret=("ret", "mean"),
        cost_rt=("cost_rt", "mean"),
    )
    liq["net_ret"] = liq["gross_ret"] - liq["cost_rt"]
    liq["median_adv_m"] = liq["median_adv"] / 1e6
    print(liq[["n", "median_adv_m", "gross_ret", "cost_rt", "net_ret"]].to_string(
        float_format=lambda v: f"{v:.4f}"))
    print()

    # ---- 3. market cap ----------------------------------------------------
    print("3. MARKET CAP band (top 10% of signals)")
    print("-" * 96)
    if top["cap_band"].notna().any():
        cap = top.dropna(subset=["cap_band"]).groupby("cap_band", observed=True).agg(
            n=("ret", "size"), gross_ret=("ret", "mean"), cost_rt=("cost_rt", "mean"),
        )
        cap["net_ret"] = cap["gross_ret"] - cap["cost_rt"]
        print(cap.to_string(float_format=lambda v: f"{v:.4f}"))
    print()

    # ---- 4. holding period ------------------------------------------------
    # Cost is paid once; a longer hold amortises it, if the edge keeps
    # accumulating rather than decaying.
    print("4. HOLDING PERIOD: cost is paid once, so does a longer hold amortise it?")
    print("-" * 96)
    px = prices.sort_values(["ticker", "date"]).copy()
    px["adj_close"] = px["close"] * px.get("adj_factor", 1.0)
    rows = []
    for h in [3, 5, 8, 13, 21, 42]:
        px[f"fwd{h}"] = px.groupby("ticker", observed=True)["adj_close"].shift(-h) / px["adj_close"] - 1
        mkt = px.groupby("date", observed=True)[f"fwd{h}"].transform("mean")
        px[f"abn{h}"] = px[f"fwd{h}"] - mkt
        m = top.merge(px[["date", "ticker", f"abn{h}"]], on=["date", "ticker"], how="left")
        g = m[f"abn{h}"].mean()
        c = m["cost_rt"].mean()
        rows.append({"hold_days": h, "n": int(m[f"abn{h}"].notna().sum()),
                     "gross_abn": g, "cost_rt": c, "net": g - c,
                     "net_per_day": (g - c) / h})
    hold = pd.DataFrame(rows)
    print(hold.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()

    best = hold.loc[hold["net"].idxmax()]
    print(f"   best horizon by net return: {int(best['hold_days'])}d  -> net {best['net']:+.4f}")
    print()

    # ---- 5. the break-even ------------------------------------------------
    print("5. BREAK-EVEN: what would have to be true?")
    print("-" * 96)
    t10 = sel[sel["pct"] == "top 10.0%"]
    g = float(t10["gross_ret"].iloc[0]) if not t10.empty else float("nan")
    c = float(t10["cost_rt"].iloc[0]) if not t10.empty else float("nan")
    print(f"   top-decile gross edge     {g:+.4f}  ({g*1e4:+.0f} bp)")
    print(f"   round-trip cost           {c:+.4f}  ({c*1e4:+.0f} bp)")
    print(f"   shortfall                 {g-c:+.4f}  ({(g-c)*1e4:+.0f} bp)")
    if c > 0:
        print(f"   edge would need to be     {c/max(g,1e-9):.1f}x larger, OR")
        print(f"   cost would need to fall   {100*(1-g/max(c,1e-9)):.0f}%")
    print()

    sig.to_parquet(store / "cost_signals.parquet")
    print(f"wrote {store / 'cost_signals.parquet'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
