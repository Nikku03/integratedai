"""End-to-end orchestration: data -> features -> labels -> model -> backtest.

This is the module that ties the pieces together and the one to read first if
you want to know what actually runs. Two entry points:

:func:`run_research`
    The full historical pass. Fetch or load, assemble, label, audit for
    lookahead, walk-forward train, backtest, report.
:func:`run_signals`
    The daily production pass. Load the persisted model, build features for
    the most recent session only, emit sized orders.
"""

from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .backtest.costs import cost_summary
from .backtest.engine import Backtester, BacktestResult
from .backtest.metrics import monthly_table, trade_attribution
from .core.config import Config
from .core.http import HttpClient
from .core.types import validate_events
from .core.universe import Universe
from .diagnostics import coverage_report, event_study, event_study_summary, label_lift
from .features.assembler import assemble, audit_lookahead
from .labels import build_labels, label_summary
from .model.ensemble import assign_payoffs
from .model.train import (
    family_importance,
    fit_production,
    make_dataset,
    walk_forward,
)
from .sources.base import SourceRegistry
from .sources.edgar import EdgarFilings, EdgarFullText
from .sources.litigation import CourtListenerDockets
from .sources.prices import YahooPrices, add_derived
from .sources.shipping import BillOfLading, ComtradeFlows, TradeExposure
from .sources.synthetic import SyntheticWorld, synthetic_events_to_frame

log = logging.getLogger(__name__)


@dataclass
class ResearchResult:
    prices: pd.DataFrame
    events: pd.DataFrame
    panel: pd.DataFrame
    labels: pd.DataFrame
    fit: object
    backtest: BacktestResult
    audit: pd.DataFrame
    diagnostics: dict = field(default_factory=dict)

    def report(self) -> str:
        lines = ["=" * 78, "RESEARCH REPORT", "=" * 78, ""]

        lines += ["DATA", "-" * 78]
        lines.append(f"  prices : {len(self.prices):>8,} bars, {self.prices['ticker'].nunique()} tickers")
        lines.append(f"  events : {len(self.events):>8,} across {self.events['source'].nunique() if not self.events.empty else 0} sources")
        if not self.events.empty:
            counts = self.events["source"].value_counts()
            for src, n in counts.items():
                lines.append(f"           {src:<16} {n:>7,}")
        lines.append(f"  panel  : {len(self.panel):>8,} rows x {self.panel.shape[1] - 2} features")
        lines.append("")

        cov = self.diagnostics.get("coverage", pd.DataFrame())
        if not cov.empty:
            lines += ["COVERAGE", "-" * 78]
            lines.append("  " + cov.to_string(index=False).replace("\n", "\n  "))
            lines.append("")

        lines += ["LABELS", "-" * 78]
        lines.append(label_summary(self.labels).to_string(index=False))
        lines.append("")

        summ = self.diagnostics.get("event_study_summary", pd.DataFrame())
        if not summ.empty:
            lines += ["EVENT STUDY (abnormal returns around each event kind)", "-" * 78]
            lines.append("  pre_car      : move BEFORE our timestamp. Large => data is late, or")
            lines.append("                 the event is endogenous to the prior move.")
            lines.append("  day0_car     : the announcement move. Not available to us.")
            lines.append("  drift_car    : days +1..+20. The only part we can trade.")
            lines.append("  survives_fdr : READ THIS, not drift_t. Benjamini-Hochberg across all")
            lines.append(f"                 {len(summ)} kinds tested here -- a |t|>2 shows up by chance otherwise.")
            lines.append("")
            lines.append("  " + summ.to_string(index=False).replace("\n", "\n  "))
            lines.append("")

        lift = self.diagnostics.get("label_lift", pd.DataFrame())
        if not lift.empty:
            lines += ["LABEL LIFT (model-free: P(upper barrier | event) vs base rate)", "-" * 78]
            lines.append("  " + lift.to_string(index=False).replace("\n", "\n  "))
            lines.append("")

        lines += ["LOOKAHEAD AUDIT", "-" * 78]
        if self.audit.empty:
            lines.append("  not run")
        else:
            flagged = self.audit[self.audit["suspicious"]]
            if flagged.empty:
                top = self.audit.head(5)[["feature", "rho", "z"]]
                lines.append("  clean. strongest associations (all within the null):")
                lines.append("  " + top.to_string(index=False).replace("\n", "\n  "))
            else:
                lines.append("  *** FLAGGED — DO NOT TRADE THIS UNTIL RESOLVED ***")
                lines.append("  " + flagged[["feature", "rho", "z"]].to_string(index=False).replace("\n", "\n  "))
        lines.append("")

        lines += ["MODEL (walk-forward, out-of-sample)", "-" * 78]
        lines.append(f"  pooled AUC   : {self.fit.auc:.4f}   (0.50 = no signal)")
        lines.append(f"  pooled Brier : {self.fit.brier:.4f}")
        lines.append("")
        lines.append("  " + self.fit.fold_metrics[["fold", "train", "test", "n_train", "n_test", "n_purged", "auc"]].to_string(index=False).replace("\n", "\n  "))
        lines.append("")
        perm = getattr(self.fit, "perm_importance", pd.DataFrame())
        if not perm.empty:
            lines.append("  contribution by data source (out-of-sample AUC drop when shuffled):")
            lines.append("  " + family_importance(perm, "auc_drop").to_string(index=False).replace("\n", "\n  "))
            lines.append("")
            lines.append("  top 12 features by AUC drop:")
            lines.append("  " + perm.head(12)[["feature", "auc_drop", "auc_drop_std"]].to_string(index=False).replace("\n", "\n  "))
            lines.append("")
            lines.append("  features whose removal would not hurt (auc_drop <= 0):")
            dead = perm[perm["auc_drop"] <= 0]["feature"].tolist()
            lines.append(f"    {len(dead)} of {len(perm)}: {', '.join(dead[:12])}{' ...' if len(dead) > 12 else ''}")
            lines.append("")
        lines.append("  split gain by data source (biased toward frequent features -- compare above):")
        lines.append("  " + family_importance(self.fit.importance, "gain").to_string(index=False).replace("\n", "\n  "))
        lines.append("")

        lines += ["BACKTEST (net of modelled costs)", "-" * 78]
        summary = self.backtest.summary()
        if summary.empty:
            lines.append("  no trades")
        else:
            for col in summary.columns:
                val = summary.iloc[0][col]
                if isinstance(val, float):
                    lines.append(f"  {col:<24} {val:>12.4f}")
                else:
                    lines.append(f"  {col:<24} {str(val):>12}")
        lines.append("")
        cs = cost_summary(self.backtest.fills, Config())
        if not cs.empty:
            lines += ["COSTS", "-" * 78, "  " + cs.to_string(index=False).replace("\n", "\n  "), ""]
        if not self.backtest.breaches.empty:
            top = self.backtest.breaches["limit"].value_counts().head(8)
            lines += ["RISK LIMITS HIT", "-" * 78]
            for k, v in top.items():
                lines.append(f"  {k:<28} {v:>6,}")
            lines.append("")

        lines.append("=" * 78)
        return "\n".join(lines)


def build_sources(
    cfg: Config,
    client: HttpClient,
    universe: Universe,
    *,
    trade_exposure: TradeExposure | None = None,
    bol_path: str | Path | None = None,
) -> SourceRegistry:
    """Wire up the sources that have what they need to run."""
    sources = [
        EdgarFilings(cfg, client, universe),
        EdgarFullText(cfg, client, universe),
        CourtListenerDockets(cfg, client, universe),
        ComtradeFlows(cfg, client, universe, exposure=trade_exposure),
        BillOfLading(cfg, client, universe, path=bol_path),
    ]
    return SourceRegistry(sources)


def load_synthetic(
    cfg: Config, **kwargs
) -> tuple[pd.DataFrame, pd.DataFrame, Universe, dict[str, str]]:
    """Deterministic offline world. See :mod:`iai.sources.synthetic` for caveats."""
    world = SyntheticWorld(**kwargs)
    prices, raw_events = world.generate()
    events = validate_events(synthetic_events_to_frame(raw_events))
    return add_derived(prices, cfg), events, world.universe(), world.sectors()


def fetch_live(
    cfg: Config,
    tickers: list[str],
    start: str,
    end: str,
    *,
    universe: Universe | None = None,
    trade_exposure: TradeExposure | None = None,
    bol_path: str | Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, Universe]:
    """Fetch real data for ``tickers`` over ``[start, end]``."""
    cfg.ensure_dirs()
    client = HttpClient(
        cfg.data.cache_dir, cfg.data.user_agent, rate_per_sec=5.0, ttl_hours=cfg.data.cache_ttl_hours
    )
    if universe is None:
        universe = Universe.from_sec(client)
    uni = universe.subset(tickers) if tickers else universe

    prices = YahooPrices(cfg, client).fetch(uni.tickers, pd.Timestamp(start), pd.Timestamp(end))
    prices = add_derived(prices, cfg)

    registry = build_sources(cfg, client, uni, trade_exposure=trade_exposure, bol_path=bol_path)
    log.info("source health:\n%s", registry.health().to_string(index=False))
    events = registry.collect(pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"))
    return prices, events, uni


def run_research(
    prices: pd.DataFrame,
    events: pd.DataFrame,
    cfg: Config,
    *,
    sectors: dict[str, str] | None = None,
    audit: bool = True,
    n_trials: int = 1,
) -> ResearchResult:
    """The full historical pass."""
    log.info("assembling features")
    panel = assemble(prices, events, cfg)
    if panel.empty:
        raise ValueError("feature panel is empty; check that prices cover the event window")

    log.info("labelling")
    labels = build_labels(prices, cfg)

    # Event study before modelling. If a source shows no tradable drift here,
    # no model will find one, and knowing that costs seconds rather than days.
    log.info("running event study")
    study = event_study(events, prices, cfg)
    study_summary = event_study_summary(study)
    lift = label_lift(events, labels, cfg)
    coverage = coverage_report(events, prices["ticker"].nunique())

    audit_df = pd.DataFrame()
    if audit:
        log.info("auditing for lookahead")
        audit_df = audit_lookahead(panel, labels)

    log.info("building dataset")
    X, y, meta = make_dataset(panel, labels, cfg)
    log.info("dataset: %d rows, %d features, base rate %.3f", len(X), X.shape[1], y.mean())

    log.info("walk-forward training")
    fit = walk_forward(X, y, meta, cfg)

    # Out-of-fold predictions become the backtest's signals. This is the only
    # honest way to backtest a model: every prediction used to trade on day t
    # came from a model that never saw day t.
    signals = fit.oof.merge(
        meta[["date", "ticker", "barrier_up", "barrier_dn"]], on=["date", "ticker"], how="left"
    )
    signals = assign_payoffs(signals, fit.payoff_table)

    log.info("backtesting %d out-of-sample signals", len(signals))
    bt = Backtester(cfg, prices, sectors=sectors).run(
        signals[["date", "ticker", "p", "dispersion", "avg_win", "avg_loss"]]
    )

    diagnostics = {
        "monthly": monthly_table(bt.equity),
        "attribution_sector": trade_attribution(bt.trades, "sector"),
        "attribution_reason": trade_attribution(bt.trades, "reason"),
        "event_study": study,
        "event_study_summary": study_summary,
        "label_lift": lift,
        "coverage": coverage,
        "n_trials": n_trials,
    }
    return ResearchResult(
        prices=prices, events=events, panel=panel, labels=labels,
        fit=fit, backtest=bt, audit=audit_df, diagnostics=diagnostics,
    )


def save_model(result: ResearchResult, X, y, meta, cfg: Config, path: Path | None = None) -> Path:
    """Refit on everything and persist model, calibrator and payoff table."""
    cfg.ensure_dirs()
    path = Path(path) if path else cfg.data.model_dir / "catalyst.pkl"
    model = fit_production(X, y, meta, cfg, result.fit)
    with open(path, "wb") as fh:
        pickle.dump({"model": model, "config": cfg.to_dict(), "features": model.features}, fh)
    (path.with_suffix(".json")).write_text(
        json.dumps(
            {
                "auc": result.fit.auc,
                "brier": result.fit.brier,
                "n_samples": int(len(X)),
                "features": model.features,
                "trained_through": str(meta["date"].max().date()),
            },
            indent=2,
        )
    )
    log.info("saved model to %s", path)
    return path


def load_model(path: Path):
    with open(path, "rb") as fh:
        return pickle.load(fh)["model"]


def run_signals(
    model,
    prices: pd.DataFrame,
    events: pd.DataFrame,
    cfg: Config,
    *,
    as_of: pd.Timestamp | None = None,
    sectors: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Produce today's sized orders.

    Returns one row per proposed position with the calibrated probability, the
    expected edge, the stop, and the target weight -- everything a human needs
    to sanity-check the trade before it is sent.
    """
    from .risk.limits import stop_levels
    from .risk.sizing import size_positions

    panel = assemble(prices, events, cfg)
    if panel.empty:
        return pd.DataFrame()

    as_of = pd.Timestamp(as_of) if as_of is not None else panel["date"].max()
    today = panel[panel["date"] == as_of].copy()
    if today.empty:
        log.warning("no feature rows for %s", as_of.date())
        return pd.DataFrame()

    X = today.reindex(columns=model.features).astype("float64")
    today["p"] = model.calibrated_proba(X)
    today["dispersion"] = model.predict_dispersion(X)

    px = prices[prices["date"] == as_of].set_index("ticker")
    rows = []
    for row in today.itertuples(index=False):
        if row.ticker not in px.index:
            continue
        bar = px.loc[row.ticker]
        sigma = float(bar.get("vol", float("nan")))
        if not pd.notna(sigma) or sigma <= 0:
            continue
        _, stop_pct = stop_levels(float(bar["close"]), sigma, cfg)
        rows.append(
            {
                "date": as_of,
                "ticker": row.ticker,
                "p": float(row.p),
                "dispersion": float(row.dispersion),
                "close": float(bar["close"]),
                "stop_pct": stop_pct,
                "target_pct": float(cfg.labels.upper_mult * sigma * (cfg.labels.max_holding_days ** 0.5)),
                "adv_usd": float(bar.get("adv_usd", float("nan"))),
                "sector": (sectors or {}).get(row.ticker, "unknown"),
            }
        )
    cand = pd.DataFrame(rows)
    if cand.empty:
        return cand

    table = getattr(model, "payoff_table", pd.DataFrame())
    if not table.empty:
        cand["barrier_up"] = cand["close"] * (1 + cand["target_pct"])
        cand["barrier_dn"] = cand["close"] * (1 - cand["stop_pct"])
        cand = assign_payoffs(cand, table)
    else:
        cand["avg_win"] = cand["target_pct"]
        cand["avg_loss"] = -cand["stop_pct"]

    sized = size_positions(cand, cfg)
    cols = ["date", "ticker", "p", "edge", "weight", "notional", "stop_pct", "target_pct",
            "risk_usd", "dispersion", "close", "sector"]
    return sized[[c for c in cols if c in sized.columns]].sort_values("edge", ascending=False)
