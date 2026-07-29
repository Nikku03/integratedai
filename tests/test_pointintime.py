"""Point-in-time correctness. These are the tests that matter most.

Every other test in this suite checks that a function does what it says. These
check that no function can see the future, which is the only failure mode that
produces a profitable backtest and an unprofitable account.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from iai.core.calendar import entry_session, is_session
from iai.core.types import Event, LookaheadError, events_to_frame, validate_events
from iai.features.assembler import assemble, assert_no_lookahead, audit_lookahead
from iai.features.events import attach_entry_session
from iai.labels import build_labels


def test_event_rejects_time_travel():
    df = events_to_frame(
        [
            Event(
                source="edgar",
                kind="8-K.1.01",
                ticker="AAA",
                event_ts="2024-03-05T14:00:00Z",
                # Available an hour BEFORE it happened.
                available_ts="2024-03-05T13:00:00Z",
            )
        ]
    )
    with pytest.raises(LookaheadError, match="time travel"):
        validate_events(df)


def test_event_timestamps_are_utc_aware():
    e = Event("edgar", "8-K.1.01", "aaa", "2024-03-05 09:30", "2024-03-05 09:45")
    assert e.event_ts.tzinfo is not None
    assert e.available_ts.tzinfo is not None
    assert e.ticker == "AAA"
    assert e.latency.total_seconds() == 900


def test_calendar_skips_weekends_and_holidays():
    assert not is_session(pd.Timestamp("2024-01-01"))  # New Year
    assert not is_session(pd.Timestamp("2024-03-29"))  # Good Friday
    assert not is_session(pd.Timestamp("2024-07-04"))  # Independence Day
    assert not is_session(pd.Timestamp("2024-06-19"))  # Juneteenth
    assert not is_session(pd.Timestamp("2024-03-30"))  # Saturday
    assert is_session(pd.Timestamp("2024-03-28"))


def test_entry_session_intraday_news_lands_same_session():
    """News at 10:00 ET Tuesday is public by Tuesday's close."""
    ts = pd.Timestamp("2024-03-05 10:00", tz="America/New_York").tz_convert("UTC")
    assert entry_session(ts, lag_days=0) == pd.Timestamp("2024-03-05")


def test_entry_session_after_hours_rolls_forward():
    """News at 16:15 ET Tuesday missed the cutoff and belongs to Wednesday."""
    ts = pd.Timestamp("2024-03-05 16:15", tz="America/New_York").tz_convert("UTC")
    assert entry_session(ts, lag_days=0) == pd.Timestamp("2024-03-06")


def test_entry_session_weekend_rolls_to_monday():
    ts = pd.Timestamp("2024-03-09 11:00", tz="America/New_York").tz_convert("UTC")  # Saturday
    assert entry_session(ts, lag_days=0) == pd.Timestamp("2024-03-11")


def test_entry_session_never_precedes_availability():
    """Fuzz: the assigned session must never be before the news arrived."""
    rng = np.random.default_rng(0)
    base = pd.Timestamp("2023-01-01", tz="UTC")
    for _ in range(400):
        ts = base + pd.Timedelta(hours=int(rng.integers(0, 24 * 700)))
        assigned = entry_session(ts, lag_days=0)
        # The session's close (16:00 ET) must be at or after the news, except
        # for news that arrived before that session even started.
        close = (assigned + pd.Timedelta(hours=16)).tz_localize("America/New_York").tz_convert("UTC")
        assert close >= ts - pd.Timedelta(hours=1), f"{ts} -> {assigned}"


def test_event_features_never_precede_the_event(world, cfg):
    """The known_date of every event is at or after its availability date."""
    ev = attach_entry_session(world["events"], cfg)
    avail_date = ev["available_ts"].dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
    assert (ev["known_date"] >= avail_date).all()


def test_single_lag_not_double(world, cfg):
    """An event known on session t must show up in the panel row dated t.

    This is a regression test for a real bug: the assembler used to apply its
    own shift(1) on top of the lag already inside the event mapping, pushing
    every catalyst feature two to three sessions late and discarding the first
    and largest part of the move.
    """
    ev = attach_entry_session(world["events"], cfg)
    panel = assemble(world["prices"], world["events"], cfg)
    col = "kind_8_K_1_01"
    assert col in panel.columns

    # Pick an event past the liquidity warm-up whose ticker/date is in the panel.
    cand = ev[(ev["kind"] == "8-K.1.01") & (ev["known_date"] > pd.Timestamp("2021-06-01"))]
    checked = 0
    for row in cand.itertuples(index=False):
        cell = panel[(panel["ticker"] == row.ticker) & (panel["date"] == row.known_date)]
        if cell.empty:
            continue
        prior = panel[
            (panel["ticker"] == row.ticker) & (panel["date"] < row.known_date)
        ].tail(1)
        if prior.empty:
            continue
        # The feature must jump on known_date, not one or two sessions later.
        assert float(cell[col].iloc[0]) > float(prior[col].iloc[0]), (
            f"{row.ticker} {row.known_date}: feature did not respond on the known date"
        )
        checked += 1
        if checked >= 15:
            break
    assert checked >= 5, "not enough events to verify"


def test_labels_enter_after_the_signal(world, cfg):
    """Entry date is strictly after the signal date. Never same-bar close."""
    labels = build_labels(world["prices"], cfg)
    assert (labels["entry_date"] > labels["date"]).all()
    assert (labels["exit_date"] >= labels["entry_date"]).all()


def test_labels_respect_max_holding(world, cfg):
    labels = build_labels(world["prices"], cfg)
    assert labels["holding_days"].max() <= cfg.labels.max_holding_days + 1


def test_audit_catches_injected_lookahead(world, cfg):
    """Plant a leak and confirm the audit refuses to let it through.

    A test that only checks clean data passes the audit proves nothing -- it
    would also pass with the audit stubbed out to `return`. This injects a
    feature that is literally the future label and asserts the alarm fires.
    """
    panel = assemble(world["prices"], world["events"], cfg)
    labels = build_labels(world["prices"], cfg)

    leaked = panel.merge(labels[["date", "ticker", "label"]], on=["date", "ticker"], how="inner")
    rng = np.random.default_rng(3)
    # Not a perfect copy -- 80% signal, 20% noise, which is the realistic shape
    # of an accidental leak and much harder to spot by eye than a perfect one.
    noise = rng.random(len(leaked)) < 0.2
    leaked["tomorrows_answer"] = np.where(noise, rng.random(len(leaked)), leaked["label"])
    leaked = leaked.drop(columns=["label"])

    report = audit_lookahead(leaked, labels)
    flagged = report[report["suspicious"]]["feature"].tolist()
    assert "tomorrows_answer" in flagged, f"audit missed the planted leak; flagged={flagged}"

    with pytest.raises(LookaheadError):
        assert_no_lookahead(leaked, labels)


def test_audit_passes_clean_panel(world, cfg):
    panel = assemble(world["prices"], world["events"], cfg)
    labels = build_labels(world["prices"], cfg)
    report = audit_lookahead(panel, labels)
    flagged = report[report["suspicious"]]["feature"].tolist()
    assert not flagged, f"clean panel was flagged: {flagged}"
