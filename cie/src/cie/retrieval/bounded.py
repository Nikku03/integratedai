"""Run one query under a time limit without disturbing the caller's transaction.

A slow query (a common word ranked over millions of rows) must cost its time limit,
not the question: the query runs inside a savepoint with ``statement_timeout`` set for
that query only. On a database error (the timeout included) the savepoint is rolled
back, which also restores the timeout, and the caller gets ``None``; on success the
caller's own timeout is put back before the savepoint is released. The limit never
exceeds a timeout the caller already set.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def current_timeout_ms(session: Session) -> int:
    return int(session.execute(text("SELECT setting FROM pg_settings WHERE name = 'statement_timeout'")).scalar() or 0)


def run_bounded(session: Session, stmt: Any, limit_ms: int, name: str = "bounded") -> list | None:
    """``stmt``'s rows, or ``None`` when it failed or ran past ``limit_ms``."""
    prev = current_timeout_ms(session)
    limit = limit_ms if prev == 0 else min(limit_ms, prev)
    session.execute(text(f"SAVEPOINT {name}"))
    try:
        session.execute(text("SELECT set_config('statement_timeout', :v, true)"), {"v": str(int(limit))})
        rows = session.execute(stmt).all()
    except DBAPIError as e:
        session.execute(text(f"ROLLBACK TO SAVEPOINT {name}"))  # also undoes the SET LOCAL above
        log.debug("bounded query %s gave up after %s ms: %s", name, limit, str(e).splitlines()[0][:200])
        return None
    session.execute(text("SELECT set_config('statement_timeout', :v, true)"), {"v": str(prev)})
    session.execute(text(f"RELEASE SAVEPOINT {name}"))
    return rows
