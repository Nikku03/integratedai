"""The complex questions (``cie.eval.complex_questions``): each kind's answer from a small haystack of raw records, the
readings that set a candidate aside, and the scorer."""

from __future__ import annotations

from cie.eval import complex_questions as C


def _d(dsid, source, title, **raw):
    return {"dsid": dsid, "source": source, "title": title, "raw": raw}


def _docs():
    return [
        _d("pr1", "github", "Speed up the router", pr_number="1248", linked_linear=["ENG-12"], author="Noor Haddad"),
        _d("pr2", "github", "Fix the badge flow", pr_number="1301", linked_linear=["ENG-14"]),
        _d("l1", "linear", "Rotate office wifi keys", key="ENG-12", assignee="Omar Singh", creator="Ava Chen", project="Lobby Refresh",
           due_date="2026-04-03", priority="P2", status="In Progress", parent_issue="ENG-10"),
        _d("l0", "linear", "Lobby epic", key="ENG-10", assignee="Priya Nair", creator="Ava Chen", project="Lobby Refresh",
           due_date="2026-05-01", priority="P1", status="Todo"),
        _d("l2", "linear", "Replace the badge printer", key="ENG-13", assignee="Omar Singh", creator="Liam Chen", project="Lobby Refresh",
           due_date="2026-03-20", priority="P2", status="Todo"),
        _d("l3", "linear", "Paint the lobby", key="ENG-14", assignee="Omar Singh", creator="Liam Chen", project="Paint",
           due_date="2026-06-01", priority="P2", status="Done"),
        _d("j1", "jira", "Soft 429s", key="SUP-1", assignee="Ava Chen"),
        _d("j2", "jira", "Invoice error", key="SUP-2", assignee="Ava Chen"),
        _d("h1", "hubspot", "Acme Robotics", owner="Dana Lee", stage="Negotiation"),
        _d("h2", "hubspot", "Vectra Analytics", owner="Ethan Park", stage="Closed Won"),
        _d("f1", "fireflies", "Acme Robotics kickoff", customer_company="Acme Robotics", redwood_owner="Ethan Park"),
        _d("f2", "fireflies", "Vectra QBR", customer_company="Vectra Analytics", redwood_owner="Ethan Park"),
        _d("g1", "gmail", "Acme Robotics pricing follow-up", related_account="Acme Robotics"),
    ]


def _all(docs):
    qs, rep = C.draw(docs, per_kind=10, seed=1)
    by = {}
    for q in qs:
        by.setdefault(q["kind"], []).append(q)
    return by, rep


def test_each_kind_reads_its_steps():
    by, rep = _all(_docs())
    # PR 1248 -> ENG-12 and PR 1301 -> ENG-14, both assigned to Omar Singh, who has three Linear issues
    assert sorted((q["pieces"][0], q["expected"]["value"]) for q in by["pr_assignee_load"]) == [("1248", "3"), ("1301", "3")]
    assert {q["expected"]["value"] for q in by["pr_parent_assignee"]} == {"Priya Nair"}  # PR 1248 -> ENG-12 -> ENG-10 -> Priya Nair
    assert {q["expected"]["value"] for q in by["meeting_account_owner"]} == {"Dana Lee", "Ethan Park"}
    assert {q["expected"]["value"] for q in by["meeting_account_stage"]} == {"Negotiation", "Closed Won"}
    assert [q["expected"]["value"] for q in by["email_account_owner"]] == ["Dana Lee"]
    assert {q["expected"]["value"] for q in by["creator_jira_load"]} == {"2"}  # Ava Chen created ENG-12 and ENG-10, holds 2 Jira tickets
    assert [q["expected"]["value"] for q in by["project_first_due"]] == ["Omar Singh"]  # Lobby Refresh: ENG-13 due 2026-03-20
    assert {q["expected"]["value"] for q in by["owner_meetings"]} == {"2"}
    assert all(q["family"] == "complex" and q["steps"] >= 3 and q["gold_docs"] for qs in by.values() for q in qs)
    assert rep["questions"] == sum(len(v) for v in by.values())


def test_open_and_priority_filters():
    docs = _docs() + [_d("l4", "linear", "Fix door", key="ENG-15", assignee="Omar Singh", creator="Liam Chen", project="Paint",
                         due_date="2026-06-02", priority="P2", status="Canceled")]
    by, _ = _all(docs)
    # Omar Singh: ENG-12 (P2, open), ENG-13 (P2, open), ENG-14 (P2, Done), ENG-15 (P2, Canceled) -> 2 open P2 issues
    assert {q["expected"]["value"] for q in by["assignee_open_p"]} == {"2"}


def test_readings_set_aside():
    docs = _docs()
    docs.append(_d("pr3", "github", "Another link", pr_number="1400", linked_linear=["ENG-12"]))  # ENG-12 now linked by two PRs
    docs.append(_d("h3", "hubspot", "Acme Robotics Labs", owner="Kim Ro", stage="Lead"))  # "Acme Robotics" inside another title
    by, rep = _all(docs)
    assert "pr_parent_assignee" not in by
    assert all("Acme" not in q["question"] for q in by.get("meeting_account_owner", []))
    assert "email_account_owner" not in by
    tie = _docs() + [_d("l5", "linear", "Tie", key="ENG-16", assignee="Liam Chen", creator="Liam Chen", project="Lobby Refresh",
                        due_date="2026-03-20", priority="P3", status="Todo")]
    assert "project_first_due" not in _all(tie)[0] and _all(tie)[1]["aside"]["project_first_due"].get("tie for first due") == 1


def test_score():
    q = {"answer_type": "count", "expected": {"value": "3"}}
    assert C.score(q, "3 issues: ENG-12, ENG-13, ENG-14") == 1.0 and C.score(q, "2") == 0.0 and C.score(q, "not found") == 0.0
    p = {"answer_type": "person", "expected": {"value": "Priya Nair"}}
    assert C.score(p, {"answer": "Priya Nair", "route": "reasoner"}) == 1.0 and C.score(p, {"answer": "x", "route": "not_found"}) == 0.0
