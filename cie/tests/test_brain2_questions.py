"""The company brain v16's new kinds of question: counts and filters, history, email and chat, two-document joins, unanswerable
fields and embedded question words; what each sets aside; the draw; and the scorer."""

from __future__ import annotations

from collections import Counter

import pytest

from cie.eval import brain2_questions as Q
from cie.eval import brain_questions as B


def _d(dsid, source, title, **raw):
    return {"dsid": dsid, "source": source, "title": title, "raw": raw}


def _gen(kinds, docs, seed=1):
    qs, rep = Q.generate(docs, seed, kinds)
    return qs, {k: Counter(v) for k, v in rep["aside"].items()}


def _by(qs, kind):
    return [q for q in qs if q["kind"] == kind]


# ------------------------------------------------------------------ the catalogue
def test_the_catalogue_names_every_new_kind_once_with_a_generator_family_and_scorer():
    cat = Q.kinds()
    names = [k["name"] for k in cat]
    assert len(names) == len(set(names)) and set(names) == set(Q.GENERATORS)
    assert {k["family"] for k in cat} == {"counts", "history", "email_chat", "multi", "unanswerable", "single"}
    assert all(k["group"] and k["scored"] and k["source"] for k in cat)
    assert not set(names) & set(B.CATALOGUE), "no new kind reuses an old kind's name"
    assert {k[len("embedded_"):] for k in names if k.startswith("embedded_")} == set(B.FIELDS)
    assert Q.family({"kind": "count1_jira"}) == "counts" and Q.family({"kind": "pr_issue"}) == "multi"
    assert Q.family({"kind": "?", "expected": {"not_found": True}}) == "not_found"
    with pytest.raises(ValueError):
        Q.generate([], kinds=["count_everything"])


def test_every_embedded_wording_puts_its_question_word_after_a_verb_of_knowing_or_telling():
    verbs = ("know", "remind me", "tell me", "idea")
    for base, ws in Q.EMBEDDED.items():
        ph = Q.PLACEHOLDER[B.ADDRESS[B.FIELDS[base][0]]]
        assert len(ws) >= 3 and all("{" + ph + "}" in w for w in ws), base
        assert all(any(v in w for v in verbs) for w in ws), base


# ------------------------------------------------------------------ counts and filters
def _jira(dsid, key, priority, issue_type, status, **x):
    return _d(dsid, "jira", f"Ticket {key}", key=key, priority=priority, issue_type=issue_type, status=status, **x)


JIRA = [_jira("j1", "SUP-101", "P2", "Bug", "In Progress"), _jira("j2", "SUP-102", "P2", "Bug", "Resolved"),
        _jira("j3", "SUP-103", "p2", "Task", "In Progress"), _jira("j4", "SUP-104", "P1", "Task", "In Progress")]


def test_count_questions_count_the_documents_holding_one_value_and_set_aside_what_is_unclear():
    qs, aside = _gen(["count1_jira"], JIRA)
    got = {tuple(map(tuple, q["filters"])): q for q in qs}
    assert {k: q["expected"]["value"] for k, q in got.items()} == {
        (("issue_type", "Bug"),): "2", (("issue_type", "Task"),): "2", (("priority", "P2"),): "3", (("status", "In Progress"),): "3"}
    p2 = got[(("priority", "P2"),)]
    assert p2["gold_docs"] == ["j1", "j2", "j3"], "'P2' and 'p2' are one value"
    assert p2["pieces"] == ["P2", "3", "SUP-101", "SUP-102", "SUP-103"] and p2["family"] == "counts" and p2["generated"]
    assert "P2" in p2["question"] and ("Jira" in p2["question"])
    assert aside["count1_jira"] == {"count outside 2-15": 2}, "P1 and Resolved are on one ticket each"


def test_two_condition_counts_narrow_both_sets_spell_out_open_and_skip_a_set_already_asked():
    qs, aside = _gen(["count2_jira", "filter_list"], JIRA)
    (two,) = _by(qs, "count2_jira")
    assert two["filters"] == [["open", "open"], ["priority", "P2"]] and two["expected"] == {"value": "2"}
    assert "status not Resolved or Closed" in two["question"] and two["gold_docs"] == ["j1", "j3"]
    assert aside["count2_jira"] == {"same set as another filter": 1}, "P2 and In Progress hold the same two tickets"
    lists = {tuple(q["expected"]["ids"]) for q in _by(qs, "filter_list")}
    assert ("SUP-101", "SUP-103") in lists and ("SUP-101", "SUP-102", "SUP-103") in lists
    assert all(q["expected"]["id_kind"] == "key" and "keys" in q["question"].lower() for q in _by(qs, "filter_list"))


def test_a_value_inside_another_value_and_a_count_written_in_the_question_are_set_aside():
    drive = [_d(f"g{i}", "google_drive", f"Doc {i}", team=t, status="draft" if i < 2 else "final") for i, t in
             enumerate(("eng", "eng", "eng-tools", "eng-tools"))]
    lin = [_d(f"l{i}", "linear", f"Issue {i}", key=f"ENG-20{i}", estimate=e, team="infra") for i, e in enumerate(("2", "2", "3"))]
    qs, aside = _gen(["count1_google_drive", "count1_linear"], drive + lin)
    assert all(q["filters"][0][0] != "team" for q in _by(qs, "count1_google_drive"))
    assert aside["count1_google_drive"]["named inside another"] == 2, "'eng' is written inside 'eng-tools'"
    assert [q["filters"] for q in _by(qs, "count1_linear")] == [[["team", "infra"]]]
    assert aside["count1_linear"]["answer in the question"] == 1, "two issues with an estimate of 2"


def test_gmail_counts_by_mailbox_and_type_and_by_account():
    def g(i, owner, ttype, account, subject=None):
        return _d(f"m{i}", "gmail", subject or f"Thread number {i}", mailbox_owner=owner, thread_type=ttype, related_account=account)

    docs = [g(1, "maya_chen", "renewal", "Northwind Health"), g(2, "maya_chen", "renewal", "Northwind Health"),
            g(3, "liam_wu", "sales", "Acme Corp"), g(4, "liam_wu", "sales", "Acme Corp"),
            g(5, "ana_ruiz", "sales", "Fjord Bank"), g(6, "ana_ruiz", "partner", "Fjord Bank"),
            g(7, "ben_ode", "misc", "N/A", subject="Intro call with Fjord Bank")]
    qs, aside = _gen(["count_gmail"], docs)
    got = {tuple(map(tuple, q["filters"])): q["expected"]["value"] for q in qs}
    assert got == {(("mailbox_owner", "Maya Chen"), ("thread_type", "renewal")): "2", (("mailbox_owner", "Liam Wu"), ("thread_type", "sales")): "2",
                   (("related_account", "Northwind Health"),): "2"}
    assert aside["count_gmail"]["generic account name"] == 1 and aside["count_gmail"]["another thread's subject names it"] == 1


# ------------------------------------------------------------------ history
def test_created_and_updated_dates_are_set_aside_when_a_dated_entry_falls_outside_them():
    docs = [_d("l1", "linear", "A", key="ENG-201", created_at="2026-01-10", updated_at="2026-01-20",
               comments=["2026-01-05 Ana Ruiz: an early note"]),
            _d("l2", "linear", "B", key="ENG-202", created_at="2026-01-10", updated_at="2026-01-20"),
            _d("l3", "linear", "C", key="ENG-203", created_at="2026-01-10", updated_at="2026-01-12",
               comments=["2026-01-15 Ana Ruiz: a later note"]),
            _d("h1", "hubspot", "Northwind Health", created_at="2025-11-02", updated_at="2025-10-01")]
    qs, aside = _gen(["created_on", "last_updated"], docs)
    assert {q["question"].split()[-1].strip("?\""): q["expected"]["date"] for q in _by(qs, "created_on")
            if "ENG" in q["question"]} == {"ENG-202": "2026-01-10", "ENG-203": "2026-01-10"}
    assert aside["created_on"] == {"history dated before it": 1}
    upd = {q["pieces"][0]: q["expected"]["date"] for q in _by(qs, "last_updated")}
    assert upd == {"ENG-201": "2026-01-20", "ENG-202": "2026-01-20"}
    assert aside["last_updated"] == {"history dated after it": 1, "updated before created": 1}


def test_days_to_merge_and_the_date_a_ticket_moved_to_its_status():
    docs = [_d("p1", "github", "PR one", pr_number="4501", state="merged", created_at="2026-02-01", merged_at="2026-02-04T10:00:00Z"),
            _d("p2", "github", "PR two", pr_number="4502", state="open", created_at="2026-02-01", merged_at="2026-02-04"),
            _d("l1", "linear", "A", key="ENG-301", status="In Review", comments=["2026-02-03 Ana Ruiz: tests pass, moving to In Review"]),
            _d("l2", "linear", "B", key="ENG-302", status="Done", comments=["2026-02-05 Ana Ruiz: marking pipeline as Done"]),
            _d("l3", "linear", "C", key="ENG-303", status="Planned",
               updates=["2026-02-01 moved this issue to Planned", "2026-02-09 moved the ticket to Planned again"])]
    qs, aside = _gen(["pr_days_to_merge", "moved_to_status"], docs)
    (days,) = _by(qs, "pr_days_to_merge")
    assert days["expected"] == {"value": "3"} and "#4501" in days["question"] and aside["pr_days_to_merge"] == {"not merged": 1}
    (moved,) = _by(qs, "moved_to_status")
    assert moved["expected"] == {"date": "2026-02-03"} and "ENG-301" in moved["question"] and "In Review" in moved["question"]
    assert aside["moved_to_status"] == {"another noun moved to the status": 1, "moved on two dates": 1}


def test_first_commenter_and_latest_comment_need_every_comment_dated_and_signed():
    docs = [_d("l1", "linear", "A", key="ENG-401", comments=["2026-02-03 Liam Wu (SRE): second", "2026-02-02 10:00 - Priya Nair: first"]),
            _d("l2", "linear", "B", key="ENG-402", comments=["2026-02-02 Product Review (Liam Chen): approved"]),
            _d("l3", "linear", "C", key="ENG-403", comments=["2026-02-02 Ana Ruiz: one", "2026-02-02 Ben Ode: two"]),
            _d("j1", "jira", "D", key="SUP-404", comments=["2026-02-02 09:38 - Support (Maya Patel): acknowledged"])]
    qs, aside = _gen(["first_commenter", "last_comment_date"], docs)
    assert [(q["pieces"][0], q["expected"]) for q in _by(qs, "first_commenter")] == [("ENG-401", {"value": "Priya Nair"})]
    assert aside["first_commenter"] == {"a role before the name": 1, "tie for the first comment": 1, "comment unparseable": 1}
    last = {q["pieces"][0]: q["expected"]["date"] for q in _by(qs, "last_comment_date")}
    assert last == {"ENG-401": "2026-02-03", "ENG-402": "2026-02-02", "ENG-403": "2026-02-02"}, "a tie on the latest date is one date"
    assert all(("Jira ticket" in q["question"]) == q["pieces"][0].startswith("SUP") for q in qs)


def test_the_first_activity_of_a_hubspot_account():
    docs = [_d("h1", "hubspot", "Northwind Health", timeline=["2026-01-15: intro call", "2026-01-10 - kickoff email"]),
            _d("h2", "hubspot", "Fjord Bank Group", timeline=["2026-01-15: intro call"], recent_activities=["2026-01-01: cold email"]),
            _d("h3", "hubspot", "Kestrel Analytics", timeline="2026-01-15 intro\nfollow-up next week")]
    qs, aside = _gen(["hubspot_first_activity"], docs)
    assert [(q["pieces"][0], q["expected"]["date"]) for q in qs] == [("Northwind Health", "2026-01-10")]
    assert aside["hubspot_first_activity"] == {"earlier date in another activity field": 1, "entry not dated": 1}


# ------------------------------------------------------------------ email and chat
def _msg(frm, to, date, cc=None, body="Hello"):
    return f"From: {frm}\nTo: {to}\n" + (f"Cc: {cc}\n" if cc else "") + f"Date: {date}\nSubject: s\n\n{body}"


def test_email_questions_read_the_first_message_and_check_it_against_the_thread_fields():
    t1 = _d("e1", "gmail", "Pilot terms and pricing", mailbox_owner="maya_chen", first_email_at="2026-12-02T11:53:00-08:00",
            message_count="2", attachments=["terms.pdf", "pricing.xlsx"], has_attachments="true", related_account="Northwind Health",
            messages=[_msg("Rachel Lim <rachel@nw.com>", "Maya Chen <maya@redwood.ai>; Liam Wu <liam@redwood.ai>",
                           "Wed, 2 Dec 2026 11:53:00 -08:00", cc="Portal Support <support@vendor.io>"),
                      _msg("Maya Chen <maya@redwood.ai>", "Rachel Lim <rachel@nw.com>", "2026-12-03T09:00:00-08:00")])
    t2 = _d("e2", "gmail", "Renewal for Acme Corp", first_email_at="2026-12-05T09:00:00-08:00", message_count="3", related_account="Acme Corp",
            messages="From: Ana Ruiz <ana@redwood.ai>\\nTo: Bo Li <bo@acme.com>\\nDate: 2026-12-05T09:00:00-08:00\\n\\nHi\\n"
                     "From: Bo Li <bo@acme.com>\\nTo: Ana Ruiz <ana@redwood.ai>\\nDate: 2026-12-04T09:00:00-08:00\\n\\nHi")
    qs, aside = _gen(["email_sender", "email_date", "email_to", "email_cc", "email_count", "email_attachments", "email_account"], [t1, t2])
    got = {(q["kind"], q["pieces"][0]): q["expected"] for q in qs}
    assert got == {("email_sender", "Pilot terms and pricing"): {"value": "Rachel Lim"},
                   ("email_date", "Pilot terms and pricing"): {"date": "2026-12-02"},
                   ("email_to", "Pilot terms and pricing"): {"names": ["Maya Chen", "Liam Wu"]},
                   ("email_count", "Pilot terms and pricing"): {"value": "2"},
                   ("email_attachments", "Pilot terms and pricing"): {"files": ["terms.pdf", "pricing.xlsx"]},
                   ("email_account", "Pilot terms and pricing"): {"value": "Northwind Health"}}
    assert aside["email_cc"]["an entry not a named person"] == 1, "Portal Support is a mailbox, not a person"
    assert aside["email_sender"]["first message is not the earliest"] == 1
    assert aside["email_date"]["first_email_at is not the earliest message"] == 1
    assert aside["email_count"]["count is not the messages written"] == 1, "message_count says 3, two are written"
    assert aside["email_account"]["answer in the question"] == 1, "the subject names Acme Corp"
    assert all(f'"{q["pieces"][0]}"' in q["question"] for q in qs)


def test_a_subject_shared_once_re_is_stripped_names_no_thread():
    docs = [_d("e1", "gmail", "Pilot terms", related_account="Northwind Health"),
            _d("e2", "gmail", "Re: Pilot terms", related_account="Fjord Bank")]
    qs, aside = _gen(["email_account"], docs)
    assert qs == [] and aside["email_account"] == {"named twice": 2}


def test_slack_threads_are_named_by_a_unique_quote_of_their_first_words():
    s1 = _d("s1", "slack", "eng-platform", channel="eng-platform",
            messages="Maya Chen: Quick sync on the canary thresholds before Friday rollout please and thanks\nSam: ok")
    s2 = _d("s2", "slack", "support", channel="support", text="anya: we saw a spike starting at noon in us-east errors\nbo: looking")
    s3 = _d("s3", "slack", "incidents", channel="incidents", messages="Ben Ode: Paging on-call now for the database failover drill please")
    s4 = _d("c1", "confluence", "Drill notes", body="Ben Ode: Paging on-call now for the database failover drill please confirm")
    qs, aside = _gen(["slack_channel", "slack_starter"], [s1, s2, s3, s4])
    ch = {q["expected"]["value"]: q["question"] for q in _by(qs, "slack_channel")}
    assert set(ch) == {"eng-platform", "support"} and '"Quick sync on the canary thresholds before Friday rollout please"' in ch["eng-platform"]
    assert [q["expected"] for q in _by(qs, "slack_starter")] == [{"value": "Maya Chen"}]
    assert aside["slack_channel"] == {"quote not unique": 1} and aside["slack_starter"]["starter not a full name"] == 1


# ------------------------------------------------------------------ two documents
def _lin(dsid, key, who, project="Gateway Hardening", team="platform", creator="Ana Ruiz", **x):
    return _d(dsid, "linear", f"Issue {key}", key=key, assignee=who, project=project, team=team, creator=creator, **x)


MULTI = [_lin("l1", "ENG-501", "Maya Chen"), _lin("l2", "ENG-502", "Maya Chen", project="Billing Revamp", team="infra"),
         _lin("l3", "ENG-503", "Omar Singh", project="Edge Cache", creator="Liam Wu"),
         _d("p1", "github", "PR one", pr_number="34501", author="Maya Chen", linked_linear=["ENG-501"]),
         _d("p2", "github", "PR two", pr_number="34502", author="Liam Wu", linked_linear=["ENG-503"], linked_jira=["SUP-900"]),
         _d("j1", "jira", "Ticket SUP-900", key="SUP-900", project="customer-support", reporter="Maya Chen", assignee="Bo Li"),
         _d("f1", "fireflies", "Northwind kickoff call", redwood_owner="Jordan Reyes"),
         _d("h1", "hubspot", "Northwind Health", owner="Jordan Reyes"), _d("h2", "hubspot", "Fjord Bank Group", owner="Jordan Reyes")]


def test_the_project_creator_and_team_of_the_issue_a_pull_request_links():
    qs, aside = _gen(list(Q.LINK), MULTI)
    got = {(q["kind"], q["question"].split("#")[1][:5]): q["expected"]["value"] for q in qs}
    assert got == {("pr_issue_project", "34501"): "Gateway Hardening", ("pr_issue_creator", "34501"): "Ana Ruiz",
                   ("pr_issue_creator", "34502"): "Liam Wu", ("pr_issue_team", "34501"): "platform", ("pr_issue_team", "34502"): "platform"}
    assert aside["pr_issue_project"] == {"linked": 1}, "PR #34502 also references SUP-900, whose project differs"
    q = next(q for q in qs if q["kind"] == "pr_issue_project")
    assert q["family"] == "multi" and q["group"] == "link" and q["field"] == "project"
    assert q["gold_docs"] == ["l1", "p1"] and q["pieces"] == ["ENG-501", "Gateway Hardening"]


def test_joins_on_a_full_name_give_keys_or_an_account_count():
    qs, aside = _gen(["author_issues", "reporter_issues", "owner_accounts"], MULTI)
    (auth,) = _by(qs, "author_issues")
    assert auth["expected"] == {"ids": ["ENG-501", "ENG-502"], "id_kind": "key"} and "#34501" in auth["question"]
    assert auth["pieces"] == ["Maya Chen", "ENG-501", "ENG-502"] and auth["gold_docs"] == ["l1", "l2", "p1"] and auth["group"] == "combine"
    assert aside["author_issues"] == {"no documents to join": 1}, "no issue is assigned to Liam Wu"
    (rep,) = _by(qs, "reporter_issues")
    assert rep["expected"]["ids"] == ["ENG-501", "ENG-502"] and "SUP-900" in rep["question"]
    (own,) = _by(qs, "owner_accounts")
    assert own["field"] == "count" and own["expected"] == {"value": "2"} and own["pieces"] == ["Jordan Reyes", "Fjord Bank Group", "Northwind Health"]


def test_a_join_whose_name_is_written_in_another_form_on_a_target_is_set_aside():
    docs = MULTI + [_lin("l4", "ENG-504", "Dr. Maya Chen")]
    qs, aside = _gen(["author_issues", "reporter_issues"], docs)
    assert qs == [] and aside["author_issues"]["the name in another form"] == 1 and aside["reporter_issues"]["the name in another form"] == 1


def test_a_single_owned_account_is_asked_as_a_count_or_by_name():
    docs = MULTI[:-1]
    seen = set()
    for seed in range(8):
        (own,) = _by(Q.generate(docs, seed, ["owner_accounts"])[0], "owner_accounts")
        seen.add(own["field"])
        assert own["expected"] == ({"value": "1"} if own["field"] == "count" else {"value": "Northwind Health"})
    assert seen == {"count", "name"}


def test_multi_questions_have_the_format_the_plan_lessons_learn_from():
    from cie.eval.brain_train import fact_questions

    qs, _ = _gen([*Q.LINK, *Q.JOIN, "owner_accounts"], MULTI)
    assert qs and fact_questions(qs) == qs
    assert all({"id", "group", "kind", "field", "question", "expected", "gold_docs", "pieces", "family"} <= set(q) for q in qs)


# ------------------------------------------------------------------ unanswerable
def test_field_absent_asks_for_a_usually_present_field_that_is_empty_here():
    docs = [_d(f"l{i}", "linear", f"Issue {i}", key=f"ENG-60{i}", due_date="2026-03-01") for i in range(3)]
    docs += [_d("l3", "linear", "Issue 3", key="ENG-603", due_date=""),
             _d("l4", "linear", "Issue 4", key="ENG-604", description="the deadline moved to next month"),
             _d("j0", "jira", "T0", key="SUP-1", sla_due_at="2026-03-01"), _d("j1", "jira", "T1", key="SUP-2"),
             _d("j2", "jira", "T2", key="SUP-3", sla_due_at="TBD")]
    qs, aside = _gen(["field_absent"], docs)
    got = {(q["field"], q["pieces"][0]): (q["expected"], q["absent_value"]) for q in qs}
    assert got == {("due_date", "ENG-603"): ({"not_found": True}, "")}
    assert aside["field_absent"] == {"another field mentions it": 1, "field usually empty": 2 + 5 + 5 + 3}, \
        "sla_due_at on two of three tickets; customer_impact and release on no issue, first_response_due_at on no ticket"
    assert qs[0]["family"] == "unanswerable" and "ENG-603" in qs[0]["question"]


# ------------------------------------------------------------------ embedded question words
def test_embedded_questions_keep_the_field_questions_expected_answers():
    docs = [_d("g1", "google_drive", "Runway model for Q3", owner="Maya Chen (Finance)"),
            _d("g2", "google_drive", "Hiring plan draft", owner="Ana Ruiz")]
    old = B.field_questions("drive_owner", docs, __import__("random").Random(1), None)
    qs, _ = _gen(["embedded_drive_owner"], docs)
    assert sorted((q["expected"]["value"], tuple(q["pieces"]), tuple(q["gold_docs"])) for q in qs) == \
        sorted((q["expected"]["value"], tuple(q["pieces"]), tuple(q["gold_docs"])) for q in old)
    assert all(q["question"] in [w.format(t=q["pieces"][0]) for w in Q.EMBEDDED["drive_owner"]] for q in qs)
    assert all(q["family"] == "single" and q["group"] == "embedded" and q["field"] == "owner" for q in qs)


# ------------------------------------------------------------------ the draw and the scorer
def test_draw_questions_mixes_new_and_old_kinds():
    docs = JIRA + MULTI + [_d("g1", "google_drive", "Runway model for Q3", owner="Maya Chen")]
    qs = Q.draw_questions(docs, 3, {"count": 2, "drive_owner": 1, "multi": 3})
    kinds = Counter(q["kind"] for q in qs)
    assert sum(kinds.values()) == 6 and kinds["drive_owner"] == 1
    assert sum(n for k, n in kinds.items() if Q.family({"kind": k}) == "counts") == 2
    assert "pr_issue" in Q.resolve("multi") and "pr_issue_project" in Q.resolve("multi")
    assert qs == Q.draw_questions(docs, 3, {"count": 2, "drive_owner": 1, "multi": 3}), "seeded"


@pytest.mark.parametrize("answer, n, hit", [
    ("3", 3, 1), ("There are three tickets.", 3, 1), ("In cycle 2026-W10 there are 3 issues", 3, 1), ("ENG-123, ENG-456: 2 of them", 2, 1),
    ("Answer: 4\nKeys: ENG-1, ENG-2", 4, 1), ("PR #4501 took 3 days", 3, 1), ("09:14 meeting, 2 threads", 2, 1), ("12", 2, 0),
    ("Two, maybe 3", 3, 0), ("none", 0, 0), ("0 days (merged the same day)", 0, 1), ("about 3.5", 3, 0)])
def test_count_hit_reads_the_first_number_of_the_answer_line(answer, n, hit):
    assert Q.count_hit(n, answer) == hit


def test_score_by_kind():
    count = {"kind": "count1_jira", "expected": {"value": "3"}}
    assert Q.score(count, "3 tickets") == 1 and Q.score(count, {"answer": "4", "route": "fact"}) == 0
    assert Q.score(count, {"answer": "not found", "route": "not_found"}) == 0
    absent = {"kind": "field_absent", "family": "unanswerable", "expected": {"not_found": True}}
    assert Q.score(absent, "Not found") == 1 and Q.score(absent, "2026-03-01") == 0
    files = {"kind": "email_attachments", "expected": {"files": ["terms.pdf", "pricing.xlsx"]}}
    assert Q.score(files, "terms.pdf, pricing.xlsx") == 1 and Q.score(files, "terms.pdf") == pytest.approx(0.667)
    assert Q.files_f1(["terms.pdf"], "terms.pdf, notes.docx") == pytest.approx(0.667)
    to = {"kind": "email_to", "expected": {"names": ["Maya Chen", "Liam Wu"]}}
    assert Q.score(to, "Maya Chen and Liam Wu") == 1
    day = {"kind": "email_date", "expected": {"date": "2026-12-02"}}
    assert Q.score(day, "2026-12-02T11:53:00-08:00") == 1 and Q.score(day, "December 2, 2026") == 1
    who = {"kind": "first_commenter", "expected": {"value": "Priya Nair"}}
    assert Q.score(who, "Priya Nair (SRE)") == 1 and Q.score(who, "Priya Naird") == 0
    multi = {"kind": "author_issues", "family": "multi", "expected": {"ids": ["ENG-501", "ENG-502"], "id_kind": "key"}}
    assert Q.score(multi, "ENG-501, ENG-502") == 1 and Q.score(multi, "ENG-501") == pytest.approx(0.667)
    emb = {"kind": "embedded_pr_merged", "family": "single", "expected": {"date": "2026-02-26"}}
    assert Q.score(emb, "2026-02-26T10:00:00Z") == 1
    old = {"kind": "drive_owner", "family": "single", "expected": {"value": "Maya Chen"}}
    assert Q.score(old, "Maya Chen") == B.score(old, "Maya Chen") == 1
