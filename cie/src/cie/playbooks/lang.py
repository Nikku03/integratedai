"""The playbook rule language: one line per rule, read by people and written by models.

    needs_finance: amount_usd > 250
    may_pay: "manager" in approvals and (not needs_finance or "finance" in approvals) unless vendor_blocked

* ``and``, ``or``, ``not``, parentheses; ``a unless b`` is ``a and not b``, read as an exception.
* Comparisons ``> >= < <= == = !=`` between a fact and a constant (or two facts): numbers (``2500``, ``$2,500`` is
  not accepted: write ``2500``), dates (``2026-03-31``), text in quotes, ``true`` and ``false``.
* ``x in [...]`` and ``x not in [...]``: a text or number in a list of constants; ``"finance" in approvals``: a
  constant in a list-valued fact.
* A bare name is a yes/no fact or another rule.

``parse`` turns the text into a JSON tree; ``check`` validates it against the playbook's facts and rules (names,
types, a text fact's allowed values). Both report problems in words a drafter (person or model) can act on.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

FACT_TYPES = ("boolean", "number", "date", "text", "list")
CMP_OPS = (">", ">=", "<", "<=", "==", "!=", "in", "not in")
KEYWORDS = {"and", "or", "not", "in", "unless", "true", "false"}
NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<date>\d{4}-\d{2}-\d{2}(?![\d-]))
  | (?P<num>-?\d+(?:_\d{3})*(?:\.\d+)?(?![\w.]|,\d))
  | (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>>=|<=|==|!=|>|<|=)
  | (?P<punct>[()\[\],])
""", re.VERBOSE)


class RuleError(ValueError):
    """A rule that cannot be read or does not fit the playbook."""


def tokens(text: str) -> list[tuple[str, str]]:
    out, i = [], 0
    while i < len(text):
        m = _TOKEN.match(text, i)
        if m is None:
            bad = text[i:i + 12]
            hint = " (write amounts as plain numbers, e.g. 2500)" if bad[:1] in "$€£" or re.match(r"\d+,\d", bad) else ""
            raise RuleError(f"cannot read {bad!r} at character {i + 1}{hint}")
        kind = m.lastgroup or ""
        if kind != "ws":
            val = m.group()
            if kind == "name" and val.lower() in KEYWORDS:
                kind, val = "kw", val.lower()
            elif kind == "op" and val == "=":
                val = "=="
            out.append((kind, val))
        i = m.end()
    return out


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.t = tokens(text)
        self.i = 0

    def peek(self, k: int = 0) -> tuple[str, str] | None:
        return self.t[self.i + k] if self.i + k < len(self.t) else None

    def take(self) -> tuple[str, str]:
        tok = self.peek()
        if tok is None:
            raise RuleError("the rule ends too early")
        self.i += 1
        return tok

    def accept(self, kind: str, val: str | None = None) -> bool:
        tok = self.peek()
        if tok is not None and tok[0] == kind and (val is None or tok[1] == val):
            self.i += 1
            return True
        return False

    def expect(self, kind: str, val: str) -> None:
        if not self.accept(kind, val):
            got = self.peek()
            raise RuleError(f"expected {val!r} but found {got[1] if got else 'the end of the rule'!r}")

    def parse(self) -> dict[str, Any]:
        if not self.t:
            raise RuleError("the rule is empty")
        node = self.rule()
        if self.peek() is not None:
            raise RuleError(f"unexpected {self.peek()[1]!r} after a complete rule")  # type: ignore[index]
        return node

    def rule(self) -> dict[str, Any]:
        base = self.disj()
        exceptions = []
        while self.accept("kw", "unless"):
            exceptions.append(self.disj())
        return {"unless": [base, *exceptions]} if exceptions else base

    def disj(self) -> dict[str, Any]:
        parts = [self.conj()]
        while self.accept("kw", "or"):
            parts.append(self.conj())
        return {"or": parts} if len(parts) > 1 else parts[0]

    def conj(self) -> dict[str, Any]:
        parts = [self.neg()]
        while self.accept("kw", "and"):
            parts.append(self.neg())
        return {"and": parts} if len(parts) > 1 else parts[0]

    def neg(self) -> dict[str, Any]:
        if self.peek() == ("kw", "not") and self.peek(1) != ("kw", "in"):
            self.take()
            return {"not": self.neg()}
        return self.comp()

    def comp(self) -> dict[str, Any]:
        left = self.term()
        tok = self.peek()
        if tok is None:
            return left
        if tok[0] == "op":
            self.take()
            return {"cmp": tok[1], "l": left, "r": self.term()}
        if tok == ("kw", "in"):
            self.take()
            return {"cmp": "in", "l": left, "r": self.term()}
        if tok == ("kw", "not") and self.peek(1) == ("kw", "in"):
            self.take()
            self.take()
            return {"cmp": "not in", "l": left, "r": self.term()}
        return left

    def literal(self) -> dict[str, Any]:
        kind, val = self.take()
        if kind == "num":
            n = float(val.replace("_", ""))
            return {"const": int(n) if n.is_integer() else n, "type": "number"}
        if kind == "date":
            try:
                date.fromisoformat(val)
            except ValueError:
                raise RuleError(f"{val} is not a valid date") from None
            return {"const": val, "type": "date"}
        if kind == "str":
            return {"const": re.sub(r"\\(.)", r"\1", val[1:-1]), "type": "text"}
        if kind == "kw" and val in ("true", "false"):
            return {"const": val == "true", "type": "boolean"}
        raise RuleError(f"expected a value but found {val!r}")

    def term(self) -> dict[str, Any]:
        tok = self.peek()
        if tok is None:
            raise RuleError("the rule ends too early")
        if tok == ("punct", "("):
            self.take()
            node = self.rule()
            self.expect("punct", ")")
            return node
        if tok == ("punct", "["):
            self.take()
            items = []
            if not self.accept("punct", "]"):
                items.append(self.literal())
                while self.accept("punct", ","):
                    items.append(self.literal())
                self.expect("punct", "]")
            types = {x["type"] for x in items}
            if len(types) > 1:
                raise RuleError("a list must hold values of one kind (all text, all numbers or all dates)")
            return {"list": [x["const"] for x in items], "type": types.pop() if types else "text"}
        if tok[0] == "name":
            self.take()
            return {"ref": tok[1]}
        return self.literal()


def parse(text: str) -> dict[str, Any]:
    """The JSON tree of one rule's condition. Raises ``RuleError``."""
    return _Parser(text).parse()


# ---------------------------------------------------------------------------------------------- checking
def _kind(node: dict[str, Any], facts: dict[str, dict[str, Any]], rules: set[str]) -> str:
    """The type a term or condition yields: boolean, number, date, text, list, or list:<type> for a constant list."""
    if "fact" in node:
        return facts[node["fact"]]["type"]
    if "rule" in node:
        return "boolean"
    if "const" in node:
        return node["type"]
    if "list" in node:
        return "list:" + node["type"]
    return "boolean"


def check(node: dict[str, Any], facts: dict[str, dict[str, Any]], rules: set[str], *, top: bool = True) -> dict[str, Any]:
    """Resolve names (``ref`` -> ``fact`` or ``rule``) and check types. Returns the resolved tree; raises
    ``RuleError`` naming the first problem."""
    if "ref" in node:
        name = node["ref"]
        if name in facts or name in rules:
            out = {"fact": name} if name in facts else {"rule": name}
            if top:
                _need_boolean(out, facts, rules)
            return out
        near = sorted(n for n in list(facts) + list(rules) if n.split("_")[0] == name.split("_")[0])[:3]
        raise RuleError(f"'{name}' is not a fact of this playbook or a rule" + (f" (did you mean {', '.join(near)}?)" if near else ""))
    for op in ("and", "or", "unless"):
        if op in node:
            out = {op: [check(x, facts, rules, top=False) for x in node[op]]}
            for x in out[op]:
                _need_boolean(x, facts, rules)
            return out
    if "not" in node:
        x = check(node["not"], facts, rules, top=False)
        _need_boolean(x, facts, rules)
        return {"not": x}
    if "cmp" in node:
        left, right = check(node["l"], facts, rules, top=False), check(node["r"], facts, rules, top=False)
        _check_cmp(node["cmp"], left, right, facts, rules)
        return {"cmp": node["cmp"], "l": left, "r": right}
    if top:
        _need_boolean(node, facts, rules)
    return dict(node)


def _need_boolean(node: dict[str, Any], facts, rules) -> None:
    k = _kind(node, facts, rules)
    if k != "boolean":
        what = node.get("fact") or node.get("const") or node.get("list")
        raise RuleError(f"{what!r} is a {k.replace('list:', 'list of ')}, not a yes/no condition: compare it with something")


def _domain(facts, node) -> list[str]:
    return [str(v).casefold() for v in (facts.get(node.get("fact", ""), {}).get("values") or [])]


def _check_cmp(op: str, left: dict, right: dict, facts, rules) -> None:
    lk, rk = _kind(left, facts, rules), _kind(right, facts, rules)
    if "fact" not in left and "fact" not in right and "rule" not in left and "rule" not in right:
        raise RuleError("a comparison needs at least one fact")
    if op in ("in", "not in"):
        if rk.startswith("list:"):  # x in [a, b]
            item = rk.split(":", 1)[1]
            if lk != item and not (lk == "date" and item == "text"):
                raise RuleError(f"cannot look for a {lk} in a list of {item}")
            dom = _domain(facts, left)
            if dom and item == "text":
                bad = [v for v in right["list"] if str(v).casefold() not in dom]
                if bad:
                    raise RuleError(f"{', '.join(map(repr, bad))} is not one of the values of {left['fact']}: {', '.join(facts[left['fact']]['values'])}")
            return
        if rk == "list":  # "finance" in approvals
            if lk not in ("text", "number"):
                raise RuleError(f"cannot look for a {lk} in the list {right.get('fact')}")
            dom = _domain(facts, right)
            if dom and "const" in left and str(left["const"]).casefold() not in dom:
                raise RuleError(f"{left['const']!r} is not one of the values of {right['fact']}: {', '.join(facts[right['fact']]['values'])}")
            return
        raise RuleError(f"'{op}' needs a list on its right, not a {rk}")
    if lk.startswith("list") or rk.startswith("list"):
        raise RuleError(f"'{op}' cannot compare lists: use 'in' to test membership")
    pair = {lk, rk}
    if pair == {"date", "text"} and ("const" in left or "const" in right):
        raise RuleError("write dates without quotes, e.g. 2026-03-31")
    if len(pair) > 1:
        raise RuleError(f"cannot compare a {lk} with a {rk}")
    if op in (">", ">=", "<", "<=") and lk not in ("number", "date"):
        raise RuleError(f"'{op}' needs numbers or dates, not {lk}")
    for a, b in ((left, right), (right, left)):
        dom = _domain(facts, a)
        if dom and "const" in b and lk == "text" and str(b["const"]).casefold() not in dom:
            raise RuleError(f"{b['const']!r} is not one of the values of {a['fact']}: {', '.join(facts[a['fact']]['values'])}")


def names_in(node: dict[str, Any], kind: str) -> set[str]:
    """Every fact (``kind='fact'``) or rule (``'rule'``) a resolved tree reads."""
    out: set[str] = set()
    if kind in node:
        out.add(node[kind])
    for op in ("and", "or", "unless"):
        for x in node.get(op, []):
            out |= names_in(x, kind)
    if "not" in node:
        out |= names_in(node["not"], kind)
    if "cmp" in node:
        out |= names_in(node["l"], kind) | names_in(node["r"], kind)
    return out


def render(node: dict[str, Any]) -> str:
    """A resolved tree back as text (for explanations)."""
    if "fact" in node:
        return node["fact"]
    if "rule" in node:
        return node["rule"]
    if "const" in node:
        c = node["const"]
        return ("true" if c else "false") if isinstance(c, bool) else (f'"{c}"' if node["type"] == "text" else str(c))
    if "list" in node:
        return "[" + ", ".join(f'"{v}"' if node["type"] == "text" else str(v) for v in node["list"]) + "]"
    if "not" in node:
        return "not " + _wrap(node["not"])
    if "cmp" in node:
        return f"{render(node['l'])} {node['cmp']} {render(node['r'])}"
    for op in ("and", "or"):
        if op in node:
            return f" {op} ".join(_wrap(x) for x in node[op])
    if "unless" in node:
        return " unless ".join(_wrap(x) for x in node["unless"])
    return "?"


def _wrap(node: dict[str, Any]) -> str:
    s = render(node)
    return f"({s})" if any(k in node for k in ("and", "or", "unless")) else s
