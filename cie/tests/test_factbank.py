"""The fact bank: sourced facts, the checker, lookup by subject, hops with a snap, votes, the journal, model-free answers."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from cie.eval import factbank_test as T
from cie.factbank import bank as B
from cie.factbank.engine import FactBank, replay, state_of
from cie.ingest.sources import SourceDoc

WHEN = datetime(2026, 3, 1, tzinfo=UTC)


def _doc(dsid, source, title, meta, body="", keys=()):
    return SourceDoc(dsid=dsid, source=source, rel=f"{source}/{dsid}.json", title=title, fields=[("body", body)], meta=meta, updated=WHEN,
                     keys=list(keys))


DOCS = [
    (_doc("d1", "linear", "Fix keycard reader timeouts", {"key": "ENG-11", "status": "In Progress", "assignee": "Omar Singh",
                                                        "due_date": "2026-03-20", "labels": ["ops", "facilities"]},
          "Badge readers time out at night.", ["ENG-11"]), {}),
    (_doc("d2", "linear", "Rotate office wifi keys", {"key": "ENG-12", "status": "Done", "assignee": "Omar Singh", "due_date": "2026-04-02"},
          "Quarterly rotation.", ["ENG-12"]), {}),
    (_doc("d3", "github", "Add retry to badge sync", {"pr_number": "4821", "repo": "redwood", "author": "Maya Chen",
                                                    "reviewers": ["Omar Singh", "Liam Chen"], "linked_linear": ["ENG-11"]})
     , {}),
    (_doc("d4", "fireflies", "Facilities sync", {"redwood_owner": "Maya Chen"}, "We talked about badges."),
     {"action_items": ["Omar Singh - replace the reader firmware on floor 3 - Due: 2026-03-25"]}),
]


def _bank(tmp_path):
    p = tmp_path / "fb.sqlite"
    rep = B.build(p, DOCS)
    return p, rep


def test_facts_are_sourced_and_checked(tmp_path):
    p, rep = _bank(tmp_path)
    assert rep["check"]["ok"] and rep["sources"] == 4
    con = sqlite3.connect(p)
    f = con.execute("SELECT value, confidence, source, source_detail FROM facts WHERE entity='doc:d1' AND parameter='assignee'").fetchone()
    assert f == ("Omar Singh", "measured", "d1", "field assignee")
    inv = con.execute("SELECT value_entity, dependencies FROM facts WHERE entity='person:omar singh' AND parameter='assignee_of'").fetchall()
    assert {v for v, _ in inv} == {"doc:d1", "doc:d2"} and all(json.loads(d) for _, d in inv), "every inverse names its forward fact"
    act = con.execute("SELECT confidence FROM facts WHERE parameter='due_date' AND entity LIKE 'action:%'").fetchone()
    assert act == ("inferred",), "parsed from text: inferred, not measured"
    linked = con.execute("SELECT value_entity FROM facts WHERE entity='doc:d3' AND parameter='linked_linear'").fetchone()
    assert linked == ("doc:d1",), "a cited key resolves to the document in the bank"
    con.execute("UPDATE facts SET confidence='sure' WHERE id='d1#1'")
    con.execute("INSERT INTO facts SELECT 'x', entity, parameter, value, value_entity, claim, 'nowhere', source_detail, context, confidence, "
                "caveats, '[\"missing\"]', last_verified FROM facts WHERE id='d1#2'")
    errs = B.check(con)["errors"]
    assert any("confidence 'sure'" in e for e in errs) and any("does not resolve" in e for e in errs) and any("dependency" in e for e in errs)


def test_answers_without_a_model(tmp_path):
    p, _ = _bank(tmp_path)
    fb = FactBank(p)
    r = fb.ask("When is the Linear issue ENG-11 due?")
    assert r.answer == "2026-03-20"
    r = fb.ask("List every Linear issue assigned to Omar Singh. Give the issue keys.")
    assert set(r.answer.split(", ")) == {"ENG-11", "ENG-12"}
    r = fb.ask('Which Linear issues assigned to Omar Singh have the status "Done"? Give the issue keys.')
    assert r.answer == "ENG-12"
    r = fb.ask("List every GitHub pull request authored by Maya Chen. Give the pull request numbers.")
    assert r.answer == "#4821"
    r = fb.ask("Which Linear issues are due between 2026-04-01 and 2026-04-14, inclusive? Give the issue keys.")
    assert r.answer == "ENG-12"
    r = fb.ask("Who owns the action item to replace the reader firmware on floor 3?")
    assert "Omar Singh" in r.answer
    assert replay(r.journal) == state_of(r.written), "the journal alone rebuilds what was written"
    assert "Omar Singh" in r.evidence and r.ms < 1000


def test_hops_follow_written_values_and_votes_settle_disagreement(tmp_path):
    p, _ = _bank(tmp_path)
    fb = FactBank(p)
    written, journal, _ = fb.run("retry pull request")
    assert ("doc:d1", "status") in written, "hop 2: the linked Linear issue's facts, reached through the pull request"
    assert written[("doc:d1", "status")].hop > written[("doc:d3", "author")].hop
    # two sources disagree about one entity: the primary system outweighs a chat message; equal weights are a contradiction
    con = sqlite3.connect(p)
    con.execute("INSERT INTO sources VALUES ('s9', 'chat', 'slack', 'secondary', '2026-03-02', '')")
    row = con.execute("SELECT * FROM facts WHERE entity='doc:d1' AND parameter='status'").fetchone()
    con.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", ("s9#1", row[1], row[2], "Blocked", None, "chat says blocked", "s9",
                                                                        "message", row[8], "measured", "[]", "[]", "2026-03-02"))
    con.commit()
    fb = FactBank(p)
    written, _, _ = fb.run("ENG-11")
    assert written[("doc:d1", "status")].values == ["In Progress"]
    con.execute("UPDATE sources SET authority='primary' WHERE id='s9'")
    con.commit()
    written, journal, _ = FactBank(p).run("ENG-11")
    assert ("doc:d1", "status") not in written
    assert any(j["op"] == "contradiction" and j["parameter"] == "status" for j in journal)


def test_scoring_helpers():
    q = {"expected": {"ids": ["ENG-11", "ENG-12"], "id_kind": "key"}}
    assert T.reachable(q, "see ENG-11 and ENG-19") == 0.5 and T.direct(q, "ENG-11, ENG-12") == 1.0
    q = {"expected": {"date": "2026-03-20"}}
    assert T.reachable(q, "due March 20, 2026") == 1.0 and T.direct(q, "2026-03-21") == 0.0
    q = {"expected": {"value": "Maya Chen"}}
    assert T.reachable(q, "owner: maya chen") == 1.0
