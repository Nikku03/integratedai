"""Drafting a playbook from a policy document with a language model.

The model is given the policy's text, the decision to make, and the facts the company's systems know about a request
(names, types, allowed values). It writes one line per rule in the playbook language, each with the policy's own
words as its quote. The draft is then checked by code: every name must be a given fact or a rule, every comparison
must fit the facts' types, and every quote is looked up in the policy. A draft with problems goes back to the model
once with the problems listed. Whatever comes out is only a draft: a person approves it before it decides anything.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from cie.playbooks import logic
from cie.playbooks.store import check_quotes

Generate = Callable[[str, str], str]  # (system, user) -> text

SYSTEM = ("You turn a company policy into decision rules that a program evaluates. You use only the facts you are "
          "given, write each rule in the rule language exactly, and copy the policy's words for each rule. "
          "You answer with JSON only.")

LANGUAGE = """Rule language (one rule per line, written as a JSON string):
- and, or, not, parentheses. "A unless B" means A, except when B holds.
- Comparisons: > >= < <= == != against numbers (write 2500, never $2,500 or 2,500), dates (2026-03-31, no quotes)
  or "quoted text".
- Lists: "finance" in approvals (a value in a list fact); expense_type in ["capital", "strategic"] (a fact in a list
  of values); not in.
- A bare name is a yes/no fact or another rule. Define helper rules for parts of the policy and use them by name.
- Use only the facts listed. If the policy depends on something none of the facts covers, leave it out of the rules
  and name it under "gaps"."""

EXAMPLE = """Example (a different, made-up policy):
Policy: "Shipments leave the warehouse only after QA sign-off. Orders above 10000 also need the regional manager.
Nothing ships to an embargoed country."
Facts: qa_signed (boolean); order_value (number); approvals (list, values: regional_manager, qa); country_embargoed (boolean)
Answer:
{"rules": [
 {"name": "needs_regional", "when": "order_value > 10000", "quote": "Orders above 10000 also need the regional manager"},
 {"name": "may_ship", "when": "qa_signed and (not needs_regional or \\"regional_manager\\" in approvals) unless country_embargoed",
  "quote": "Shipments leave the warehouse only after QA sign-off"}],
 "decision": "may_ship", "gaps": []}"""


def describe_facts(facts: dict[str, dict[str, Any]]) -> str:
    lines = []
    for name, f in facts.items():
        t = f.get("type", "text")
        vals = f.get("values")
        kind = t + (f", values: {', '.join(vals)}" if vals else "")
        lines.append(f"- {name} ({kind})" + (f": {f['description']}" if f.get("description") else ""))
    return "\n".join(lines)


def prompt(text: str, *, question: str, facts: dict[str, dict[str, Any]], decision: str, title: str = "") -> str:
    return (f"Policy document{f' ({title})' if title else ''}:\n<<<\n{text.strip()}\n>>>\n\n"
            f"Decision to write rules for: {question}\nName the rule that answers it \"{decision}\": yes means the request "
            f"may go ahead under this policy.\n\nFacts known about each request (use only these names):\n{describe_facts(facts)}\n\n"
            f"{LANGUAGE}\n\n{EXAMPLE}\n\nNow write the rules for the policy above. Every rule needs \"quote\": the policy's "
            f"exact words it comes from, copied. Answer with JSON only: "
            f'{{"rules": [{{"name": ..., "when": ..., "quote": ...}}], "decision": "{decision}", "gaps": [...]}}')


def parse(raw: str) -> dict[str, Any] | None:
    """The first JSON object in a model's answer (code fences and text around it are ignored)."""
    s = re.sub(r"```(?:json)?", "", raw or "")
    i = s.find("{")
    while i >= 0:
        try:
            obj, _ = json.JSONDecoder().raw_decode(s[i:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        i = s.find("{", i + 1)
    return None


@dataclass
class Draft:
    spec: dict[str, Any]
    problems: list[str]
    quotes: dict[str, bool]
    gaps: list[str] = field(default_factory=list)
    attempts: int = 0
    raw: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _spec(obj: dict[str, Any] | None, *, name: str, question: str, facts: dict[str, Any], decision: str) -> dict[str, Any]:
    rules = []
    for r in (obj or {}).get("rules") or []:
        if isinstance(r, dict):
            rules.append({"name": str(r.get("name") or "").strip(), "when": str(r.get("when") or "").strip(),
                          "quote": str(r.get("quote") or "").strip()[:1000]})
    return {"name": name, "question": question, "decision": str((obj or {}).get("decision") or decision).strip(), "facts": facts,
            "rules": rules}


def draft(generate: Generate, text: str, *, question: str, facts: dict[str, dict[str, Any]], decision: str = "may_proceed",
          name: str = "", title: str = "", repairs: int = 1) -> Draft:
    """Draft a playbook for ``question`` from the policy ``text``. ``facts`` is the playbook's fact schema."""
    user = prompt(text, question=question, facts=facts, decision=decision, title=title)
    raws: list[str] = []
    spec: dict[str, Any] = {}
    probs: list[str] = []
    obj: dict[str, Any] | None = None
    for attempt in range(repairs + 1):
        if attempt == 0:
            raw = generate(SYSTEM, user)
        else:
            raw = generate(SYSTEM, user + "\n\nYour previous answer:\n" + raws[-1][:6000] + "\n\nIt has these problems:\n"
                           + "\n".join(f"- {p}" for p in probs[:12]) + "\n\nWrite the corrected JSON only.")
        raws.append(raw or "")
        obj = parse(raw or "")
        spec = _spec(obj, name=name or title or decision, question=question, facts=facts, decision=decision)
        probs = logic.problems(spec) if obj is not None else ["the answer is not JSON"]
        if spec.get("decision") != decision and decision in {r["name"] for r in spec["rules"]}:
            spec["decision"] = decision
            probs = logic.problems(spec)
        if not probs:
            break
    gaps = [str(g)[:300] for g in (obj or {}).get("gaps") or [] if str(g).strip()][:20] if isinstance((obj or {}).get("gaps"), list) else []
    return Draft(spec=spec, problems=probs, quotes=check_quotes(spec, [text]), gaps=gaps, attempts=len(raws), raw=raws)


def from_provider(provider, max_tokens: int = 2000) -> Generate:
    """A ``Generate`` from a ``cie.agents.providers`` provider."""
    return lambda system, user: provider.complete(system, user, max_tokens=max_tokens).text
