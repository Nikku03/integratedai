from __future__ import annotations

import random

import pytest

from cie.memory.lexicon import CAPACITY, LEAD_SET, SYMBOL_BASE, Lexicon, build, coverage

CORPUS = [
    "The company must pay the supplier within 30 days after delivery unless the inspection fails.",
    "Rahul said the company must pay the supplier within 45 days after delivery.",
    "Rahul asked whether the supplier can ship within 10 days (after the audit).",
    "The company must pay the supplier within 60 days after delivery, unless Rahul objects.",
    "Supplier invoices: the company must pay within 30 days after delivery.",
] * 6


def test_round_trips_are_exact_on_awkward_text():
    lex = build(CORPUS, min_count=3)
    odd = ["", "   ", "\n\n", "the", "the ", " the", "the  supplier", "café — naïve 日本 the supplier", "supplier (after delivery)",
           "THE COMPANY", "the\tcompany", "after delivery,unless", "x" * 5000, "Company must pay supplier $50,000 within 30 days after "
           "delivery unless inspection fails.", "within days", "the company\n"]
    for t in CORPUS + odd:
        assert lex.decode(lex.encode(t)) == t, repr(t)
    rng = random.Random(0)
    words = ["the", "company", "must", "pay", "supplier", "Rahul", " ", "  ", ",", "\n", "30", "é", "(", "after", "delivery"]
    for _ in range(300):
        t = "".join(rng.choice(words) for _ in range(rng.randint(0, 40)))
        assert lex.decode(lex.encode(t)) == t, repr(t)


def test_frequent_phrases_become_entries_and_names_stay_text():
    lex = build(CORPUS, min_count=3)
    assert any(" " in e.strip() for e in lex.entries), "phrases, not only words"
    assert "the company must pay " in [e.lower() for e in lex.entries] or "company must pay the " in [e.lower() for e in lex.entries]
    assert not any("rahul" in e.lower() for e in lex.entries), "a word written with a capital nearly every time is a name"
    assert not any(c.isdigit() for e in lex.entries for c in e), "numbers stay as they are"
    no_supplier = build(CORPUS, exclude=["supplier"], min_count=3)
    assert not any("supplier" in e.lower() for e in no_supplier.entries)
    enc = lex.encode(CORPUS[0])
    assert len(enc) < len(CORPUS[0].encode()) and any(b in LEAD_SET for b in enc)
    assert 0.5 < coverage(lex, CORPUS) <= 1.0


def test_symbols_legend_and_files(tmp_path):
    lex = build(CORPUS, min_count=3)
    s = lex.symbols(CORPUS[0])
    assert any(ord(c) >= SYMBOL_BASE for c in s) and "30" in s
    legend = lex.legend([CORPUS[0]])
    assert all(" = " in line for line in legend.splitlines()) and "supplier" in legend
    path = tmp_path / "lexicon.json"
    lex.save(path)
    again = Lexicon.load(path)
    assert again.entries == lex.entries and again.version == lex.version and again.encode(CORPUS[1]) == lex.encode(CORPUS[1])
    with pytest.raises(ValueError):
        Lexicon(["w"] * (CAPACITY + 1))
