"""Questions that need several documents: plans over the fact bank, the revised (v4) rules, learning, and the test sets."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from cie.eval import factbank_multi as M
from cie.eval.memory_test import _jsonl, _write_jsonl
from cie.factbank import bank as B
from cie.factbank import plans as P
from cie.factbank.trained import TrainedBank
from cie.ingest.sources import SourceDoc

WHEN = datetime(2026, 3, 1, tzinfo=UTC)


def _doc(dsid, source, title, meta, keys=()):
    return SourceDoc(dsid=dsid, source=source, rel=f"{source}/{dsid}.json", title=title, fields=[("body", "")], meta=meta, updated=WHEN,
                     keys=list(keys))


DOCS = [
    (_doc("d1", "linear", "Fix keycard reader timeouts",
          {"key": "ENG-11", "status": "In Progress", "assignee": "Omar Singh", "due_date": "2026-03-20"}, ["ENG-11"]), {}),
    (_doc("d2", "linear", "Rotate office wifi keys",
          {"key": "ENG-12", "status": "Done", "assignee": "Omar Singh", "due_date": "2026-04-02"}, ["ENG-12"]), {}),
    (_doc("d3", "linear", "Replace the badge printer",
          {"key": "ENG-13", "status": "Todo", "assignee": "Liam Chen", "due_date": "2026-05-01", "dependencies": ["ENG-12"]}, ["ENG-13"]), {}),
    (_doc("d4", "github", "Add retry to badge sync", {"pr_number": "4821", "author": "Maya Chen", "linked_linear": ["ENG-11"]}), {}),
]
OMAR = "person:omar singh"


def _bank(tmp_path):
    p = tmp_path / "fb.sqlite"
    B.build(p, DOCS, text_facts=True)
    return TrainedBank(p)


def test_plans_follow_links_and_combine(tmp_path):
    tb = _bank(tmp_path)
    pl = P.Planner(tb, "v4")
    assert tb.named("What about pull request #4821?") == ["doc:d4"], "a pull request is named by its number"
    assert pl.execute(P.Plan(("doc:d4",), ("linked_linear",), "assignee", "single")) == "Omar Singh"
    assert pl.execute(P.Plan((OMAR,), ("assignee_of",), "label", "count")) == "2"
    assert pl.execute(P.Plan((OMAR,), ("assignee_of",), "due_date", "earliest")) == "ENG-11"
    assert pl.execute(P.Plan(("doc:d1", "doc:d3"), (), "due_date", "latest")) == "ENG-13"
    journal: list = []
    assert pl.execute(P.Plan(("doc:d3",), ("dependencies",), "assignee", "single"), journal) == "Omar Singh"
    assert journal == [{"op": "hop", "hop": 1, "relation": "dependencies", "reached": ["doc:d2"]}], "each hop writes down what it reached"
    # one value means one value: two issues, two statuses
    assert pl.execute(P.Plan((OMAR,), ("assignee_of",), "status", "single")) is None
    assert P.Planner(tb, "v3").execute(P.Plan((OMAR,), ("assignee_of",), "status", "single")) in ("In Progress", "Done")


def test_v4_does_not_walk_back_or_echo(tmp_path):
    tb = _bank(tmp_path)
    q = "Who is assigned to the ticket that ENG-13 is linked to?"
    v3, v4 = P.Planner(tb, "v3").candidates(q), P.Planner(tb, "v4").candidates(q)
    walks_back = lambda c: [p for p, _ in c if len(p.path) == 2 and P.inverse(*p.path)]  # noqa: E731
    echoes = lambda c: [p for p, m in c if p.starts == ("doc:d3",) and m["answer"] == "ENG-13"]  # noqa: E731 - answers with its own start
    assert walks_back(v3) and echoes(v3), "the first version allowed both"
    assert not walks_back(v4) and not echoes(v4)
    assert any(p.path == ("dependencies",) and p.field == "assignee" and m["answer"] == "Omar Singh" for p, m in v4)


def test_plan_lessons_are_learned_saved_and_used(tmp_path):
    tb = _bank(tmp_path)
    qs = [{"question": "Who is assigned to the Linear issue that pull request #4821 is linked to?", "expected": {"value": "Omar Singh"}},
          {"question": "How many Linear issues are assigned to Omar Singh?", "expected": {"value": "2"}},
          {"question": "How many Linear issues are assigned to Liam Chen?", "expected": {"value": "1"}},
          {"question": "Which of the Linear issues assigned to Omar Singh is due first? Give the key.",
           "expected": {"ids": ["ENG-11"], "id_kind": "key"}},
          {"question": "Which is due sooner, ENG-11 or ENG-13?", "expected": {"ids": ["ENG-11"], "id_kind": "key"}},
          {"question": "Who is assigned to the ticket that ENG-13 is linked to?", "expected": {"value": "Omar Singh"}}]
    les = P.learn_plans(tb, qs, log=lambda *_: None)
    les.save(tmp_path / "plans.json")
    again = P.PlanLessons.load(tmp_path / "plans.json")
    assert again.rules == "v4" and again.features == P.FEATURES_V4 and again.trained_on["questions_with_a_right_plan"] == 6
    assert any(line.startswith("words → kind of answer") for line in again.describe())
    ans, best, journal, top = P.answer(tb, again, qs[0]["question"])
    assert best is not None and journal[0]["op"] == "plan" and ans == P.Planner(tb, "v4").execute(best) and top[0][1] == best
    for q in qs:  # six questions are too few to expect the weights to be right; every answer is a plan's own answer
        ans, best, _, _ = P.answer(tb, again, q["question"])
        assert best is not None and ans == P.Planner(tb, "v4").execute(best)
    # lessons saved before v4 have no features or rules: they load as the first version
    old = {k: v for k, v in json.loads((tmp_path / "plans.json").read_text()).items() if k not in ("features", "kind_assoc", "rules")}
    old["weights"] = old["weights"][:len(P.FEATURES)]
    (tmp_path / "old.json").write_text(json.dumps(old))
    v3 = P.PlanLessons.load(tmp_path / "old.json")
    assert v3.rules == "v3" and v3.features == P.FEATURES and v3.assocs()[2] is None


def test_lift_scores_what_a_word_adds():
    lift = P.Lift()
    lift.add({"how", "many", "ticket"}, {"count"})
    lift.add({"who", "ticket"}, {"person"})
    lift.add({"who", "ticket"}, {"person"})
    assert lift.score({"many"}, {"count"}) > 0.2, "'many' came only with counts"
    assert abs(lift.score({"ticket"}, {"count"})) < 1e-9, "'ticket' comes with everything: it adds nothing"
    assert lift.score({"who"}, {"count"}) < 0 < lift.score({"who"}, {"person"})
    assert P.Lift(lift.to_json()).score({"many"}, {"count"}) == lift.score({"many"}, {"count"})
    assert "who" in P.question_words('Who took "the item"?') and "item" not in P.question_words('Who took "the item"?')


def _raw_docs():
    lin = lambda k, a, due, **x: {"dsid": f"l{k}", "source": "linear", "title": f"issue {k}",  # noqa: E731
                                  "raw": {"key": f"ENG-{k}", "assignee": a, "due_date": due, "status": "Todo", **x}}
    return [lin(11, "Omar Singh", "2026-03-20"), lin(12, "Omar Singh", "2026-04-02"), lin(13, "Liam Chen", "2026-05-01", dependencies=["ENG-12"]),
            lin(14, "Liam Chen", "2026-06-01"),
            {"dsid": "g1", "source": "github", "title": "Add retry", "raw": {"pr_number": "4821", "author": "Maya Chen", "linked_linear": ["ENG-11"]}}]


def test_multi_document_question_sets():
    docs = _raw_docs()
    assert {u["kind"] for u in M.units(docs)} == {"person", "pr", "ticket"}
    qs = M.questions(docs, {d["dsid"] for d in docs}, held_out=False, seed=1)
    by = {q["kind"]: q for q in qs}
    assert {"pr_issue", "issue_pr_author", "ticket_link", "person_count", "person_first", "compare_two"} <= set(by)
    assert by["issue_pr_author"]["expected"] == {"value": "Maya Chen"} and by["issue_pr_author"]["group"] == "link"
    counts = {q["question"]: q["expected"]["value"] for q in qs if q["kind"] == "person_count"}
    assert sorted(counts.values()) == ["2", "2"]
    first = next(q for q in qs if q["kind"] == "person_first" and "Omar Singh" in q["question"])
    assert first["expected"]["ids"] == ["ENG-11"] and first["pieces"][:2] == ["2026-03-20", "ENG-11"]
    # expected answers are computed within the set: without ENG-12, Omar has one issue and no count question
    small = M.questions(docs, {"l11", "l13", "l14", "g1"}, held_out=False, seed=1)
    assert not any(q["kind"] == "person_count" and "Omar" in q["question"] for q in small)
    retest = M.questions(docs, {d["dsid"] for d in docs}, held_out=True, seed=1, retest=True)
    wordings = {w.split("{")[0] for ws in M.RETEST.values() for w in ws}
    assert all(any(q["question"].startswith(w) or w == "" for w in wordings) for q in retest)
    assert not {q["question"] for q in retest} & {q["question"] for q in qs}
    ids = M.fresh(docs, exclude={"l11"})
    assert "l11" not in ids and ids, "a new set shares no document with what it excludes"


def test_pieces_and_rule_checks():
    q = {"pieces": ["ENG-11", "2026-03-20", "Omar Singh"]}
    assert M.pieces_in(q, "ENG-11 is due March 20, 2026; assignee: omar singh") == 1.0
    assert abs(M.pieces_in(q, "ENG-11 only") - 1 / 3) < 1e-9
    assert M.at_least(0.0, -0.05), "a difference of exactly 0 meets a rule that allows a drop"
    assert not M.at_least(None, -0.05) and not M.at_least(-0.06, -0.05) and M.at_least(0.2, 0.20)


def test_changed_information_also_changes_the_pieces(tmp_path):
    from cie.eval import factbank_split as SP

    src = tmp_path / "bench" / "generated_data" / "sources" / "linear"
    src.mkdir(parents=True)
    (src / "l11.json").write_text(json.dumps({"key": "ENG-11", "assignee": "Omar Singh", "due_date": "2026-03-20"}))
    work = tmp_path / "w"
    work.mkdir()
    (work / "haystack.json").write_text(json.dumps({"root": str(tmp_path / "bench"), "dsids": ["l11"]}))
    (work / "index.json").write_text(json.dumps({"index": {"l11": "linear/l11.json"}}))
    _write_jsonl(work / "questions.jsonl", [{"id": "a", "question": "Who has ENG-11?", "expected": {"value": "Omar Singh"},
                                             "pieces": ["ENG-11", "Omar Singh", "2026-03-20"]}])
    SP.changed(work, tmp_path / "c")
    q = _jsonl(tmp_path / "c" / "questions.jsonl")[0]
    assert q["pieces"][0] == "ENG-11" and q["pieces"][2] == "2026-04-12"
    assert q["pieces"][1] == q["expected"]["value"] != "Omar Singh", "a renamed person is renamed in the pieces too"


def test_v5_new_words_borrow_meaning_from_the_documents(tmp_path):
    import random

    from cie.factbank import lexicon as L

    rng = random.Random(5)
    sents = []
    for _ in range(300):
        who = rng.choice(["Omar Singh", "Liam Chen", "Maya Chen"])
        sents += [f"{who} will own the ticket and drive it", f"{who} is assigned the ticket and will drive it",
                  f"the deadline is {rng.choice(['2026-03-05', '2026-04-01'])} for the launch", "the launch looks fine and the pool is warm"]
    space = L.build_space((L.tokens(s) for s in sents), min_count=5, window=4, dim=6, log=lambda *_: None)
    lex = L.Lexicon(space, L.typing(sents, {"omar singh", "liam chen", "maya chen"}, set()), {})
    tb = _bank(tmp_path)
    pl = P.Planner(tb, "v4", lex, known=["assign", "many", "linear", "issu", "date"])
    plain = pl.plain_words('How many Linear issues does Omar Singh own? See "Fix keycard reader" and ENG-11.')
    assert "own" in plain and "many" in plain, plain
    assert not plain & {"omar", "singh", "fix", "keycard", "eng", "does", "how"}, "names, titles, keys and stop words lend nothing"
    got = pl.enrich({"own", "many", "deadline"}, {"own", "many", "deadline"}, floor=0.3, type_floor=0.05)
    assert got["many"] == 1.0 and got["own"] == 1.0, "the question's own words keep their full weight"
    assert 0 < got.get("assign", 0) < 1, "a new word borrows the known word nearest it in meaning"
    assert got.get("zzwhen", 0) > 0, "a word found next to dates is a word about dates"
    # with no lexicon the planner is v4: nothing borrowed
    assert P.Planner(tb, "v4").features("How many Linear issues does Omar Singh own?", P.Plan((OMAR,), ("assignee_of",), "label", "count"),
                                        {"named": 1.0, "rank": 1.0, "answer": "2", "fanout": 2}, P.Assoc(), P.Assoc(), P.Lift())["path_overlap"] == 0.0
    f = pl.features("How many Linear issues does Omar Singh own?", P.Plan((OMAR,), ("assignee_of",), "label", "count"),
                    {"named": 1.0, "rank": 1.0, "answer": "2", "fanout": 2}, P.Assoc(), P.Assoc(), P.Lift())
    assert 0 < f["path_overlap"] < 1, "a borrowed word overlaps a relation's name as much as it is near"


def test_v6_reads_nearness_from_general_english_too(tmp_path):
    from cie.factbank import lexicon as L

    company = L.build_space(([w for w in s.split()] for s in ["the ticket was created in jira today"] * 50 + ["owner took the ticket"] * 50),
                            min_count=5, dim=4, log=lambda *_: None)
    general = L.build_space(([w for w in s.split()] for s in ["she wrote the book and created the story"] * 50
                             + ["he wrote the letter and authored the story"] * 50), min_count=5, dim=4, log=lambda *_: None)
    tb = _bank(tmp_path)
    lex, gen = L.Lexicon(company), L.Lexicon(general)
    among = ["ticket", "authored", "owner"]
    by = {c: P.Planner(tb, "v4", lex, ["ticket", "authored", "owner"], gen, c).lenders("created", among, 3, -1.0)
          for c in ("company", "general", "max", "mean")}
    assert "authored" not in dict(by["company"]), "'authored' is not in the company's words: only the company's lenders count"
    assert by["general"][0][0] == "authored", "in general English, 'created' is used like 'authored'"
    assert dict(by["max"])["authored"] == dict(by["general"])["authored"]
    assert dict(by["mean"])["ticket"] == dict(by["company"])["ticket"], "a word one space lacks is read from the other alone"
    les = P.PlanLessons([0.0] * len(P.FEATURES_V4), {}, {}, {}, list(P.FEATURES_V4))
    assert (les.general_lexicon, les.combine, les.floor) == ("", "company", 0.5), "lessons saved before v6 read as v5"


def test_changed_information_renames_people_only(tmp_path):
    """Found after the tests had run: a status such as "In Progress" was renamed like a person, and "PM: Jordan Lee" apart
    from "Jordan Lee"."""
    from cie.eval import factbank_split as SP

    src = tmp_path / "bench" / "generated_data" / "sources" / "linear"
    src.mkdir(parents=True)
    (src / "l11.json").write_text(json.dumps({"key": "ENG-11", "assignee": "Jordan Lee", "status": "In Progress", "due_date": "2026-03-20"}))
    (src / "l12.json").write_text(json.dumps({"key": "ENG-12", "assignee": "Omar Singh", "reviewers": ["PM: Jordan Lee"], "status": "Done"}))
    work = tmp_path / "w"
    work.mkdir()
    (work / "haystack.json").write_text(json.dumps({"root": str(tmp_path / "bench"), "dsids": ["l11", "l12"]}))
    (work / "index.json").write_text(json.dumps({"index": {"l11": "linear/l11.json", "l12": "linear/l12.json"}}))
    _write_jsonl(work / "questions.jsonl", [{"id": "a", "question": "What state is ENG-11 in?", "expected": {"value": "In Progress"}},
                                            {"id": "b", "question": "Who has ENG-11?", "expected": {"value": "Jordan Lee"}}])
    SP.changed(work, tmp_path / "c")
    qs = {q["id"]: q for q in _jsonl(tmp_path / "c" / "questions.jsonl")}
    names = json.loads((tmp_path / "c" / "renamed.json").read_text())
    assert qs["a"]["expected"] == {"value": "In Progress"} and "In Progress" not in names, "a status is not a person"
    assert set(names) == {"Jordan Lee", "Omar Singh"}
    doc = json.loads((tmp_path / "c" / "erb_changed" / "generated_data" / "sources" / "linear" / "l12.json").read_text())
    assert doc["reviewers"] == [f"PM: {names['Jordan Lee']}"], "one person keeps one new name, label and all"
    assert qs["b"]["expected"] == {"value": names["Jordan Lee"]}
    SP.changed(work, tmp_path / "old", legacy=True)
    assert "In Progress" in json.loads((tmp_path / "old" / "renamed.json").read_text()), "the first version, kept for reproducing"


def test_single_key_kinds_need_the_exact_key():
    """Found in review: one-key questions were scored with F1, so "A, B" to "which is due first, A or B?" scored 0.667."""
    q = {"kind": "compare_two", "expected": {"ids": ["ENG-11"], "id_kind": "key"}, "group": "compare"}
    assert M.own_score(q, "ENG-11") == 1.0 and M.own_score(q, "ENG-11, ENG-13") == 0.0
    lst = {"kind": "action_owner_issues", "expected": {"ids": ["ENG-11", "ENG-12"], "id_kind": "key"}, "group": "combine"}
    assert M.own_score(lst, "ENG-11") == 0.667, "a list still scores F1 (rounded to three places)"


def test_v9_training_asks_every_field_in_every_wording():
    import hashlib

    docs = _raw_docs()
    ids = {d["dsid"] for d in docs}
    # the questions the code gave before v9, for these documents (recorded from that code): the defaults must not change
    before = [(1, False, {}, "47a24339f2be1794"), (2, True, {}, "38db03f85e823f2a"), (3, True, {"retest": True}, "75c02a7b02053703"),
              (4, True, {"wordings": M.BLIND2}, "75d02dc034bbeb6e")]
    for seed, held, kw, digest in before:
        qs = M.questions(docs, ids, held, seed, **kw)
        assert hashlib.sha256(json.dumps(qs, sort_keys=True).encode()).hexdigest()[:16] == digest
    base = M.questions(docs, ids, held_out=False, seed=1)
    full = M.questions(docs, ids, held_out=False, seed=1, every_field=True, all_wordings=True, max_q=None)
    assert {q["question"] for q in base} <= {q["question"] for q in full}, "the full set holds the default questions, pairs included"
    pr = [q for q in full if q["kind"] == "pr_issue"]
    assert sorted({q["field"] for q in pr}) == ["assignee", "due_date", "status"] and len(pr) == 9, "three fields in three wordings"
    due = next(q for q in pr if q["field"] == "due_date")
    assert due["expected"] == {"date": "2026-03-20"} and due["pieces"] == ["ENG-11", "2026-03-20"]
    assert {q["question"] for q in pr if q["field"] == "assignee"} == {w.format(n="4821") for w in M.T[("pr_issue", "assignee")][0]}


def test_v9_reads_what_a_plan_rests_on(tmp_path):
    pl = P.Planner(_bank(tmp_path), "v9")
    read = pl.reads(P.Plan(("doc:d4",), ("linked_linear",), "assignee", "single"))
    assert read == {"ends": ["eng-11"], "values": ["omar singh"], "people": []}
    assert P.rests_on(["ENG-11", "Omar Singh"], read) and not P.rests_on(["ENG-12", "Omar Singh"], read)
    by_due = pl.reads(P.Plan(("doc:d1", "doc:d3"), (), "due_date", "earliest"))
    assert P.rests_on(["2026-03-20", "2026-05-01"], by_due)
    assert not P.rests_on(["2026-03-20", "2026-05-01"], pl.reads(P.Plan(("doc:d1", "doc:d3"), (), "status", "single"))), \
        "the right key by another field is right by coincidence"
    # a key passed through on the way is not what the plan answers about: ENG-12 is reached, then left for its assignee
    via = pl.reads(P.Plan(("doc:d3",), ("dependencies", "assignee"), "label", "single"))
    assert "eng-12" not in via["ends"] and not P.rests_on(["ENG-12", "Omar Singh"], via)
    assert P.rests_on(["ENG-12", "Omar Singh"], pl.reads(P.Plan(("doc:d3",), ("dependencies",), "assignee", "single")))
    owner = pl.reads(P.Plan((OMAR,), ("assignee_of",), "label", "list"))
    assert P.rests_on(["Omar Singh", "ENG-11", "ENG-12"], owner), "a person the plan starts from or passes through counts"
    assert P.rests_on(["ENG-11"], ["eng-11"]), "a flat list (recorded before roles) counts for every role"


def test_v9_planner_rules_and_checks(tmp_path):
    tb = _bank(tmp_path)
    pl = P.Planner(tb, "v9")
    assert pl.target_system(["github", "linear"], ("doc:d1",)) == "github", "it starts in Linear and asks about the pull request"
    assert pl.target_system(["linear"], ("doc:d1",)) == "linear" and pl.target_system([], ("doc:d1",)) == ""
    assert pl.one_by_construction(("doc:d3",), ()) and pl.one_by_construction(("doc:d3",), ("assignee",))
    assert not pl.one_by_construction((OMAR,), ("assignee_of",))
    assert not any(p.aggregate == "count" and not p.path for p, _ in pl.candidates("How many issues does Omar Singh have?"))
    q = "Which is due sooner, ENG-11 or ENG-13?"
    kept = pl.check(q, pl.candidates(q), "key")
    assert kept and all(set(p.starts) == {"doc:d1", "doc:d3"} and not p.path for p, _ in kept), "a choice compares exactly what it names"
    assert all(set(p.starts) == {"doc:d1", "doc:d3"} for p, _ in pl.check(q, pl.candidates(q))), "whatever kind of answer the plan gives"
    q2 = "Who opened the GitHub pull request that references Linear issue ENG-11?"
    kept2 = pl.check(q2, pl.candidates(q2), "person")
    assert kept2 and all(p.system == "github" for p, _ in kept2), "it starts in Linear and asks about GitHub"
    assert {m["answer"] for _, m in kept2} == {"Maya Chen"}
    assert pl.kind9(P.Plan(("doc:d3",), ("assignee",), "label", "single"), "Liam Chen") == "person"
    assert pl.out_kind(P.Plan(("doc:d3",), ("assignee",), "label", "single"), "Liam Chen") == "key", "the v4 features keep the old kind"
    assert {m["answer"] for p, m in kept if p.field == "due_date" and p.aggregate == "earliest"} == {"ENG-11"}
    q = "Who is assigned to the ticket that ENG-13 is linked to?"
    cands = pl.candidates(q)
    kept = pl.check(q, cands, "person", ("assignee",))
    assert kept and all(p.starts == ("doc:d3",) and p.field == "assignee" and pl.out_kind(p, m["answer"]) == "person" for p, m in kept)
    assert pl.check(q, cands, "count"), "a check no plan passes is skipped"


def test_v9_lessons_learn_the_kind_of_answer_and_answer_through_the_checks(tmp_path):
    tb = _bank(tmp_path)
    qs = [{"question": "Who is assigned to the Linear issue that pull request #4821 is linked to?", "expected": {"value": "Omar Singh"},
           "pieces": ["ENG-11", "Omar Singh"]},
          {"question": "How many Linear issues are assigned to Omar Singh?", "expected": {"value": "2"}, "pieces": ["ENG-11", "ENG-12"]},
          {"question": "How many Linear issues are assigned to Liam Chen?", "expected": {"value": "1"}, "pieces": ["ENG-13"]},
          {"question": "Which is due sooner, ENG-11 or ENG-13?", "expected": {"ids": ["ENG-11"], "id_kind": "key"},
           "pieces": ["2026-03-20", "2026-05-01"]},
          {"question": "Which is due sooner, ENG-13 or ENG-12?", "expected": {"ids": ["ENG-12"], "id_kind": "key"},
           "pieces": ["2026-05-01", "2026-04-02"]},
          {"question": "Who is assigned to the ticket that ENG-13 is linked to?", "expected": {"value": "Omar Singh"},
           "pieces": ["ENG-12", "Omar Singh"]}]
    les = P.learn_plans(tb, qs, log=lambda *_: None, rules="v9", proper=True)
    les.save(tmp_path / "v9.json")
    again = P.PlanLessons.load(tmp_path / "v9.json")
    assert again.rules == "v9" and again.trained_on["proper"] and again.asked_kind["kind"]["count"] == 2
    ak = P.AskedKind(again.asked_kind)
    assert ak.asked("How many Linear issues are assigned to Maya Chen?", 0.5) == "count"
    assert P.AskedKind(ak.to_json()).posterior({"how", "many"}) == ak.posterior({"how", "many"})
    ans, best, _, _ = P.answer(tb, again, "Which is due sooner, ENG-12 or ENG-11?")
    assert ans == "ENG-11" and best.field == "due_date" and not best.path
    form = {"kind": "person", "fields": ("assignee",)}
    ans, best, _, _ = P.answer(tb, again, "Who is assigned to the ticket that ENG-13 is linked to?", form=form)
    assert best.field == "assignee" and best.starts == ("doc:d3",) and ans in ("Omar Singh", "Liam Chen"), \
        "the form keeps the plans reading the assignee; five questions are too few for the weights to pick the link"


def test_the_measure_counts_an_answer_right_for_the_right_reason_only_if_its_plan_read_the_facts(tmp_path):
    q = {"id": "c1", "group": "compare", "kind": "compare_two", "field": "", "question": "Which is due sooner, ENG-11 or ENG-13?",
         "expected": {"ids": ["ENG-11"], "id_kind": "key"}, "pieces": ["2026-03-20", "2026-05-01"]}
    _write_jsonl(tmp_path / "questions.jsonl", [q])
    both = {"ends": ["eng-11", "eng-13"], "values": ["2026-03-20", "2026-05-01"], "people": []}
    created = {"ends": ["eng-11", "eng-13"], "values": ["2026-01-02", "2026-01-05"], "people": []}
    _write_jsonl(tmp_path / "factbank_v9.jsonl", [{"id": "c1", "answer": "ENG-11", "evidence": "", "reads": both}])
    _write_jsonl(tmp_path / "factbank_v4.jsonl", [{"id": "c1", "answer": "ENG-11", "evidence": "", "reads": created}])
    m = M.measure(tmp_path)
    assert m["direct"]["v9"]["mean"] == m["direct"]["v4"]["mean"] == 1.0
    assert m["reason"]["v9"]["mean"] == 1.0 and m["reason"]["v4"]["mean"] == 0.0
    q2 = {**q, "id": "a1", "group": "combine", "kind": "action_owner_issues", "question": "Which keys?",
          "expected": {"ids": ["ENG-11", "ENG-12"], "id_kind": "key"}, "pieces": ["ENG-11", "ENG-12"]}
    _write_jsonl(tmp_path / "questions.jsonl", [q, q2])
    _write_jsonl(tmp_path / "factbank_v9.jsonl", [{"id": "c1", "answer": "ENG-11", "evidence": "", "reads": both},
                                                 {"id": "a1", "answer": "ENG-11", "evidence": "", "reads": {"ends": ["eng-11", "eng-12"]}}])
    rows = {r["id"]: r for r in M.measure(tmp_path)["rows"]}
    assert 0 < rows["a1"]["direct"]["v9"] < 1 and rows["a1"]["reason"]["v9"] == 0.0, "a partly right list is not right for the right reason"


def test_v11_a_ticket_means_a_linear_or_jira_item(tmp_path):
    tb = _bank(tmp_path)
    v9, v11 = P.Planner(tb, "v9"), P.Planner(tb, "v9")
    v11.tickets = True
    q = "Which tickets are assigned to Omar Singh?"
    assert v9.systems_named(q) == [] and v11.systems_named(q) == ["ticket"], "off by default: v9 is unchanged"
    assert v11.systems_named("What is the status of the Linear ticket ENG-11?") == ["linear", "ticket"], "a named tracker comes first"
    assert v11.in_system("doc:d1", "ticket") and not v11.in_system("doc:d4", "ticket") and v11.in_system("doc:d4", "github")
    assert v11.own_systems(("doc:d1",)) == {"linear", "ticket"} and v9.own_systems(("doc:d1",)) == {"linear"}
    assert v11.target_system(v11.systems_named("Who opened the PR for ticket ENG-11?"), ("doc:d1",)) == "github"
    assert v11.target_system(v11.systems_named("The ticket that PR #4821 is linked to: who has it?"), ("doc:d4",)) == "ticket"
    q2 = "The ticket that PR #4821 is linked to: who has it?"
    kept = v11.check(q2, v11.candidates(q2), "person")
    assert kept and all(p.system == "ticket" for p, _ in kept) and {m["answer"] for _, m in kept} == {"Omar Singh"}
    assert v11.execute(P.Plan((OMAR,), ("assignee_of",), "label", "count", "ticket")) == "2"
    qs = [{"question": "How many tickets are assigned to Omar Singh?", "expected": {"value": "2"}, "pieces": ["ENG-11", "ENG-12"]},
          {"question": "How many tickets are assigned to Liam Chen?", "expected": {"value": "1"}, "pieces": ["ENG-13"]}]
    les = P.learn_plans(tb, qs, log=lambda *_: None, rules="v9", proper=True, tickets=True)
    les.save(tmp_path / "v11.json")
    again = P.PlanLessons.load(tmp_path / "v11.json")
    assert again.tickets and again.planner(tb).tickets
    old = {k: v for k, v in json.loads((tmp_path / "v11.json").read_text()).items() if k != "tickets"}
    (tmp_path / "v9.json").write_text(json.dumps(old))
    assert not P.PlanLessons.load(tmp_path / "v9.json").tickets, "lessons saved before v11 have no ticket rule"


def test_v11_keeps_linked_keys_without_a_document_and_v9_behaviour_from_a_ticket(tmp_path):
    docs = DOCS + [(_doc("d5", "linear", "Audit the door logs",
                         {"key": "ENG-15", "status": "Todo", "assignee": "Liam Chen", "due_date": "2026-06-01", "dependencies": ["ENG-12", "ENG-99"]},
                         ["ENG-15"]), {})]
    p = tmp_path / "fb5.sqlite"
    B.build(p, docs, text_facts=True)
    tb = TrainedBank(p)
    v9, v11 = P.Planner(tb, "v9"), P.Planner(tb, "v9")
    v11.tickets = True
    key99 = next(e for e in tb.kinds if tb.label_of(e) == "ENG-99")
    assert tb.kinds[key99] == "identifier" and tb.system_of_entity(key99) == ""
    assert v11.in_system(key99, "ticket") and not v11.in_system(OMAR, "ticket"), "a ticket key with no document is still a ticket"
    q = "ENG-15 is linked to another ticket. Who is that one assigned to?"
    a, b = v9.candidates(q), v11.candidates(q)
    assert {(p.path, p.field, p.aggregate, m["answer"]) for p, m in a} == {(p.path, p.field, p.aggregate, m["answer"]) for p, m in b}, \
        "from a ticket, naming no other system, v11 plans exactly as v9"
    assert not any(p.system for p, _ in b if p.starts == ("doc:d5",)), "no filter on plans from the ticket itself"
    d5 = P.Plan(("doc:d5",), ("dependencies",), "label", "single", "ticket")
    assert v11.execute(d5) is None, "with the filter too, the key without a document stays, so the two keys disagree"
    assert not any(p.starts == ("doc:d5",) and p.path == ("dependencies",) and p.field == "label" and p.aggregate == "single" for p, _ in b), \
        "two linked keys, one without a document: no single key is the answer"


def test_the_ticket_test_judges_action_items_that_name_no_tracker():
    assert M.NAMES_TRACKER.search("Which Linear issues does she have?") and M.NAMES_TRACKER.search("any JIRA tickets?")
    assert not M.NAMES_TRACKER.search("Whoever got the to-do, list the ticket IDs") and not M.NAMES_TRACKER.search("nonlinear")
    assert M.MIN_UNNAMED == 4


def test_v13_a_question_asking_for_several_things_gets_no_first_one_due(tmp_path):
    tb = _bank(tmp_path)
    v11, v13 = P.Planner(tb, "v9"), P.Planner(tb, "v9")
    v11.tickets = v13.tickets = v13.orders = True
    several, rank = P.Planner.asks_several, P.Planner.asks_rank
    assert several("Which tickets are assigned to Omar Singh? Ticket keys please.") and several("Can you list the ticket IDs?")
    assert several("Who took it? What are their tickets?") and several("What Linear issues does she have?")
    assert not several("Which of Omar Singh's tickets has the tightest deadline? Key please."), "which of the tickets asks for one"
    assert not several("Which ticket assigned to Omar Singh is most overdue?") and not several("Of A and B, which is due first?")
    assert not several('Who took "List the keys" in the meeting?'), "quoted titles are not read"
    assert rank("Which is due 1st?") and rank("the soonest") and not rank("Need them as soon as you can, before my call.")
    q = "Which tickets are assigned to Omar Singh? Keys please."
    cands = v11.candidates(q)
    assert any(p.aggregate == "earliest" for p, _ in v11.check(q, cands, "key")), "v11 keeps plans that pick the first one due"
    kept = v13.check(q, cands, "key")
    assert kept and not any(p.aggregate in ("earliest", "latest") for p, _ in kept)
    assert ("ENG-11, ENG-12") in {m["answer"] for p, m in kept if p.aggregate == "list"}
    for q2 in ("Of the tickets assigned to Omar Singh, which has the tightest deadline? Give the key.",
               "What tickets does Omar Singh have due soonest? Key please."):
        assert any(p.aggregate == "earliest" for p, _ in v13.check(q2, v13.candidates(q2), "key")), "one thing, or a rank: it may"
    qs = [{"question": "How many tickets are assigned to Omar Singh?", "expected": {"value": "2"}, "pieces": ["ENG-11", "ENG-12"]}]
    les = P.learn_plans(tb, qs, log=lambda *_: None, rules="v9", proper=True, tickets=True, orders=True)
    les.save(tmp_path / "v13.json")
    assert P.PlanLessons.load(tmp_path / "v13.json").planner(tb).orders
    old = {k: v for k, v in json.loads((tmp_path / "v13.json").read_text()).items() if k != "orders"}
    (tmp_path / "v11.json").write_text(json.dumps(old))
    assert not P.PlanLessons.load(tmp_path / "v11.json").orders, "lessons saved before v13 have no order check"
