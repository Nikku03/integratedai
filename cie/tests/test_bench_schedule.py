"""Smoke test of the scheduling simulation (the full run is cie.eval.bench_schedule)."""

from __future__ import annotations

import pytest

from cie.eval.bench_schedule import generate, run_world

pytestmark = pytest.mark.db


def test_generated_projects_are_acyclic_and_repeatable():
    a, b = generate(7, 20, 4), generate(7, 20, 4)
    assert [(t.role, t.hours, t.needs) for t in a.tasks] == [(t.role, t.hours, t.needs) for t in b.tasks]
    assert all(p < t.i for t in a.tasks for p, _ in t.needs) and len(a.changes) == 4


def test_early_release_is_correct_and_redoes_only_what_changed(session):
    from cie.core import db as dbmod

    whole = run_world(dbmod.session_factory(), 5, "whole-fifo", 12, 3)
    early = run_world(dbmod.session_factory(), 5, "outputs-schedule", 12, 3)
    for r in (whole, early):
        assert r["phase1"]["incomplete"] == r["phase2"]["incomplete"] == 0
        assert r["phase1"]["stale_inputs"] == r["phase2"]["stale_inputs"] == 0
    assert early["phase1"]["makespan_h"] <= whole["phase1"]["makespan_h"]
    assert early["phase2"]["reruns_unneeded"] == 0 and early["phase2"]["reruns"] <= whole["phase2"]["reruns"]
