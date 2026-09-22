"""Objective decomposition into a task DAG.

``RulePlanner`` maps an objective to specialist tasks with dependencies using
keyword templates; it is deterministic and used by the simulation.
``LLMPlanner`` asks a provider for the same JSON structure and validates it
against the same schema. Both return ``TaskSpec`` lists; the head agent
persists them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from cie.agents.providers import LLMProvider


@dataclass
class TaskSpec:
    key: str  # local key for dependency references
    task_type: str
    title: str
    brief: str
    depends_on: list[str] = field(default_factory=list)
    risk_level: str = "low"
    priority: int = 5
    query: str | None = None  # retrieval query for the evidence packet


_FOCUS = {
    "legal": "termination notice period liability indemnity clause obligations deadlines compliance risk",
    "finance": "monthly fee penalty cap budget cost amount payment invoice spend",
    "operations": "timeline deadline plan milestones dependencies tasks rollout transition",
    "engineering": "requirements integration API system implementation technical dependencies prototype",
}


def _entities(objective: str) -> str:
    from cie.retrieval.exact import _capitalised_spans

    return " ".join(_capitalised_spans(objective))


_TEMPLATES = {
    "legal": (re.compile(r"\b(contract|agreement|clause|terminat|liabilit|complian|legal|obligation|notice|penalt|indemn|risk)\w*", re.I),
              "Review the governing clauses, obligations, deadlines and legal risks relevant to the objective. Cite clause numbers and pages."),
    "finance": (re.compile(r"\b(fee|cost|budget|price|payment|invoice|revenue|forecast|penalt|financ|amount|spend|saving)\w*", re.I),
                "Quantify the financial terms and exposures relevant to the objective: fees, caps, penalties, budgets. Cite every figure."),
    "operations": (re.compile(r"\b(plan|timeline|schedule|deadline|milestone|deliver|resource|renegotiat|transition|migrat|rollout)\w*", re.I),
                   "Produce the operational plan: ordered steps, owners, dates and dependencies, grounded in the evidence."),
    "engineering": (re.compile(r"\b(implement|build|system|integrat|api|code|architecture|prototype|technical|software|automation)\w*", re.I),
                    "Assess implementation requirements and technical dependencies; list requirements with sources."),
}


class RulePlanner:
    name = "rule_planner_v1"

    def plan(self, objective: str, forced_specialists: list[str] | None = None) -> list[TaskSpec]:
        specs: list[TaskSpec] = [TaskSpec("research", "research", "Gather evidence", "Collect the records and documents relevant to the "
                                          f"objective: '{objective}'. Return findings with citations and open questions.",
                                          risk_level="low", priority=1, query=objective)]
        chosen = forced_specialists or [name for name, (pat, _) in _TEMPLATES.items() if pat.search(objective)]
        if not chosen:
            chosen = ["operations"]
        for name in chosen:
            brief = _TEMPLATES[name][1]
            deps = ["research"]
            if name == "operations":
                deps += [c for c in ("legal", "finance") if c in chosen]
            if name == "engineering":
                deps += [c for c in ("operations",) if c in chosen]
            risk = "high" if name in ("legal", "finance") else "medium"
            specs.append(TaskSpec(name, name, f"{name.title()} analysis", f"{brief} Objective: '{objective}'.",
                                  depends_on=deps, risk_level=risk, priority=3,
                                  query=f"{_entities(objective)} {_FOCUS[name]}".strip()))
        specs.append(TaskSpec("synthesis", "synthesis", "Synthesize final answer",
                              f"Combine verified specialist outputs into one answer with evidence and uncertainty for: '{objective}'.",
                              depends_on=[s.key for s in specs], risk_level="medium", priority=9, query=objective))
        return specs


class LLMPlanner:
    name = "llm_planner_v1"
    PROMPT = ("Decompose the objective into 3-7 tasks for specialists: research, finance, legal, operations, engineering. "
              "Return JSON: {\"tasks\":[{\"key\":str,\"task_type\":one of the specialists,\"title\":str,\"brief\":str,"
              "\"depends_on\":[keys],\"risk_level\":\"low|medium|high\"}]}. Always start with a research task and end with "
              "a task_type 'synthesis' depending on all others. Output JSON only.")

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def plan(self, objective: str, forced_specialists: list[str] | None = None) -> list[TaskSpec]:
        r = self.provider.complete(self.PROMPT, f"Objective: {objective}", max_tokens=1200)
        try:
            data = json.loads(r.text[r.text.index("{"):r.text.rindex("}") + 1])
            specs = [TaskSpec(t["key"], t["task_type"], t["title"], t["brief"], list(t.get("depends_on", [])),
                              t.get("risk_level", "medium"), query=objective) for t in data["tasks"]]
            keys = {s.key for s in specs}
            for s in specs:
                s.depends_on = [d for d in s.depends_on if d in keys and d != s.key]
            if not any(s.task_type == "synthesis" for s in specs):
                specs.append(TaskSpec("synthesis", "synthesis", "Synthesize final answer", "Combine outputs.", [s.key for s in specs], query=objective))
            return specs
        except Exception:
            return RulePlanner().plan(objective, forced_specialists)  # fall back, and say so via name
