"""Deterministic checks for exhaustive mode: the same record always gives the same answer.

A check is ``{"field": "promised_date", "op": "gt", "value": "2026-10-15"}``, or ``{"all": [...]}``,
``{"any": [...]}``, ``{"not": {...}}``. Fields are record attributes; ``name``, ``key``, ``type``,
``verification`` and ``version`` are the record's own. Operators: eq, ne, lt, le, gt, ge, in, not_in, contains,
exists, missing. Numbers compare as numbers and ISO dates as dates. A record whose field is missing or cannot be
compared is *unreadable* for that check: counted separately, never as a match or a non-match.
"""

from __future__ import annotations

from typing import Any

from cie.state import domain

OPS = ("eq", "ne", "lt", "le", "gt", "ge", "in", "not_in", "contains", "exists", "missing")
OWN = ("name", "key", "type", "verification", "version", "review_status")


class Unreadable(Exception):
    pass


def validate(check: dict[str, Any]) -> None:
    if not isinstance(check, dict) or not check:
        raise ValueError("a check is a non-empty object")
    if "all" in check or "any" in check:
        for c in check.get("all", check.get("any")):
            validate(c)
        return
    if "not" in check:
        validate(check["not"])
        return
    if check.get("op") not in OPS or not check.get("field"):
        raise ValueError(f"a check needs a field and an op among {OPS}")


def _value(node, field: str) -> Any:
    f = field.removeprefix("attrs.")
    if field in OWN:
        return getattr(node, field)
    if f not in (node.attrs or {}):
        raise KeyError(f)
    return node.attrs[f]


def _number(x: Any) -> float | None:
    if isinstance(x, bool):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _date(x: Any):
    return domain.as_date(x) if len(str(x)) >= 10 else None


def _comparable(a: Any, b: Any) -> tuple[Any, Any]:
    """Numbers as numbers, dates as dates, text as text; a number or date against anything else is unreadable."""
    na, nb = _number(a), _number(b)
    if na is not None and nb is not None:
        return na, nb
    da, db = _date(a), _date(b)
    if da is not None and db is not None:
        return da, db
    if na is None and nb is None and da is None and db is None and isinstance(a, str) and isinstance(b, str):
        return a, b
    raise Unreadable(f"cannot compare {a!r} with {b!r}")


def evaluate(check: dict[str, Any], node) -> bool:
    """True or False; raises ``Unreadable`` when the record does not carry what the check needs."""
    if "all" in check:
        return all(evaluate(c, node) for c in check["all"])
    if "any" in check:
        results, unreadable = [], None
        for c in check["any"]:
            try:
                results.append(evaluate(c, node))
            except Unreadable as e:
                unreadable = e
        if any(results):
            return True
        if unreadable is not None:
            raise unreadable
        return False
    if "not" in check:
        return not evaluate(check["not"], node)
    op, field = check["op"], check["field"]
    try:
        v = _value(node, field)
    except KeyError:
        if op in ("exists", "missing"):
            return op == "missing"
        raise Unreadable(f"{field} is missing") from None
    if op == "exists":
        return v is not None
    if op == "missing":
        return v is None
    target = check.get("value")
    if op in ("in", "not_in"):
        hit = str(v) in {str(x) for x in (target or [])}
        return hit if op == "in" else not hit
    if op == "contains":
        return str(target).lower() in str(v).lower()
    if v is None:
        raise Unreadable(f"{field} is empty")
    try:
        a, b = _comparable(v, target)
    except Unreadable:
        if op in ("eq", "ne"):
            return (str(v) == str(target)) == (op == "eq")
        raise
    return {"eq": a == b, "ne": a != b, "lt": a < b, "le": a <= b, "gt": a > b, "ge": a >= b}[op]
