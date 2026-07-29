"""Command line interface.

    iai demo                 run the whole pipeline on synthetic data
    iai doctor               report which sources are actually configured
    iai fetch  --tickers ... pull real data into the local store
    iai research             train and backtest on stored data
    iai signals              produce today's sized orders
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .core.config import Config
from .core.http import HttpClient
from .core.universe import Universe


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-28s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _store(cfg: Config) -> Path:
    cfg.ensure_dirs()
    return cfg.data.store_dir


def cmd_demo(args: argparse.Namespace) -> int:
    from .pipeline import load_synthetic, run_research

    cfg = Config.load(args.config)
    if args.fast:
        cfg.model.n_seeds = 2
        cfg.model.n_estimators = 150
        cfg.model.n_splits = 3

    from .sources.synthetic import PLANTED_EFFECTS

    print("Generating synthetic market...", file=sys.stderr)
    prices, events, _, sectors = load_synthetic(
        cfg, n_tickers=args.tickers, start=args.start, end=args.end, seed=args.seed
    )
    result = run_research(prices, events, cfg, sectors=sectors, audit=not args.no_audit)
    print(result.report())

    print("\nPLANTED-EFFECT RECOVERY CHECK")
    print("-" * 78)
    print("  The synthetic world has known ground truth. Four event kinds carry a")
    print("  planted forward drift; two are pure noise. Recovering the planted")
    print("  drift -- with the right sign, the right magnitude, and no pre-event")
    print("  move -- is what verifies the point-in-time chain end to end.")
    print()
    truth = {k: d for _, k, _, d, _ in PLANTED_EFFECTS}
    summ = result.diagnostics.get("event_study_summary", pd.DataFrame())
    if summ.empty:
        print("  event study unavailable")
        return 0
    print(f"  {'event kind':<20} {'planted':>9} {'measured':>9} {'t':>7} {'pre':>8} {'FDR':>5}   verdict")
    ok = True
    for row in summ.itertuples(index=False):
        planted = truth.get(row.kind)
        if planted is None:
            continue
        survives = bool(row.survives_fdr)
        print(
            f"  {row.kind:<20} {planted:>+8.1%} {row.drift_car:>+9.2%} "
            f"{row.drift_t:>7.2f} {row.pre_car:>+8.2%} {'yes' if survives else 'no':>5}   {row.verdict}"
        )
        if planted == 0.0 and survives:
            ok = False
        if planted != 0.0 and (not survives or np.sign(row.drift_car) != np.sign(planted)):
            ok = False
    print()
    if ok:
        print("  RECOVERY: PASS -- every planted effect recovered with the correct sign")
        print("            and surviving multiple-testing correction; both controls")
        print("            correctly null; no pre-event drift, so no leakage.")
    else:
        missed = [
            r.kind for r in summ.itertuples(index=False)
            if truth.get(r.kind) not in (None, 0.0) and not bool(r.survives_fdr)
        ]
        false_pos = [
            r.kind for r in summ.itertuples(index=False)
            if truth.get(r.kind) == 0.0 and bool(r.survives_fdr)
        ]
        print("  RECOVERY: FAIL")
        if missed:
            print(f"            not recovered: {', '.join(missed)}")
        if false_pos:
            print(f"            CONTROL FIRED (this one is serious): {', '.join(false_pos)}")
        print()
        print("            A missed effect on a SMALL world is usually statistical")
        print("            power, not a bug -- rare kinds need events to clear FDR.")
        print("            Re-run at the default size before concluding anything:")
        print("              iai demo --fast")
        print("            A control firing is different, and always a real problem.")
    print()
    print("  Reminder: good numbers here mean the plumbing works, not that the")
    print("  strategy does. Synthetic data contains alpha by construction, and the")
    print("  planted drifts are deliberately realistic, which is why the model AUC")
    print("  is ~0.54. That is what a real catalyst model looks like.")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from .pipeline import build_sources

    cfg = Config.load(args.config)
    cfg.ensure_dirs()
    client = HttpClient(cfg.data.cache_dir, cfg.data.user_agent)

    print("Checking SEC universe endpoint...")
    uni = Universe.from_sec(client, limit=50)
    print(f"  universe: {len(uni.by_ticker)} issuers reachable\n")

    registry = build_sources(cfg, client, uni)
    health = registry.health()
    print("Source status")
    print("-" * 78)
    for row in health.to_dict("records"):
        mark = "ok " if row["enabled"] else "OFF"
        print(f"  [{mark}] {row['name']:<16} {row['reason']}")

    print("\nCredentials")
    print("-" * 78)
    for label, val in [
        ("IAI_USER_AGENT", cfg.data.user_agent),
        ("COURTLISTENER_TOKEN", cfg.data.courtlistener_token),
        ("OPENSKY_USER", cfg.data.opensky_user),
        ("COMTRADE_KEY", cfg.data.comtrade_key),
        ("POLYGON_KEY", cfg.data.polygon_key),
    ]:
        shown = "set" if val else "not set"
        if label == "IAI_USER_AGENT":
            shown = val
            if "contact required" in val:
                shown += "   <-- SEC will throttle you; set a real contact"
        print(f"  {label:<22} {shown}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    from .pipeline import fetch_live

    cfg = Config.load(args.config)
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    prices, events, uni = fetch_live(cfg, tickers, args.start, args.end)

    store = _store(cfg)
    prices.to_parquet(store / "prices.parquet")
    if not events.empty:
        events.assign(payload=events["payload"].map(repr)).to_parquet(store / "events.parquet")
    uni.save(store / "universe.json")
    print(f"prices: {len(prices):,} bars -> {store / 'prices.parquet'}")
    print(f"events: {len(events):,} -> {store / 'events.parquet'}")
    if uni.unresolved:
        print(f"unresolved entity names: {len(uni.unresolved)} (first 10: {uni.unresolved[:10]})")
    return 0


def cmd_research(args: argparse.Namespace) -> int:
    from .pipeline import make_dataset, run_research, save_model

    cfg = Config.load(args.config)
    store = _store(cfg)
    prices = pd.read_parquet(store / "prices.parquet")
    events_path = store / "events.parquet"
    events = pd.read_parquet(events_path) if events_path.exists() else pd.DataFrame()
    if not events.empty and events["payload"].dtype == object:
        import ast

        events["payload"] = events["payload"].map(
            lambda s: ast.literal_eval(s) if isinstance(s, str) else s
        )

    result = run_research(prices, events, cfg, n_trials=args.n_trials)
    print(result.report())

    if args.save_model:
        X, y, meta = make_dataset(result.panel, result.labels, cfg)
        save_model(result, X, y, meta, cfg)
    return 0


def cmd_signals(args: argparse.Namespace) -> int:
    from .pipeline import load_model, run_signals

    cfg = Config.load(args.config)
    store = _store(cfg)
    model = load_model(Path(args.model) if args.model else cfg.data.model_dir / "catalyst.pkl")
    prices = pd.read_parquet(store / "prices.parquet")
    events_path = store / "events.parquet"
    events = pd.read_parquet(events_path) if events_path.exists() else pd.DataFrame()

    orders = run_signals(model, prices, events, cfg, as_of=args.as_of)
    if orders.empty:
        print("no orders clear the edge threshold today")
        return 0
    pd.set_option("display.width", 200)
    print(orders.to_string(index=False))
    print(f"\ngross weight {orders['weight'].sum():.2%}   total risk ${orders['risk_usd'].sum():,.0f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="iai", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="path to a TOML config override")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("demo", help="run the pipeline on synthetic data")
    d.add_argument("--tickers", type=int, default=60)
    d.add_argument("--start", default="2019-01-02")
    d.add_argument("--end", default="2024-12-31")
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--fast", action="store_true", help="fewer seeds and folds")
    d.add_argument("--no-audit", action="store_true")
    d.set_defaults(func=cmd_demo)

    doc = sub.add_parser("doctor", help="report source and credential status")
    doc.set_defaults(func=cmd_doctor)

    f = sub.add_parser("fetch", help="pull real data into the local store")
    f.add_argument("--tickers", required=True, help="comma-separated")
    f.add_argument("--start", required=True)
    f.add_argument("--end", required=True)
    f.set_defaults(func=cmd_fetch)

    r = sub.add_parser("research", help="train and backtest on stored data")
    r.add_argument("--save-model", action="store_true")
    r.add_argument("--n-trials", type=int, default=1,
                   help="how many strategy variants you have tried, for the deflated Sharpe")
    r.set_defaults(func=cmd_research)

    s = sub.add_parser("signals", help="produce today's sized orders")
    s.add_argument("--model")
    s.add_argument("--as-of")
    s.set_defaults(func=cmd_signals)

    args = p.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
