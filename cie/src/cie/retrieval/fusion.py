"""Reciprocal rank fusion of ranked lists."""

from __future__ import annotations

from typing import Any


def rrf(lists: dict[str, list[tuple[Any, float]]], k: int = 60, weights: dict[str, float] | None = None) -> dict[Any, dict]:
    """Returns {id: {"score": fused, "sources": {name: (rank, raw)}}}."""
    weights = weights or {}
    out: dict[Any, dict] = {}
    for name, ranked in lists.items():
        w = weights.get(name, 1.0)
        for rank, (rid, raw) in enumerate(ranked, start=1):
            entry = out.setdefault(rid, {"score": 0.0, "sources": {}})
            entry["score"] += w / (k + rank)
            entry["sources"][name] = (rank, raw)
    return out
