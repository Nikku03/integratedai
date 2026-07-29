"""Configuration. Everything tunable lives here or in a user TOML override."""

from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path(os.environ.get("IAI_HOME", Path.home() / ".iai"))


@dataclass
class DataConfig:
    root: Path = DEFAULT_ROOT
    cache_ttl_hours: float = 12.0
    #: Contact string sent as User-Agent. The SEC blocks anonymous scrapers and
    #: is entirely within its rights to; put a real address here.
    user_agent: str = os.environ.get("IAI_USER_AGENT", "integratedai/0.1 (research contact required)")
    #: Optional API keys. Absent keys degrade the relevant source to no-op
    #: rather than raising, so the pipeline still runs on free data alone.
    courtlistener_token: str | None = os.environ.get("COURTLISTENER_TOKEN")
    opensky_user: str | None = os.environ.get("OPENSKY_USER")
    opensky_pass: str | None = os.environ.get("OPENSKY_PASS")
    comtrade_key: str | None = os.environ.get("COMTRADE_KEY")
    polygon_key: str | None = os.environ.get("POLYGON_KEY")

    @property
    def cache_dir(self) -> Path:
        return Path(self.root) / "cache"

    @property
    def store_dir(self) -> Path:
        return Path(self.root) / "store"

    @property
    def model_dir(self) -> Path:
        return Path(self.root) / "models"


@dataclass
class FeatureConfig:
    #: Half-lives in trading days for exponentially decayed event intensity.
    #: Short captures "something just happened"; long captures "this name has
    #: been structurally busy for a quarter".
    halflives: tuple[int, ...] = (2, 5, 21, 63)
    #: Lookback for the surprise/novelty z-score baseline.
    novelty_window: int = 252
    #: Market microstructure lookbacks.
    vol_window: int = 21
    momentum_windows: tuple[int, ...] = (5, 21, 63, 126)
    #: Minimum dollar volume to keep a name in the tradable universe.
    min_adv_usd: float = 2_000_000.0
    #: Minimum price, to keep sub-dollar names out of the backtest where the
    #: bid-ask spread eats the entire edge.
    min_price: float = 3.0


@dataclass
class LabelConfig:
    """Triple-barrier labelling parameters.

    The horizon is deliberately days-to-weeks: that is the window over which an
    8-K, a docket entry or a discharged cargo actually gets absorbed into price.
    Shorter and you are competing with latency shops; longer and the catalyst is
    swamped by beta.
    """

    max_holding_days: int = 15
    #: Barriers are set at ``mult * sigma`` where sigma is trailing daily vol
    #: scaled to the holding horizon. Volatility-scaled barriers keep the label
    #: balanced across a 90%-vol biotech and a 15%-vol utility.
    #:
    #: These multipliers are not free parameters to tune for backtest Sharpe --
    #: they define what the model is being asked to predict, and they must make
    #: the label *bind*. At 2.0/1.5 the barriers are so wide that 83% of trades
    #: exit on the time stop, which means the "loss" bucket is dominated by
    #: flat outcomes, ``avg_loss`` collapses toward zero, and the Kelly
    #: denominator explodes. At 1.0/0.8 roughly a third of trades touch each
    #: barrier and the payoff ratio lands near 3:1 -- an asymmetric bet, which
    #: is the shape this strategy wants, on a label that is actually decidable.
    upper_mult: float = 1.0
    lower_mult: float = 0.8
    vol_window: int = 21
    #: Trades are entered on the open *after* availability, never the close of
    #: the day the news broke.
    entry_lag_days: int = 1


@dataclass
class ModelConfig:
    n_seeds: int = 5
    learning_rate: float = 0.03
    num_leaves: int = 31
    min_child_samples: int = 60
    feature_fraction: float = 0.7
    bagging_fraction: float = 0.8
    bagging_freq: int = 1
    lambda_l2: float = 5.0
    n_estimators: int = 400
    early_stopping_rounds: int = 50
    #: Purge and embargo, in trading days, for walk-forward CV. Purge must be
    #: >= max_holding_days or the label of a training sample overlaps the test
    #: window and the model is scored on information it partly memorised.
    purge_days: int = 15
    embargo_days: int = 5
    n_splits: int = 6
    min_train_samples: int = 500


@dataclass
class RiskConfig:
    """The 'safe' half of 'safe high variability'.

    Variance is bought at the portfolio level through breadth and convexity,
    never by concentrating into a single name. Each individual bet is small
    and hard-capped; the distribution of outcomes is wide because there are
    many of them and their payoffs are skewed, not because any one of them can
    sink the book.
    """

    capital: float = 100_000.0
    #: Fraction of full Kelly to actually deploy. Full Kelly on estimated edges
    #: is a good way to find out how wrong your estimates are.
    kelly_fraction: float = 0.25
    #: Hard cap on capital at risk in a single position.
    max_risk_per_trade: float = 0.01
    #: Hard cap on notional in a single position.
    max_weight_per_name: float = 0.06
    max_gross_exposure: float = 1.5
    max_net_exposure: float = 0.5
    max_positions: int = 30
    #: Cap on summed weight of names sharing a sector.
    max_sector_weight: float = 0.30
    #: Annualised portfolio vol target used to scale total gross.
    target_vol: float = 0.20
    #: Stop loss and time stop.
    stop_loss_sigma: float = 1.5
    max_holding_days: int = 15
    #: Below this calibrated edge, do not trade. Covers costs plus a margin.
    min_edge: float = 0.015
    #: Kill switch: flatten everything if trailing drawdown exceeds this.
    max_drawdown: float = 0.20


@dataclass
class CostConfig:
    commission_bps: float = 0.5
    #: Half-spread paid on entry and exit.
    half_spread_bps: float = 5.0
    #: Square-root market impact coefficient: impact_bps = coef * sqrt(participation).
    impact_coef_bps: float = 25.0
    #: Max fraction of ADV a single order may take.
    max_participation: float = 0.05
    borrow_bps_annual: float = 300.0


@dataclass
class Config:
    data: DataConfig = field(default_factory=DataConfig)
    features: FeatureConfig = field(default_factory=FeatureConfig)
    labels: LabelConfig = field(default_factory=LabelConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    costs: CostConfig = field(default_factory=CostConfig)

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        cfg = cls()
        if path is None:
            return cfg
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
        for section, values in raw.items():
            if not hasattr(cfg, section):
                raise KeyError(f"unknown config section: {section}")
            sub = getattr(cfg, section)
            valid = {f.name: f for f in fields(sub)}
            for key, val in values.items():
                if key not in valid:
                    raise KeyError(f"unknown key {section}.{key}")
                if valid[key].type in ("tuple[int, ...]", tuple) and isinstance(val, list):
                    val = tuple(val)
                setattr(sub, key, val)
        return cfg

    def to_dict(self) -> dict[str, Any]:
        def _clean(obj: Any) -> Any:
            if isinstance(obj, Path):
                return str(obj)
            if isinstance(obj, tuple):
                return list(obj)
            if isinstance(obj, dict):
                return {k: _clean(v) for k, v in obj.items()}
            return obj

        return {k: _clean(v) for k, v in asdict(self).items() if is_dataclass(getattr(self, k))}

    def ensure_dirs(self) -> None:
        for d in (self.data.cache_dir, self.data.store_dir, self.data.model_dir):
            d.mkdir(parents=True, exist_ok=True)

    @classmethod
    def short_horizon(cls) -> Config:
        """Preset for fast, asymmetric, small/mid-cap catalyst trades.

        Differs from the default in four ways, each deliberate:

        **Horizon 8 sessions, not 15.** The move you are trying to capture is
        the reaction to a discrete event. Past a couple of weeks you are no
        longer holding a catalyst, you are holding beta, and the ratio of
        signal to noise falls the whole way.

        **Asymmetric barriers (1.5 up / 0.75 down).** You asked for big reward
        on a short trade. That means accepting a *lower* hit rate to get a
        payoff ratio near 4:1 -- cut fast, let the winners run to a distant
        target. This is the opposite of the symmetric barrier that maximises
        label balance, and it is the right trade-off when the payoff is the
        point.

        **Faster decay half-lives.** A volume surge is stale in a week. The
        default half-lives are tuned for filings that matter for a quarter.

        **Wider participation and lower ADV floor**, because small caps are the
        target and a $2m ADV floor screens most of them out. This raises real
        execution cost, which the cost model then charges you for -- the
        backtest gets worse and more honest at the same time.
        """
        cfg = cls()

        cfg.labels.max_holding_days = 8
        cfg.labels.upper_mult = 1.5
        cfg.labels.lower_mult = 0.75
        cfg.labels.vol_window = 21

        cfg.features.halflives = (1, 3, 10, 21)
        cfg.features.min_adv_usd = 750_000.0
        cfg.features.min_price = 2.0

        cfg.model.purge_days = 10  # must stay >= max_holding_days
        cfg.model.embargo_days = 3

        cfg.risk.max_holding_days = 8
        cfg.risk.stop_loss_sigma = 1.0
        cfg.risk.max_positions = 25
        cfg.risk.max_weight_per_name = 0.05
        cfg.risk.max_risk_per_trade = 0.0075
        # Small caps on news days are expensive. Charge for it.
        cfg.costs.half_spread_bps = 15.0
        cfg.costs.impact_coef_bps = 45.0
        cfg.costs.max_participation = 0.03
        return cfg
