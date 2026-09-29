"""Smoke test of the loop benchmark on a small world (the full run is cie.eval.bench_loop)."""

from __future__ import annotations

import pytest

from cie.eval.bench_loop import LoopWorld, Namespace, run_world

pytestmark = pytest.mark.db


def test_oracle_states_line_up_with_events():
    lw = LoopWorld(3, n_events=6, tag="t")
    assert len(lw.states) == len(lw.events) + 1
    assert all(n.endswith("(fictional)") for n in lw.base.suppliers.values()) and all("[t]" in p["name"] for p in lw.base.projects.values())
    assert set(lw.base.suppliers.values()) != set(LoopWorld(3, n_events=6, tag="u").base.suppliers.values()), "each world its own names"
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


def fake_analyst(errors: dict[int, str]):
    """A stand-in for the model: it reads the data block in the prompt and applies the definitions, except on the
    calls named in ``errors`` ('garbage': not JSON; 'cost': the committed cost inflated by 10%)."""
    import json
    from datetime import date, timedelta

    from cie.agents.providers import FakeProvider

    n = {"calls": 0}

    def answer(system, user):
        n["calls"] += 1
        err = errors.get(n["calls"])
        if err == "garbage":
            return "I think the project is fine."
        d = json.loads(user.split("Data (JSON):\n", 1)[1].split("\n\nReply with", 1)[0])
        ms = []
        for m in d["milestones"]:
            limit = date.fromisoformat(m["due_date"]) + timedelta(days=m["slack_days"])
            short = [p for p, need in m["needs"].items()
                     if d["stock_available"].get(p, 0) + sum(float(o["qty"]) for o in d["open_orders"] if o["for_milestone"] == m["id"]
                                                             and o["product"] == p and date.fromisoformat(o["promised_date"]) <= limit) < need]
            ms.append({"id": m["id"], "at_risk": bool(short), "reason": ", ".join(short)})
        lines = [{"order": o["id"], "qty": o["qty"], "unit_price": o["unit_price"]} for o in d["open_orders"]]
        cost = sum(float(x["qty"]) * float(x["unit_price"]) for x in lines) * (1.1 if err == "cost" else 1.0)
        return "```json\n" + json.dumps({"milestones": ms, "cost_lines": lines, "cost": cost, "budget": d["budget"],
                                         "within_budget": cost <= d["budget"], "feasible": not any(m["at_risk"] for m in ms)}) + "\n```"

    return FakeProvider(answer)


def test_model_analyst_errors_are_counted_and_wrong_figures_blocked(session, embedder):
    from cie.core import db as dbmod
    from cie.core.settings import get_settings

    model = fake_analyst({1: "garbage", 3: "cost"})
    out = run_world(dbmod.session_factory(), 3, "llm-relied", 5, None, embedder, get_settings(), log=lambda *a: None, model=model)
    c, acc, vc = out["cost"], out["answer_accuracy"], out["verification_catch"]
    assert c["model_bad_json"] == 1 and c["model_calls"] == len(model.calls) and c["model_invented_refs"] == 0
    assert vc["wrong_numbers"] >= 1 and vc["wrong_numbers_blocked"] == vc["wrong_numbers"], "an inflated cost fails recalculation"
    assert vc["right_numbers_blocked"] == 0
    assert out["citation_accuracy"]["published_answers_correct"] == 1.0, "an answer resting on a blocked figure is not published"
    assert acc["answers_given"] > acc["answers_given"] * acc["right_when_given"], "the inflated answer is counted wrong"
    assert out["stale_state_errors"]["stale_answers_served"] == 0 and out["missed_dependencies"]["missed"] == 0
    assert out["retrieval_completeness"]["needed_records_relied_on"] == 1.0, "every milestone and order is cited"
    with pytest.raises(SystemExit):
        run_world(dbmod.session_factory(), 3, "llm-relied", 1, None, embedder, get_settings(), log=lambda *a: None)
