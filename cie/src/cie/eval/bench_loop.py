"""The one-project loop benchmark: does the company operating system keep an answer about a project right while the
project changes?

FICTIONAL, GENERATED project data (``cie.eval.rem_dataset``). Each world has a dozen projects with milestones,
orders, suppliers, stock, penalty clauses and tasks, plus a stream of changes (supplier delays, stock counts,
replacement orders, cancellations, deletions, earlier due dates). This benchmark adds unit prices and a budget per
project. The expected answers come from the generator's own world model, not from the engine.

Worlds can be loaded into a *host* tenant that already holds a real memory bank (for example the
EnterpriseRAG-Bench documents loaded by ``cie.eval.bench_enterprise``). Search then has to find the project's
documents among that corpus. Each world's identifiers, and its supplier, product and project names, carry a tag,
so several worlds (seeds, arms) live in one tenant as different companies' projects.

**The loop**, for every project of a world:

1. A task asks "Can <project> deliver every milestone on time and within budget?" through the workflow engine.
2. An analyst builds the task's context with the context builder, using the operations agent's principal:
   exhaustive scans of the project's milestones and open orders, entity views of the project and its milestones
   (stock, the quantities each milestone needs, the budget), traversal, and search over the whole company memory.
   It then applies the documented business definition: a milestone is at risk when stock plus open orders promised
   by its due date plus slack cannot cover a product it needs; the committed cost is the sum of quantity times
   unit price over open orders. The analyst is deterministic, so the metrics measure the loop (what the context
   holds and whether it is current), not a model's reasoning.
3. The findings carry state references with versions, and a calculation for the cost. The engine checks the
   inputs are current; the publication gate verifies each finding (state freshness and recalculation) before it
   reaches the project.
4. Every change is applied as an event, with REM's change rules as analysis. Event routing reopens or flags the
   tasks that used a changed record, and the analyst re-runs them. Each event is also delivered a second time
   with the same key, and each supplier notice a second time under a new key (the same notice forwarded twice).

**Arms.**
* ``loop`` routes changes to tasks; every live-state record in a task's context counts as an input (the context
  builder's conservative default).
* ``loop-explicit`` is the same, but only the records the analyst named and the collections it scanned count as
  inputs.
* ``no-routing`` applies the same events with routing off: what a system that answers once and never revisits
  would serve.

**Measures** (per arm, over worlds):

* retrieval completeness: the share of the records an answer needs (the project, its milestones, its open orders)
  that the task's context held; for questions about supplier delays, the share of the evidence the context found
  (traversal plus search over the whole company memory, including the host corpus);
* citation accuracy: the share of findings that passed verification at publication, and the share of published
  answers that match the oracle;
* stale-state errors: after each change and the reaction to it, completed answers that no longer match the oracle
  and were not reopened or flagged; published findings whose referenced versions are out of date;
* missed dependencies: projects whose inputs the change touched (per the oracle) but whose task was neither
  reopened nor flagged;
* duplicate actions: extra state versions, task reopenings, task transitions or suggestions caused by
  re-delivered or duplicated events;
* task completion: tasks completed at the end, re-runs, tasks waiting on a person;
* latency (p50 and p95): event processing, context building, analysis, verification and publication, and the
  whole reaction to a change;
* cost: the tokens the contexts would put in front of a model. The analyst calls no model, so there is no model
  cost.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from cie.eval.rem_dataset import PEOPLE, World

ARMS = ("loop", "loop-explicit", "loop-relied", "no-routing", "llm-relied", "llm-no-routing")
# what becomes a task's input in each arm (cie.context.builder.ContextRequest.inputs)
INPUTS = {"loop": "all", "loop-explicit": "explicit", "loop-relied": "relied", "no-routing": "all", "llm-relied": "relied",
          "llm-no-routing": "relied"}
TAGS = {"loop": "L", "loop-explicit": "E", "loop-relied": "R", "no-routing": "N", "llm-relied": "M", "llm-no-routing": "K"}


def _parse_json(text: str) -> dict[str, Any] | None:
    """The JSON object in a model's reply. Models wrap it in prose or code fences, and small ones split it into
    several objects (``{"milestones": ...}, {"cost": ...}``): every top-level object is read and their keys merged,
    the first occurrence of a key winning."""
    if not text:
        return None
    t = text.replace("```json", "```").replace("```", " ")
    dec, out, i = json.JSONDecoder(), {}, t.find("{")
    while 0 <= i < len(t):
        try:
            v, end = dec.raw_decode(t, i)
        except json.JSONDecodeError:
            i = t.find("{", i + 1)
            continue
        if isinstance(v, dict):
            out = {**v, **out}
        i = t.find("{", end)
    return out or None


ANALYST_KEYS = ("milestones", "cost_lines", "cost", "budget", "within_budget", "feasible")


def _num(x: Any) -> float | None:
    """A number from a model's reply, or None (never NaN, which JSON storage refuses)."""
    try:
        v = float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _bool(x: Any) -> bool:
    return x is True or str(x).strip().lower() in ("true", "yes", "1")


def _close(a: Any, b: Any) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) < 0.01


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))], 1)


def ratio(a: float, b: float) -> float | None:
    return round(a / b, 4) if b else None


# ---------------------------------------------------------------------------------------------- worlds
class Namespace:
    """Renames one world's identifiers with a tag (values only; texts are left as they are)."""

    def __init__(self, world: World, tag: str, company: str | None = None):
        p = f"{tag}-"
        m: dict[str, str] = {}
        for k in list(world.projects) + list(world.products) + list(world.suppliers) + list(world.milestones) + list(world.orders) \
                + list(world.tasks) + list(world.reqs):
            m[k] = p + k
        for r in world.reqs.values():
            m[r["contract"]] = p + r["contract"]
        for k in world.summaries:
            m[k] = "summary-" + p + k.removeprefix("summary-")
        for name in PEOPLE:
            m[name] = f"{name} [{tag}]"
        for d in ("Operations", "Engineering", "Legal"):
            m[f"{d} {world.seed}"] = f"{d} [{tag}]"
        m[world.company] = company or f"Synthetic Co [{tag}]"
        self.m, self.p, self.seed, self.tag = m, p, world.seed, tag
        self.prefixes = (f"PO-{world.seed}", f"notice-{world.seed}-", f"synthetic-{world.seed}-")

    def s(self, x: str) -> str:
        if x in self.m:
            return self.m[x]
        if x.endswith("#text"):
            base = self.s(x[:-5])
            return base + "#text" if base != x[:-5] else x
        if x.startswith(self.prefixes):
            return self.p + x
        return x

    def __call__(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.s(obj)
        if isinstance(obj, list):
            return [self(x) for x in obj]
        if isinstance(obj, tuple):
            return tuple(self(x) for x in obj)
        if isinstance(obj, dict):
            return {k: self(v) for k, v in obj.items()}
        return obj

    def key(self, typed: str) -> str:
        """'milestone:prj00-m0' -> 'milestone:<tag>-prj00-m0'."""
        t, _, k = typed.partition(":")
        return f"{t}:{self.s(k)}"


SUPPLIER_STEMS = ("Arden", "Brisk", "Corvid", "Delta", "Eider", "Fulmar", "Grebe", "Harrier", "Ibis", "Jacana", "Kestrel", "Lapwing",
                  "Merlin", "Nightjar", "Osprey", "Petrel", "Quillon", "Rook", "Siskin", "Tern", "Upland", "Vireo", "Wren", "Yarrow")
SUPPLIER_KINDS = ("Metals", "Circuits", "Castings", "Fasteners", "Optics", "Plastics", "Electronics", "Forge", "Polymers", "Components",
                  "Machining", "Alloys")


def _rename(w: World, tag: str) -> World:
    """Each world gets its own supplier and product names (drawn by its tag) and a tagged project name, so worlds
    sharing a tenant are different companies' projects, as they would be, not copies with near-identical texts."""
    rng = random.Random(f"names:{tag}")
    stems = rng.sample(SUPPLIER_STEMS, len(w.suppliers))
    w.suppliers = {k: f"{stems[i]} {rng.choice(SUPPLIER_KINDS)} {rng.randint(10, 99)} (fictional)" for i, k in enumerate(sorted(w.suppliers))}
    w.products = {k: f"{v.rsplit(' ', 1)[0]} {rng.choice('BCDFGHJKLMNPQRSTVWXZ')}{rng.randint(100, 999)}" for k, v in w.products.items()}
    for p in w.projects.values():
        p["name"] = f"{p['name']} [{tag}]"
    return w


class LoopWorld:
    """A world, its change stream, the oracle state after every change, prices and budgets."""

    def __init__(self, seed: int, n_events: int, tag: str = ""):
        self.seed, self.tag = seed, tag
        self.base = _rename(World(seed, n_events=n_events), tag) if tag else World(seed, n_events=n_events)
        final = _rename(World(seed, n_events=n_events), tag) if tag else World(seed, n_events=n_events)
        self.events = final.events()
        # the model after each emitted event: the generator's loop draws the same kinds for any length, and a
        # step that emits no event changes nothing, so the world after k steps is the state after its events
        self.states = [World(seed, n_events=0)]
        emitted = 0
        for k in range(1, n_events + 1):
            w = World(seed, n_events=k)
            e = w.events()
            if len(e) == emitted + 1:
                self.states.append(w)
                emitted += 1
        assert len(self.states) == len(self.events) + 1, "oracle states do not line up with the events"
        rng = random.Random(seed * 101 + 17)
        self.price = {p: rng.randint(20, 400) for p in sorted(self.base.products)}
        self.budget = {pk: int(self.committed(self.base, pk) * rng.choice([0.9, 1.05, 1.15, 1.3])) for pk in sorted(self.base.projects)}

    def committed(self, w: World, pk: str) -> int:
        return sum(o.qty * self.price[o.product] for o in w.orders.values() if o.project == pk and o.status == "open" and not o.deleted)

    def oracle(self, j: int, pk: str) -> dict[str, Any]:
        w = self.states[j]
        at_risk = sorted(mk for mk, m in w.milestones.items() if m.project == pk and w._status(mk) == "at_risk")
        cost = self.committed(w, pk)
        return {"feasible": not at_risk, "within_budget": cost <= self.budget[pk], "at_risk": at_risk, "cost": cost}

    def needed(self, j: int, pk: str) -> set[str]:
        """The records an answer about ``pk`` needs: the project, its milestones and its open orders."""
        w = self.states[j]
        out = {f"project:{pk}"} | {f"milestone:{mk}" for mk, m in w.milestones.items() if m.project == pk}
        return out | {f"order:{o.key}" for o in w.orders.values() if o.project == pk and o.status == "open" and not o.deleted}

    def fingerprint(self, j: int, pk: str) -> str:
        w = self.states[j]
        ms = sorted((mk, m.due.isoformat(), m.slack, sorted(m.needs.items())) for mk, m in w.milestones.items() if m.project == pk)
        os_ = sorted((o.key, o.promised.isoformat(), o.status, o.deleted, o.qty, o.product, o.milestone)
                     for o in w.orders.values() if o.project == pk)
        st = sorted((p, q) for (h, p), q in w.stock.items() if h == pk)
        return json.dumps([ms, os_, st])

    def priced(self, ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for op in ops:
            if op.get("op") == "upsert_node" and op.get("type") == "order":
                op = {**op, "attrs": {**op.get("attrs", {}), "unit_price": self.price[op["attrs"]["product"]]}}
            elif op.get("op") == "upsert_node" and op.get("type") == "project":
                op = {**op, "attrs": {**op.get("attrs", {}), "budget": self.budget[op["key"]]}}
            out.append(op)
        return out


# ---------------------------------------------------------------------------------------------- setup
def _admin(session, tenant_id, root):
    from cie.core.models import Permission, Principal, PrincipalKind
    from cie.governance.permissions import ensure_role, grant_role

    name = "loop-bench-admin"
    p = session.scalar(select(Principal).where(Principal.tenant_id == tenant_id, Principal.name == name))
    if p is None:
        p = Principal(tenant_id=tenant_id, kind=PrincipalKind.user, name=name, attributes={})
        session.add(p)
        session.flush()
        grant_role(session, tenant_id=tenant_id, principal=p, role=ensure_role(session, tenant_id, "loop-admin", Permission.admin, 4), scope=root)
    return p


def host(session, name: str | None, tag: str):
    """(tenant, root scope). A named host tenant is reused; otherwise a new tenant is made."""
    from cie.core.models import Scope, ScopeKind, Tenant
    from cie.memory.scopes import create_scope

    if name:
        t = session.scalar(select(Tenant).where(Tenant.name == name))
        if t is None:
            raise SystemExit(f"no tenant named {name!r}")
        roots = list(session.scalars(select(Scope).where(Scope.tenant_id == t.id, Scope.parent_id.is_(None)).order_by(Scope.created_at)))
        return t, roots[0]
    t = Tenant(name=f"loop-{tag}-{uuid.uuid4().hex[:6]}")
    session.add(t)
    session.flush()
    return t, create_scope(session, t.id, ScopeKind.company, f"Synthetic Co [{tag}]")


def memory_docs(session, tenant_id, ops: list[dict[str, Any]], scopes: dict[str, uuid.UUID], embedder) -> int:
    """The world's passages (purchase orders, notices, clauses, notes) also become documents in knowledge memory."""
    from cie.core.models import RecordType
    from cie.memory.records import create_record

    n = 0
    for op in ops:
        if op.get("op") != "upsert_node" or op.get("type") != "passage":
            continue
        text = op.get("summary") or op.get("name")
        create_record(session, tenant_id=tenant_id, scope_id=scopes[op["scope"]], type=RecordType.fact, summary=op["name"][:200], detail=text,
                      content={"state_key": f"passage:{op['key']}"}, source_locations=[{"quote": text[:200], **(op.get("source_pointers") or [{}])[0]}],
                      sensitivity=int(op.get("sensitivity", 1)), keywords=[w for w in text.lower().split() if len(w) > 4][:8],
                      producing_agent="loop-bench-loader", embedder=embedder, dedup=False)
        n += 1
    return n


class Run:
    """One world in one arm."""

    def __init__(self, session, lw: LoopWorld, arm: str, host_name: str | None, embedder, settings, model=None):
        from cie.agents.head import create_project
        from cie.agents.registry import ensure_default_agents
        from cie.core.models import Agent, Principal, Scope, ScopeKind
        from cie.memory.scopes import create_scope
        from cie.rem.change import process_event, submit_event

        self.s, self.lw, self.arm, self.emb, self.settings, self.model = session, lw, arm, embedder, settings, model
        if arm.startswith("llm") and model is None:
            raise SystemExit(f"arm {arm} needs a language model (set CIE_LLM_PROVIDER and CIE_LLM_MODEL)")
        self.answered: dict[str, int] = {}
        self.last_model_error = self.last_bad_reply = ""
        self.tag = lw.tag or tag_for(lw.seed, arm)
        self.tenant, self.root = host(session, host_name, self.tag)
        self.ns = Namespace(lw.base, self.tag, company=self.root.name)
        self.admin = _admin(session, self.tenant.id, self.root)
        scopes = {self.root.name: self.root.id}
        for sc in self.ns(lw.base.scopes()):
            if sc["kind"] == "company":
                continue
            parent = scopes.get(sc.get("parent"), self.root.id)
            scopes[sc["name"]] = create_scope(session, self.tenant.id, ScopeKind(sc["kind"]), sc["name"], parent).id
        self.scopes = scopes
        self.agents = ensure_default_agents(session, self.tenant.id, self.root)
        self.analyst = self.agents["operations"]
        self.analyst_principal = session.get(Principal, self.analyst.principal_id)
        ops = self.ns(lw.priced(lw.base.ops()))
        t0 = time.perf_counter()
        ev, _ = submit_event(session, self.tenant.id, kind="ops", payload={"ops": ops}, idempotency_key=f"{self.tag}-corpus")
        process_event(session, ev.id, embedder=embedder, policy="rules")
        self.load_s = time.perf_counter() - t0
        self.docs = memory_docs(session, self.tenant.id, ops, scopes, embedder)
        session.commit()
        self.projects = {}
        for pk, p in lw.base.projects.items():
            dept = session.get(Scope, scopes[self.ns.s(f"{p['dept']} {lw.seed}")])
            self.projects[pk] = create_project(session, tenant_id=self.tenant.id, parent_scope=dept, name=p["name"])
        self.tasks: dict[str, uuid.UUID] = {}
        self.m: dict[str, Any] = {k: [] for k in ("event_ms", "context_ms", "analyse_ms", "publish_ms", "reaction_ms", "question_ms",
                                                  "needed_recall", "inputs_recall", "question_recall", "question_recall_search",
                                                  "context_tokens", "model_ms")}
        self.c: dict[str, int] = {k: 0 for k in ("findings", "verified", "published_answers", "published_answers_right", "runs", "reruns",
                                                 "stale_answers", "stale_published", "affected", "missed", "reopened_unaffected", "routed",
                                                 "dup_versions", "dup_reopenings", "dup_transitions", "dup_suggestions", "redelivered",
                                                 "duplicated", "answers_checked", "answers_right", "exhaustive_incomplete", "memory_docs",
                                                 "model_wrong_served", "answers_computed", "answers_computed_right", "part_feasible_right",
                                                 "part_within_budget_right", "part_cost_right", "part_at_risk_set_right", "wrong_numbers",
                                                 "wrong_numbers_blocked", "right_numbers_blocked", "no_answer", "model_calls", "model_tokens_in",
                                                 "model_tokens_out", "model_cost_usd_micros", "model_bad_json", "model_invented_refs",
                                                 "model_errors_call", "affected_no_answer")}
        self.c["memory_docs"] = self.docs
        self._agent = session.get(Agent, self.analyst.id)

    # ------------------------------------------------------------------------------------------ the analyst
    def gather(self, task, pk: str) -> dict[str, Any]:
        """The task's context, through the context builder with the analyst's principal: exhaustive scans of the
        project's milestones and open orders, entity views of the project and its milestones, traversal and search."""
        from cie.context.builder import ContextRequest, build_context

        mpk = self.ns.s(pk)
        s, tid, mode = self.s, self.tenant.id, INPUTS[self.arm]
        t0 = time.perf_counter()
        ms = build_context(s, tid, self.analyst_principal, ContextRequest(mode="exhaustive", task_id=task.id, inputs=mode,
                           collection={"type": "milestone", "project_key": mpk}, check={"field": "type", "op": "eq", "value": "milestone"})).data
        orders = build_context(s, tid, self.analyst_principal, ContextRequest(mode="exhaustive", task_id=task.id, inputs=mode,
                               collection={"type": "order", "project_key": mpk}, check={"field": "status", "op": "eq", "value": "open"})).data
        self.c["exhaustive_incomplete"] += int(not ms["coverage"]["complete"]) + int(not orders["coverage"]["complete"])
        entities = [["project", mpk]] + [m["entity_id"].split(":", 1) for m in ms["matches"]]
        req = ContextRequest(question=task.title, task_id=task.id, entities=entities, project_keys=[mpk], scope_id=self.root.id,
                             budget_tokens=60_000, inputs=mode)
        views, tokens = [], 0
        while True:
            d = build_context(s, tid, self.analyst_principal, req, embedder=self.emb, settings=self.settings).data
            views += d.get("entities", [])
            tokens += d.get("token_estimate", 0)
            if not d.get("cursor"):
                break
            req = ContextRequest(**{**req.__dict__, "cursor": d["cursor"]})
        self.m["context_ms"].append((time.perf_counter() - t0) * 1000)
        self.m["context_tokens"].append(tokens)
        by = {v["entity_id"]: v for v in views}
        proj = by[f"project:{mpk}"]
        open_orders = {m["entity_id"].split(":", 1)[1]: m for m in orders["matches"]}
        milestones = []
        for m in ms["matches"]:
            v = by.get(m["entity_id"])
            if v is None:
                continue
            deps = [d for d in v["dependencies"] if d["relation"] == "depends_on" and d["direction"] == "out"]
            milestones.append({"key": v["key"], "id": v["id"], "version": v["version"], "name": v["name"],
                               "due": str(v["facts"]["due_date"]["value"])[:10], "slack": int(v["facts"].get("slack_days", {}).get("value") or 0),
                               "needs": {d["key"]: float((d.get("attrs") or {}).get("qty") or 0) for d in deps if d["type"] == "product"},
                               "product_names": {d["key"]: d["name"] for d in deps if d["type"] == "product"},
                               "orders": [d["key"] for d in deps if d["type"] == "order" and d["key"] in open_orders]})
        return {"project": proj, "milestones": milestones, "orders": open_orders,
                "stock": {r["product"]: r["available"] for r in proj.get("stock", [])},
                "budget": float(proj["facts"]["budget"]["value"]),
                "in_context": {f"project:{mpk}"} | {f"milestone:{x['key']}" for x in milestones} | {f"order:{k}" for k in open_orders}}

    def decide_rule(self, g: dict[str, Any]) -> dict[str, Any]:
        """The documented business definition, applied exactly."""
        from datetime import date, timedelta

        at_risk, reasons = [], {}
        for m in g["milestones"]:
            limit = date.fromisoformat(m["due"]) + timedelta(days=m["slack"])
            short = []
            for prod, need in m["needs"].items():
                supply = g["stock"].get(prod, 0.0) + sum(float(g["orders"][o]["attrs"]["qty"]) for o in m["orders"]
                                                         if g["orders"][o]["attrs"].get("product") == prod
                                                         and date.fromisoformat(str(g["orders"][o]["attrs"]["promised_date"])[:10]) <= limit)
                if supply < need:
                    short.append(f"{m['product_names'].get(prod, prod)}: {supply:g} available by {limit.isoformat()} against {need:g} needed")
            if short:
                at_risk.append(m["key"])
                reasons[m["key"]] = "; ".join(short)
        lines = [{"order": k, "qty": float(o["attrs"]["qty"]), "unit_price": float(o["attrs"]["unit_price"])} for k, o in sorted(g["orders"].items())]
        cost = sum(x["qty"] * x["unit_price"] for x in lines)
        return {"at_risk": at_risk, "reasons": reasons, "cost_lines": lines, "cost": cost, "budget": g["budget"],
                "within_budget": cost <= g["budget"], "feasible": not at_risk, "cited_milestones": [m["key"] for m in g["milestones"]]}

    def decide_llm(self, g: dict[str, Any]) -> dict[str, Any] | None:
        """A language model reads the same data and returns the assessment as JSON. Records are given short aliases
        (M1, O1, P1) and mapped back; an alias the data does not contain is counted as invented."""
        ms = {f"M{i + 1}": m for i, m in enumerate(g["milestones"])}
        os_ = {f"O{i + 1}": (k, o) for i, (k, o) in enumerate(sorted(g["orders"].items()))}
        prods = sorted({p for m in g["milestones"] for p in m["needs"]} | {o["attrs"].get("product") for _, o in os_.values()})
        pa = {p: f"P{i + 1}" for i, p in enumerate(prods)}
        pnames = {p: n for m in g["milestones"] for p, n in m["product_names"].items()}
        ma = {m["key"]: a for a, m in ms.items()}
        data = {"project": g["project"]["name"], "budget": g["budget"],
                "stock_available": {pa[p]: q for p, q in g["stock"].items() if p in pa},
                "products": {a: pnames.get(p, p) for p, a in pa.items()},
                "milestones": [{"id": a, "name": m["name"], "due_date": m["due"], "slack_days": m["slack"],
                                "needs": {pa[p]: q for p, q in m["needs"].items()}} for a, m in ms.items()],
                "open_orders": [{"id": a, "for_milestone": next((ma[m["key"]] for m in g["milestones"] if k in m["orders"]), None),
                                 "product": pa.get(o["attrs"].get("product")), "qty": o["attrs"]["qty"], "unit_price": o["attrs"]["unit_price"],
                                 "promised_date": str(o["attrs"]["promised_date"])[:10]} for a, (k, o) in os_.items()]}
        user = (f"Question: can {g['project']['name']} deliver every milestone on time and within budget?\n\n"
                "Definitions:\n"
                "- A milestone is at risk if, for some product it needs, the project's available stock of that product plus the "
                "quantities of the milestone's open orders for that product with a promised date on or before (due date + slack days) "
                "is less than the quantity needed.\n"
                "- The project can deliver on time if no milestone is at risk.\n"
                "- Committed cost = the sum over all open orders of qty x unit_price. The project is within budget if committed cost <= budget.\n\n"
                f"Data (JSON):\n{json.dumps(data)}\n\n"
                "Reply with one JSON object and nothing else, in this form:\n"
                '{"milestones": [{"id": "M1", "at_risk": false, "reason": "..."}], '
                '"cost_lines": [{"order": "O1", "qty": 0, "unit_price": 0}], "cost": 0, "budget": 0, "within_budget": true, "feasible": true}\n'
                "List every milestone and every open order. Keep each reason under 20 words.")
        system = "You are a careful operations analyst. Use only the data given. Check dates and arithmetic. Reply with JSON only."
        out = None
        for _attempt in range(2):
            self._keep_lease()
            t0 = time.perf_counter()
            try:
                r = self.model.complete(system, user, max_tokens=2000)  # a local provider caps it (CIE_LLM_LOCAL_MAX_OUTPUT_TOKENS)
            except Exception as e:  # noqa: BLE001 - a model server error counts as a failed call, not a benchmark crash
                self.c["model_errors_call"] += 1
                self.last_model_error = str(e)[:300]
                continue
            self.m["model_ms"].append((time.perf_counter() - t0) * 1000)
            self.c["model_calls"] += 1
            self.c["model_tokens_in"] += int(r.tokens_in or 0)
            self.c["model_tokens_out"] += int(r.tokens_out or 0)
            self.c["model_cost_usd_micros"] += int(round(float(r.cost_usd or 0) * 1e6))
            out = _parse_json(r.text)
            missing = [k for k in ANALYST_KEYS if k not in (out or {})]
            if not missing and isinstance(out["milestones"], list) and isinstance(out["cost_lines"], list):
                break
            self.c["model_bad_json"] += 1
            self.last_bad_reply = f"{r.tokens_out} tokens: {(r.text or '')[:200]!r} ... {(r.text or '')[-100:]!r}"
            out = None
            user += ("\n\nYour previous reply was not one JSON object in the requested form"
                     + (f" (missing: {', '.join(missing)})" if missing else "") + ". Reply with the JSON object only, with every key.")
        if out is None:
            return None
        invented = 0
        at_risk, reasons, cited = [], {}, []
        for x in out.get("milestones") or []:
            m = ms.get(str(x.get("id")))
            if m is None:
                invented += 1
                continue
            cited.append(m["key"])
            if _bool(x.get("at_risk")):
                at_risk.append(m["key"])
                reasons[m["key"]] = str(x.get("reason") or "")[:300]
        lines = []
        for x in out.get("cost_lines") or []:
            o = os_.get(str(x.get("order")))
            if o is None:
                invented += 1
                continue
            lines.append({"order": o[0], "qty": _num(x.get("qty")), "unit_price": _num(x.get("unit_price"))})
        self.c["model_invented_refs"] += invented
        cost, budget = _num(out.get("cost")), _num(out.get("budget"))
        return {"at_risk": at_risk, "reasons": reasons, "cost_lines": lines, "cost": cost, "budget": budget,
                "within_budget": _bool(out.get("within_budget")), "feasible": _bool(out.get("feasible")), "cited_milestones": cited}

    def findings(self, g: dict[str, Any], d: dict[str, Any]) -> dict[str, Any]:
        """Findings with state references (the versions read) and a recalculable cost; the answer is the last one and
        rests on the others, so the gate blocks it when any of them fails verification."""
        proj = g["project"]
        mby = {m["key"]: m for m in g["milestones"]}
        oref = lambda k: {"ref": g["orders"][k]["id"], "version": g["orders"][k]["version"]}  # noqa: E731
        found, refs_all = [], [{"ref": proj["id"], "version": proj["version"]}]
        for mk in d["cited_milestones"]:
            m = mby[mk]
            refs = [{"ref": m["id"], "version": m["version"]}] + [oref(o) for o in m["orders"]]
            refs_all += refs
            if mk in d["at_risk"]:
                found.append({"claim": f"{m['name']} is at risk: {d['reasons'].get(mk, '')}", "kind": "assessment", "value": "at_risk",
                              "state_refs": refs, "confidence": 0.9})
        inputs, terms = {}, []
        for i, x in enumerate(d["cost_lines"]):
            inputs[f"q{i}"] = {"ref": g["orders"][x["order"]]["id"], "field": "qty"}
            inputs[f"p{i}"] = {"ref": g["orders"][x["order"]]["id"], "field": "unit_price"}
            terms.append(f"q{i} * p{i}")
            refs_all.append(oref(x["order"]))
        fmt = lambda v: f"{v:g}" if v is not None else "an unreadable amount"  # noqa: E731
        found.append({"claim": f"Open orders commit {fmt(d['cost'])}", "kind": "metric", "value": d["cost"],
                      "calculation": {"expression": " + ".join(terms) or "0", "inputs": inputs, "tolerance": 0.01}, "confidence": 0.95})
        found.append({"claim": f"The budget of {proj['name']} is {fmt(d['budget'])}", "kind": "metric", "value": d["budget"],
                      "state_refs": [{"ref": proj["id"], "version": proj["version"], "field": "budget", "value": proj["facts"]["budget"]["value"]
                                      if _close(d["budget"], g["budget"]) else d["budget"]}], "confidence": 0.95})
        answer = {"feasible": d["feasible"], "within_budget": d["within_budget"], "at_risk": sorted(d["at_risk"]), "cost": d["cost"]}
        found.append({"claim": f"{proj['name']} {'can' if answer['feasible'] else 'cannot'} deliver every milestone on time and is "
                               f"{'within' if answer['within_budget'] else 'over'} budget", "kind": "answer", "value": answer,
                      "state_refs": refs_all, "depends_on": list(range(len(found))), "confidence": 0.9})
        return {"summary": found[-1]["claim"], "answer": answer, "findings": found}

    def analyse(self, task, pk: str, j: int) -> dict[str, Any]:
        g = self.gather(task, pk)
        need = {self.ns.key(k) for k in self.lw.needed(j, pk)}
        self.m["needed_recall"].append(len(need & g["in_context"]) / len(need))
        t1 = time.perf_counter()
        d = self.decide_llm(g) if self.arm.startswith("llm") else self.decide_rule(g)
        self.m["analyse_ms"].append((time.perf_counter() - t1) * 1000)
        if d is None:  # the model gave no usable answer: nothing to submit but an empty result
            self.c["no_answer"] += 1
            return {"summary": "no usable answer", "answer": None, "findings": []}
        return self.findings(g, d)

    def run_task(self, pk: str, j: int, rerun: bool) -> None:
        from cie.agents import publication
        from cie.core.models import MemoryRecord, TaskStatus
        from cie.state.store import GraphReader
        from cie.workflow import engine
        from cie.workflow.models import TaskInput

        s = self.s
        t = engine.claim_task(s, self.tasks[pk], worker=f"analyst:{self.tag}", agent_id=self.analyst.id)
        self._running = t.id
        for _ in range(3):  # a change that lands while it runs, or an unusable answer, sends it back
            result = self.analyse(t, pk, j)
            if result["findings"]:
                publication.stage(s, t, self._agent, self.projects[pk], result, embedder=self.emb)
            self._keep_lease()
            t = engine.submit(s, t.id, worker=f"analyst:{self.tag}", result=result, usage={"tools": ["retrieval"]})
            if t.status != TaskStatus.running:
                break
        self.c["runs"] += 1
        self.c["reruns"] += int(rerun)
        got = {i.label for i in s.scalars(select(TaskInput).where(TaskInput.task_id == t.id, TaskInput.ref_kind == "record"))}
        need = {self.ns.key(k) for k in self.lw.needed(j, pk)}
        self.m["inputs_recall"].append(len(need & got) / len(need))
        if t.status != TaskStatus.completed or not result.get("answer"):
            return
        oracle = self.lw.oracle(j, pk)
        right = self._same(result["answer"], oracle)
        self.answered[pk] = j
        self.c["answers_computed"] += 1
        self.c["answers_computed_right"] += int(right)
        for k, ok in (("feasible", result["answer"]["feasible"] == oracle["feasible"]),
                      ("within_budget", result["answer"]["within_budget"] == oracle["within_budget"]),
                      ("cost", _close(result["answer"]["cost"], oracle["cost"])),
                      ("at_risk_set", sorted(result["answer"]["at_risk"]) == sorted(self.ns.s(x) for x in oracle["at_risk"]))):
            self.c[f"part_{k}_right"] += int(ok)
        t0 = time.perf_counter()
        out = publication.publish(s, t, verifier="verification", reader=GraphReader(s, self.tenant.id, None), embedder=self.emb)
        self.m["publish_ms"].append((time.perf_counter() - t0) * 1000)
        n = len(result["findings"])
        self.c["findings"] += n
        self.c["verified"] += n - len(out["blocked"])
        blocked = {int((s.get(MemoryRecord, uuid.UUID(b)).content or {}).get("finding", -1)) for b in out["blocked"]}
        cost_i, budget_i = n - 3, n - 2  # the cost and budget findings precede the answer
        cost_wrong = not _close(result["findings"][cost_i]["value"], oracle["cost"])
        budget_wrong = not _close(result["findings"][budget_i]["value"], self.lw.budget[pk])
        self.c["wrong_numbers"] += int(cost_wrong) + int(budget_wrong)
        self.c["wrong_numbers_blocked"] += int(cost_wrong and cost_i in blocked) + int(budget_wrong and budget_i in blocked)
        self.c["right_numbers_blocked"] += int(not cost_wrong and cost_i in blocked) + int(not budget_wrong and budget_i in blocked)
        if (n - 1) not in blocked:  # the answer is the last finding
            self.c["published_answers"] += 1
            self.c["published_answers_right"] += int(right)

    def _keep_lease(self) -> None:
        """A worker renews its lease while it works: long enough for one model call (the provider times out at 600 s)."""
        from cie.workflow import engine

        engine.heartbeat(self.s, self._running, worker=f"analyst:{self.tag}", lease_seconds=900)

    def _same(self, a: dict[str, Any], b: dict[str, Any]) -> bool:
        """An answer matches the oracle when the verdicts, the cost and the set of milestones at risk all do."""
        return (a["feasible"] == b["feasible"] and a["within_budget"] == b["within_budget"] and _close(a["cost"], b["cost"])
                and sorted(a["at_risk"]) == sorted(self.ns.s(x) for x in b["at_risk"]))

    # ------------------------------------------------------------------------------------------ the loop
    def start(self) -> None:
        from cie.workflow import engine

        for pk, proj in self.projects.items():
            name = self.lw.base.projects[pk]["name"]
            t = engine.propose(self.s, tenant_id=self.tenant.id, project_id=proj.id, scope_id=proj.scope_id, task_type="operations",
                               title=f"Can {name} deliver every milestone on time and within budget?",
                               acceptance={"min_findings": 1, "review": "auto"}, limits={"tools": ["retrieval"]}, actor="loop-bench")
            engine.accept(self.s, t, actor="loop-bench")
            self.tasks[pk] = t.id
        for pk in self.projects:
            self.run_task(pk, 0, rerun=False)
        self.s.commit()
        self.check(0)

    def counts(self) -> dict[str, int]:
        from cie.state.models import RemNodeVersion, RemSuggestion
        from cie.workflow.models import TaskInvalidation, TaskTransition

        tid = self.tenant.id
        return {"versions": self.s.scalar(select(func.count()).select_from(RemNodeVersion).where(RemNodeVersion.tenant_id == tid)),
                "invalidations": self.s.scalar(select(func.count()).select_from(TaskInvalidation).where(TaskInvalidation.tenant_id == tid)),
                "transitions": self.s.scalar(select(func.count()).select_from(TaskTransition).where(TaskTransition.tenant_id == tid)),
                "suggestions": self.s.scalar(select(func.count()).select_from(RemSuggestion).where(RemSuggestion.tenant_id == tid))}

    def apply(self, j: int, ev: dict[str, Any]) -> None:
        """Event j (0-based) moves the world from state j to state j+1."""
        from cie.core.models import Task, TaskStatus
        from cie.rem.change import process_event, submit_event

        s, tid = self.s, self.tenant.id
        payload = self.ns(ev["payload"])
        if ev["kind"] == "ops":  # replacement orders created by a change carry their unit price too
            payload = {**payload, "ops": self._priced_ns(payload["ops"])}
        route = not self.arm.endswith("no-routing")
        answering = {pk for pk, x in self.tasks.items() if s.get(Task, x).status == TaskStatus.completed and (s.get(Task, x).result or {}).get("answer")}
        t0 = time.perf_counter()
        e, _ = submit_event(s, tid, kind=ev["kind"], payload=payload, idempotency_key=self.ns.s(ev["key"]))
        summary = process_event(s, e.id, embedder=self.emb, policy="rules", route_tasks=route)
        self.m["event_ms"].append((time.perf_counter() - t0) * 1000)
        new_passages = [op for op in payload.get("ops", []) if op.get("op") == "upsert_node" and op.get("type") == "passage"]
        self.c["memory_docs"] += memory_docs(s, tid, new_passages, self.scopes, self.emb)
        s.commit()
        # duplicates: the same event again, and a supplier notice forwarded a second time under a new key
        before = self.counts()
        e2, created = submit_event(s, tid, kind=ev["kind"], payload=payload, idempotency_key=self.ns.s(ev["key"]))
        if not created:
            process_event(s, e2.id, embedder=self.emb, policy="rules", route_tasks=route)
        self.c["redelivered"] += 1
        if ev["kind"] == "supplier_delay":
            e3, _ = submit_event(s, tid, kind=ev["kind"], payload=payload, idempotency_key=self.ns.s(ev["key"]) + "-forwarded")
            process_event(s, e3.id, embedder=self.emb, policy="rules", route_tasks=route)
            self.c["duplicated"] += 1
        after = self.counts()
        self.c["dup_versions"] += after["versions"] - before["versions"]
        self.c["dup_reopenings"] += after["invalidations"] - before["invalidations"]
        self.c["dup_transitions"] += after["transitions"] - before["transitions"]
        self.c["dup_suggestions"] += after["suggestions"] - before["suggestions"]
        s.commit()
        # missed dependencies: projects whose inputs changed, per the oracle, against the tasks routing reached
        routed_ids = {uuid.UUID(x) for k in ("reopened", "flagged") for x in (summary.get("tasks") or {}).get(k, [])}
        routed = {pk for pk, tid_ in self.tasks.items() if tid_ in routed_ids}
        changed = {pk for pk in self.projects if self.lw.fingerprint(j, pk) != self.lw.fingerprint(j + 1, pk)}
        affected = changed & answering  # a task holding no answer (it waits on a person) has nothing to refresh
        self.c["affected_no_answer"] += len(changed - answering)
        self.c["affected"] += len(affected)
        self.c["missed"] += len(affected - routed)
        self.c["reopened_unaffected"] += len(routed - affected)
        self.c["routed"] += len(routed)
        # the reaction: re-run what routing reopened
        t1 = time.perf_counter()
        if route:
            for pk, task_id in self.tasks.items():
                t = s.get(Task, task_id)
                if t.status == TaskStatus.ready:
                    self.run_task(pk, j + 1, rerun=True)
        self.m["reaction_ms"].append((time.perf_counter() - t1) * 1000 + self.m["event_ms"][-1])
        s.commit()
        if ev.get("question"):
            self.question(ev["question"])
        self.check(j + 1)

    def _priced_ns(self, ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        inv = {v: k for k, v in self.ns.m.items()}
        for op in ops:
            if op.get("op") == "upsert_node" and op.get("type") == "order":
                prod = inv.get(op["attrs"]["product"], op["attrs"]["product"])
                op = {**op, "attrs": {**op["attrs"], "unit_price": self.lw.price[prod]}}
            out.append(op)
        return out

    def question(self, q: dict[str, Any]) -> None:
        from cie.context.builder import ContextRequest, build_context

        t0 = time.perf_counter()
        d = build_context(self.s, self.tenant.id, self.analyst_principal, ContextRequest(question=q["text"], scope_id=self.root.id,
                          budget_tokens=8000, channels=("traversal", "retrieval")), embedder=self.emb, settings=self.settings, record=False).data
        self.m["question_ms"].append((time.perf_counter() - t0) * 1000)
        found_state = {f"{e['node']['type']}:{e['node']['key']}" for e in d.get("state_evidence", [])}
        found_search = {(i.get("content") or {}).get("state_key") for i in d.get("memory_evidence", [])} - {None}
        gold = {self.ns.key(k) for k in q["gold_evidence"]}
        self.m["question_recall"].append(len(gold & (found_state | found_search)) / len(gold))
        passages = {g for g in gold if g.startswith("passage:")}
        if passages:
            self.m["question_recall_search"].append(len(passages & found_search) / len(passages))

    def check(self, j: int) -> None:
        """After the reaction: answers that are wrong now and were not reopened or flagged are stale-state errors."""
        from cie.core.models import MemoryRecord, RecordType, Task, TaskStatus, VerificationStatus
        from cie.state.models import RemNodeVersion

        s = self.s
        for pk, task_id in self.tasks.items():
            t = s.get(Task, task_id)
            if t.status != TaskStatus.completed:
                continue
            if not (t.result or {}).get("answer"):
                continue
            self.c["answers_checked"] += 1
            right = self._same(t.result["answer"], self.lw.oracle(j, pk))
            self.c["answers_right"] += int(right)
            if not right:  # completed, so neither reopened nor flagged, and wrong now: was it right when it was given?
                was_right = self._same(t.result["answer"], self.lw.oracle(self.answered.get(pk, j), pk))
                self.c["stale_answers" if was_right else "model_wrong_served"] += 1
        pub = list(s.scalars(select(MemoryRecord).where(MemoryRecord.tenant_id == self.tenant.id, MemoryRecord.type == RecordType.result,
                                                        MemoryRecord.verification == VerificationStatus.verified,
                                                        MemoryRecord.superseded_by_id.is_(None),
                                                        MemoryRecord.content["task_id"].astext.in_([str(x) for x in self.tasks.values()]))))
        if not pub:
            return
        current = dict(s.execute(select(RemNodeVersion.node_id, RemNodeVersion.version).where(RemNodeVersion.tenant_id == self.tenant.id,
                                                                                               RemNodeVersion.sys_to.is_(None))).all())
        for r in pub:
            t = s.get(Task, uuid.UUID(r.content["task_id"]))
            f = (t.result or {}).get("findings", [])[int(r.content.get("finding", 0))] if t.result else {}
            refs = f.get("state_refs") or []
            if any(current.get(uuid.UUID(str(x["ref"]))) != x.get("version") for x in refs if x.get("version") is not None):
                self.c["stale_published"] += 1

    def finish(self) -> dict[str, Any]:
        from cie.core.models import Task, TaskStatus
        from cie.workflow import engine

        ts = [self.s.get(Task, x) for x in self.tasks.values()]
        c, m = self.c, self.m
        return {
            "world": self.lw.seed, "arm": self.arm, "tenant": self.tenant.name, "tag": self.tag, "events": len(self.lw.events),
            "load_s": round(self.load_s, 1), "memory_docs": c["memory_docs"],
            "retrieval_completeness": {"needed_records_in_context": ratio(sum(m["needed_recall"]), len(m["needed_recall"])),
                                       "needed_records_relied_on": ratio(sum(m["inputs_recall"]), len(m["inputs_recall"])),
                                       "question_evidence_found": ratio(sum(m["question_recall"]), len(m["question_recall"])),
                                       "question_passages_found_by_search": ratio(sum(m["question_recall_search"]), len(m["question_recall_search"])),
                                       "questions": len(m["question_recall"]), "exhaustive_scans_incomplete": c["exhaustive_incomplete"]},
            "citation_accuracy": {"findings_verified": ratio(c["verified"], c["findings"]), "findings": c["findings"],
                                  "published_answers_correct": ratio(c["published_answers_right"], c["published_answers"]),
                                  "published_answers": c["published_answers"]},
            "answers_correct_when_served": ratio(c["answers_right"], c["answers_checked"]),
            "stale_state_errors": {"stale_answers_served": c["stale_answers"], "stale_published_findings": c["stale_published"],
                                   "answer_checks": c["answers_checked"]},
            "answer_accuracy": {"answers_given": c["answers_computed"], "right_when_given": ratio(c["answers_computed_right"], c["answers_computed"]),
                                "feasible_right": ratio(c["part_feasible_right"], c["answers_computed"]),
                                "within_budget_right": ratio(c["part_within_budget_right"], c["answers_computed"]),
                                "cost_right": ratio(c["part_cost_right"], c["answers_computed"]),
                                "at_risk_set_right": ratio(c["part_at_risk_set_right"], c["answers_computed"]),
                                "wrong_answers_served_by_model_error": c["model_wrong_served"], "no_usable_answer": c["no_answer"]},
            "verification_catch": {"wrong_numbers": c["wrong_numbers"], "wrong_numbers_blocked": c["wrong_numbers_blocked"],
                                   "right_numbers_blocked": c["right_numbers_blocked"]},
            "missed_dependencies": {"affected_projects": c["affected"], "missed": c["missed"], "routed": c["routed"],
                                    "affected_without_answer": c["affected_no_answer"],
                                    "routed_but_unaffected": c["reopened_unaffected"]},
            "duplicate_actions": {"redelivered_events": c["redelivered"], "forwarded_duplicates": c["duplicated"],
                                  "extra_versions": c["dup_versions"], "extra_reopenings": c["dup_reopenings"],
                                  "extra_transitions": c["dup_transitions"], "extra_suggestions": c["dup_suggestions"]},
            "task_completion": {"tasks": len(ts), "completed": sum(t.status == TaskStatus.completed for t in ts),
                                "awaiting_person": sum(engine.awaiting_person(t) for t in ts), "failed": sum(t.status == TaskStatus.failed for t in ts),
                                "runs": c["runs"], "reruns": c["reruns"]},
            "latency_ms": {k: {"p50": pct(m[k], 0.5), "p95": pct(m[k], 0.95), "n": len(m[k])}
                           for k in ("event_ms", "context_ms", "analyse_ms", "publish_ms", "reaction_ms", "question_ms", "model_ms")},
            "cost": {"context_tokens_total": int(sum(m["context_tokens"])), "context_tokens_per_run": pct(m["context_tokens"], 0.5),
                     "model": getattr(self.model, "model", None), "model_calls": c["model_calls"], "model_tokens_in": c["model_tokens_in"],
                     "model_tokens_out": c["model_tokens_out"], "model_cost_usd": round(c["model_cost_usd_micros"] / 1e6, 4),
                     "model_bad_json": c["model_bad_json"], "model_invented_refs": c["model_invented_refs"],
                     "model_call_errors": c["model_errors_call"], "last_model_error": self.last_model_error,
                     "last_invalid_reply": self.last_bad_reply},
        }


def tag_for(seed: int, arm: str, run: str = "") -> str:
    return f"w{seed}{TAGS[arm]}{run}"


def run_world(factory, seed: int, arm: str, n_events: int, host_name: str | None, embedder, settings, log=print,
              run: str = "", model=None) -> dict[str, Any]:
    lw = LoopWorld(seed, n_events, tag=tag_for(seed, arm, run))
    with factory() as s:
        r = Run(s, lw, arm, host_name, embedder, settings, model=model)
        log(f"  world {seed} [{arm}]: loaded in {r.load_s:.1f} s into {r.tenant.name}; {len(lw.events)} changes")
        r.start()
        for j, ev in enumerate(lw.events):
            r.apply(j, ev)
        out = r.finish()
        s.commit()
    return out


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def total(path: list[str]) -> float:
        v = 0.0
        for r in rows:
            x: Any = r
            for p in path:
                x = x[p]
            v += x or 0
        return v

    def mean(path: list[str]) -> float | None:
        xs = []
        for r in rows:
            x: Any = r
            for p in path:
                x = x[p]
            if x is not None:
                xs.append(x)
        return round(sum(xs) / len(xs), 4) if xs else None

    return {
        "worlds": len(rows),
        "retrieval_completeness": {"needed_records_in_context": mean(["retrieval_completeness", "needed_records_in_context"]),
                                   "needed_records_relied_on": mean(["retrieval_completeness", "needed_records_relied_on"]),
                                   "question_evidence_found": mean(["retrieval_completeness", "question_evidence_found"]),
                                   "question_passages_found_by_search": mean(["retrieval_completeness", "question_passages_found_by_search"]),
                                   "exhaustive_scans_incomplete": int(total(["retrieval_completeness", "exhaustive_scans_incomplete"]))},
        "citation_accuracy": {"findings_verified": ratio(sum(r["citation_accuracy"]["findings_verified"] * r["citation_accuracy"]["findings"]
                                                             for r in rows if r["citation_accuracy"]["findings_verified"] is not None),
                                                         total(["citation_accuracy", "findings"])),
                              "published_answers_correct": mean(["citation_accuracy", "published_answers_correct"])},
        "answers_correct_when_served": mean(["answers_correct_when_served"]),
        "answer_accuracy": {"answers_given": int(total(["answer_accuracy", "answers_given"])),
                            **{k: ratio(sum((r["answer_accuracy"][k] or 0) * r["answer_accuracy"]["answers_given"] for r in rows),
                                        total(["answer_accuracy", "answers_given"]))
                               for k in ("right_when_given", "feasible_right", "within_budget_right", "cost_right", "at_risk_set_right")},
                            "wrong_answers_served_by_model_error": int(total(["answer_accuracy", "wrong_answers_served_by_model_error"])),
                            "no_usable_answer": int(total(["answer_accuracy", "no_usable_answer"]))},
        "verification_catch": {k: int(total(["verification_catch", k])) for k in rows[0]["verification_catch"]},
        "stale_state_errors": {"stale_answers_served": int(total(["stale_state_errors", "stale_answers_served"])),
                               "stale_published_findings": int(total(["stale_state_errors", "stale_published_findings"])),
                               "answer_checks": int(total(["stale_state_errors", "answer_checks"]))},
        "missed_dependencies": {"affected_projects": int(total(["missed_dependencies", "affected_projects"])),
                                "missed": int(total(["missed_dependencies", "missed"])),
                                "routed_but_unaffected": int(total(["missed_dependencies", "routed_but_unaffected"])),
                                "affected_without_answer": int(total(["missed_dependencies", "affected_without_answer"]))},
        "duplicate_actions": {k: int(total(["duplicate_actions", k])) for k in rows[0]["duplicate_actions"]},
        "task_completion": {k: int(total(["task_completion", k])) for k in rows[0]["task_completion"]},
        "latency_ms_p50_of_worlds": {k: mean(["latency_ms", k, "p50"]) for k in rows[0]["latency_ms"]},
        "latency_ms_p95_max": {k: max((r["latency_ms"][k]["p95"] or 0) for r in rows) for k in rows[0]["latency_ms"]},
        "cost": {"context_tokens_total": int(total(["cost", "context_tokens_total"])), "model": rows[0]["cost"]["model"],
                 **{k: int(total(["cost", k])) for k in ("model_calls", "model_tokens_in", "model_tokens_out", "model_bad_json",
                                                          "model_invented_refs", "model_call_errors")},
                 "model_cost_usd": round(total(["cost", "model_cost_usd"]), 4),
                 **{k: next((r["cost"][k] for r in reversed(rows) if r["cost"].get(k)), "") for k in ("last_model_error", "last_invalid_reply")}},
    }


def verdict(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The criteria fixed in docs/LOOP_PREREGISTRATION.md: 1-6 for the deterministic arms with routing, plus 7 for
    ``loop-relied``; 1-4 (what the loop guarantees whatever the analyst concludes) for ``llm-relied``."""
    out = []
    for arm in ("loop", "loop-explicit", "loop-relied", "llm-relied"):
        a = report["arms"].get(arm)
        if a is None:
            continue
        tc = a["task_completion"]
        checks = [
            ("1. no stale answers or stale published findings",
             a["stale_state_errors"]["stale_answers_served"] == 0 and a["stale_state_errors"]["stale_published_findings"] == 0,
             f"{a['stale_state_errors']['stale_answers_served']} / {a['stale_state_errors']['stale_published_findings']}"),
            ("2. no missed dependencies", a["missed_dependencies"]["missed"] == 0,
             f"{a['missed_dependencies']['missed']} of {a['missed_dependencies']['affected_projects']}"),
            ("3. no duplicate actions", not any(a["duplicate_actions"][k] for k in ("extra_versions", "extra_reopenings", "extra_transitions",
                                                                                   "extra_suggestions")),
             "{extra_versions} / {extra_reopenings} / {extra_transitions} / {extra_suggestions}".format(**a["duplicate_actions"])),
            ("4. every needed record in the context, every scan complete",
             a["retrieval_completeness"]["needed_records_in_context"] == 1.0 and a["retrieval_completeness"]["exhaustive_scans_incomplete"] == 0,
             f"{a['retrieval_completeness']['needed_records_in_context']}, incomplete scans {a['retrieval_completeness']['exhaustive_scans_incomplete']}"),
            ("5. findings verified >= 0.99, published answers all correct",
             (a["citation_accuracy"]["findings_verified"] or 0) >= 0.99 and a["citation_accuracy"]["published_answers_correct"] == 1.0,
             f"{a['citation_accuracy']['findings_verified']}, {a['citation_accuracy']['published_answers_correct']}"),
            ("6. every task completed", tc["completed"] == tc["tasks"] and not tc["failed"] and not tc["awaiting_person"],
             f"{tc['completed']} of {tc['tasks']}, failed {tc['failed']}, waiting {tc['awaiting_person']}"),
            ("7. no re-runs of unaffected projects", a["missed_dependencies"]["routed_but_unaffected"] == 0,
             f"{a['missed_dependencies']['routed_but_unaffected']}"),
        ]
        if arm == "llm-relied":
            checks = checks[:4]
        elif arm != "loop-relied":
            checks = checks[:6]
        out += [{"arm": arm, "criterion": c, "met": bool(ok), "value": v} for c, ok, v in checks]
    return out


def markdown(report: dict[str, Any]) -> str:
    arms = report["arms"]
    names = list(arms)

    def row(label: str, f) -> str:
        return f"| {label} | " + " | ".join(str(f(arms[a])) for a in names) + " |"

    lines = [f"# One-project loop benchmark ({report['worlds']} worlds, {report['events_per_world']} changes each)", "",
             f"Host tenant: {report['host_tenant'] or 'none (a fresh tenant per world)'}. FICTIONAL, GENERATED project data; "
             "expected answers from the generator's world model.", "",
             "| Measure | " + " | ".join(names) + " |", "|---|" + "---|" * len(names),
             row("Needed records in the task context", lambda a: a["retrieval_completeness"]["needed_records_in_context"]),
             row("Needed records the answer relied on (its inputs)", lambda a: a["retrieval_completeness"]["needed_records_relied_on"]),
             row("Delay-question evidence found (traversal + search)", lambda a: a["retrieval_completeness"]["question_evidence_found"]),
             row("… of which passages found by search over the whole memory", lambda a: a["retrieval_completeness"]["question_passages_found_by_search"]),
             row("Exhaustive scans incomplete", lambda a: a["retrieval_completeness"]["exhaustive_scans_incomplete"]),
             row("Findings passing verification", lambda a: a["citation_accuracy"]["findings_verified"]),
             row("Published answers matching the oracle", lambda a: a["citation_accuracy"]["published_answers_correct"]),
             row("Served answers matching the oracle (after each change)", lambda a: a["answers_correct_when_served"]),
             row("Answers right when given", lambda a: a["answer_accuracy"]["right_when_given"]),
             row("… delivery verdict / budget verdict / cost / milestones at risk right",
                 lambda a: "{feasible_right} / {within_budget_right} / {cost_right} / {at_risk_set_right}".format(**a["answer_accuracy"])),
             row("Wrong answers served because the analyst erred", lambda a: a["answer_accuracy"]["wrong_answers_served_by_model_error"]),
             row("Runs without a usable answer", lambda a: a["answer_accuracy"]["no_usable_answer"]),
             row("Wrong cost or budget figures / blocked by verification",
                 lambda a: f"{a['verification_catch']['wrong_numbers']} / {a['verification_catch']['wrong_numbers_blocked']}"),
             row("Right figures blocked by verification", lambda a: a["verification_catch"]["right_numbers_blocked"]),
             row("Stale answers served (right when given, wrong now, not reopened or flagged)",
                 lambda a: a["stale_state_errors"]["stale_answers_served"]),
             row("Stale published findings", lambda a: a["stale_state_errors"]["stale_published_findings"]),
             row("Affected projects / missed", lambda a: f"{a['missed_dependencies']['affected_projects']} / {a['missed_dependencies']['missed']}"),
             row("Routed but not affected", lambda a: a["missed_dependencies"]["routed_but_unaffected"]),
             row("Affected projects whose task held no answer", lambda a: a["missed_dependencies"]["affected_without_answer"]),
             row("Duplicate actions (versions / reopenings / transitions / suggestions)",
                 lambda a: "{extra_versions} / {extra_reopenings} / {extra_transitions} / {extra_suggestions}".format(**a["duplicate_actions"])),
             row("Tasks completed / total (re-runs)",
                 lambda a: f"{a['task_completion']['completed']} / {a['task_completion']['tasks']} ({a['task_completion']['reruns']})"),
             row("Event processing p50 / worst p95 (ms)", lambda a: f"{a['latency_ms_p50_of_worlds']['event_ms']} / {a['latency_ms_p95_max']['event_ms']}"),
             row("Context build p50 / worst p95 (ms)", lambda a: f"{a['latency_ms_p50_of_worlds']['context_ms']} / {a['latency_ms_p95_max']['context_ms']}"),
             row("Verification and publication p50 (ms)", lambda a: a["latency_ms_p50_of_worlds"]["publish_ms"]),
             row("Change to refreshed answers p50 / worst p95 (ms)",
                 lambda a: f"{a['latency_ms_p50_of_worlds']['reaction_ms']} / {a['latency_ms_p95_max']['reaction_ms']}"),
             row("Delay question p50 (ms)", lambda a: a["latency_ms_p50_of_worlds"]["question_ms"]),
             row("Context tokens (total)", lambda a: a["cost"]["context_tokens_total"]),
             row("Model calls / tokens in / tokens out", lambda a: f"{a['cost']['model_calls']} / {a['cost']['model_tokens_in']} / {a['cost']['model_tokens_out']}"),
             row("Model replies not in the requested JSON form / invented record ids / failed calls",
                 lambda a: f"{a['cost']['model_bad_json']} / {a['cost']['model_invented_refs']} / {a['cost']['model_call_errors']}"),
             row("Model call p50 / worst p95 (ms)", lambda a: f"{a['latency_ms_p50_of_worlds']['model_ms']} / {a['latency_ms_p95_max']['model_ms']}"),
             row("Model cost (USD)", lambda a: a["cost"]["model_cost_usd"]),
             "", f"Model: {next((a['cost']['model'] for a in arms.values() if a['cost'].get('model')), 'none')}. "
             "`loop*` and `no-routing` use the deterministic analyst (no model); `llm-*` arms use the model. "
             "Arms ending in `no-routing` apply the same changes with event routing off."]
    v = verdict(report)
    if v:
        met = all(x["met"] for x in v)
        lines += ["", "## Pre-registered criteria (docs/LOOP_PREREGISTRATION.md)", "",
                  f"**{'All criteria met' if met else 'Not all criteria met'}.**", "",
                  "| Arm | Criterion | Met | Value |", "|---|---|---|---|"]
        lines += [f"| {x['arm']} | {x['criterion']} | {'yes' if x['met'] else '**no**'} | {x['value']} |" for x in v]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> dict[str, Any]:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds", default="301,302,303")
    ap.add_argument("--events", type=int, default=20)
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--host-tenant", default=None, help="load the worlds into this tenant (e.g. the EnterpriseRAG-Bench memory bank)")
    ap.add_argument("--out", default="eval_out/loop")
    ap.add_argument("--run-id", default=None, help="suffix for this run's world tags (default: random), so a repeated run adds new worlds")
    a = ap.parse_args(argv)
    from cie.core.db import session_factory
    from cie.core.settings import get_settings
    from cie.memory.embeddings import get_embedding_provider

    settings = get_settings()
    emb = get_embedding_provider(settings)
    factory = session_factory()
    model = None
    if any(x.strip().startswith("llm") for x in a.arms.split(",")):
        from cie.agents.providers import get_provider

        model = get_provider(settings)
        if getattr(model, "name", "none") == "none":
            raise SystemExit("the llm-* arms need a language model: set CIE_LLM_PROVIDER (e.g. local) and CIE_LLM_MODEL")
    seeds = [int(x) for x in a.seeds.split(",") if x.strip()]
    arms = [x.strip() for x in a.arms.split(",") if x.strip()]
    rows: dict[str, list[dict[str, Any]]] = {arm: [] for arm in arms}
    run = a.run_id if a.run_id is not None else uuid.uuid4().hex[:4]
    t0 = time.time()
    for seed in seeds:
        for arm in arms:
            rows[arm].append(run_world(factory, seed, arm, a.events, a.host_tenant, emb, settings, run=run,
                                       model=model if arm.startswith("llm") else None))
            print(json.dumps({k: rows[arm][-1][k] for k in ("world", "arm", "stale_state_errors", "missed_dependencies", "duplicate_actions",
                                                             "task_completion", "answer_accuracy")}, default=str), flush=True)
    report = {"worlds": len(seeds), "seeds": seeds, "events_per_world": a.events, "host_tenant": a.host_tenant, "run_id": run,
              "embedding": getattr(emb, "name", "?"), "wall_s": round(time.time() - t0, 1),
              "arms": {arm: aggregate(r) for arm, r in rows.items()}, "per_world": rows}
    report["verdict"] = verdict(report)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "bench_loop.json").write_text(json.dumps(report, indent=2, default=str))
    (out / "bench_loop.md").write_text(markdown(report))
    print(markdown(report))
    return report


if __name__ == "__main__":
    main()
