"""The evidence audit's fact check and stages (no database)."""

from __future__ import annotations

from cie.eval import evidence_audit as ea

FACTS = ["The default per file upload size limit (max_file_size) for multipart uploads is 10 MiB.",
         "The default total request size limit (max_total_request_size) for multipart uploads is 50 MiB."]
GOLD = ["Multipart uploads: max_file_size defaults to 10 MiB per file upload; max_total_request_size defaults to 50 MiB "
        "per request (total request size limit)."]


def test_a_fact_must_sit_in_one_passage_with_its_numbers():
    assert ea.present(FACTS[0], GOLD[0])
    assert not ea.present(FACTS[0], GOLD[0].replace("10 MiB", "100 MiB")), "10 is not 100"
    assert not ea.present(FACTS[0], "Revenue in 2010 rose."), "a number inside another is not it"
    scattered = ["default upload size limit", "multipart file max", "10 MiB"]
    assert not ea.present_in_one(FACTS[0], [(t, ea._stems(t)) for t in scattered]), "words spread over passages do not count"


def test_stages():
    other = ["Quarterly planning notes for the GPU fleet."]
    c = ea.classify(FACTS, GOLD, ["d2"], {"d1"}, other, other)
    assert c["stage"] == "search_missed_document"
    c = ea.classify(FACTS, GOLD, ["d1"], {"d1"}, other, other)
    assert c["stage"] == "right_document_wrong_part"
    c = ea.classify(FACTS, GOLD, ["d1"], {"d1"}, GOLD + other, other)
    assert c["stage"] == "cut_before_model"
    c = ea.classify(FACTS, GOLD, ["d1"], {"d1"}, GOLD, GOLD, answer_text="Up to 10 MiB per file.")
    assert c["stage"] == "everything_reached_model" and c["checkable"] == 2 and c["in_answer"] == 0
    assert ea.classify(["Something no passage says."], GOLD, ["d1"], {"d1"}, GOLD, GOLD)["stage"] is None, "not checkable"
    s = ea.summarise([{**c, "status": "answered"}])
    assert s["stages"]["everything_reached_model"] == 1 and s["everything_reached_model_but_answer_missed_a_fact"] == 1


def test_the_model_view_follows_the_budget():
    items = [{"summary": "s", "detail": "x" * 3000}] * 10
    assert len(ea.model_view(items, 4000)) == 2 and all(len(p) == 1500 for p in ea.model_view(items, None))
