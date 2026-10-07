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


def test_free_text_is_split_into_sentences():
    raw = {"key": "ENG-1", "title": "short", "description": "Fix the reader.\\nOwner: Sofia handles the rollout now.",
           "messages": "Ava: PR #20501 is ready for review today\nOmar: looks good to me, ship it"}
    got = L.texts_of(raw)
    assert "Owner: Sofia handles the rollout now." in got and "PR #20501 is ready for review today" in got
    assert "looks good to me, ship it" in got and not any(s.startswith("Ava:") for s in got)
    ref, vals = L.item_facts({"key": "eng-77", "assignee": "Sofia Martinez (PM)", "status": "In Review", "due_date": "2026-03-20"}, "linear")
    assert ref == "ENG-77" and vals["assignee"] == ["sofia martinez", "sofia"] and vals["status"] == ["in review"]


def test_words_go_with_the_kinds_of_value_found_next_to_them():
    sents = ["Sofia Martinez is handling the rollout this week.", "The deadline is 2026-03-05 for the launch.",
             "We moved it to In Review after lunch.", "The pool has 12 nodes and the warmup looks fine."] * 30
    assert L.mark("Sofia Martinez owns ENG-12, due Mar 5; 3 items moved to In Review.", {"sofia martinez"}, {"in review"}).split() == \
        ["zzwho", "owns", "ENG-12,", "due", "zzwhen", ";", "zznum", "items", "moved", "to", "zzstate", "."]
    ty = L.typing(sents, {"sofia martinez"}, {"in review"})
    assert ty.score("handl", "who", k=5, min_count=5) > ty.score("handl", "when", k=5, min_count=5)
    assert ty.score("deadline", "when", k=5, min_count=5) > ty.score("deadline", "who", k=5, min_count=5)
    assert ty.score("node", "num", k=5, min_count=5) > 0 and ty.score("lunch", "state", k=5, min_count=5) > 0


def test_lexicon_saves_and_loads(tmp_path):
    space = L.build_space(_corpus(), min_count=5, dim=8, log=lambda *_: None)
    ty = L.typing(["The deadline is 2026-03-05 for the launch.", "The launch looks fine and the pool is warm."] * 30, set(), set())
    lex = L.Lexicon(space, ty, {"documents": 3})
    lex.save(tmp_path / "lex.npz")
    again = L.Lexicon.load(tmp_path / "lex.npz")
    assert again.info == {"documents": 3} and again.space.vocab == space.vocab
    assert abs(again.space.sim("owns", "responsible") - space.sim("owns", "responsible")) < 1e-2
    assert again.kind_of("deadline", "when") == lex.kind_of("deadline", "when") > 0
