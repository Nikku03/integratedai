"""The model's tools over a fact bank (``cie.factbank.tools``) and the bank's derived tables (``cie.factbank.store``): names
read as people write them, a record read by any of its names, loose values that say what they counted, filters that
explain an empty result, sorting, grouping and ranges, search that filters by system before it ranks, and the schema read
from the data."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from cie.factbank import bank as BK
from cie.factbank import store
from cie.factbank import tools as T
from cie.ingest.sources import SourceDoc

WHEN = datetime(2026, 3, 1, tzinfo=UTC)


def _doc(dsid, source, title, meta, body="", keys=()):
    return SourceDoc(dsid=dsid, source=source, rel=f"{source}/{dsid}.json", title=title, fields=[("body", body)] if body else [],
                     meta=meta, updated=WHEN, keys=list(keys))


def _issue(n, status, priority, assignee, due, estimate, project="Badge Revamp"):
    return (_doc(f"l{n}", "linear", f"Linear issue number {n}", {"key": f"ENG-{n}", "status": status, "priority": priority, "assignee": assignee,
                                                                "due_date": due, "estimate": estimate, "project": project}, keys=[f"ENG-{n}"]), {})


DOCS = [
    _issue(1, "Done", "P1", "Omar Singh", "2026-04-02", 3),
    _issue(2, "In Progress", "P1", "Omar Singh", "2026-03-20", 8),
    _issue(3, "In Progress", "P2", "Omar Singh", "2026-05-11", 13),
    _issue(4, "Todo", "P2", "Liam O'Connor", "2026-03-25", 5, project="Lobby Refresh"),
    (_doc("l5", "linear", "No due date here", {"key": "ENG-5", "status": "Todo", "priority": "P1", "assignee": "Liam OConnor"}, keys=["ENG-5"]), {}),
    (_doc("g1", "gmail", "Kickoff with Solstice Health", {"related_account": "Solstice Health", "thread_type": "sales"}, "Kickoff notes."), {}),
    (_doc("g2", "gmail", "Renewal for Solstice Health", {"related_account": "Solstice Health", "thread_type": "sales"}, "Renewal terms."), {}),
    (_doc("g3", "gmail", "Onboarding SolsticeHealth", {"related_account": "SolsticeHealth", "thread_type": "support"}, "Onboarding plan."), {}),
    (_doc("g4", "gmail", "Solstice Labs intro", {"related_account": "Solstice Labs", "thread_type": "sales"}, "An intro."), {}),
    (_doc("h1", "hubspot", "Acme AI", {"stage": "procurement", "owner": "Jordan Blake", "account_tier": "smb"}, "Acme AI is a customer."), {}),
    (_doc("h2", "hubspot", "Conversify Support", {"stage": "evaluation", "owner": "Maya Chen", "account_tier": "enterprise"},
          "Conversify builds support AI assistants for retail."), {}),
    (_doc("p1", "github", "Fix the metering regression", {"pr_number": "412", "author": "Ava Chen", "state": "merged", "linked_linear": "ENG-2"},
          "Fixes ENG-2.", keys=[]), {}),
    (_doc("s1", "slack", "incidents", {"channel": "incidents"}, "The API gateway returned 502s for ten minutes."), {}),
    (_doc("s2", "slack", "incidents", {"channel": "incidents"}, "Paging the on-call for the AI gateway."), {}),
    (_doc("s3", "slack", "incidents", {"channel": "incidents"}, "Resolved after the rollback."), {}),
    (_doc("s4", "slack", "incidents", {"channel": "incidents"}, "Postmortem scheduled."), {}),
]


@pytest.fixture(scope="module")
def path(tmp_path_factory):
    p = tmp_path_factory.mktemp("tools") / "factbank_v2.sqlite"
    BK.build(p, DOCS)
    return p


@pytest.fixture(scope="module")
def box(path):
    return T.Toolbox(path, brain=lambda q: {"answer": "2026-04-02", "route": "fact", "reason": "due_date of doc:l1",
                                            "evidence": "Answer: 2026-04-02", "journal": [{"op": "seed", "entity": "doc:l1"}]})


# ------------------------------------------------------------------ the store
def test_values_as_they_are_compared():
    assert store.norm("  In   Progress ") == "in progress"
    assert store.loose("Solstice Health") == store.loose("SolsticeHealth") == store.loose("solstice-health") == "solsticehealth"
    assert store.loose("O'Connor") == store.loose("OConnor") and store.loose("ACME Corp.") == "acmecorp"
    assert store.loose("Zoë  Müller") == "zoemuller" and store.loose("in_progress") == store.loose("In Progress")
    assert store.loose("1.0") != store.loose("10") and store.loose("v1.2") != store.loose("v12"), "a number keeps its point"
    assert store.day_of("2026-03-20") == store.day_of("2026-03-20T10:00:00Z") == "2026-03-20" and store.day_of("March 20") is None
    assert store.number_of("1,200") == 1200.0 and store.number_of("3.5") == 3.5 and store.number_of("ENG-12") is None
    assert store.number_of("2026-03-20") is None and store.number_of("45%") == 45.0


def test_the_store_is_built_with_the_bank_and_only_once(path):
    con = sqlite3.connect(path)
    for t in ("text_rows", "passages_fts", "passage_docs", "doc_fields", "schema_fields", "store_meta"):
        assert store.has(con, t), t
    m = store.meta(con)
    assert m["version"] == store.VERSION and m["facts"] == con.execute("SELECT count(*) FROM facts").fetchone()[0]
    assert con.execute("SELECT count(*) FROM text_rows").fetchone()[0] == con.execute("SELECT count(*) FROM entities_fts").fetchone()[0]
    rows = con.execute("SELECT field, value, norm, loose, day, num, ref FROM doc_fields WHERE doc = 'l2' ORDER BY rowid").fetchall()
    assert ("title", "Linear issue number 2", "linear issue number 2", "linearissuenumber2", None, None, None) in rows
    assert ("due_date", "2026-03-20", "2026-03-20", "20260320", "2026-03-20", None, None) in rows
    assert ("estimate", "8", "8", "8", None, 8.0, None) in rows and ("assignee", "Omar Singh", "omar singh", "omarsingh", None, None, "person") in rows
    con.close()
    assert store.ensure(path) == {}, "a complete bank file is left alone"
    con = sqlite3.connect(path)
    con.execute("UPDATE store_meta SET value = '0' WHERE key = 'version'")
    con.commit()
    con.close()
    again = store.ensure(path)
    assert {"text_rows", "passages", "fields"} <= set(again), "another version's tables are built again"


def test_a_file_that_is_not_a_bank_is_left_alone(tmp_path):
    p = tmp_path / "empty.sqlite"
    sqlite3.connect(p).close()
    assert store.ensure(p) == {}
    with pytest.raises(RuntimeError, match="store.ensure"):
        BK.build(tmp_path / "plain.sqlite", DOCS[:2], derived=False)
        T.Toolbox(tmp_path / "plain.sqlite")


def test_the_schema_is_read_from_the_data(box):
    lin = box.schema["linear"]
    assert lin["assignee"][0] == "person" and lin["due_date"][0] == "date" and lin["estimate"][0] == "number"
    assert lin["status"][0] == "value" and lin["title"][0] == "title" and lin["status"][1:3] == (5, 3)
    d = box.describe()
    assert {"system": "linear", "records": 5, "fields": len(lin)} in d["systems"]
    one = box.describe("Linear")
    assert one["records"] == 5 and {"field": "due_date", "kind": "date", "records": 4} in one["fields"]
    assert any(f["field"] == "status" and f["examples"][0] in ("In Progress", "Todo") for f in one["fields"])
    brief = box.schema_brief()
    assert "- linear (5 records;" in brief and "assignee (person)" in brief and "due_date (date)" in brief and "estimate (number)" in brief
    call = json.loads(box.example_call())
    assert call["tool"] == "find" and call["args"]["system"] in box.systems
    (f, v), = call["args"]["where"].items()
    assert box.find(call["args"]["system"], {f: v})["count"] > 0, "the example call of the instructions works"


# ------------------------------------------------------------------ names
def test_fields_and_systems_are_read_as_people_write_them(box):
    for name in ("due_date", "due date", "Due Date", "dueDate", "due-date", "DUEDATE"):
        assert box.field("linear", name) == ("due_date", None), name
    assert box.field("hubspot", "name") == ("title", None) and box.field("gmail", "subject") == ("title", None)
    f, err = box.field("linear", "deadline")
    assert f is None and "no field 'deadline' in linear" in err["error"] and "due_date" not in err["error"].split("most held")[0]
    f, err = box.field("linear", "due")
    assert f is None and "Closest: due_date" in err["error"], "a near name is offered, never used unasked"
    assert 'schema {"system": "linear"}' in err["error"]
    for name in ("gmail", "Gmail", "email", "emails", "e-mail"):
        assert box.system(name) == ("gmail", None), name
    assert box.system("PRs")[0] == "github" and box.system("accounts")[0] == "hubspot"
    s, err = box.system("tickets")
    assert s is None and err["error"].startswith("no system 'tickets'. The systems are: github (1 records), gmail (4 records)")
    assert box.find("gdrive")["error"].startswith("no system 'gdrive'"), "a usual name applies only when the bank has that system"


def test_a_record_is_read_by_any_of_its_names(box):
    for ref, how in (("l2", None), ("doc:l2", None), ("ENG-2", "key"), ("eng-2", "key"), ("Linear issue number 2", "title"),
                     ("linear issue  number 2", "title"), ("Linear-issue number 2", "title, written another way")):
        r = box.read(ref)
        assert r["doc"] == "l2" and r.get("found_by") == how and r["key"] == "ENG-2", ref
        assert r["fields"]["due_date"] == "2026-03-20" and "title" not in r["fields"]
    for ref in ("412", "#412", "PR 412", "pr #412", "pull request 412"):
        assert box.read(ref)["doc"] == "p1", ref
    r = box.read("incidents")
    assert r["error"].startswith("4 records are named 'incidents'") and len(r["records"]) == 4 and r["records"][0]["doc"] == "s1"
    assert box.read("ENG-999")["error"].startswith("no record 'ENG-999'")
    assert box.run("read", {"key": "ENG-2"})["doc"] == "l2" and "missing argument" in box.run("read", {"query": "x"})["error"]


# ------------------------------------------------------------------ find
def test_find_counts_loosely_and_says_what_it_counted(box):
    r = box.find("gmail", {"related account": "Solstice Health"})
    assert r["count"] == 3 and r["counted_spellings"] == {"related_account": ["Solstice Health", "SolsticeHealth"]}
    assert box.find("gmail", {"related_account": "Solstice Health"}, exact=True)["count"] == 2
    assert box.find("gmail", {"related_account": "solstice health"})["count"] == 3 and "counted_spellings" in box.find(
        "gmail", {"related_account": "solstice-health"})
    r = box.find("linear", {"assignee": "Liam O'Connor"})
    assert r["count"] == 2 and r["counted_spellings"]["assignee"] == ["Liam O'Connor", "Liam OConnor"]
    assert "counted_spellings" not in box.find("linear", {"assignee": "omar singh"}), "one spelling in another case is not two"
    assert box.find("linear", {"estimate": 8})["count"] == 1 and box.find("linear", {"estimate": "8"})["count"] == 1


def test_an_empty_result_says_why(box):
    r = box.find("linear", {"assignee": "Omar Sing"})
    assert r["count"] == 0 and r["records"] == [] and "closest values: 'Omar Singh' (3)" in r["why_none"][0]
    r = box.find("linear", {"status": "Shipped"})
    assert 'call values {"system": "linear", "field": "status"}' in r["why_none"][0]
    r = box.find("linear", {"status": "Done", "priority": "P2"})
    assert r["count"] == 0 and r["why_none"] == ["each condition matches some records, but no record matches them all"]
    assert "no field 'colour' in linear" in box.find("linear", {"colour": "red"})["error"], "an unknown field is an error, never 0 records"
    assert "no operator 'near'" in box.find("linear", {"status": {"near": "Done"}})["error"]


def test_find_conditions(box):
    def keys(where, **kw):
        return sorted(x["key"] for x in box.find("linear", where, ["key"], **kw)["records"])

    assert keys({"status": ["Done", "Todo"]}) == ["ENG-1", "ENG-4", "ENG-5"]
    assert keys({"status": {"not": "Done"}}) == ["ENG-2", "ENG-3", "ENG-4", "ENG-5"]
    assert keys({"status": {"not": ["Done", "Todo"]}, "priority": "P1"}) == ["ENG-2"]
    assert keys({"title": {"contains": "due date"}}) == ["ENG-5"]
    assert keys({"due_date": {"before": "2026-04-01"}}) == ["ENG-2", "ENG-4"] and keys({"due date": {"after": "2026-04-02"}}) == ["ENG-3"]
    assert keys({"due_date": {"between": ["2026-03-21", "2026-04-02"]}}) == ["ENG-1", "ENG-4"]
    assert keys({"due_date": {"on": "2026-03"}}) == ["ENG-2", "ENG-4"], "a month covers its days"
    assert keys({"due_date": {"after": "2026-03"}}) == ["ENG-1", "ENG-3"]
    assert keys({"estimate": {"gte": 8}}) == ["ENG-2", "ENG-3"] and keys({"estimate": {"gt": 3, "lt": 13}}) == ["ENG-2", "ENG-4"]
    assert keys({"due_date": {"exists": False}}) == ["ENG-5"] and keys({"due_date": None}) == ["ENG-5"]
    assert keys({"due_date": {"exists": True}, "priority": "P2"}) == ["ENG-3", "ENG-4"]
    assert keys({"id": "ENG-2"}) == ["ENG-2"] and keys({"id": ["l1", "Linear issue number 3"]}) == ["ENG-1", "ENG-3"]
    assert "takes a date" in box.find("linear", {"due_date": {"before": "next week"}})["error"]
    assert "takes a number" in box.find("linear", {"estimate": {"gt": "many"}})["error"]


def test_find_sorts_limits_groups_and_shows(box):
    r = box.find("linear", {"assignee": "Omar Singh"}, ["key"], sort="due_date", limit=1)
    assert r["count"] == 3 and [(x["key"], x["due_date"]) for x in r["records"]] == [("ENG-2", "2026-03-20")], "the one due first"
    assert [x["key"] for x in box.find("linear", {}, ["key"], sort="-due date")["records"]] == ["ENG-3", "ENG-1", "ENG-4", "ENG-2", "ENG-5"]
    assert "1 records have no due_date: they come last" in box.find("linear", {}, sort="due_date")["note"]
    assert [x["key"] for x in box.find("linear", {}, ["key"], sort={"by": "estimate", "order": "desc"}, limit=2)["records"]] == ["ENG-3", "ENG-2"]
    assert [x["key"] for x in box.find("linear", {}, ["key"], sort="due date desc", limit=1)["records"]] == ["ENG-3"]
    assert [x["key"] for x in box.find("linear", {}, ["key"], sort=["estimate"], limit=1)["records"]] == ["ENG-1"]
    g = box.find("linear", {}, group_by="status")
    assert g["count"] == 5 and g["groups"] == [{"status": "In Progress", "records": 2}, {"status": "Todo", "records": 2},
                                               {"status": "Done", "records": 1}] and "records" not in g
    g = box.find("linear", {"priority": "P1"}, group_by="due date")
    assert g["records_without_due_date"] == 1 and len(g["groups"]) == 2
    r = box.find("linear", {"key": "ENG-2"}, ["id", "title", "status", "colour", "due date"])
    row = r["records"][0]
    assert row == {"doc": "l2", "title": "Linear issue number 2", "key": "ENG-2", "status": "In Progress", "due_date": "2026-03-20"}
    assert "no field 'colour' in linear" in r["note"], "a field that does not exist is said, never shown as empty"
    assert box.find("linear", {"key": "ENG-5"}, ["due_date"])["records"][0]["due_date"] is None, "a field the record lacks is null"
    assert box.find("linear", {}, "key, status")["records"][0].keys() >= {"key", "status"}  # "show" as one string


def test_find_keeps_what_fits(box, monkeypatch):
    monkeypatch.setattr(T, "RESULT_CHARS", 150)
    r = box.find("linear", {}, ["key", "status", "assignee"])
    assert 0 < len(r["records"]) < r["count"] and r["note"].startswith(f"{r['count']} records match; the first {len(r['records'])}")
    assert "narrow" in r["note"] and T._cut("x" * 400) == "x" * T.FIELD_CHARS + " [...]"


# ------------------------------------------------------------------ values, search
def test_values_and_like(box):
    v = box.values("linear", "Status")
    assert v["field"] == "status" and v["kind"] == "value" and v["distinct"] == 3 and v["values"][0]["records"] == 2
    v = box.values("gmail", "related account", like="solstice")
    assert [x["value"] for x in v["values"]] == ["Solstice Health", "Solstice Labs", "SolsticeHealth"] and v["matching"] == 3
    assert box.values("gmail", "related_account", like="solsticeh")["matching"] == 2, "like is loose too"
    assert "no field 'colour'" in box.values("linear", "colour")["error"] and "no system" in box.values("nope", "x")["error"]


def test_search_filters_by_system_before_it_ranks(box):
    r = box.search("Acme AI", system="hubspot")
    assert r["results"][0]["title"] == "Acme AI" and r["results"][0]["exact_title"] and r["results"][0]["all_words"]
    assert all(x["system"] == "hubspot" for x in r["results"]) and [x["doc"] for x in r["results"]][0] == "h1"
    assert not any(x.get("exact_title") for x in r["results"][1:])
    assert T.search_terms("Acme AI is at it in Q3") == ["acme", "ai", "q3"], "a short word in capitals is a name; small words are not"
    assert box.search("ENG-2")["results"][0]["doc"] == "l2" and box.search("#412")["results"][0]["doc"] == "p1"
    r = box.search("incidents")
    assert not any(x.get("exact_title") for x in r["results"]), "a title that many records share names none of them"
    r = box.search("gateway rollback postmortem")
    assert r["results"] and not any(x["all_words"] for x in r["results"]) and r["note"].startswith("no record holds all of these words")
    assert box.search("zygomorphic quasars")["note"] == "no record holds any of these words"
    assert box.search("gateway", system="hubspot") == {"results": [], "note": "no record holds any of these words in hubspot"}
    assert "no system" in box.search("gateway", system="nope")["error"] and box.search("is it")["note"] == "no searchable words in the query"


# ------------------------------------------------------------------ the brain's row, and the calls
def test_the_brain_row_the_model_sees(box):
    v = box.run("brain", {"question": "When is ENG-1 due?"})
    assert v["answer"] == "2026-04-02" and v["records"] == ["l1"] and list(v) == ["answer", "route", "reason", "records", "evidence"]
    long = {"answer": "q", "route": "prose", "reason": "", "evidence": "x" * 9000}
    assert len(T.brain_view(long)["evidence"]) == T.EVIDENCE_CHARS_PROSE + 6 and len(T.brain_view({**long, "route": "fact"})["evidence"]) == \
        T.EVIDENCE_CHARS + 6, "a free-text row shows more of its evidence"
    assert T.records_read({"reason": "quoted from doc:dsid_a1.", "journal": "[{'op': 'prose', 'doc': 'doc:dsid_b2'}]"}) == ["dsid_a1", "dsid_b2"]


def test_run_never_raises(box):
    assert "missing argument" in box.run("find", {"where": {}})["error"]
    assert "no tool" in box.run("delete", {})["error"] and "must be an object" in box.run("find", {"system": "linear", "where": "x"})["error"]
    assert box.run("schema", {})["systems"] and box.run("values", {"system": "linear", "field": "status"})["distinct"] == 3
    assert box.run("find", {"system": "linear", "where": {"assignee": "Omar Singh"}, "sort": "due_date", "limit": "1"})["records"][0]["key"] == "ENG-2"
