from __future__ import annotations

import pytest

from iai.core.config import Config
from iai.pipeline import load_synthetic


@pytest.fixture(scope="session")
def cfg() -> Config:
    c = Config()
    c.model.n_seeds = 2
    c.model.n_estimators = 120
    c.model.n_splits = 3
    return c


@pytest.fixture(scope="session")
def world(cfg):
    """Small deterministic world, shared across the suite for speed."""
    prices, events, universe, sectors = load_synthetic(
        cfg, n_tickers=25, start="2020-01-02", end="2023-06-30", seed=11
    )
    return {"prices": prices, "events": events, "universe": universe, "sectors": sectors}
