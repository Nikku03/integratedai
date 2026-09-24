"""The Anthropic provider without network access: refusal handling, fallback parameter, thinking headroom."""

from __future__ import annotations

from types import SimpleNamespace

from cie.agents.providers import AnthropicProvider, LLMResponse, estimate_cost


class _Messages:
    def __init__(self, response, accept_fallbacks=True):
        self.response, self.accept_fallbacks, self.calls = response, accept_fallbacks, []

    def create(self, **kw):
        if not self.accept_fallbacks and "fallbacks" in kw:
            raise TypeError("unexpected keyword argument 'fallbacks'")
        self.calls.append(kw)
        return self.response


def _provider(response, accept_fallbacks=True):
    p = AnthropicProvider.__new__(AnthropicProvider)
    p.model = "claude-opus-5"
    beta = _Messages(response, accept_fallbacks)
    plain = _Messages(response)
    p.client = SimpleNamespace(beta=SimpleNamespace(messages=beta), messages=plain)
    return p, beta, plain


def _resp(text="Answer [1].", stop="end_turn"):
    return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
                           usage=SimpleNamespace(input_tokens=1000, output_tokens=200), stop_reason=stop, model="claude-opus-5")


def test_text_only_from_text_blocks_and_generous_ceiling():
    p, beta, _ = _provider(_resp())
    r = p.complete("sys", "user", max_tokens=700)
    assert r.text == "Answer [1]." and r.stop_reason == "end_turn"
    call = beta.calls[0]
    assert call["max_tokens"] >= 16000, "thinking counts against max_tokens; a 700-token ceiling would truncate answers"
    assert call["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in call["betas"]
    assert "temperature" not in call, "sampling parameters are rejected by current models"
    assert r.cost_usd == estimate_cost("claude-opus-5", 1000, 200) == round((1000 * 5 + 200 * 25) / 1e6, 6)


def test_refusal_is_reported_not_answered_and_old_sdk_falls_back():
    p, _, plain = _provider(_resp(text="", stop="refusal"), accept_fallbacks=False)
    r = p.complete("sys", "user")
    assert r.stop_reason == "refusal" and plain.calls, "an SDK without the fallbacks parameter uses the plain endpoint"


def test_assisted_answer_falls_back_to_extractive_on_refusal():
    import uuid

    from cie.retrieval.answer import assisted
    from cie.retrieval.intent import classify
    from cie.retrieval.packet import EvidencePacket

    class Declines:
        def complete(self, system, user, max_tokens=16000):
            return LLMResponse("", "claude-opus-5", 10, 0, 1.0, 0.0, stop_reason="refusal")

    item = {"id": str(uuid.uuid4()), "kind": "record", "type": "metric", "summary": "The monthly fee is USD 140,000.",
            "detail": "The monthly fee is USD 140,000.", "score": 0.9, "support": 0.9, "citations": [{"page_no": 1}]}
    pk = EvidencePacket(tenant_id=uuid.uuid4(), query="What is the monthly fee?", items=[item])
    res = assisted(pk, classify("What is the monthly fee?"), Declines())
    assert res.mode.startswith("extractive") and "declined" in res.mode


def _items(n: int, size: int = 400):
    import uuid

    return [{"id": str(uuid.uuid4()), "kind": "record", "type": "fact", "summary": f"Item {i} says the canary ramp waits 30 minutes.",
             "detail": "x" * size, "score": 0.9 - i / 100, "support": 0.9, "citations": [{"page_no": 1}]} for i in range(1, n + 1)]


def test_local_model_is_deterministic_bounded_and_free():
    from cie.agents.providers import OpenAIProvider

    calls = []

    class Completions:
        def create(self, **kw):
            calls.append(kw)
            msg = SimpleNamespace(content="The ramp waits 30 minutes [1].")
            return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                                   usage=SimpleNamespace(prompt_tokens=900, completion_tokens=12))

    p = OpenAIProvider.__new__(OpenAIProvider)
    p.model, p.local, p.max_output_tokens, p.evidence_budget_chars, p.name = "llama3.1:8b", True, 1024, 24000, "local"
    p.client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    r = p.complete("sys", "user", max_tokens=16000)
    assert calls[0]["temperature"] == 0 and calls[0]["max_tokens"] == 1024, "sized for thinking models, capped for a local one"
    assert r.cost_usd == 0.0 and r.cost_known and r.tokens_in == 900


def test_small_model_gets_budgeted_evidence_and_tolerant_citations():
    import uuid

    from cie.retrieval.answer import assisted
    from cie.retrieval.intent import classify
    from cie.retrieval.packet import EvidencePacket

    seen = {}

    class Llama:
        evidence_budget_chars = 1200

        def complete(self, system, user, max_tokens=16000):
            seen["user"] = user
            return LLMResponse("The canary ramp waits 30 minutes between steps [1, 2].", "llama", 500, 20, 1.0, 0.0)

    pk = EvidencePacket(tenant_id=uuid.uuid4(), query="How long does the canary ramp wait?", items=_items(10))
    res = assisted(pk, classify(pk.query), Llama())
    assert "[3]" not in seen["user"] and "[2]" in seen["user"], "only the best items that fit the budget are sent"
    assert res.mode == "assisted" and [c["n"] for c in res.citations] == [1, 2], "'[1, 2]' cites two items"


def test_unverifiable_model_answer_falls_back_to_the_evidence():
    import uuid

    from cie.retrieval.answer import assisted
    from cie.retrieval.intent import classify
    from cie.retrieval.packet import EvidencePacket

    class Uncited:
        def complete(self, system, user, max_tokens=16000):
            return LLMResponse("Probably about half an hour, based on what I know.", "llama", 500, 20, 1.0, 0.0)

    pk = EvidencePacket(tenant_id=uuid.uuid4(), query="How long does the canary ramp wait?", items=_items(3))
    res = assisted(pk, classify(pk.query), Uncited())
    assert res.mode == "extractive (model answer not verifiable)" and res.status == "answered" and res.citations
    assert res.unsupported_claims and res.tokens_in == 500


def test_uncited_bullets_are_attributed_but_invented_numbers_are_not():
    import uuid

    from cie.retrieval.answer import assisted
    from cie.retrieval.intent import classify
    from cie.retrieval.packet import EvidencePacket

    items = [{"id": str(uuid.uuid4()), "kind": "record", "type": "fact", "summary": "Upload limits",
              "detail": "Multipart uploads are limited to 10 MiB per file and 50 MiB per request, configurable in the API config.",
              "score": 0.9, "support": 0.9, "citations": [{"page_no": 1}]},
             {"id": str(uuid.uuid4()), "kind": "record", "type": "fact", "summary": "Unrelated", "detail": "The canary ramp waits 30 minutes.",
              "score": 0.5, "support": 0.5, "citations": [{"page_no": 1}]}]

    class Bullets:
        def complete(self, system, user, max_tokens=16000):
            return LLMResponse("Based on the evidence, the limits are:\n\n* Multipart uploads: 10 MiB per file limit\n"
                               "* Multipart uploads: 50 MiB per request limit\n* Multipart uploads: 200 MiB per tenant limit", "llama", 500, 40, 1.0, 0.0)

    pk = EvidencePacket(tenant_id=uuid.uuid4(), query="What are the multipart upload limits?", items=items)
    res = assisted(pk, classify(pk.query), Bullets())
    assert res.mode == "assisted" and res.citations_attributed == 2
    assert "10 MiB per file limit [1]" in res.answer and "50 MiB" in res.answer
    assert "200" not in res.answer and any("200" in u for u in res.unsupported_claims), "a number no item states is never kept"


def test_claims_join_labels_and_bare_citations_and_miscounted_items_are_corrected():
    import uuid

    from cie.retrieval.answer import _claims, assisted
    from cie.retrieval.intent import classify
    from cie.retrieval.packet import EvidencePacket

    assert _claims("The new metric is:\n`stream.timebox_finalized`\n[2].") == ["The new metric is: `stream.timebox_finalized` [2]."]
    items = [{"id": str(uuid.uuid4()), "kind": "record", "type": "fact", "summary": f"Item {i}", "detail": d, "score": 0.9,
              "support": 0.9, "citations": [{"page_no": 1}]}
             for i, d in enumerate(["The canary ramp waits 30 minutes.", "SRE added the stream.timebox_finalized metric to track "
                                    "streaming sessions finalized at the time limit."], start=1)]

    class Miscounts:
        def complete(self, system, user, max_tokens=16000):
            return LLMResponse("SRE added the stream.timebox_finalized metric to track streaming sessions finalized at the time limit [1].",
                               "llama", 500, 30, 1.0, 0.0)

    pk = EvidencePacket(tenant_id=uuid.uuid4(), query="Which metric tracks streaming sessions finalized at the time limit?", items=items)
    res = assisted(pk, classify(pk.query), Miscounts())
    assert res.answer.endswith("time limit [2]."), res.answer
    assert [c["n"] for c in res.citations] == [2] and res.citations_attributed == 1
