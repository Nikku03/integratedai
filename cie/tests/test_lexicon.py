"""Word meanings learned from documents, with no language model: the word space, field anchoring, and their use in plans."""

from __future__ import annotations

import random

from cie.factbank import lexicon as L


def _corpus():
    rng = random.Random(3)
    out = []
    for _ in range(400):
        who = rng.choice(["sofia", "omar", "liam", "maya"])
        out.append(L.tokens(f"{who} owns the rollout and will drive it this week"))
        out.append(L.tokens(f"{who} is responsible for the rollout and will drive it this week"))
        out.append(L.tokens(f"the deadline for the migration is friday so ship before {rng.choice(['noon', 'eod'])}"))
        out.append(L.tokens(f"the due date for the migration is friday so ship before {rng.choice(['noon', 'eod'])}"))
        out.append(L.tokens(f"latency on the {rng.choice(['gpu', 'cpu'])} pool spiked after the kernel change"))
    return out


def test_words_used_alike_end_up_close():
    space = L.build_space(_corpus(), min_count=5, window=4, dim=8, log=lambda *_: None)
    assert space.sim("owns", "responsible") > space.sim("owns", "latency")
    assert space.sim("deadline", "due") > space.sim("deadline", "gpu")
    near = space.neighbours("deadline", ["due", "latency", "gpu", "rollout"], k=1, floor=0.0)
    assert near and near[0][0] == "due"
    assert space.sim("unseen", "unseen") == 1.0 and space.sim("unseen", "due") == 0.0


def test_sentences_that_state_a_field_anchor_their_words():
    facts = {"ENG-12": {"assignee": ["sofia martinez", "sofia"], "status": ["in review"], "due_date": ["2026-03-20"]},
             "pr:20501": {"author": ["ava chen", "ava"]}}
    sents = ["Sofia is handling ENG-12 this sprint.", "ENG-12 is handled by Sofia now.", "ENG-12 moved to in review today.",
             "PR #20501 was opened by Ava yesterday.", "ENG-12 is due March 20, 2026 per the plan.", "ENG-12 came up in standup again.",
             "We looked at ENG-12 and the plan.", "Nothing about tickets here at all."]
    an = L.anchor(sents, facts)
    assert an.n == 7, "only sentences that name a known ticket or pull request count"
    assert an.field["assignee"] == 2 and an.field["author"] == 1 and an.field["due_date"] == 1 and an.field["status"] == 1
    assert an.score("handl", "assignee", min_count=2) > an.score("plan", "assignee", min_count=2) == 0.0
    again = L.Anchors(an.to_json(min_count=1))
    assert again.score("handl", "assignee", min_count=2) == an.score("handl", "assignee", min_count=2)


def test_free_text_is_split_into_sentences():
    raw = {"key": "ENG-1", "title": "short", "description": "Fix the reader.\\nOwner: Sofia handles the rollout now.",
           "messages": "Ava: PR #20501 is ready for review today\nOmar: looks good to me, ship it"}
    got = L.texts_of(raw)
    assert "Owner: Sofia handles the rollout now." in got and "PR #20501 is ready for review today" in got
    assert "looks good to me, ship it" in got and not any(s.startswith("Ava:") for s in got)
    ref, vals = L.item_facts({"key": "eng-77", "assignee": "Sofia Martinez (PM)", "status": "In Review", "due_date": "2026-03-20"}, "linear")
    assert ref == "ENG-77" and vals["assignee"] == ["sofia martinez", "sofia"] and vals["status"] == ["in review"]


def test_lexicon_saves_and_loads(tmp_path):
    space = L.build_space(_corpus(), min_count=5, dim=8, log=lambda *_: None)
    an = L.anchor(["Sofia is handling ENG-12 this sprint."] * 4, {"ENG-12": {"assignee": ["sofia"]}})
    lex = L.Lexicon(space, an, {"documents": 3})
    lex.save(tmp_path / "lex.npz")
    again = L.Lexicon.load(tmp_path / "lex.npz")
    assert again.info == {"documents": 3} and again.space.vocab == space.vocab
    assert abs(again.space.sim("owns", "responsible") - space.sim("owns", "responsible")) < 1e-2
    assert again.field_anchor({"handl"}, "assignee_of") == again.field_anchor({"handl"}, "assignee")
    assert again.field_sim({"deadline"}, {"due"}) > again.field_sim({"gpu"}, {"due"})
