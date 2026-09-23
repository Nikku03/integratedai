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
