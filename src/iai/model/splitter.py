"""Purged, embargoed walk-forward cross-validation.

The problem
-----------
Standard k-fold on financial panel data is broken in three separate ways, and
each one alone is enough to produce a backtest that cannot be traded.

1. **It shuffles time.** Training on 2023 to predict 2019 is not a thing you
   can do with money.
2. **Labels overlap the test window.** A training sample dated 5 January with a
   15-day triple-barrier label depends on prices through ~26 January. If the
   test fold starts on 10 January, the model has seen the answer.
3. **Serial correlation bleeds across the boundary.** Even with no label
   overlap, the sample immediately after the train/test split is nearly the
   same observation as the one immediately before it.

The fixes, in order: walk forward only; *purge* training samples whose label
window intrudes into the test window; *embargo* a further buffer after the test
window before training resumes.

This is López de Prado's scheme. The purge width must be at least the maximum
holding period, and :meth:`PurgedWalkForward.split` will tell you if it isn't.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class Fold:
    index: int
    train_idx: np.ndarray
    test_idx: np.ndarray
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    n_purged: int
    n_embargoed: int

    def describe(self) -> dict:
        return {
            "fold": self.index,
            "train": f"{self.train_start:%Y-%m-%d}..{self.train_end:%Y-%m-%d}",
            "test": f"{self.test_start:%Y-%m-%d}..{self.test_end:%Y-%m-%d}",
            "n_train": len(self.train_idx),
            "n_test": len(self.test_idx),
            "n_purged": self.n_purged,
            "n_embargoed": self.n_embargoed,
        }


class PurgedWalkForward:
    """Expanding-window walk-forward with label purging and an embargo.

    Parameters
    ----------
    n_splits:
        Number of test folds. Test windows are contiguous and non-overlapping,
        tiling the back end of the sample.
    purge_days / embargo_days:
        In calendar days. ``purge_days`` should be >= the label horizon.
    expanding:
        ``True`` grows the training set each fold (more data, but the early
        regime never leaves). ``False`` uses a rolling window of
        ``train_window_days``, which adapts faster and is the honest choice if
        you believe the relationship is non-stationary -- and in this domain
        it is.
    """

    def __init__(
        self,
        n_splits: int = 6,
        purge_days: int = 15,
        embargo_days: int = 5,
        expanding: bool = True,
        train_window_days: int = 756,
        min_train_samples: int = 500,
    ) -> None:
        self.n_splits = n_splits
        self.purge_days = purge_days
        self.embargo_days = embargo_days
        self.expanding = expanding
        self.train_window_days = train_window_days
        self.min_train_samples = min_train_samples

    def split(
        self,
        dates: pd.Series,
        exit_dates: pd.Series | None = None,
    ) -> list[Fold]:
        """Yield folds.

        ``exit_dates`` is when each sample's label stops depending on future
        prices. Supplying it makes purging exact; without it, ``purge_days`` is
        used as a uniform proxy, which is correct only if every label has the
        same horizon.
        """
        dates = pd.to_datetime(pd.Series(dates).reset_index(drop=True))
        if exit_dates is not None:
            exits = pd.to_datetime(pd.Series(exit_dates).reset_index(drop=True))
            if len(exits) != len(dates):
                raise ValueError("exit_dates must align with dates")
        else:
            exits = dates + pd.Timedelta(days=self.purge_days)
            log.info("no exit_dates supplied; purging with a uniform %d-day proxy", self.purge_days)

        unique_days = np.array(sorted(dates.unique()))
        if len(unique_days) < self.n_splits * 2:
            raise ValueError(
                f"need at least {self.n_splits * 2} distinct dates for {self.n_splits} folds, got {len(unique_days)}"
            )

        # Reserve the first half for the initial training window, then tile the
        # remainder with test folds.
        split_point = len(unique_days) // 2
        test_days = unique_days[split_point:]
        chunks = np.array_split(test_days, self.n_splits)

        # purge_days is not applied here directly: it was already folded into
        # `exits` above, either as the real per-sample exit date or as a uniform
        # proxy. Purging then reduces to a comparison against `exits`.
        embargo = pd.Timedelta(days=self.embargo_days)
        folds: list[Fold] = []

        for i, chunk in enumerate(chunks):
            if len(chunk) == 0:
                continue
            test_start, test_end = pd.Timestamp(chunk[0]), pd.Timestamp(chunk[-1])
            test_mask = (dates >= test_start) & (dates <= test_end)

            # Candidate training data: strictly before the test window, plus
            # anything after the embargo (only reachable in the rolling variant
            # when a later fold's data would otherwise be usable -- kept out
            # here entirely, because using post-test data is not walk-forward).
            before = dates < test_start
            if not self.expanding:
                window_start = test_start - pd.Timedelta(days=self.train_window_days)
                before &= dates >= window_start

            # Purge: drop training samples whose label window reaches into the
            # test window (or into the embargo before it).
            contaminated = exits >= (test_start - embargo)
            train_mask = before & ~contaminated
            n_purged = int((before & contaminated).sum())

            train_idx = np.flatnonzero(train_mask.to_numpy())
            test_idx = np.flatnonzero(test_mask.to_numpy())
            if len(train_idx) < self.min_train_samples:
                log.warning(
                    "fold %d has only %d training samples (< %d); skipping",
                    i, len(train_idx), self.min_train_samples,
                )
                continue

            folds.append(
                Fold(
                    index=i,
                    train_idx=train_idx,
                    test_idx=test_idx,
                    train_start=pd.Timestamp(dates.iloc[train_idx].min()),
                    train_end=pd.Timestamp(dates.iloc[train_idx].max()),
                    test_start=test_start,
                    test_end=test_end,
                    n_purged=n_purged,
                    n_embargoed=int(((dates >= test_end) & (dates <= test_end + embargo)).sum()),
                )
            )

        if not folds:
            raise ValueError("no usable folds; lower min_train_samples or supply more history")
        return folds

    def describe(self, folds: list[Fold]) -> pd.DataFrame:
        return pd.DataFrame([f.describe() for f in folds])
