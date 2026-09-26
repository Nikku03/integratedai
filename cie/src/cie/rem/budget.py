"""Separate, configurable limits for one exploration, and the reason it stopped.

Depth, visited nodes, returned tokens, database calls and wall-clock time are limited independently.
When any limit is reached the result is marked ``incomplete`` with that limit as the stopping reason,
and its frontier is saved so the caller can resume it. No limit is derived from the graph size: the
module makes no claim about how exploration cost grows with N.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


def est_tokens(text: str) -> int:
    """Token estimate used for budgets: about four characters per token (a heuristic, not a tokenizer)."""
    return max(1, (len(text) + 3) // 4)


@dataclass
class Limits:
    max_depth: int = 3
    max_visited: int = 400
    max_tokens: int = 4000
    max_db_calls: int = 120
    max_ms: int = 5000

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Limits:
        d = d or {}
        return cls(**{k: int(v) for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Usage:
    depth: int = 0
    visited: int = 0
    tokens: int = 0
    db_calls: int = 0
    ms: float = 0.0
    model_calls: int = 0


@dataclass
class Budget:
    limits: Limits = field(default_factory=Limits)
    usage: Usage = field(default_factory=Usage)
    started: float = field(default_factory=time.perf_counter)

    def tick(self, db_calls: int) -> None:
        self.usage.db_calls = db_calls
        self.usage.ms = (time.perf_counter() - self.started) * 1000

    def exceeded(self) -> str | None:
        """The first exploration limit that has been reached (tokens are checked when evidence is packed)."""
        if self.usage.visited >= self.limits.max_visited:
            return "budget:max_visited"
        if self.usage.db_calls >= self.limits.max_db_calls:
            return "budget:max_db_calls"
        if self.usage.ms >= self.limits.max_ms:
            return "budget:max_ms"
        return None

    def report(self) -> dict[str, Any]:
        return {"limits": asdict(self.limits), "used": {k: (round(v, 1) if isinstance(v, float) else v)
                                                        for k, v in asdict(self.usage).items()}}
