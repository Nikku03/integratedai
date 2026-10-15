"""Round 4's scoring (``cie.eval.brain4_test``): the pre-registered rules read v18 against v17 in a ``brain2_test.score`` report,
with the free-text answers' mean length; the size rule is reported apart; v18 minus v17 is paired per family."""

from __future__ import annotations

import copy
import json

from cie.eval import brain4_test as T4
from cie.eval import brain_test as H
from cie.eval.brain2_test import FAMILIES2


def _report(v17: dict[str, float], v18: dict[str, float], fnf=0.02, size=0.0, lengths=(1000.0, 1000.0)) -> dict:
    def arm(f):
        return {"by_family": f, "mean_of_families": sum(f.values()) / len(f), "false_not_found": {"all": fnf}}
    return {"scores": {"v17": arm(v17), "v18": arm(v18)}, "prose_length4": {"v17": lengths[0], "v18": lengths[1]},
            "small": {"differences": {"v18": {"big_minus_small": dict.fromkeys(("single", "multi", "prose"), size)}}}}


BASE = dict.fromkeys(FAMILIES2, 0.8)
GOOD = {**BASE, "not_found": 0.97, "counts": 0.96, "unanswerable": 0.85, "prose": 0.86}


def _verdicts(rep):
    return [fn(rep) for fn in T4.preregistered4().values()]


def test_rules_met():
    assert _verdicts(_report(BASE, GOOD)) == [True] * 8
    assert T4.size_rule(_report(BASE, GOOD))


def test_each_rule_can_fail():
    assert _verdicts(_report(BASE, {**GOOD, "not_found": 0.94}))[0] is False
    assert _verdicts(_report(BASE, {**GOOD, "counts": 0.94}))[1] is False
    assert _verdicts(_report(BASE, {**GOOD, "unanswerable": 0.82}))[2] is False  # lead below 0.03
    assert _verdicts(_report(BASE, {**GOOD, "prose": 0.83}))[3] is False  # lead below 0.04
    assert _verdicts(_report(BASE, {**GOOD, "history": 0.76}))[4] is False  # another family falls by more than 0.03
    assert _verdicts(_report(BASE, {**GOOD, "history": 0.775}))[4] is True
    assert _verdicts(_report(BASE, GOOD, fnf=0.06))[5] is False
    high = {**BASE, "not_found": 0.95, "counts": 0.95}
    weak = {**high, "unanswerable": 0.83, "prose": 0.84, "single": 0.78, "multi": 0.78}
    assert _verdicts(_report(high, weak))[6] is False  # the mean rises by less than 0.02
    assert _verdicts(_report(BASE, GOOD, lengths=(1000.0, 1060.0)))[7] is False
    assert _verdicts(_report(BASE, GOOD, lengths=(1000.0, 1050.0)))[7] is True
    assert not T4.size_rule(_report(BASE, GOOD, size=-0.06))


def test_rules_need_their_numbers():
    broken = copy.deepcopy(_report(BASE, GOOD))
    del broken["scores"]["v18"]
    del broken["prose_length4"]
    assert all(v is None for v in H.rules(broken, T4.preregistered4()).values())


def test_prose_length(tmp_path):
    rows = [{"id": "a", "family": "prose"}, {"id": "b", "family": "prose"}, {"id": "c", "family": "single"}]
    (tmp_path / "factbank_v18.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (
        {"id": "a", "answer": "x" * 10}, {"id": "b", "answer": "x" * 20}, {"id": "c", "answer": "x" * 500})))
    assert T4.prose_length(tmp_path, rows) == {"v18": 15.0, "v17": None}
