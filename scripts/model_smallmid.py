"""Train and backtest the short-horizon small/mid-cap model on fetched real data.

Run ``scripts/run_smallmid.py`` first to populate the store.

    python scripts/model_smallmid.py --n-trials 8
"""

from __future__ import annotations

import argparse
import ast
import logging
import sys
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

from iai.core.config import Config  # noqa: E402
from iai.model.train import family_importance  # noqa: E402
from iai.pipeline import run_research  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-trials", type=int, default=1,
                    help="how many strategy variants you have tried, for the deflated Sharpe")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--splits", type=int, default=5)
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)-24s %(message)s",
        datefmt="%H:%M:%S", stream=sys.stderr,
    )

    cfg = Config.short_horizon()
    cfg.model.n_seeds = args.seeds
    cfg.model.n_splits = args.splits
    cfg.ensure_dirs()
    store = cfg.data.store_dir

    prices = pd.read_parquet(store / "sm_prices.parquet")
    events = pd.read_parquet(store / "sm_events.parquet")
    events["payload"] = events["payload"].map(
        lambda s: ast.literal_eval(s) if isinstance(s, str) else s
    )
    caps = pd.read_parquet(store / "sm_caps.parquet")
    caps = caps[["date", "ticker", "log_market_cap"]]

    # Sector map from SEC SIC codes carried on the EDGAR event payloads.
    # Without it every name lands in one "unknown" bucket and the 30% sector
    # cap throttles the entire book to a third of its intended gross -- which
    # is a limit doing its job on bad input, not a limit misbehaving.
    sectors = {}
    sector_file = store / "sm_sectors.csv"
    if sector_file.exists():
        sec_df = pd.read_csv(sector_file, dtype={"sic": str, "sector": str})
        sectors = dict(zip(sec_df["ticker"], sec_df["sector"].fillna("unknown"), strict=False))
        print(f"sectors: {len(set(sectors.values()))} groups over {len(sectors)} tickers",
              file=sys.stderr)

    result = run_research(
        prices, events, cfg, n_trials=args.n_trials, extra_features=caps, sectors=sectors
    )
    pd.set_option("display.width", 250)
    print(result.report())

    perm = result.fit.perm_importance
    if not perm.empty:
        print("\nCONTRIBUTION BY SOURCE (out-of-sample AUC drop)")
        print(family_importance(perm, "auc_drop").to_string(index=False))

    bt = result.backtest
    if not bt.trades.empty:
        print("\nTRADE OUTCOME MIX")
        print(bt.trades["reason"].value_counts().to_string())
        print("\nP&L BY EXIT REASON")
        print(bt.trades.groupby("reason", observed=True)["pnl"].agg(["count", "sum", "mean"]).to_string())

    monthly = result.diagnostics.get("monthly")
    if monthly is not None and not monthly.empty:
        print("\nMONTHLY RETURNS")
        print((monthly * 100).round(1).to_string())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
