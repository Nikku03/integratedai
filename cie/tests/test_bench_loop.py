"""Smoke test of the loop benchmark on a small world (the full run is cie.eval.bench_loop)."""

from __future__ import annotations

import pytest

from cie.eval.bench_loop import LoopWorld, Namespace, run_world

pytestmark = pytest.mark.db


def test_oracle_states_line_up_with_events():
    lw = LoopWorld(3, n_events=6, tag="t")
    assert len(lw.states) == len(lw.events) + 1
    assert all("[t]" in n for n in lw.base.suppliers.values())
    ns = Namespace(lw.base, "t")
    pk = sorted(lw.base.projects)[0]
    assert ns.s(pk) == f"t-{pk}" and ns.key(f"milestone:{pk}-m0") == f"milestone:t-{pk}-m0"
    assert ns.s(f"{sorted(lw.base.orders)[0]}#text").startswith("t-PO-")


def test_loop_run_small(session, embedder):
    from cie.core import db as dbmod
    from cie.core.settings import get_settings

    out = run_world(dbmod.session_factory(), 3, "loop-explicit", 5, None, embedder, get_settings(), log=lambda *a: None)
    assert out["stale_state_errors"]["stale_answers_served"] == 0 and out["missed_dependencies"]["missed"] == 0
    assert out["duplicate_actions"]["extra_versions"] == 0 and out["task_completion"]["completed"] == out["task_completion"]["tasks"]
    assert out["retrieval_completeness"]["needed_records_in_context"] == 1.0
