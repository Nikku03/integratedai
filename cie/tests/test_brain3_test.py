"""Round 3's scoring (``cie.eval.brain3_test``): the pre-registered rules read v17 against v16 in a ``brain2_test.score``
report; v17 minus v16 paired per family and on the descriptive questions; the questions whose score changed."""

from __future__ import annotations

import copy

from cie.eval import brain3_test as T3
from cie.eval.brain2_test import FAMILIES2


def _report(v16: dict[str, float], v17: dict[str, float], desc=(0.5, 0.7), fnf=0.02, size=0.0) -> dict:
    def arm(f, d):
        return {"by_family": f, "by_group": {"descriptive": d}, "mean_of_families": sum(f.values()) / len(f),
                "false_not_found": {"all": fnf}}
    return {"scores": {"v16": arm(v16, desc[0]), "v17": arm(v17, desc[1])},
            "small": {"differences": {"v17": {"big_minus_small": dict.fromkeys(("single", "multi", "prose"), size)}}}}


BASE = dict.fromkeys(FAMILIES2, 0.8)


def _verdicts(rep):
    return [fn(rep) for fn in T3.preregistered3().values()]


def test_rules_met():
    v17 = {**BASE, "single": 0.9}  # the mean over eight families rises by 0.0125
    assert _verdicts(_report(BASE, v17)) == [True] * 7


def test_each_rule_can_fail():
    v17 = {**BASE, "single": 0.9}
    assert _verdicts(_report(BASE, v17, desc=(0.5, 0.59)))[0] is False  # descriptive lead below 0.10
    assert _verdicts(_report(BASE, {**v17, "single": 0.82}))[1] is False  # single lead below 0.03
    assert _verdicts(_report(BASE, {**v17, "prose": 0.76}))[2] is False  # another family falls by more than 0.03
    assert _verdicts(_report(BASE, {**v17, "prose": 0.775}))[2] is True
    low = {**BASE, "unanswerable": 0.69}
    assert _verdicts(_report(low, {**low, "single": 0.9}))[3] is False
    assert _verdicts(_report(BASE, v17, fnf=0.06))[4] is False
    assert _verdicts(_report(BASE, {**BASE, "single": 0.85}))[5] is False  # the mean rises by 0.00625, less than 0.01
    assert _verdicts(_report(BASE, v17, size=-0.06))[6] is False


def test_rules_need_their_numbers():
    rep = _report(BASE, {**BASE, "single": 0.9})
    broken = copy.deepcopy(rep)
    del broken["scores"]["v17"]
    broken["small"]["differences"] = None
    from cie.eval import brain_test as H

    assert all(v is None for v in H.rules(broken, T3.preregistered3()).values())


def test_paired_and_changed():
    rows = [{"id": "a", "family": "single", "group": "descriptive", "kind": "descriptive", "score": {"v16": 0.0, "v17": 1.0},
             "route": {"v16": "plan", "v17": "described"}},
            {"id": "b", "family": "single", "group": "fields", "kind": "jira_status", "score": {"v16": 1.0, "v17": 1.0}, "route": {}},
            {"id": "c", "family": "prose", "group": "prose", "kind": "prose", "score": {"v16": 1.0, "v17": 0.5}, "route": {}}]
    p = T3.paired(rows)
    assert p["single"]["mean"] == 0.5 and (p["single"]["better"], p["single"]["worse"]) == (1, 0)
    assert p["descriptive"]["questions"] == 1 and p["descriptive"]["mean"] == 1.0
    assert p["prose"]["mean"] == -0.5 and p["prose"]["worse"] == 1 and p["all"]["questions"] == 3
    ch = T3.changed(rows)
    assert [c["id"] for c in ch] == ["a", "c"] and ch[0]["routes"] == {"v16": "plan", "v17": "described"}
