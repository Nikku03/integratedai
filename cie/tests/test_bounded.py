"""Time-limited queries: a slow query costs its limit, never the question or the caller's own timeout."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from cie.retrieval.bounded import current_timeout_ms, run_bounded


@pytest.mark.db
def test_timeout_is_contained_and_the_callers_limit_restored(session):
    session.execute(text("SET LOCAL statement_timeout = '60s'"))
    assert run_bounded(session, text("SELECT pg_sleep(2)"), 50) is None, "the query ran past its limit"
    assert session.execute(text("SELECT 1")).scalar() == 1, "the transaction is still usable"
    assert current_timeout_ms(session) == 60_000, "the caller's timeout is back after a timeout"
    assert run_bounded(session, text("SELECT 42"), 5_000) == [(42,)]
    assert current_timeout_ms(session) == 60_000, "and after a success (the old code left no timeout at all)"


@pytest.mark.db
def test_the_limit_never_exceeds_the_callers_timeout(session):
    session.execute(text("SET LOCAL statement_timeout = '100ms'"))
    assert run_bounded(session, text("SELECT pg_sleep(1)"), 10_000) is None
    assert current_timeout_ms(session) == 100


@pytest.mark.db
def test_keyword_search_survives_tiers_that_run_out_of_time(session, world, monkeypatch):
    """At 3M sections a full-match tier can exceed the question's time limit; that tier must contribute nothing,
    not fail the question (the old code rolled back to a savepoint only the last tier created)."""
    from cie.core.models import Section
    from cie.retrieval import lexical

    monkeypatch.setattr(lexical, "run_bounded", lambda s, stmt, ms, name="b": run_bounded(s, text("SELECT pg_sleep(1)"), 20, name))
    flt = Section.tenant_id == world.tenant.id
    assert lexical.search_sections(session, "monthly fee supplier termination notice", flt, 10, tenant_id=world.tenant.id) == []
    assert session.execute(text("SELECT 1")).scalar() == 1
