"""Assemble the modelling matrix and audit it for lookahead.

Two things happen here that are worth stating plainly.

**One timing convention, applied once.**

    panel row dated t  ->  contains only what was public at the close of t
    trade for row t    ->  entered at the open of t+1

Market features on row ``t`` are computed from bars through ``t``, which is
close-of-``t`` information. Event features on row ``t`` come from
:func:`~iai.features.events.attach_entry_session`, which assigns each event to
the session by whose close it was public. The single session of lag between
knowing and trading lives in :mod:`iai.labels` and in the backtest engine,
both of which fill at the open of ``t+1``.

There is deliberately **no** extra ``shift(1)`` here. An earlier version of
this module applied one, which -- stacked on top of the lag already inside the
event mapping -- pushed event features two to three sessions late and threw
away the first and largest part of every catalyst move. If you add a lag, add
it in exactly one place and write down which.

**The audit is not optional.** :func:`audit_lookahead` runs a shuffle test: it
re-computes the correlation between each feature and the label after randomly
permuting the label *within each date*. Any feature whose real correlation sits
outside the permuted distribution by an implausible margin is flagged. This
catches the leak class that visual inspection never does -- a feature that is
subtly a function of the future -- because a genuine cross-sectional signal has
a correlation of a few percent and a leaked one has a correlation of thirty.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..core.config import Config
from ..core.types import LookaheadError
from .events import build_event_features, kind_features
from .market import build_market_features

log = logging.getLogger(__name__)

ID_COLS = ["date", "ticker"]


def assemble(
    prices: pd.DataFrame,
    events: pd.DataFrame,
    cfg: Config,
    *,
    include_kinds: bool = True,
    kind_top_k: int = 25,
) -> pd.DataFrame:
    """Join market and event features into one lagged panel.

    Rows are restricted to tradable (ticker, date) cells: below the liquidity
    or price floor there is no trade to make, and keeping those rows would let
    the model fit relationships it can never act on.
    """
    market = build_market_features(prices, cfg)
    if market.empty:
        return pd.DataFrame(columns=ID_COLS)

    ev = build_event_features(events, cfg, calendar=pd.DatetimeIndex(sorted(market["date"].unique())))
    panel = market.merge(ev, on=ID_COLS, how="left") if not ev.empty else market

    if include_kinds and not events.empty:
        kinds = kind_features(events, cfg, top_k=kind_top_k)
        if not kinds.empty:
            panel = panel.merge(kinds, on=ID_COLS, how="left")

    feature_cols = [c for c in panel.columns if c not in ID_COLS]
    # Event features are genuinely zero where no event occurred; market
    # features are genuinely missing during warm-up and must stay NaN so the
    # model can route around them rather than being told "the vol was 0".
    event_like = [c for c in feature_cols if c.startswith(("kind_", "all_")) or "_int_h" in c or "_cnt_" in c or "_maxw_" in c]
    panel[event_like] = panel[event_like].fillna(0.0)

    # Row t already holds only close-of-t information; the lag to execution is
    # applied once, at fill time. See the module docstring.
    out = panel.sort_values(ID_COLS).reset_index(drop=True)

    # Restrict to tradable cells.
    if "tradable" in prices.columns:
        mask = prices[["date", "ticker", "tradable"]]
        out = out.merge(mask, on=ID_COLS, how="left")
        out = out[out["tradable"].fillna(False)].drop(columns=["tradable"])

    return out.reset_index(drop=True)


def feature_columns(panel: pd.DataFrame) -> list[str]:
    return [c for c in panel.columns if c not in ID_COLS and not c.startswith("label")]


def audit_lookahead(
    panel: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    n_shuffles: int = 30,
    z_threshold: float = 6.0,
    seed: int = 0,
) -> pd.DataFrame:
    """Flag features whose association with the label is too strong to be real.

    For each feature, compare its Spearman correlation with the label against
    the distribution obtained by shuffling the label within each date. A
    cross-sectional equity signal that survives costs typically lands at
    |rho| < 0.10. Anything sitting six sigma outside its own null is far more
    likely to be a leak than a discovery, and this returns those rows sorted
    worst-first.
    """
    df = panel.merge(labels[["date", "ticker", "label"]], on=ID_COLS, how="inner").dropna(
        subset=["label"]
    )
    if df.empty:
        return pd.DataFrame(columns=["feature", "rho", "null_mean", "null_std", "z", "suspicious"])

    cols = [c for c in feature_columns(df) if c != "label" and pd.api.types.is_numeric_dtype(df[c])]
    rng = np.random.default_rng(seed)
    y = df["label"].to_numpy(dtype="float64")
    date_codes = pd.factorize(df["date"])[0]

    def _rho(a: np.ndarray, b: np.ndarray) -> float:
        ok = np.isfinite(a) & np.isfinite(b)
        if ok.sum() < 30:
            return np.nan
        ra = pd.Series(a[ok]).rank().to_numpy()
        rb = pd.Series(b[ok]).rank().to_numpy()
        sa, sb = ra.std(), rb.std()
        if sa == 0 or sb == 0:
            return 0.0
        return float(np.corrcoef(ra, rb)[0, 1])

    # Pre-compute the within-date shuffles once and reuse across features, so
    # every feature is tested against the same null.
    order = np.argsort(date_codes, kind="stable")
    shuffled = []
    for _ in range(n_shuffles):
        y_s = y.copy()
        for _, idx in pd.Series(order).groupby(date_codes[order]):
            block = idx.to_numpy()
            y_s[block] = rng.permutation(y[block])
        shuffled.append(y_s)

    rows = []
    for col in cols:
        x = df[col].to_numpy(dtype="float64")
        rho = _rho(x, y)
        if not np.isfinite(rho):
            continue
        null = np.array([_rho(x, ys) for ys in shuffled], dtype="float64")
        null = null[np.isfinite(null)]
        if null.size < 5:
            continue
        mu, sd = float(null.mean()), float(null.std(ddof=1))
        z = (rho - mu) / sd if sd > 0 else 0.0
        rows.append(
            {
                "feature": col,
                "rho": rho,
                "null_mean": mu,
                "null_std": sd,
                "z": z,
                "suspicious": bool(abs(z) > z_threshold and abs(rho) > 0.15),
            }
        )

    out = pd.DataFrame(rows).sort_values("z", key=lambda s: s.abs(), ascending=False)
    n_bad = int(out["suspicious"].sum()) if not out.empty else 0
    if n_bad:
        log.warning(
            "lookahead audit flagged %d feature(s): %s",
            n_bad,
            out.loc[out["suspicious"], "feature"].tolist(),
        )
    return out.reset_index(drop=True)


def assert_no_lookahead(panel: pd.DataFrame, labels: pd.DataFrame, **kwargs) -> None:
    """Raise :class:`LookaheadError` if the audit flags anything."""
    report = audit_lookahead(panel, labels, **kwargs)
    bad = report[report["suspicious"]] if not report.empty else report
    if not bad.empty:
        raise LookaheadError(
            "features implausibly correlated with the label:\n"
            + bad[["feature", "rho", "z"]].to_string(index=False)
        )
