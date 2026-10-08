"""A small language model reads the question (v7) and a glossary written once (v8): the parts that need no model."""

from __future__ import annotations

import json

from cie.factbank import reader as R


def test_the_menu_is_the_training_wordings_with_letters():
    m = R.menu()
    assert len(m) == 10 and "How many Linear issues are assigned to P?" in m
    assert all("{" not in w for w in m) and "Answer with the standard question only." in R.system_prompt()


def test_a_rewrite_is_used_only_if_it_keeps_what_it_must(tmp_path):
    cache = tmp_path / "rw.jsonl"
    q = 'Whoever picked up "send the SOC2 deck" in "Security review": which Linear tickets do they have? Keys only.'
    good = 'Which Linear issues are assigned to the person who took the action item "send the SOC2 deck" in the meeting "Security review"? Give the keys.'
    q2 = "how many linear tickets are on Maya Patel's plate?"
    cache.write_text("\n".join(json.dumps(r) for r in [{"question": q, "model": "x", "rewrite": good},
                                                       {"question": q2, "model": "x", "rewrite": "How many Linear issues are assigned to Maya?"}]) + "\n")
    rd = R.Reader(cache)  # every question is in the cache: no model is called
    got = rd.read(q, [])
    assert got["used_rewrite"] and got["asked"] == good and got["must_keep"] == ["send the SOC2 deck", "Security review"]
    got = rd.read(q2, ["Maya Patel"])
    assert not got["used_rewrite"] and got["asked"] == q2, "the rewrite dropped part of the name: the original is used"
    assert R.must_keep("Is PR #4821 linked to ENG-11?", []) == ["ENG-11", "#4821"]


def test_the_glossary_adds_the_standard_words_of_phrases_it_finds():
    g = R.Glossary([{"phrase": "on their plate", "kind": "field", "target": "assignee"},
                    {"phrase": "soonest", "kind": "combine", "target": "earliest"},
                    {"phrase": "put up the pr", "kind": "field", "target": "author"},
                    {"phrase": "nonsense", "kind": "field", "target": "not-a-target"}])
    assert len(g.entries) == 3, "an entry whose target is unknown is left out"
    q, k = g.words("Which ticket on their plate is due soonest? Key please.")
    assert {"assign", "first", "earliest", "soon"} <= q, "\"sooner\" is stemmed to \"soon\""
    assert g.words('Who put up the PR for ENG-12? See "on their plate"')[0] >= {"author", "wrote", "open"}
    assert g.words('See "on their plate" only') == (set(), set()), "phrases inside quoted titles are not read"
