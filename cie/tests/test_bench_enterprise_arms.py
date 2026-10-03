from __future__ import annotations

from types import SimpleNamespace

import pytest

from cie.core.settings import get_settings
from cie.eval import bench_enterprise as be


class _Session:
    def execute(self, *a, **k):
        return None

    def rollback(self):
        return None


class _Retriever:
    """Records what each question was asked with: the retrieval settings and the evidence the model may read."""

    def __init__(self):
        self.settings = get_settings()
        self.calls = []

    def answer(self, query, principal, scope, *, mode, provider, **cfg):
        self.calls.append({"mode": mode, "cfg": cfg, "evidence_chars": getattr(provider, "evidence_budget_chars", None)})
        result = SimpleNamespace(tokens_in=10, tokens_out=2, cost_usd=0.0, cost_known=True, mode="assisted", status="answered",
                                 answer="An answer [1].", citations_attributed=0)
        return result, SimpleNamespace(packet=SimpleNamespace(items=[]), trace={})


def test_read_more_arm_reads_more_and_passes_only_retrieval_settings_on(monkeypatch, tmp_path):
    monkeypatch.setattr(be, "assisted_provider", lambda settings: SimpleNamespace(evidence_budget_chars=24000, model="llama"))
    r = _Retriever()
    q = [{"question_id": "qst_0001", "question": "What is the limit?", "expected_doc_ids": ["d1"], "question_type": "basic"}]
    rep = be.evaluate(_Session(), r, None, None, q, {}, arms={be.ASSISTED_ARM: {"mode": "assisted"}, be.READ_MORE_ARM: dict(be.READ_MORE)},
                      out=tmp_path, log=lambda *_: None)
    default, more = r.calls
    assert default["cfg"] == {} and default["evidence_chars"] == 24000
    assert more["cfg"] == {"token_budget": 24000, "max_records": 200, "expand_documents": 10}, "evidence_chars is the model's, not retrieval's"
    assert more["evidence_chars"] == 60000
    assert rep[be.READ_MORE_ARM]["overall"]["llm"]["evidence_chars"] == 60000
    assert (tmp_path / "answers_hybrid_graph_rem_composed_answers_read_more.jsonl").exists()


def test_read_more_leaves_a_long_context_model_reading_the_whole_packet(monkeypatch, tmp_path):
    monkeypatch.setattr(be, "assisted_provider", lambda settings: SimpleNamespace(evidence_budget_chars=None, model="claude"))
    r = _Retriever()
    q = [{"question_id": "qst_0002", "question": "Who owns it?", "expected_doc_ids": [], "question_type": "info_not_found"}]
    be.evaluate(_Session(), r, None, None, q, {}, arms={be.READ_MORE_ARM: dict(be.READ_MORE)}, out=tmp_path, log=lambda *_: None)
    assert r.calls[0]["evidence_chars"] is None


def test_read_more_needs_composed_answers():
    with pytest.raises(SystemExit):
        be.main(["--root", "x", "--read-more"])
