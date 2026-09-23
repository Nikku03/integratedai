"""LLM provider adapters with a single interface.

``complete(system, user, max_tokens) -> LLMResponse`` reporting real token
usage from the provider where available. Cost is an estimate from a price
table and is labelled as such. ``FakeProvider`` is for tests only and is named
so nothing can mistake it for a real model.

STATUS: the Anthropic/OpenAI/Gemini/local adapters are implemented against
their public APIs but were NOT exercised against live endpoints in this build
(no API keys available). See docs/KNOWN_LIMITATIONS.md.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from cie.core.settings import Settings, get_settings

# USD per 1M tokens (input, output). Estimates; update from provider pricing pages.
PRICES: dict[str, tuple[float, float]] = {  # USD per million tokens (input, output), list prices
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.3, 2.5),
}


@dataclass
class LLMResponse:
    text: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    cost_usd: float
    usage_is_estimate: bool = False
    raw: dict = field(default_factory=dict)
    stop_reason: str | None = None  # "refusal" when the model declined; callers must not treat that as an answer


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return round((tokens_in * pin + tokens_out * pout) / 1e6, 6)


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse: ...


class NoProvider:
    """Explicit 'no model configured'. Any call raises; nothing is faked."""

    name = "none"
    model = "none"

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        raise RuntimeError("No LLM provider configured (CIE_LLM_PROVIDER=none). Use strict extractive mode.")


class FakeProvider:
    """Scripted responses for tests. ``script`` maps a substring of the user
    prompt to a response, or a callable(system, user) -> str."""

    name = "fake"
    model = "fake-model"

    def __init__(self, script: dict[str, str] | Callable[[str, str], str] | None = None):
        self.script = script or {}
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        self.calls.append((system, user))
        if callable(self.script):
            text = self.script(system, user)
        else:
            text = next((v for k, v in self.script.items() if k in user), "")
        from cie.core.util import estimate_tokens

        ti, to = estimate_tokens(system + user), estimate_tokens(text)
        return LLMResponse(text, self.model, ti, to, 1.0, 0.0, usage_is_estimate=True)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str):
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int = 16000) -> LLMResponse:
        """One grounded completion. Current models think by default and thinking counts against
        ``max_tokens``, so the ceiling is generous (a short answer still costs only what it uses).
        A refusal is reported through ``stop_reason``, never as answer text. On models that
        support it, a declined request is re-run on a fallback model server-side (beta)."""
        t = time.perf_counter()
        kw = {"model": self.model, "max_tokens": max(max_tokens, 16000), "system": system, "messages": [{"role": "user", "content": user}]}
        try:
            r = self.client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
        except TypeError:  # an SDK release without the fallbacks parameter
            r = self.client.messages.create(**kw)
        text = "".join(b.text for b in r.content if getattr(b, "type", None) == "text")
        ti, to = r.usage.input_tokens, r.usage.output_tokens
        served_by = getattr(r, "model", None) or self.model
        return LLMResponse(text, served_by, ti, to, (time.perf_counter() - t) * 1000, estimate_cost(served_by, ti, to),
                           stop_reason=getattr(r, "stop_reason", None))


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key or "none", base_url=base_url or None)
        self.model = model
        if base_url:
            self.name = "local"

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        t = time.perf_counter()
        r = self.client.chat.completions.create(model=self.model, max_tokens=max_tokens,
                                                messages=[{"role": "system", "content": system},
                                                          {"role": "user", "content": user}])
        text = r.choices[0].message.content or ""
        ti = r.usage.prompt_tokens if r.usage else 0
        to = r.usage.completion_tokens if r.usage else 0
        return LLMResponse(text, self.model, ti, to, (time.perf_counter() - t) * 1000, estimate_cost(self.model, ti, to),
                           usage_is_estimate=r.usage is None)


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str):
        import httpx

        self.key = api_key
        self.model = model
        self.client = httpx.Client(timeout=120)

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        t = time.perf_counter()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {"system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0}}
        r = self.client.post(url, params={"key": self.key}, json=body)
        r.raise_for_status()
        j = r.json()
        text = "".join(p.get("text", "") for c in j.get("candidates", []) for p in c.get("content", {}).get("parts", []))
        um = j.get("usageMetadata", {})
        ti, to = um.get("promptTokenCount", 0), um.get("candidatesTokenCount", 0)
        return LLMResponse(text, self.model, ti, to, (time.perf_counter() - t) * 1000, estimate_cost(self.model, ti, to), raw=um)


def get_provider(settings: Settings | None = None) -> LLMProvider:
    s = settings or get_settings()
    if s.llm_provider == "anthropic":
        return AnthropicProvider(s.anthropic_api_key, s.llm_model)
    if s.llm_provider == "openai":
        return OpenAIProvider(s.openai_api_key, s.llm_model)
    if s.llm_provider == "local":
        return OpenAIProvider("none", s.llm_model, s.llm_base_url or "http://localhost:11434/v1")
    if s.llm_provider == "gemini":
        return GeminiProvider(s.gemini_api_key, s.llm_model)
    if s.llm_provider == "fake":
        return FakeProvider()
    return NoProvider()
