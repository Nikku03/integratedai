"""The fact bank's opt-in engine modes for the company brain (v15): whole-word system names, evidence that starts with the
answer, blocks ordered by their largest single vote, keys on relation lines, and passages of document text."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime

from cie.factbank import bank as B
from cie.factbank.engine import PASSAGE, FactBank, replay, state_of, systems_in, windows
from cie.ingest.sources import SourceDoc

WHEN = datetime(2026, 3, 1, tzinfo=UTC)


def _doc(dsid, source, title, meta, body="", keys=()):
    return SourceDoc(dsid=dsid, source=source, rel=f"{source}/{dsid}.json", title=title, fields=[("body", body)], meta=meta, updated=WHEN,
                     keys=list(keys))


DOCS = [
    (_doc("d1", "linear", "Fix keycard reader timeouts", {"key": "ENG-11", "status": "In Progress", "assignee": "Omar Singh",
                                                        "due_date": "2026-03-20"}, "Badge readers time out at night.", ["ENG-11"]), {}),
    (_doc("d2", "linear", "Rotate office wifi keys", {"key": "ENG-12", "status": "Done", "assignee": "Omar Singh", "due_date": "2026-04-02"},
          "Quarterly rotation.", ["ENG-12"]), {}),
    (_doc("d3", "github", "Add retry to badge sync", {"pr_number": "4821", "repo": "redwood", "author": "Maya Chen",
                                                    "reviewers": ["Omar Singh"], "linked_linear": ["ENG-11"]}), {}),
    (_doc("d4", "hubspot", "Brightfjord Labs", {"owner": "Maya Chen", "forecast_close_month": "2026-04", "stage": "discovery"},
          "Brightfjord Labs wants a private deployment."), {}),
    # three messages in one Slack channel: they share the channel's name as their title
    *[(_doc(f"s{i}", "slack", "customer-success", {"participants_internal": ["Maya Chen"]}, f"Message {i} about onboarding."), {})
      for i in range(3)],
    (_doc("d5", "confluence", "Telemetry runbook",
          {}, "Overview of the service. " * 20 + "To verify the telemetry mode, query the status endpoint on port 9100. "
          "The mode should then read local-only. " + "Unrelated closing notes follow here. " * 20), {}),
    (_doc("d6", "fireflies", "Facilities sync", {}, "We talked about badges."),
     {"action_items": ["Omar Singh - replace the reader firmware on floor 3 - Due: 2026-03-25"]}),
]

QUESTIONS = ["When is the Linear issue ENG-11 due?", "What is the forecast close month of Brightfjord Labs?",
             "List every Linear issue assigned to Omar Singh. Give the issue keys.",
             'Which Linear issues assigned to Omar Singh have the status "Done"? Give the issue keys.',
             "List every GitHub pull request authored by Maya Chen. Give the pull request numbers.",
             "Which Linear issues are due between 2026-04-01 and 2026-04-14, inclusive? Give the issue keys.",
             "Who reviewed the pull request adding retry to badge sync?", "What is the zebra policy?"]


def _bank(tmp_path) -> FactBank:
    p = tmp_path / "fb.sqlite"
    assert B.build(p, DOCS)["check"]["ok"]
    return FactBank(p)


def _old_evidence(fb: FactBank, written, seeds, budget: int) -> str:
    """The evidence as v1 wrote it before the opt-in modes existed (``FactBank.evidence`` at commit 392c7c5)."""
    by_e = defaultdict(list)
    for w in written.values():
        by_e[w.entity].append(w)
    order = sorted(by_e, key=lambda e: -max(w.score for w in by_e[e]))
    parts, used = [], 0
    for e in order:
        lines = [f"[{fb.kinds.get(e, '?')}] {fb.names.get(e, e)}"] + [
            f"- {w.parameter.replace('_', ' ')}: {', '.join(w.values)[:400]}" for w in sorted(by_e[e], key=lambda w: w.parameter)]
        block = "\n".join(lines)
        if used + len(block) > budget:
            break
        parts.append(block)
        used += len(block) + 2
    for e, _ in seeds:
        if fb.kinds.get(e) != "document" or used >= budget:
            continue
        row = fb.con.execute("SELECT text FROM entities_fts WHERE id = ?", (e,)).fetchone()
        if row:
            text = row[0][: max(0, min(6000, budget - used - 50))]
            parts.append(f"[text] {fb.names.get(e, e)}\n{text}")
            used += len(text) + 60
    return "\n\n".join(parts)


def test_system_words_as_whole_words():
    assert systems_in("Which CI-driven rollout is late?") == ["google_drive"], "the old matcher, unchanged by default"
    assert systems_in("Which CI-driven rollout is late?", whole_words=True) == []
    assert systems_in("Which issue is due Apr 3?") == ["github"] and systems_in("Which issue is due Apr 3?", True) == []
    assert systems_in("Which PRs and emails mention the Google Drive folder?", True) == ["github", "gmail", "google_drive"]
    assert systems_in("the Linear-tracked GitHub pull requests", True) == ["linear", "github"]
    assert systems_in("nonlinear drivers", True) == [] and systems_in("nonlinear drivers") == ["linear", "google_drive"]


def test_whole_system_words_is_opt_in_on_the_bank(tmp_path):
    fb = _bank(tmp_path)
    q = "List every issue assigned to Omar Singh that is CI-driven. Give the issue keys."
    assert fb.named_systems(q) == ["google_drive"] and fb.ask(q).answer == "not found", "off: 'CI-driven' names Google Drive"
    fb.whole_system_words = True
    assert fb.named_systems(q) == [] and set(fb.ask(q).answer.split(", ")) == {"ENG-11", "ENG-12"}
    assert FactBank.whole_system_words is False, "set on the instance only"


def test_modes_off_reproduce_v1(tmp_path):
    fb = _bank(tmp_path)
    assert fb.brain is False and fb.whole_system_words is False
    for q in QUESTIONS:
        r = fb.ask(q)
        written, _, seeds = fb.run(q)
        assert r.evidence == _old_evidence(fb, written, seeds, 24_000)
        assert (r.answer, r.reason) == fb.answer(q, written, seeds) and not r.evidence.startswith("Answer:")
        assert replay(r.journal) == state_of(r.written)


def test_brain_changes_evidence_not_answers(tmp_path):
    fb = _bank(tmp_path)
    off = {q: fb.ask(q) for q in QUESTIONS}
    fb.brain = True
    for q in QUESTIONS:
        r = fb.ask(q)
        assert (r.answer, r.reason, r.journal) == (off[q].answer, off[q].reason, off[q].journal)
        assert len(r.evidence) <= 24_000
        if r.answer == "not found":
            assert not r.evidence.startswith("Answer:")
        else:
            assert r.evidence.startswith(f"Answer: {r.answer}\n- ")


def test_answer_first_with_its_facts(tmp_path):
    fb = _bank(tmp_path)
    fb.brain = True
    ev = fb.ask("When is the Linear issue ENG-11 due?").evidence
    assert ev.split("\n")[:2] == ["Answer: 2026-03-20", "- due date of ENG-11 (Fix keycard reader timeouts): 2026-03-20"]
    ev = fb.ask("What is the forecast close month of Brightfjord Labs?").evidence
    assert ev.split("\n")[:2] == ["Answer: 2026-04", "- forecast close month of Brightfjord Labs: 2026-04"]
    head = fb.ask('Which Linear issues assigned to Omar Singh have the status "Done"? Give the issue keys.').evidence.split("\n\n")[0]
    assert head == "Answer: ENG-12\n- assignee of ENG-12 (Rotate office wifi keys): Omar Singh; status: Done"
    head = fb.ask("List every Linear issue assigned to Omar Singh. Give the issue keys.").evidence.split("\n\n")[0]
    assert set(head.split("\n")[1:]) == {"- assignee of ENG-11 (Fix keycard reader timeouts): Omar Singh",
                                         "- assignee of ENG-12 (Rotate office wifi keys): Omar Singh"}
    head = fb.ask("Which Linear issues are due between 2026-04-01 and 2026-04-14, inclusive? Give the issue keys.").evidence.split("\n\n")[0]
    assert head == "Answer: ENG-12\n- due date of ENG-12 (Rotate office wifi keys): 2026-04-02"
    q = "Who reviewed the pull request adding retry to badge sync?"
    written, _, seeds = fb.run(q)
    assert fb.answer_facts(q, written, seeds) == ("Omar Singh", "reviewers of Add retry to badge sync",
                                                  ["reviewers of #4821 (Add retry to badge sync): Omar Singh"])


def test_answer_first_is_separate_from_the_brain_order(tmp_path):
    """Under a planner that prints its own answer: the brain order and keys without the engine's "Answer:" line; and the
    answer first without the brain order."""
    fb = _bank(tmp_path)
    assert fb.answer_first is None and fb.leads_with_answer is False
    fb.brain = True
    assert fb.leads_with_answer is True, "None follows brain"
    fb.answer_first = False
    assert fb.leads_with_answer is False
    for q in QUESTIONS:
        r = fb.ask(q)
        written, _, seeds = fb.run(q)
        assert r.evidence == fb.evidence(written, seeds, 24_000) and not re.search(r"^Answer:", r.evidence, re.M)
    q = "What is the forecast close month of Brightfjord Labs?"
    assert fb.ask(q).evidence.split("\n")[0] == "[document] Brightfjord Labs", "the largest single vote first, as with brain"
    ev = fb.ask("Which issues is Omar Singh working on?").evidence
    assert "- assignee of: ENG-11: Fix keycard reader timeouts, ENG-12: Rotate office wifi keys" in ev
    fb.brain, fb.answer_first = False, True
    r = fb.ask(q)
    written, _, seeds = fb.run(q)
    head = "Answer: 2026-04\n- forecast close month of Brightfjord Labs: 2026-04"
    assert r.evidence == (head + "\n\n" + _old_evidence(fb, written, seeds, 24_000 - len(head) - 2)).strip(), "v1 order after"
    assert FactBank.answer_first is None, "set on the instance only"


def test_blocks_ordered_by_largest_single_vote(tmp_path):
    fb = _bank(tmp_path)
    q = "What is the forecast close month of Brightfjord Labs?"
    written, _, seeds = fb.run(q)
    w = written[("person:maya chen", "participants_internal_of")]
    assert w.values == ["customer-success"] and len(w.facts) == 3, "three same-titled messages vote for one value"
    assert w.score > written[("doc:d4", "owner")].score > w.top, "summed, the person beats the account; by one vote, not"
    assert fb.ask(q).evidence.startswith("[person] Maya Chen"), "off: the busy poster is printed first"
    fb.brain = True
    blocks = [b.split("\n")[0] for b in fb.ask(q).evidence.split("\n\n")]
    assert blocks[1] == "[document] Brightfjord Labs" and blocks.index("[document] Brightfjord Labs") < blocks.index("[person] Maya Chen")


def test_relation_lines_show_keys(tmp_path):
    fb = _bank(tmp_path)
    q = "Which issues is Omar Singh working on?"
    written, _, seeds = fb.run(q)
    assert "- assignee of: Fix keycard reader timeouts, Rotate office wifi keys" in fb.evidence(written, seeds, 24_000)
    fb.brain = True
    ev = fb.evidence(written, seeds, 24_000)
    assert "- assignee of: ENG-11: Fix keycard reader timeouts, ENG-12: Rotate office wifi keys" in ev
    assert "- reviewers of: #4821: Add retry to badge sync" in ev
    assert "- assignee: Omar Singh" in ev, "a value whose entity has no key is shown as before"
    assert fb.key_label("doc:d3") == "#4821" and fb.key_label("person:omar singh") is None


def test_windows():
    text = "Title line\nsource: confluence\n" + " ".join(f"Sentence number {i} says something useful." for i in range(60))
    ws = windows(text)
    assert all(len(w) <= PASSAGE[1] for w in ws) and len(ws) > 3
    assert all(len(w) >= PASSAGE[0] for w in ws[1:-1]), "packed to at least the low mark, except at the edges"
    assert re.sub(r"\s+", " ", " ".join(ws)) == re.sub(r"\s+", " ", text), "nothing lost, nothing repeated"
    long = "word " * 400
    assert all(len(w) <= 600 for w in windows(long)) and re.sub(r"\s+", "", "".join(windows(long))) == re.sub(r"\s+", "", long)
    assert windows("") == [] and windows("One short line.") == ["One short line."]
    assert windows("A" * 250 + ".\nShort tail.", 300, 600) == ["A" * 250 + ".\nShort tail."], "a short last passage joins the one before"


def test_passages(tmp_path):
    fb = _bank(tmp_path)
    ps = fb.passages("How do I verify the telemetry mode on port 9100?")
    assert ps and set(ps[0]) == {"doc", "title", "text", "score"}
    assert ps[0]["doc"] == "doc:d5" and "port 9100" in ps[0]["text"] and ps[0]["title"] == "Telemetry runbook"
    assert all(len(p["text"]) <= PASSAGE[1] for p in ps)
    assert [p["score"] for p in ps] == sorted((p["score"] for p in ps), reverse=True), "best first"
    assert 0 < ps[0]["score"] <= 1
    small = fb.passages("How do I verify the telemetry mode on port 9100?", budget=700)
    assert sum(len(p["text"]) for p in small) <= 700 and small[0] == ps[0]
    assert len({p["doc"] for p in fb.passages("telemetry badge readers wifi", k_docs=1)}) == 1
    assert len({p["doc"] for p in fb.passages("telemetry badge readers wifi", k_docs=3)}) == 3
    docs = [p["doc"] for p in fb.passages("Who will replace the reader firmware on floor 3?")]
    assert "doc:d6" in docs, "an action item found by content brings in the meeting it came from"
    assert fb.passages("What does ENG-12 say?")[0]["doc"] == "doc:d2", "a document the question names comes in first"
    big = fb.passages("How do I verify the telemetry mode on port 9100?", size=(600, 1000))
    assert any(len(p["text"]) > 600 for p in big) and all(len(p["text"]) <= 1000 for p in big)
    assert fb.passages("zzzz qqqq") == []


def test_trained_bank_inherits_the_modes(tmp_path):
    from cie.factbank.learn import train
    from cie.factbank.trained import TrainedBank

    p = tmp_path / "fb2.sqlite"
    B.build(p, DOCS, text_facts=True)
    tb = TrainedBank(p)
    assert tb.brain is False and tb.whole_system_words is False
    q = "When is the Linear issue ENG-11 due?"
    off = tb.ask(q)
    tb.brain = True
    on = tb.ask(q)
    assert on.answer == off.answer and on.evidence.startswith("Answer: 2026-03-20\n- due date of ENG-11"), "no lessons: v1 in brain mode"
    qs = [{"id": "a", "group": "deadlines", "kind": "linear_due", "question": "When is the Linear issue \"Fix keycard reader timeouts\" due?",
           "expected": {"date": "2026-03-20"}, "gold_docs": ["d1"]},
          {"id": "b", "group": "deadlines", "kind": "linear_due", "question": "When is the Linear issue \"Rotate office wifi keys\" due?",
           "expected": {"date": "2026-04-02"}, "gold_docs": ["d2"]},
          {"id": "c", "group": "owners", "kind": "metadata", "question": "Who is assigned to the ticket about keycard reader timeouts?",
           "expected": {"value": "Omar Singh"}, "gold_docs": ["d1"]},
          {"id": "f", "group": "owners", "kind": "metadata", "question": "Who authored the pull request adding retry to badge sync?",
           "expected": {"value": "Maya Chen"}, "gold_docs": ["d3"]},
          {"id": "d", "group": "lists", "kind": "github_author",
           "question": "List every GitHub pull request authored by Maya Chen. Give the pull request numbers.",
           "expected": {"ids": ["4821"], "id_kind": "pr"}, "gold_docs": ["d3"]},
          {"id": "e", "group": "lists", "kind": "linear_assignee",
           "question": "List every Linear issue assigned to Omar Singh. Give the issue keys.",
           "expected": {"ids": ["ENG-11", "ENG-12"], "id_kind": "key"}, "gold_docs": ["d1", "d2"]}]
    tb = TrainedBank(p, train(TrainedBank(p), qs, log=lambda *_: None))
    for q in [x["question"] for x in qs] + ["What is the forecast close month of Brightfjord Labs?"]:
        tb.brain = False
        off = tb.ask(q)
        tb.brain = True
        on = tb.ask(q)
        assert on.answer == off.answer and off.evidence.startswith("Most likely answers, best first:\n")
        assert on.evidence.startswith(f"Answer: {on.answer}\n- ") or on.answer == "not found"
    q = "List every GitHub pull request authored by Maya Chen. Give the pull request numbers."
    assert tb.ask(q).evidence.split("\n\n")[0] == "Answer: #4821\n- author of #4821 (Add retry to badge sync): Maya Chen"
    q = "Who authored the pull request adding retry to badge sync?"
    head = tb.ask(q).evidence.split("\n\n")
    assert head[0].startswith(f"Answer: {tb.ask(q).answer}\n- ") and head[1].startswith("Other likely answers, best first:\n- ")
    for q in [x["question"] for x in qs] + ["What is the forecast close month of Brightfjord Labs?"]:
        tb.brain, tb.answer_first = False, None
        off = tb.ask(q)
        tb.brain, tb.answer_first = True, False  # as under ask_plans: the planner prints the only answer
        r = tb.ask(q)
        top = off.evidence.split("\n\n")[0]
        assert r.answer == off.answer and top.startswith("Most likely answers, best first:\n"), "v2's candidates, as v13 shows them"
        assert r.evidence == (top + "\n\n" + tb.evidence(r.written, r.seeds, 24_000 - len(top) - 2)).strip()
        assert not re.search(r"^(Answer|Other likely answers)", r.evidence, re.M)
    tb.brain, tb.answer_first = False, None
    tb.whole_system_words = True
    assert tb.list_ask("List every issue assigned to Omar Singh that is CI-driven.")[0] != "not found"
    tb.whole_system_words = False
    assert tb.list_ask("List every issue assigned to Omar Singh that is CI-driven.")[0] == "not found"
