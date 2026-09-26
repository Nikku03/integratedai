"""Controlled, versioned dependency dataset for REM change-impact and evidence tests.

FICTIONAL, GENERATED DATA. A seeded generator builds a small company (projects, milestones, suppliers, products,
orders, stock, tasks, penalty clauses, generated summaries, distractor passages) and a sequence of change events.

The expected results are computed by the oracle in this module, from the generator's own world model, by an
implementation written separately from ``cie.rem`` (this module imports nothing from it). The oracle encodes the
business definitions, not the rule engine's code:

* a milestone is exposed when, for some product it needs, stock held by its project plus open orders promised
  by its due date plus slack is less than the quantity needed; it is covered when some order for it is late
  but stock and on-time orders still cover every need; an earlier assessment is resolved when neither holds
  any more. Only milestones whose inputs the event touched are re-assessed.
* an exposed milestone puts its project at risk, asks review of open tasks that truly depend on it (including
  tasks in other projects) and of penalty clauses that govern it.
* summaries generated from a changed or deleted order are out of date; a completed task unblocks tasks whose
  other blockers are done; a changed clause asks review of the milestones it governs; a deleted order asks
  review of the milestones that relied on it.

Simplification shared by oracle and rules: stock is not allocated between milestones (the generator never has
two milestones of one project needing the same product). Answer keys are written outside the searchable corpus.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

BASE = date(2026, 11, 1)
GREEK = ["Aster", "Birch", "Cedar", "Dune", "Ember", "Fjord", "Garnet", "Heron", "Iris", "Juniper", "Kelp", "Lumen",
         "Moraine", "Nectar", "Onyx", "Pumice"]
PARTS = ["sensor module", "power board", "valve body", "gear set", "display panel", "battery pack", "pump housing",
         "control cable", "relay unit", "heat sink", "fan assembly", "encoder disc"]
SUPPLIERS = ["Arden Metals", "Brisk Circuits", "Corvid Castings", "Delta Fasteners", "Eider Optics", "Fulmar Plastics",
             "Grebe Electronics", "Harrier Forge"]
PEOPLE = ["R. Okafor", "L. Chen", "M. Duarte", "S. Varga", "T. Nakamura", "A. Haddad"]


@dataclass
class Order:
    key: str
    project: str
    milestone: str
    product: str
    supplier: str
    qty: int
    promised: date
    status: str = "open"
    deleted: bool = False


@dataclass
class Milestone:
    key: str
    project: str
    name: str
    due: date
    slack: int
    needs: dict[str, int]
    governed_by: list[str] = field(default_factory=list)


@dataclass
class Task:
    key: str
    project: str
    name: str
    depends_on: list[str]  # true dependencies (milestone keys), explicit in the tracker
    inferred: list[tuple[str, bool]] = field(default_factory=list)  # (milestone, is it really a dependency?)
    blocks: list[str] = field(default_factory=list)
    status: str = "open"


class World:
    """The generator's world model. ``ops()`` renders it as source records; ``events()`` yields change events with
    their expected impacts, computed by the oracle on this model."""

    def __init__(self, seed: int, n_projects: int = 12, n_events: int = 12):
        self.seed = seed
        self.rng = random.Random(seed)
        rng = self.rng
        self.n_events = n_events
        self.company = f"Synthetic Co {seed}"
        self.projects: dict[str, dict[str, Any]] = {}
        for i in range(n_projects):
            k = f"prj{i:02d}"
            self.projects[k] = {"name": f"Project {GREEK[i % len(GREEK)]} {i:02d}", "dept": "Operations" if i % 2 == 0 else "Engineering",
                                "owner": rng.choice(PEOPLE)}
        self.products = {f"prd{i:02d}": f"{p} P{i:02d}" for i, p in enumerate(PARTS[:10])}
        self.suppliers = {f"sup{i:02d}": f"{s} (fictional)" for i, s in enumerate(SUPPLIERS[:6])}
        self.sources: dict[str, list[str]] = {p: rng.sample(sorted(self.suppliers), rng.choice([1, 2])) for p in self.products}
        self.milestones: dict[str, Milestone] = {}
        self.orders: dict[str, Order] = {}
        self.stock: dict[tuple[str, str], int] = {}
        self.tasks: dict[str, Task] = {}
        self.reqs: dict[str, dict[str, Any]] = {}
        self.summaries: dict[str, list[str]] = {}
        n_order = 1000
        for pk in self.projects:
            used_products: set[str] = set()
            for j in range(rng.randint(2, 3)):
                mk = f"{pk}-m{j}"
                prods = [p for p in rng.sample(sorted(self.products), 2) if p not in used_products][: rng.choice([1, 1, 2])]
                if not prods:
                    continue
                used_products |= set(prods)
                due = BASE + timedelta(days=rng.randint(12, 50))
                m = Milestone(mk, pk, f"{self.projects[pk]['name']} milestone {j + 1}", due, rng.choice([0, 0, 0, 3, 5, 7]),
                              {p: rng.randint(10, 60) for p in prods})
                self.milestones[mk] = m
                for p, qty in m.needs.items():
                    stock = 0 if rng.random() < 0.55 else rng.randint(5, qty + 20)
                    self.stock[(pk, p)] = stock
                    split = rng.random() < 0.25 and len(self.sources[p]) > 1
                    parts = [(self.sources[p][0], qty - qty // 3), (self.sources[p][1], qty // 3)] if split else [(rng.choice(self.sources[p]), qty)]
                    for sup, q in parts:
                        n_order += 1
                        ok = f"PO-{seed}{n_order}"
                        self.orders[ok] = Order(ok, pk, mk, p, sup, q, due - timedelta(days=rng.randint(3, 20)))
                if rng.random() < 0.3:
                    rk = f"{mk}-clause"
                    self.reqs[rk] = {"milestone": mk, "contract": f"contract-{pk}", "rate": f"{rng.choice([1, 1.5, 2])}% per week"}
                    m.governed_by.append(rk)
        tnum = 0
        ms = sorted(self.milestones)
        for mk in ms:
            m = self.milestones[mk]
            for _ in range(rng.randint(1, 3)):
                tnum += 1
                tk = f"task{seed}-{tnum:03d}"
                self.tasks[tk] = Task(tk, m.project, f"{rng.choice(['Assemble', 'Test', 'Install', 'Inspect', 'Ship'])} units for {m.name}", [mk])
        keys = sorted(self.tasks)
        for tk in keys:
            t = self.tasks[tk]
            if rng.random() < 0.15:  # cross-project dependency
                other = rng.choice([x for x in ms if self.milestones[x].project != t.project])
                t.depends_on.append(other)
            if rng.random() < 0.08:  # a dependency proposed by a model from chat; half are wrong
                other = rng.choice([x for x in ms if x not in t.depends_on])
                t.inferred.append((other, rng.random() < 0.5))
            if rng.random() < 0.25:
                same = [x for x in keys if x != tk and self.tasks[x].project == t.project]
                if same:
                    t.blocks.append(rng.choice(same))  # may form cycles; the engine must terminate
        for pk in self.projects:
            self.summaries[f"summary-{pk}"] = [o.key for o in self.orders.values() if o.project == pk]
        self.assess: dict[str, str | None] = {m: None for m in self.milestones}
        self.invalidated: set[str] = set()

    # ------------------------------------------------------------------ rendering as source records
    def scopes(self) -> list[dict[str, Any]]:
        out = [{"name": self.company, "kind": "company"}]
        out += [{"name": f"{d} {self.seed}", "kind": "department", "parent": self.company} for d in ("Operations", "Engineering", "Legal")]
        out += [{"name": p["name"], "kind": "project", "parent": f"{p['dept']} {self.seed}"} for p in self.projects.values()]
        return out

    def _scope(self, pk: str) -> str:
        return self.projects[pk]["name"]

    def order_text(self, o: Order) -> str:
        return (f"{o.key}: {o.qty} units of {self.products[o.product]} from {self.suppliers[o.supplier]}, promised delivery "
                f"{o.promised.isoformat()}, for {self.projects[o.project]['name']}.")

    def order_ops(self, o: Order) -> list[dict[str, Any]]:
        sc = self._scope(o.project)
        return [
            {"op": "upsert_node", "type": "order", "key": o.key, "name": o.key, "scope": sc, "project_keys": [o.project],
             "summary": f"{o.qty} x {self.products[o.product]} from {self.suppliers[o.supplier]}",
             "attrs": {"product": o.product, "supplier": o.supplier, "qty": o.qty, "promised_date": o.promised.isoformat(),
                       "status": o.status, "source_system": "erp"},
             "source_pointers": [{"system": "erp", "record": o.key}], "verification": "verified", "root_sources": [f"erp:{o.key}"]},
            {"op": "upsert_node", "type": "passage", "key": f"{o.key}#text", "name": f"Purchase order {o.key}", "scope": sc,
             "project_keys": [o.project], "summary": self.order_text(o), "attrs": {"source_system": "erp"},
             "source_pointers": [{"system": "synthetic-docs", "document": f"po-{o.key}.txt", "char_start": 0,
                                  "char_end": len(self.order_text(o))}], "root_sources": [f"erp:{o.key}"]},
            {"op": "upsert_edge", "src": ["passage", f"{o.key}#text"], "kind": "supports", "dst": ["order", o.key]},
            {"op": "upsert_edge", "src": ["order", o.key], "kind": "depends_on", "dst": ["supplier", o.supplier]},
            {"op": "upsert_edge", "src": ["milestone", o.milestone], "kind": "depends_on", "dst": ["order", o.key]},
        ]

    def ops(self) -> list[dict[str, Any]]:
        ops: list[dict[str, Any]] = []
        for pk, p in self.projects.items():
            ops.append({"op": "upsert_node", "type": "project", "key": pk, "name": p["name"], "scope": self._scope(pk),
                        "attrs": {"source_system": "project_tracker"}, "source_pointers": [{"system": "project_tracker", "record": pk}]})
        for name in PEOPLE:
            ops.append({"op": "upsert_node", "type": "person", "key": name, "name": name, "scope": self.company})
        for sk, name in self.suppliers.items():
            ops.append({"op": "upsert_node", "type": "supplier", "key": sk, "name": name, "scope": self.company,
                        "attrs": {"source_system": "erp"}, "source_pointers": [{"system": "erp", "record": sk}]})
        for pk_, name in self.products.items():
            ops.append({"op": "upsert_node", "type": "product", "key": pk_, "name": name, "scope": self.company,
                        "attrs": {"source_system": "erp"}, "source_pointers": [{"system": "erp", "record": pk_}]})
        for mk, m in self.milestones.items():
            ops.append({"op": "upsert_node", "type": "milestone", "key": mk, "name": m.name, "scope": self._scope(m.project),
                        "project_keys": [m.project], "attrs": {"due_date": m.due.isoformat(), "slack_days": m.slack,
                                                               "source_system": "project_tracker"},
                        "source_pointers": [{"system": "project_tracker", "record": mk}], "verification": "verified"})
        for tk, t in self.tasks.items():
            ops.append({"op": "upsert_node", "type": "task", "key": tk, "name": t.name, "scope": self._scope(t.project),
                        "project_keys": [t.project], "attrs": {"status": t.status, "source_system": "project_tracker"},
                        "source_pointers": [{"system": "project_tracker", "record": tk}]})
        for rk, r in self.reqs.items():
            legal = f"Legal {self.seed}"
            ops += [{"op": "upsert_node", "type": "contract", "key": r["contract"], "name": f"Customer agreement for {self.projects[self.milestones[r['milestone']].project]['name']}",
                     "scope": legal, "sensitivity": 3, "attrs": {"source_system": "contract_repository"},
                     "source_pointers": [{"system": "contract_repository", "record": r["contract"]}]},
                    {"op": "upsert_node", "type": "requirement", "key": rk, "name": f"Late-delivery penalty clause for {self.milestones[r['milestone']].name}",
                     "scope": legal, "sensitivity": 3, "attrs": {"kind": "late_delivery_penalty", "rate": r["rate"], "source_system": "contract_repository"},
                     "source_pointers": [{"system": "contract_repository", "record": r["contract"], "clause": rk}], "verification": "verified"},
                    {"op": "upsert_node", "type": "passage", "key": f"{rk}#text", "name": "Penalty clause text", "scope": legal, "sensitivity": 3,
                     "summary": f"CONFIDENTIAL-CLAUSE: a penalty of {r['rate']} applies if {self.milestones[r['milestone']].name} is late.",
                     "source_pointers": [{"system": "synthetic-docs", "document": f"{r['contract']}.txt"}], "root_sources": [f"doc:{r['contract']}"]}]
        for sk, prods in [(s, [p for p, ss in self.sources.items() if s in ss]) for s in self.suppliers]:
            ops += [{"op": "upsert_edge", "src": ["supplier", sk], "kind": "supplies", "dst": ["product", p]} for p in prods]
        for o in self.orders.values():
            ops += self.order_ops(o)
        for mk, m in self.milestones.items():
            ops.append({"op": "upsert_edge", "src": ["project", m.project], "kind": "depends_on", "dst": ["milestone", mk]})
            ops += [{"op": "upsert_edge", "src": ["milestone", mk], "kind": "depends_on", "dst": ["product", p], "attrs": {"qty": q}}
                    for p, q in m.needs.items()]
            ops += [{"op": "upsert_edge", "src": ["milestone", mk], "kind": "governed_by", "dst": ["requirement", rk]} for rk in m.governed_by]
        for rk, r in self.reqs.items():
            ops += [{"op": "upsert_edge", "src": ["requirement", rk], "kind": "derived_from", "dst": ["contract", r["contract"]]},
                    {"op": "upsert_edge", "src": ["passage", f"{rk}#text"], "kind": "supports", "dst": ["requirement", rk]}]
        for tk, t in self.tasks.items():
            ops += [{"op": "upsert_edge", "src": ["task", tk], "kind": "depends_on", "dst": ["milestone", mk]} for mk in t.depends_on]
            ops += [{"op": "upsert_edge", "src": ["task", tk], "kind": "depends_on", "dst": ["milestone", mk], "provenance": "inferred",
                     "derivation": {"model": "relation-extractor (synthetic)", "source": "chat"}} for mk, _ in t.inferred]
            ops += [{"op": "upsert_edge", "src": ["task", tk], "kind": "blocks", "dst": ["task", b]} for b in t.blocks]
        for pk, p in self.projects.items():
            ops.append({"op": "upsert_edge", "src": ["project", pk], "kind": "owned_by", "dst": ["person", p["owner"]]})
        for sk, orders in self.summaries.items():
            pk = sk.removeprefix("summary-")
            ops.append({"op": "upsert_node", "type": "artifact", "key": sk, "name": f"Generated supply summary for {self.projects[pk]['name']}",
                        "scope": self._scope(pk), "project_keys": [pk], "authoritative": False,
                        "summary": f"All deliveries for {self.projects[pk]['name']} are on schedule.", "attrs": {"source_system": "generated"},
                        "root_sources": [f"erp:{o}" for o in orders]})
            ops += [{"op": "upsert_edge", "src": ["artifact", sk], "kind": "derived_from", "dst": ["order", o]} for o in orders]
        rng = random.Random(self.seed * 7 + 1)
        for i in range(40):  # distractors: they name suppliers, products and projects but support nothing
            p, s, pk = rng.choice(sorted(self.products)), rng.choice(sorted(self.suppliers)), rng.choice(sorted(self.projects))
            text = rng.choice([f"Quarterly quality review: {self.suppliers[s]} passed the audit for {self.products[p]}.",
                               f"Meeting notes: {self.projects[pk]['name']} discussed test results for {self.products[p]}.",
                               f"Price list update from {self.suppliers[s]}: {self.products[p]} unit price unchanged."])
            ops.append({"op": "upsert_node", "type": "passage", "key": f"noise-{i}", "name": f"Note {i}", "scope": self.company,
                        "summary": text, "attrs": {"source_system": "document"},
                        "source_pointers": [{"system": "synthetic-docs", "document": f"note-{i}.txt"}], "root_sources": [f"doc:note-{i}"]})
        for (pk, p), q in self.stock.items():
            ops.append({"op": "set_stock", "product": p, "holder": ["project", pk], "on_hand": q, "reserved": 0, "scope": self._scope(pk),
                        "source_pointers": [{"system": "inventory", "record": f"{pk}/{p}"}]})
        return ops

    def restricted_keys(self) -> set[tuple[str, str]]:
        out = set()
        for rk, r in self.reqs.items():
            out |= {("requirement", rk), ("contract", r["contract"]), ("passage", f"{rk}#text")}
        return out

    # ------------------------------------------------------------------ oracle
    def _status(self, mk: str) -> str | None:
        m = self.milestones[mk]
        limit = m.due + timedelta(days=m.slack)
        late_any, short = False, False
        for p, qty in m.needs.items():
            mine = [o for o in self.orders.values() if o.milestone == mk and o.product == p and o.status == "open" and not o.deleted]
            late = [o for o in mine if o.promised > limit]
            supply = self.stock.get((m.project, p), 0) + sum(o.qty for o in mine if o not in late)
            late_any = late_any or bool(late)
            short = short or supply < qty
        return "at_risk" if short else ("covered" if late_any else None)

    def _assess(self, touched: set[str], expected: set[tuple[str, str]]) -> None:
        for mk in sorted(touched):
            st = self._status(mk)
            if st is None:
                if self.assess[mk] is not None:
                    expected.add((f"milestone:{mk}", "resolved"))
                self.assess[mk] = None
                continue
            self.assess[mk] = st
            expected.add((f"milestone:{mk}", st))
            if st != "at_risk":
                continue
            m = self.milestones[mk]
            expected.add((f"project:{m.project}", "at_risk"))
            for t in self.tasks.values():
                if t.status != "done" and (mk in t.depends_on or (mk, True) in t.inferred):
                    expected.add((f"task:{t.key}", "needs_review"))
            for rk in m.governed_by:
                expected.add((f"requirement:{rk}", "needs_review"))

    def _invalidate_for(self, order_keys: set[str], expected: set[tuple[str, str]]) -> None:
        for sk, orders in self.summaries.items():
            if set(orders) & order_keys:
                expected.add((f"artifact:{sk}", "invalidated"))
                self.invalidated.add(sk)

    def events(self) -> list[dict[str, Any]]:
        """Generate the event sequence, applying each to the world model and recording the oracle's expectation."""
        rng = random.Random(self.seed * 13 + 5)
        out = []
        kinds = ["delay"] * 7 + ["stock"] * 3 + ["alt"] * 3 + ["done"] * 2 + ["clause"] * 2 + ["cancel", "delete", "due"]
        n_alt = 0
        for i in range(self.n_events):
            kind = rng.choice(kinds)
            expected: set[tuple[str, str]] = set()
            open_orders = [o for o in self.orders.values() if o.status == "open" and not o.deleted]
            ev: dict[str, Any]
            if kind == "delay" and open_orders:
                o0 = rng.choice(open_orders)
                s, p = o0.supplier, o0.product
                pool = [o for o in open_orders if o.supplier == s and o.product == p]
                new = max(o.promised for o in pool) + timedelta(days=rng.randint(5, 30))
                hit = [o for o in pool if o.promised < new]
                notice = f"notice-{self.seed}-{i}"
                text = f"{self.suppliers[s]} notice: shipments of {self.products[p]} are delayed; the new delivery date is {new.isoformat()}."
                ops = [{"op": "upsert_node", "type": "passage", "key": notice, "name": f"Delay notice from {self.suppliers[s]}", "scope": self.company,
                        "summary": text, "attrs": {"source_system": "email"}, "root_sources": [f"doc:{notice}"],
                        "source_pointers": [{"system": "synthetic-docs", "document": f"{notice}.eml"}]}]
                ops += [{"op": "upsert_edge", "src": ["passage", notice], "kind": "supports", "dst": ["order", o.key]} for o in hit]
                ev = {"kind": "supplier_delay", "payload": {"supplier": s, "product": p, "new_date": new.isoformat(), "ops": ops},
                      "question": {"text": f"Which projects are affected by the {self.products[p]} delivery delay from {self.suppliers[s]}?",
                                   "gold_projects": sorted({o.project for o in hit}),
                                   "gold_evidence": sorted({f"passage:{o.key}#text" for o in hit} | {f"order:{o.key}" for o in hit} | {f"passage:{notice}"})}}
                for o in hit:
                    o.promised = new
                self._invalidate_for({o.key for o in hit}, expected)
                self._assess({o.milestone for o in hit}, expected)
            elif kind == "stock":
                (pk, p), _ = rng.choice(sorted(self.stock.items()))
                mk = next(m.key for m in self.milestones.values() if m.project == pk and p in m.needs)
                q = rng.randint(0, self.milestones[mk].needs[p])
                if q == self.stock[(pk, p)]:
                    continue  # an unchanged count is not a change
                self.stock[(pk, p)] = q
                ev = {"kind": "stock_count", "payload": {"product": p, "holder": ["project", pk], "on_hand": q, "reserved": 0,
                                                         "scope": self._scope(pk), "source_pointers": [{"system": "inventory", "record": f"{pk}/{p}"}]}}
                self._assess({mk}, expected)
            elif kind == "alt":
                risky = sorted(m for m, st in self.assess.items() if st == "at_risk") or sorted(self.milestones)
                mk = rng.choice(risky)
                m = self.milestones[mk]
                p = rng.choice(sorted(m.needs))
                n_alt += 1
                o = Order(f"PO-{self.seed}9{n_alt:03d}", m.project, mk, p, rng.choice(sorted(self.suppliers)), m.needs[p],
                          m.due - timedelta(days=rng.randint(1, 5)))
                self.orders[o.key] = o
                ev = {"kind": "ops", "payload": {"ops": self.order_ops(o)}}
                self._assess({mk}, expected)
            elif kind == "done":
                cands = sorted(t.key for t in self.tasks.values() if t.blocks and t.status == "open")
                if not cands:
                    continue
                tk = rng.choice(cands)
                self.tasks[tk].status = "done"
                ev = {"kind": "task_status", "payload": {"task": tk, "status": "done"}}
                for b in self.tasks[tk].blocks:
                    blockers = [t for t in self.tasks.values() if b in t.blocks and t.key != tk]
                    if all(t.status == "done" for t in blockers):
                        expected.add((f"task:{b}", "unblocked"))
            elif kind == "clause" and self.reqs:
                rk = rng.choice(sorted(self.reqs))
                self.reqs[rk]["rate"] = f"{rng.choice([2.5, 3, 4])}% per week"
                ev = {"kind": "ops", "payload": {"ops": [{"op": "revise_node", "ref": ["requirement", rk], "attrs": {"rate": self.reqs[rk]["rate"]}}]}}
                expected.add((f"milestone:{self.reqs[rk]['milestone']}", "needs_review"))
            elif kind in ("cancel", "delete") and open_orders:
                o = rng.choice(open_orders)
                if kind == "cancel":
                    o.status = "cancelled"
                    ev = {"kind": "ops", "payload": {"ops": [{"op": "revise_node", "ref": ["order", o.key], "attrs": {"status": "cancelled"}}]}}
                    self._invalidate_for({o.key}, expected)
                else:
                    o.deleted = True
                    ev = {"kind": "ops", "payload": {"ops": [{"op": "delete_node", "ref": ["order", o.key]}]}}
                    self._invalidate_for({o.key}, expected)
                    expected.add((f"milestone:{o.milestone}", "needs_review"))
                    self.summaries = {k: [x for x in v if x != o.key] for k, v in self.summaries.items()}
                self._assess({o.milestone}, expected)
            elif kind == "due":
                mk = rng.choice(sorted(self.milestones))
                m = self.milestones[mk]
                m.due = m.due - timedelta(days=rng.randint(3, 15))
                ev = {"kind": "ops", "payload": {"ops": [{"op": "revise_node", "ref": ["milestone", mk], "attrs": {"due_date": m.due.isoformat()}}]}}
                self._assess({mk}, expected)
            else:
                continue
            ev["key"] = f"synthetic-{self.seed}-{i}"
            ev["expected"] = sorted(f"{t}|{imp}" for t, imp in expected)
            ev["current_at_risk"] = sorted(f"milestone:{m}" for m, st in self.assess.items() if st == "at_risk")
            out.append(ev)
        return out

    def extra_questions(self) -> list[dict[str, Any]]:
        """Questions about the final state (asked after all events)."""
        rng = random.Random(self.seed * 31 + 7)
        qs = []
        for mk in rng.sample(sorted(self.milestones), 3):
            m = self.milestones[mk]
            live = [o for o in self.orders.values() if o.milestone == mk and not o.deleted]
            qs.append({"text": f"What is the supply status of {m.name}?", "kind": "milestone_status",
                       "gold_evidence": sorted({f"order:{o.key}" for o in live} | {f"passage:{o.key}#text" for o in live} | {f"milestone:{mk}"})})
        cross = [t for t in self.tasks.values() if len(t.depends_on) > 1]
        for t in rng.sample(cross, min(2, len(cross))):
            gold = {f"milestone:{mk}" for mk in t.depends_on}
            gold |= {f"order:{o.key}" for o in self.orders.values() if o.milestone in t.depends_on and not o.deleted}
            qs.append({"text": f"What does the task '{t.name}' depend on?", "kind": "task_dependencies", "gold_evidence": sorted(gold)})
        return qs


def split_seeds(split: str) -> list[int]:
    """Development seeds are for building and debugging; held-out seeds are run once, with frozen settings."""
    return [1, 2, 3, 4] if split == "dev" else [101, 102, 103, 104, 105, 106]
