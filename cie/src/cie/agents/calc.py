"""A safe arithmetic evaluator for recalculating findings: numbers, + - * / // % **, parentheses, and min, max, abs,
round and days_between. No names other than the given inputs, no attribute access, no other calls."""

from __future__ import annotations

import ast
import operator
from datetime import date
from typing import Any

from cie.state import domain

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod, ast.Pow: operator.pow}
_UN = {ast.USub: operator.neg, ast.UAdd: operator.pos}
MAX_EXPONENT = 10
MAX_LENGTH = 500


class CalcError(ValueError):
    pass


def _days_between(a: Any, b: Any) -> float:
    da, db = domain.as_date(a), domain.as_date(b)
    if da is None or db is None:
        raise CalcError(f"days_between needs two dates, got {a!r} and {b!r}")
    return float((db - da).days)


FUNCS = {"min": min, "max": max, "abs": abs, "round": round, "days_between": _days_between}


def evaluate(expression: str, names: dict[str, Any]) -> float:
    if len(expression) > MAX_LENGTH:
        raise CalcError("expression too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise CalcError(f"not an expression: {e.msg}") from None

    def ev(n: ast.AST) -> Any:
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return n.value
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and domain.as_date(n.value) is not None:
            return n.value  # a literal date, only meaningful inside days_between
        if isinstance(n, ast.Name):
            if n.id not in names:
                raise CalcError(f"unknown name {n.id!r}")
            return names[n.id]
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            a, b = _num(ev(n.left)), _num(ev(n.right))
            if isinstance(n.op, ast.Pow) and abs(b) > MAX_EXPONENT:
                raise CalcError("exponent too large")
            try:
                return _BIN[type(n.op)](a, b)
            except ZeroDivisionError:
                raise CalcError("division by zero") from None
        if isinstance(n, ast.UnaryOp) and type(n.op) in _UN:
            return _UN[type(n.op)](_num(ev(n.operand)))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS and not n.keywords:
            args = [ev(a) for a in n.args]
            if n.func.id != "days_between":
                args = [_num(a) for a in args]
            if n.func.id == "round":
                if len(args) not in (1, 2) or (len(args) == 2 and not (0 <= args[1] <= 12 and args[1] == int(args[1]))):
                    raise CalcError("round takes a number and 0 to 12 digits")
                return round(args[0], int(args[1]) if len(args) == 2 else 0)
            if not args:
                raise CalcError(f"{n.func.id} needs arguments")
            return FUNCS[n.func.id](*args)
        raise CalcError(f"not allowed in a calculation: {type(n).__name__}")

    return _num(ev(tree))


def _num(x: Any) -> float:
    if isinstance(x, bool):
        raise CalcError("not a number: a boolean")
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, date):
        raise CalcError("a date is only allowed inside days_between")
    try:
        return float(x)
    except (TypeError, ValueError):
        raise CalcError(f"not a number: {x!r}") from None
