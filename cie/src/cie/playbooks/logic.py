"""Deciding with a playbook: yes, no or unknown, a proof of every step, and the facts that would settle it.

**Three values.** A fact that is not known is *unknown*, never false. ``and``, ``or``, ``not`` and ``unless`` follow
strong Kleene logic: ``false and unknown`` is false, ``true and unknown`` is unknown, ``true or unknown`` is true.
A comparison with an unknown side is unknown. So a decision is yes or no only when the known facts settle it
whatever the unknown ones turn out to be.

**Goal-directed.** Only the decision's rule and the rules and facts it reads are evaluated, and evaluation stops as
soon as a part is settled (``and`` at the first false part, ``or`` at the first true one). Each fact and rule is
evaluated once per decision; nothing is kept between decisions.

**Proof.** Every step (a fact read, a comparison, a connective, a rule) is recorded with its inputs and value.
``verify`` checks a proof against the approved playbook and the recorded facts without trusting the evaluator:
each step must be the right node of the right rule, read its children in order, stop only where the logic allows
and have the value its inputs give. A changed value, a skipped part or a step from another version is rejected.

**What is missing.** For an unknown decision, ``investigate`` tries each unknown fact the decision depends on at
the values the rules test it against, one fact at a time, and reports which value gives yes, which gives no.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from cie.playbooks.lang import FACT_TYPES, KEYWORDS, NAME, RuleError, check, names_in, parse

DEFAULT_BUDGET = 20000
_OTHER = "\x00another value"  # a text value no rule names


class PlaybookError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class Part:
    when: str
    tree: dict[str, Any]
    quote: str = ""


@dataclass
class Rule:
    name: str
    parts: list[Part]


@dataclass
class Playbook:
    name: str
    question: str
    decision: str
    facts: dict[str, dict[str, Any]]
    rules: dict[str, Rule]
    spec: dict[str, Any]
    hash: str

    def node(self, path: str) -> dict[str, Any] | None:
        """The condition node at ``rule/part.child.child...``."""
        try:
            rule, rest = path.split("/", 1)
            idx = [int(x) for x in rest.split(".")]
            node = self.rules[rule].parts[idx[0]].tree
            for i in idx[1:]:
                node = children(node)[i]
            return node
        except (KeyError, IndexError, ValueError):
            return None


def children(node: dict[str, Any]) -> list[dict[str, Any]]:
    for op in ("and", "or", "unless"):
        if op in node:
            return node[op]
    if "not" in node:
        return [node["not"]]
    return []


def kind_of(node: dict[str, Any]) -> str:
    for k in ("and", "or", "unless", "not", "cmp", "fact", "rule", "const"):
        if k in node:
            return k
    return "?"


def spec_hash(spec: dict[str, Any]) -> str:
    body = {"facts": spec.get("facts") or {}, "decision": spec.get("decision"),
            "rules": [{"name": r.get("name"), "when": r.get("when"), "quote": r.get("quote") or ""} for r in spec.get("rules") or []]}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def problems(spec: dict[str, Any]) -> list[str]:
    """Every problem with a playbook spec, in words a drafter can act on; empty when it compiles."""
    try:
        compile_playbook(spec)
    except PlaybookError as e:
        return e.problems
    return []


def compile_playbook(spec: dict[str, Any]) -> Playbook:
    """Check and compile a spec: ``{"name", "question", "decision", "facts": {name: {"type", "description",
    "values", "from"}}, "rules": [{"name", "when", "quote"}]}``. A rule named twice is the ``or`` of its parts.
    Raises ``PlaybookError`` listing every problem."""
    errs: list[str] = []
    if not isinstance(spec, dict):
        raise PlaybookError(["the playbook must be a JSON object"])
    facts_in = spec.get("facts") or {}
    if not isinstance(facts_in, dict) or not facts_in:
        errs.append("'facts' must name at least one fact, e.g. {\"amount_usd\": {\"type\": \"number\"}}")
        facts_in = {}
    facts: dict[str, dict[str, Any]] = {}
    for name, f in facts_in.items():
        f = f if isinstance(f, dict) else {"type": f}
        t = str(f.get("type") or "").lower()
        t = {"bool": "boolean", "yes/no": "boolean", "string": "text", "int": "number", "float": "number", "array": "list"}.get(t, t)
        if not NAME.match(str(name)) or name in KEYWORDS:
            errs.append(f"fact name {name!r} must be lower case letters, digits and _ (not a keyword)")
            continue
        if t not in FACT_TYPES:
            errs.append(f"fact {name}: type must be one of {', '.join(FACT_TYPES)}, not {f.get('type')!r}")
            continue
        values = f.get("values")
        if values is not None and (not isinstance(values, list) or t not in ("text", "list")):
            errs.append(f"fact {name}: 'values' is a list, for a text or list fact")
            values = None
        facts[name] = {**{k: v for k, v in f.items() if k not in ("type", "values")}, "type": t,
                       **({"values": [str(v) for v in values]} if values else {})}
    for name, f in facts.items():
        src = f.get("from")
        if src is not None:
            if not isinstance(src, dict) or not src.get("entity") or not src.get("key") or not src.get("field"):
                errs.append(f"fact {name}: 'from' needs entity, key and field")
                continue
            for ref in re.findall(r"\{([^}]*)\}", str(src["key"])):
                if ref not in facts or facts[ref]["type"] not in ("text", "number") or ref == name:
                    errs.append(f"fact {name}: the key refers to {{{ref}}}, which must be another text or number fact")
    rules_in = spec.get("rules") or []
    if not isinstance(rules_in, list) or not rules_in:
        errs.append("'rules' must hold at least one rule, e.g. {\"name\": \"may_pay\", \"when\": \"amount_usd <= 250\"}")
        rules_in = []
    rule_names = []
    for i, r in enumerate(rules_in):
        if not isinstance(r, dict):
            errs.append(f"rule {i + 1} must be an object with name and when")
            continue
        n = str(r.get("name") or "")
        if not NAME.match(n) or n in KEYWORDS:
            errs.append(f"rule {i + 1}: name {n!r} must be lower case letters, digits and _ (not a keyword)")
        elif n in facts:
            errs.append(f"rule {n}: a fact has the same name")
        elif n not in rule_names:
            rule_names.append(n)
    rules: dict[str, Rule] = {n: Rule(n, []) for n in rule_names}
    for r in rules_in:
        if not isinstance(r, dict) or str(r.get("name") or "") not in rules:
            continue
        n, when = r["name"], str(r.get("when") or "").strip()
        try:
            tree = check(parse(when), facts, set(rule_names))
        except RuleError as e:
            errs.append(f"rule {n} ({when!r}): {e}")
            continue
        rules[n].parts.append(Part(when=when, tree=tree, quote=str(r.get("quote") or "")))
    decision = str(spec.get("decision") or "")
    if decision not in rules:
        errs.append(f"'decision' must name one of the rules ({', '.join(rule_names) or 'none yet'}), not {decision!r}")
    # rules may not depend on themselves through other rules
    deps = {n: set().union(*[names_in(p.tree, "rule") for p in rule.parts]) if rule.parts else set() for n, rule in rules.items()}
    state: dict[str, int] = {}

    def visit(n: str, trail: list[str]) -> None:
        if state.get(n) == 2:
            return
        if state.get(n) == 1:
            errs.append("rules depend on each other in a circle: " + " -> ".join(trail[trail.index(n):] + [n]))
            return
        state[n] = 1
        for d in sorted(deps.get(n, ())):
            visit(d, trail + [n])
        state[n] = 2

    for n in rules:
        visit(n, [])
    if errs:
        raise PlaybookError(errs)
    return Playbook(name=str(spec.get("name") or decision), question=str(spec.get("question") or ""), decision=decision,
                    facts=facts, rules=rules, spec=spec, hash=spec_hash(spec))


# ---------------------------------------------------------------------------------------------- facts
def normalize(ftype: str, value: Any) -> tuple[Any, str]:
    """A fact value in its canonical form (dates as ISO text) and a note when it could not be read. ``None``: unknown."""
    if value is None:
        return None, ""
    if ftype == "boolean":
        if isinstance(value, bool):
            return value, ""
        s = str(value).strip().lower()
        if s in ("true", "yes", "y", "1"):
            return True, ""
        if s in ("false", "no", "n", "0"):
            return False, ""
        return None, "" if s in ("", "unknown") else f"not yes or no: {value!r}"
    if ftype == "number":
        if isinstance(value, bool):
            return None, f"not a number: {value!r}"
        if isinstance(value, (int, float)):
            return value, ""
        s = re.sub(r"[\s$,€£]", "", str(value))
        if s in ("", "unknown"):
            return None, ""
        try:
            n = float(s)
        except ValueError:
            return None, f"not a number: {value!r}"
        return int(n) if n.is_integer() else n, ""
    if ftype == "date":
        if isinstance(value, datetime):
            return value.date().isoformat(), ""
        if isinstance(value, date):
            return value.isoformat(), ""
        s = str(value).strip()
        if s in ("", "unknown"):
            return None, ""
        try:
            return date.fromisoformat(s[:10]).isoformat(), ""
        except ValueError:
            return None, f"not a date (YYYY-MM-DD): {value!r}"
    if ftype == "list":
        if isinstance(value, str):
            value = [x for x in value.split(",")] if value.strip() else []
        if not isinstance(value, (list, tuple, set)):
            return None, f"not a list: {value!r}"
        return sorted({str(x).strip() for x in value if str(x).strip()}, key=str.casefold), ""
    s = str(value).strip()
    return (s if s and s.lower() != "unknown" else None), ""


@dataclass
class Fact:
    value: Any  # canonical; None: unknown
    source: dict[str, Any] = field(default_factory=lambda: {"kind": "given"})
    note: str = ""


class FactSource:
    """Where a decision's facts come from. ``get`` is called at most once per fact and decision."""

    def get(self, name: str, spec: dict[str, Any], lookup: Callable[[str], Any]) -> Fact:
        raise NotImplementedError


class Given(FactSource):
    """Facts supplied with the request (a form, an action's payload)."""

    def __init__(self, values: Mapping[str, Any] | None = None):
        self.values = dict(values or {})

    def get(self, name, spec, lookup) -> Fact:
        v, note = normalize(spec["type"], self.values.get(name))
        return Fact(v, {"kind": "given"} if name in self.values else {"kind": "not_given"}, note)


class Overlay(FactSource):
    """``base`` with some facts set to trial values (for ``investigate``)."""

    def __init__(self, base: FactSource, values: Mapping[str, Any]):
        self.base, self.values = base, dict(values)

    def get(self, name, spec, lookup) -> Fact:
        if name in self.values:
            return Fact(self.values[name], {"kind": "trial"})
        return self.base.get(name, spec, lookup)


# ---------------------------------------------------------------------------------------------- logic
def k_and(vals: list[bool | None]) -> bool | None:
    if any(v is False for v in vals):
        return False
    return True if all(v is True for v in vals) else None


def k_or(vals: list[bool | None]) -> bool | None:
    if any(v is True for v in vals):
        return True
    return False if all(v is False for v in vals) else None


def k_not(v: bool | None) -> bool | None:
    return None if v is None else not v


def _fold(v: Any) -> Any:
    return v.casefold() if isinstance(v, str) else v


def compare(op: str, a: Any, b: Any) -> bool | None:
    """A comparison of canonical values; unknown when either side is unknown or they cannot be compared."""
    if a is None or b is None:
        return None
    if op in ("in", "not in"):
        if not isinstance(b, list):
            return None
        hit = _fold(a) in {_fold(x) for x in b}
        return hit if op == "in" else not hit
    if isinstance(a, bool) != isinstance(b, bool) or isinstance(a, list) or isinstance(b, list):
        return None
    if isinstance(a, (int, float)) != isinstance(b, (int, float)):
        return None
    a, b = _fold(a), _fold(b)
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    try:
        return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[op]
    except TypeError:
        return None


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Decision:
    playbook: str
    playbook_hash: str
    goal: str
    result: bool | None
    proof: dict[str, Any]
    inputs: dict[str, Any]  # every fact read: canonical value or None
    sources: dict[str, dict[str, Any]]
    why: list[str] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    rules_evaluated: int = 0
    facts_read: int = 0

    @property
    def answer(self) -> str:
        return {True: "yes", False: "no", None: "unknown"}[self.result]

    def to_dict(self) -> dict[str, Any]:
        return {"playbook": self.playbook, "playbook_hash": self.playbook_hash, "goal": self.goal, "answer": self.answer,
                "why": self.why, "missing": self.missing, "inputs": self.inputs, "sources": self.sources, "notes": self.notes,
                "rules_evaluated": self.rules_evaluated, "facts_read": self.facts_read, "proof": self.proof}


class _Run:
    def __init__(self, pb: Playbook, source: FactSource, budget: int):
        self.pb, self.source, self.budget = pb, source, budget
        self.steps: list[dict[str, Any]] = []
        self.fact_step: dict[str, int] = {}
        self.rule_step: dict[str, int] = {}
        self.facts: dict[str, Fact] = {}
        self.active: set[str] = set()

    def add(self, step: dict[str, Any]) -> int:
        if len(self.steps) >= self.budget:
            raise BudgetExceeded(f"stopped after {self.budget} steps")
        step["id"] = len(self.steps)
        self.steps.append(step)
        return step["id"]

    def value(self, sid: int) -> Any:
        return self.steps[sid]["value"]

    def lookup(self, name: str) -> Any:
        """A fact's value, for another fact's ``from`` key."""
        return self.value(self.fact(name))

    def fact(self, name: str) -> int:
        if name not in self.fact_step:
            if name in self.active:
                raise BudgetExceeded(f"fact {name} refers to itself")
            self.active.add(name)
            f = self.source.get(name, self.pb.facts[name], self.lookup)
            self.active.discard(name)
            self.facts[name] = f
            self.fact_step[name] = self.add({"kind": "fact", "name": name, "type": self.pb.facts[name]["type"], "value": f.value})
        return self.fact_step[name]

    def rule(self, name: str) -> int:
        if name not in self.rule_step:
            if name in self.active:
                raise BudgetExceeded(f"rule {name} depends on itself")
            self.active.add(name)
            args = []
            for k, part in enumerate(self.pb.rules[name].parts):
                args.append(self.cond(part.tree, f"{name}/{k}"))
                if self.value(args[-1]) is True:
                    break
            self.active.discard(name)
            self.rule_step[name] = self.add({"kind": "rule", "name": name, "args": args, "value": k_or([self.value(a) for a in args])})
        return self.rule_step[name]

    def operand(self, node: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        if "fact" in node:
            sid = self.fact(node["fact"])
            return self.value(sid), {"step": sid}
        if "rule" in node:
            sid = self.rule(node["rule"])
            return self.value(sid), {"step": sid}
        if "list" in node:
            return list(node["list"]), {"list": list(node["list"])}
        return node["const"], {"const": node["const"]}

    def cond(self, node: dict[str, Any], path: str) -> int:
        k = kind_of(node)
        if k == "fact":
            return self.fact(node["fact"])
        if k == "rule":
            return self.rule(node["rule"])
        if k == "const":
            return self.add({"kind": "const", "node": path, "value": node["const"]})
        if k == "cmp":
            (a, x), (b, y) = self.operand(node["l"]), self.operand(node["r"])
            return self.add({"kind": "cmp", "node": path, "op": node["cmp"], "args": [x, y], "value": compare(node["cmp"], a, b)})
        if k == "not":
            sid = self.cond(node["not"], path + ".0")
            return self.add({"kind": "not", "node": path, "args": [sid], "value": k_not(self.value(sid))})
        stop = True if k == "or" else False
        args, vals = [], []
        for i, child in enumerate(children(node)):
            args.append(self.cond(child, f"{path}.{i}"))
            v = self.value(args[-1])
            vals.append(k_not(v) if k == "unless" and i > 0 else v)
            if vals[-1] is stop:
                break
        return self.add({"kind": k, "node": path, "args": args, "value": k_or(vals) if k == "or" else k_and(vals)})


def evaluate(pb: Playbook, source: FactSource | Mapping[str, Any], goal: str | None = None, *, budget: int = DEFAULT_BUDGET,
             explore: bool = True) -> Decision:
    """Decide ``goal`` (the playbook's decision by default) from the facts in ``source``."""
    goal = goal or pb.decision
    if goal not in pb.rules:
        raise PlaybookError([f"no rule named {goal!r}"])
    if not isinstance(source, FactSource):
        source = Given(source)
    run = _Run(pb, source, budget)
    notes = []
    try:
        run.rule(goal)
        result = run.value(run.rule_step[goal])
    except BudgetExceeded as e:
        result, notes = None, [str(e)]
    proof = {"playbook_hash": pb.hash, "goal": goal, "result": result, "steps": run.steps}
    d = Decision(playbook=pb.name, playbook_hash=pb.hash, goal=goal, result=result, proof=proof,
                 inputs={n: f.value for n, f in run.facts.items()}, sources={n: f.source for n, f in run.facts.items()},
                 notes=notes + [f"{n}: {f.note}" for n, f in run.facts.items() if f.note],
                 rules_evaluated=len(run.rule_step), facts_read=len(run.fact_step))
    d.why = why(pb, proof)
    if result is None and explore and not notes:
        d.missing = investigate(pb, source, goal, open_facts(proof), budget=budget)
    return d


# ---------------------------------------------------------------------------------------------- verification
def verify(pb: Playbook, proof: dict[str, Any], inputs: Mapping[str, Any] | None = None) -> list[str]:
    """Problems with ``proof`` as a decision of ``pb`` from ``inputs`` (the recorded fact values); empty when every
    step checks. Recomputes each step from its inputs; does not run the evaluator."""
    errs: list[str] = []
    if proof.get("playbook_hash") != pb.hash:
        return ["the proof was made with another version of the playbook"]
    steps = proof.get("steps") or []
    if not isinstance(steps, list):
        return ["the proof has no steps"]
    seen_fact: dict[str, int] = {}
    seen_rule: dict[str, int] = {}

    def val(i: int) -> Any:
        return steps[i]["value"]

    def arg_ok(sid: Any, here: int) -> bool:
        return isinstance(sid, int) and not isinstance(sid, bool) and 0 <= sid < here

    def child_ok(child: dict[str, Any], sid: int, path: str) -> str:
        st = steps[sid]
        k = kind_of(child)
        if k == "fact":
            return "" if st.get("kind") == "fact" and st.get("name") == child["fact"] else f"should read fact {child['fact']}"
        if k == "rule":
            return "" if st.get("kind") == "rule" and st.get("name") == child["rule"] else f"should use rule {child['rule']}"
        return "" if st.get("node") == path and st.get("kind") == k else f"should be the {k} at {path}"

    def operand_value(node: dict[str, Any], a: Any, here: int) -> tuple[Any, str]:
        if not isinstance(a, dict):
            return None, "an operand is malformed"
        if "fact" in node or "rule" in node:
            sid = a.get("step")
            if not arg_ok(sid, here):
                return None, "an operand points to a later or missing step"
            bad = child_ok(node, sid, "")
            return val(sid), bad
        if "list" in node:
            return node["list"], "" if a.get("list") == node["list"] else "a list differs from the rule's"
        same = a.get("const") == node["const"] and isinstance(a.get("const"), bool) == isinstance(node["const"], bool)
        return node["const"], "" if same else "a value differs from the rule's"

    for i, st in enumerate(steps):
        if not isinstance(st, dict) or st.get("id") != i:
            errs.append(f"step {i}: out of order")
            continue
        kind, value = st.get("kind"), st.get("value")
        where = f"step {i} ({kind} {st.get('name') or st.get('node') or ''})".replace(" )", ")")
        if kind == "fact":
            name = st.get("name")
            if name not in pb.facts:
                errs.append(f"{where}: no such fact")
                continue
            if name in seen_fact:
                errs.append(f"{where}: read twice")
            seen_fact[name] = i
            if inputs is not None:
                want, _ = normalize(pb.facts[name]["type"], inputs.get(name))
                if json.dumps(want, default=str) != json.dumps(value, default=str):
                    errs.append(f"{where}: value {value!r} is not the recorded {want!r}")
            continue
        if kind == "rule":
            name = st.get("name")
            if name not in pb.rules:
                errs.append(f"{where}: no such rule")
                continue
            if name in seen_rule:
                errs.append(f"{where}: evaluated twice")
            seen_rule[name] = i
            args, parts = st.get("args") or [], pb.rules[name].parts
            if not all(arg_ok(a, i) for a in args) or not args or len(args) > len(parts):
                errs.append(f"{where}: its parts are missing or point ahead")
                continue
            for k, (a, part) in enumerate(zip(args, parts, strict=False)):
                if bad := child_ok(part.tree, a, f"{name}/{k}"):
                    errs.append(f"{where}: part {k} {bad}")
            vals = [val(a) for a in args]
            if any(v is True for v in vals[:-1]) or (len(args) < len(parts) and vals[-1] is not True):
                errs.append(f"{where}: stops too early or too late")
            if value != k_or(vals):
                errs.append(f"{where}: value {value!r} does not follow from its parts")
            continue
        node = pb.node(str(st.get("node") or ""))
        if node is None or kind_of(node) != kind:
            errs.append(f"{where}: not a {kind} of the approved rules")
            continue
        if kind == "const":
            if value != node["const"]:
                errs.append(f"{where}: value differs from the rule")
            continue
        if kind == "cmp":
            args = st.get("args") or []
            if st.get("op") != node["cmp"] or len(args) != 2:
                errs.append(f"{where}: not the rule's comparison")
                continue
            (a, ea), (b, eb) = operand_value(node["l"], args[0], i), operand_value(node["r"], args[1], i)
            if ea or eb:
                errs.append(f"{where}: {ea or eb}")
            elif value != compare(node["cmp"], a, b):
                errs.append(f"{where}: {a!r} {node['cmp']} {b!r} is {compare(node['cmp'], a, b)!r}, not {value!r}")
            continue
        args, kids = st.get("args") or [], children(node)
        if not args or len(args) > len(kids) or not all(arg_ok(a, i) for a in args):
            errs.append(f"{where}: its parts are missing or point ahead")
            continue
        for k, (a, child) in enumerate(zip(args, kids, strict=False)):
            if bad := child_ok(child, a, f"{st['node']}.{k}"):
                errs.append(f"{where}: part {k} {bad}")
        if kind == "not":
            if value != k_not(val(args[0])):
                errs.append(f"{where}: value does not follow")
            continue
        vals = [val(a) for a in args]
        if kind == "unless":
            vals = [vals[0]] + [k_not(v) for v in vals[1:]]
        stop = True if kind == "or" else False
        if any(v is stop for v in vals[:-1]) or (len(args) < len(kids) and vals[-1] is not stop):
            errs.append(f"{where}: stops too early or too late")
        if value != (k_or(vals) if kind == "or" else k_and(vals)):
            errs.append(f"{where}: value {value!r} does not follow from its parts")
    goal = proof.get("goal")
    if goal not in seen_rule:
        errs.append(f"the proof never decides {goal!r}")
    elif steps[seen_rule[goal]]["value"] != proof.get("result"):
        errs.append("the stated result is not the goal's value")
    return errs


# ---------------------------------------------------------------------------------------------- explanation
def _leaf(pb: Playbook, steps: list[dict[str, Any]], st: dict[str, Any]) -> str:
    def show(a: dict[str, Any]) -> str:
        if "step" in a:
            s = steps[a["step"]]
            return f"{s['name']} ({_show(s['value'])})"
        return _show(a.get("const", a.get("list")))

    if st["kind"] == "fact":
        return f"{st['name']} is {_show(st['value'])}"
    if st["kind"] == "cmp":
        a, b = st["args"]
        return f"{show(a)} {st['op']} {show(b)}: {_show(st['value'])}"
    return f"{st.get('node')}: {_show(st['value'])}"


def _show(v: Any) -> str:
    if v is None:
        return "unknown"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, list):
        return "[" + ", ".join(map(str, v)) + "]" if v else "none"
    return str(v)


def decisive(steps: list[dict[str, Any]], st: dict[str, Any]) -> list[int]:
    """The arguments of a step that settle its value."""
    args, v, kind = st.get("args") or [], st["value"], st["kind"]
    if kind in ("fact", "const", "cmp"):
        return []
    if kind == "not":
        return args
    if v is None:
        return [a for a in args if steps[a]["value"] is None]
    if kind in ("or", "rule"):
        return args[-1:] if v is True else args
    if v is False:  # and / unless: the part that made it false
        return args[-1:]
    return args


def why(pb: Playbook, proof: dict[str, Any], limit: int = 14) -> list[str]:
    """The steps that settle the decision, from the goal down: each rule with its condition and quote, then the
    facts and comparisons it rests on."""
    steps = proof.get("steps") or []
    goal = proof.get("goal")
    root = next((s for s in reversed(steps) if s.get("kind") == "rule" and s.get("name") == goal), None)
    if root is None:
        return []
    out: list[str] = []
    seen: set[int] = set()

    def walk(st: dict[str, Any], depth: int) -> None:
        if st["id"] in seen or len(out) >= limit:
            return
        seen.add(st["id"])
        if st["kind"] == "rule":
            parts = pb.rules[st["name"]].parts[:len(st["args"])]  # parts are tried in order until one holds
            part = parts[-1] if st["value"] is True or len(pb.rules[st["name"]].parts) == 1 else None
            text = part.when if part else " | ".join(p.when for p in parts)
            quote = f' — "{part.quote[:160]}"' if part and part.quote else ""
            out.append(f"{'  ' * depth}{st['name']}: {_show(st['value'])} ({text}){quote}")
        elif st["kind"] in ("fact", "cmp", "const"):
            out.append("  " * depth + _leaf(pb, steps, st))
            if st["kind"] == "cmp":
                for a in st["args"]:
                    if "step" in a and steps[a["step"]]["kind"] == "rule":
                        walk(steps[a["step"]], depth + 1)
            return
        for a in decisive(steps, st):
            walk(steps[a], depth + (1 if st["kind"] == "rule" else 0))

    walk(root, 0)
    return out


def open_facts(proof: dict[str, Any]) -> list[str]:
    """The unknown facts an unknown decision depends on: reached from the goal through unknown steps only."""
    steps = proof.get("steps") or []
    goal = proof.get("goal")
    root = next((s for s in reversed(steps) if s.get("kind") == "rule" and s.get("name") == goal), None)
    out: list[str] = []
    seen: set[int] = set()

    def walk(st: dict[str, Any]) -> None:
        if st["id"] in seen or st["value"] is not None:
            return
        seen.add(st["id"])
        if st["kind"] == "fact":
            out.append(st["name"]) if st["name"] not in out else None
            return
        if st["kind"] == "cmp":
            for a in st["args"]:
                if "step" in a:
                    walk(steps[a["step"]])
            return
        for a in st.get("args") or []:
            walk(steps[a])

    if root is not None:
        walk(root)
    return out


# ---------------------------------------------------------------------------------------------- investigation
def candidates(pb: Playbook, name: str) -> list[Any]:
    """The values worth trying for a fact: those its rules test it against, and just either side of each bound."""
    spec = pb.facts[name]
    t = spec["type"]
    if t == "boolean":
        return [True, False]
    consts: list[Any] = []

    def scan(node: dict[str, Any]) -> None:
        if "cmp" in node:
            for a, b in ((node["l"], node["r"]), (node["r"], node["l"])):
                if a.get("fact") == name:
                    if "const" in b:
                        consts.append(b["const"])
                    elif "list" in b:
                        consts.extend(b["list"])
                if b.get("fact") == name and "const" in a and node["cmp"] in ("in", "not in"):
                    consts.append(a["const"])
        for c in children(node):
            scan(c)
        if "cmp" in node:
            scan(node["l"])
            scan(node["r"])

    for rule in pb.rules.values():
        for p in rule.parts:
            scan(p.tree)
    if t == "number":
        out: set[Any] = set()
        for c in consts:
            if isinstance(c, (int, float)) and not isinstance(c, bool):
                d = 1 if float(c).is_integer() else 0.01
                out |= {c - d, c, c + d}
        return sorted(out)
    if t == "date":
        out_d: set[str] = set()
        for c in consts:
            try:
                d0 = date.fromisoformat(str(c))
            except ValueError:
                continue
            out_d |= {(d0 + timedelta(days=k)).isoformat() for k in (-1, 0, 1)}
        return sorted(out_d)
    if t == "text":
        vals = list(spec.get("values") or []) or sorted({str(c) for c in consts}, key=str.casefold)
        return vals + [_OTHER]
    named = sorted({str(c) for c in consts} | set(spec.get("values") or []), key=str.casefold)[:8]
    return [[]] + [[v] for v in named] + ([named] if len(named) > 1 else [])


def investigate(pb: Playbook, source: FactSource, goal: str, facts: list[str], *, budget: int = DEFAULT_BUDGET,
                limit: int = 12) -> list[dict[str, Any]]:
    """For each unknown fact the decision depends on: the decision with that fact set to each candidate value, the
    others as they are. Facts that settle it both ways come first, then those that settle it one way."""
    out = []
    for name in facts[:limit]:
        outcomes = []
        for v in candidates(pb, name):
            d = evaluate(pb, Overlay(source, {name: v}), goal, budget=budget, explore=False)
            outcomes.append({"value": "another value" if v == _OTHER else v, "answer": d.answer})
        answers = {o["answer"] for o in outcomes}
        settles = sorted(answers - {"unknown"})
        out.append({"fact": name, "description": pb.facts[name].get("description", ""), "settles": settles,
                    "outcomes": _merge(outcomes)})
    out.sort(key=lambda x: (-len(x["settles"]), facts.index(x["fact"])))
    return out


def _merge(outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Neighbouring trial numbers or dates with the same answer, as one range (``value`` to ``to``)."""
    out: list[dict[str, Any]] = []
    for o in outcomes:
        v = o["value"]
        ordered = (isinstance(v, (int, float)) and not isinstance(v, bool)) or (isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v))
        if ordered and out and out[-1]["answer"] == o["answer"] and out[-1].get("ordered"):
            out[-1]["to"] = v
        else:
            out.append({**o, "ordered": bool(ordered)})
    return [{k: v for k, v in o.items() if k != "ordered"} for o in out]


def summary(d: Decision) -> str:
    """One line: the answer, and for an unknown one, what would settle it."""
    if d.result is not None:
        return d.answer
    asks = [m for m in d.missing if m["settles"]]
    if not asks:
        return "unknown: " + (", ".join(m["fact"] for m in d.missing) or "; ".join(d.notes) or "no fact can settle it alone")
    return "unknown: needs " + ", ".join(m["fact"] for m in asks[:3])
