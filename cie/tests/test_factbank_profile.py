"""The company profile (``cie.factbank.profile``): the default is the lists the code held, a profile can be read from
the documents, and a bank keeps the profile it was built with."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest
from test_bank_sync import company, rows

from cie.factbank import bank as B
from cie.factbank import brain as BR
from cie.factbank import profile as P
from cie.ingest import sources as S
from cie.ingest.sources import SourceDoc

WHEN = datetime(2026, 3, 1, tzinfo=UTC)
STAFF = ["Maya Chen", "Omar Singh", "Priya Nair", "Liam Chen", "Ava Chen"]


def _doc(i: int) -> tuple[SourceDoc, dict]:
    """A ticket of another company: its fields have other names than the ones the code lists."""
    meta = {"ticket": f"OPS-{100 + i}", "handler": STAFF[i % 5], "raised_by": STAFF[(i + 2) % 5], "watchers": [STAFF[(i + 1) % 5], "ops-bot"],
            "vendor_domain": f"north{i % 3}.example", "squad": ["Payments Platform", "Core Infra"][i % 2], "opened_on": f"2026-02-{1 + i % 27:02d}",
            "sprint": f"2026-W{10 + i % 3}", "blocked_by": f"OPS-{100 + (i + 1) % 30}", "state": ["Open", "Done"][i % 2]}
    return SourceDoc(dsid=f"t{i:02d}", source="tracker", rel=f"tracker/t{i:02d}.json", title=f"Ticket {i}", fields=[("body", "Some text.")],
                     meta=meta, updated=WHEN, keys=[f"OPS-{100 + i}"]), {}


DOCS = [_doc(i) for i in range(30)]


def test_the_default_profile_is_what_the_code_held(tmp_path):
    d = P.Profile.default()
    assert set(d.people_fields) == set(S.PEOPLE_FIELDS) and set(d.ref_fields) == set(S.REF_FIELDS) and d.org_fields == tuple(S.ORG_FIELDS)
    assert set(d.person_fields) == BR.PERSON_FIELDS and set(d.primary_systems) == B.PRIMARY_SYSTEMS and set(d.skip_fields) == B.SKIP_FIELDS
    assert d.date_fields is None and d.is_date("merged_at") and d.is_date("due") and not d.is_date("status"), "dates by the field's name"
    assert d.names_people("assignee") and d.cites("linked_issues") and d.skips("dsid") and d.primary("jira") and not d.primary("slack")
    docs = list(company(2, 25).values())
    a, b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    B.build(a, docs, text_facts=True)
    B.build(b, docs, text_facts=True, profile=d)
    assert rows(a, True) == rows(b, True), "a bank built with the default profile is the bank built without one"
    assert P.Profile.of_bank(sqlite3.connect(a)) == d, "and a bank that keeps no profile was built with the default"


def test_a_profile_is_a_file(tmp_path):
    d = P.Profile.default()
    d.save(tmp_path / "p.json")
    assert P.Profile.load(tmp_path / "p.json") == d
    mine = P.Profile.from_json({"people_fields": ["handler"], "date_fields": ["opened_on"], "source": "ours"})
    assert mine.people_fields == ("handler",) and mine.names_people("handler") and not mine.names_people("assignee")
    assert mine.is_date("opened_on") and not mine.is_date("merged_at") and mine.ref_fields == d.ref_fields, "what is not given is the default"
    with pytest.raises(ValueError, match="no \\['peoples'\\]"):
        P.Profile.from_json({"peoples": []})


def test_a_profile_read_from_the_documents():
    prof, sv = P.derive(DOCS)
    f = sv["fields"]
    seen = set(prof.seen_fields)
    assert seen == set(DOCS[0][0].meta), "the fields the documents hold"
    assert set(prof.people_fields) & seen == {"handler", "raised_by", "watchers"}, "fields whose values are names that other such fields hold"
    assert f["squad"]["people"] == 30 and f["squad"]["known"] == 0, "shaped like names, but nobody by that name anywhere else"
    assert f["watchers"]["people"] == 30 and f["watchers"]["values"] == 60, "half its values are not names: it still names people"
    assert set(prof.person_fields) & seen == {"handler", "raised_by"}, "a holder of these is a person for certain"
    assert set(prof.date_fields) & seen == {"opened_on"} and f["sprint"]["dates"] == 0, "a week is not a day"
    assert set(prof.ref_fields) & seen == {"blocked_by"} and f["ticket"]["own"] == 30 and f["ticket"].get("keys", 0) == 0, \
        "its own key is not a citation"
    assert prof.source == "derived" and prof.org_fields == P.Profile.default().org_fields, "what the values do not tell is kept"
    # a field the documents do not hold keeps the base's lists, and a date is still told by its name: documents added
    # later can hold it
    assert prof.names_people("assignee") and prof.cites("linked_issues") and prof.is_date("merged_at") and not prof.is_date("state")
    few, _ = P.derive(DOCS[:5], base=P.Profile.from_json({"people_fields": ["handler"]}))
    assert few.people_fields == ("handler",) and not {"blocked_by", "opened_on"} & set(few.ref_fields + few.date_fields), \
        "too few values to tell: a field is left as the profile it starts from has it"
    ag = P.agreement(P.Profile.default(), prof, sv)
    assert ag["people"]["fields_both"] == 0 and set(ag["people"]["only_derived"]) == {"handler", "raised_by", "watchers"}, \
        "compared on the fields the documents hold"
    assert P.compare(prof, prof) == {} and set(P.compare(P.Profile.default(), prof)) >= {"people_fields", "ref_fields", "date_fields"}
    assert P.form_keys("see OPS-12 and https://github.com/acme/api/pull/77") == ["OPS-12", "pr:api#77"]


def test_digits_that_other_records_carry_are_identifiers_not_dates():
    # each ticket names another one's account number, which that ticket carries as its own identifier
    docs = [(SourceDoc(**{**sd.__dict__, "meta": {**sd.meta, "account_no": f"{1_700_000_000 + (i + 1) % 30}", "phone": f"{5_551_230_000 + i}"},
                          "keys": [*sd.keys, f"id:{1_700_000_000 + i}"]}), raw) for i, (sd, raw) in enumerate(DOCS)]
    prof, sv = P.derive(docs)
    assert sv["fields"]["account_no"]["carried"] == 30 and prof.cites("account_no") and not prof.is_date("account_no")
    assert prof.is_date("phone"), "a known limit: ten digits that no record carries read as epoch seconds"


def test_a_custom_profile_is_kept_whatever_its_name(tmp_path):
    named_default = P.Profile.from_json({"people_fields": ["handler", "raised_by", "watchers"]})
    assert named_default.source == "default" and not named_default.is_default() and P.Profile.default().is_default()
    assert P.Profile.from_json({**P.Profile.default().to_json(), "source": "mine"}).is_default()
    path = tmp_path / "bank.sqlite"
    B.build(path, DOCS[:20], profile=named_default)
    assert P.Profile.of_bank(sqlite3.connect(path)) == named_default
    rep = B.sync(path, DOCS)
    assert (rep["added"], rep["same"]) == (10, 20), "the profile kept in the bank reads the new documents"
    con = sqlite3.connect(path)
    assert con.execute("SELECT value_entity FROM facts WHERE entity = 'doc:t25' AND parameter = 'handler'").fetchone() == \
        (f"person:{STAFF[0].lower()}",)


def test_a_bank_keeps_the_profile_it_was_built_with(tmp_path):
    prof, _ = P.derive(DOCS)
    plain, mine = tmp_path / "plain.sqlite", tmp_path / "mine.sqlite"
    B.build(plain, DOCS[:20])
    B.build(mine, DOCS[:20], profile=prof)
    con = sqlite3.connect(mine)
    assert P.Profile.of_bank(con) == prof
    people = {r[0] for r in con.execute("SELECT name FROM entities WHERE kind = 'person'")}
    assert people == set(STAFF), "the people its own fields name"
    assert not sqlite3.connect(plain).execute("SELECT 1 FROM entities WHERE kind = 'person'").fetchone(), "the code's lists know none of them"
    cited = con.execute("SELECT value_entity FROM facts WHERE entity = 'doc:t00' AND parameter = 'blocked_by'").fetchone()
    assert cited == ("doc:t01",), "a citation by a field the code does not list"
    con.close()
    rep = B.sync(mine, DOCS, text_facts=False)
    assert (rep["added"], rep["same"]) == (10, 20), "the profile is part of a document's hash: the same profile, nothing read again"
    con = sqlite3.connect(mine)
    assert con.execute("SELECT value_entity FROM facts WHERE entity = 'doc:t25' AND parameter = 'handler'").fetchone() == \
        (f"person:{STAFF[0].lower()}",), "a document added later is read with the bank's profile"
    fresh = tmp_path / "fresh.sqlite"
    B.build(fresh, DOCS, profile=prof)
    got, want = rows(mine), rows(fresh)
    assert all(got[t] == want[t] for t in want), "and the bank is the one a fresh build with that profile gives"
    b = BR.BrainBank(mine)
    assert b.profile() == prof and {"handler", "raised_by"} <= set(b.profile().person_fields) and "watchers" not in b.profile().person_fields
