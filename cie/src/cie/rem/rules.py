"""Explicit dependency rules for change mode.

A rule fires on a trigger (a changed record, or an impact another rule produced) and may emit impacts on specific
records. Nothing is affected merely because it is connected: each rule states the business condition under
which a consequence follows, and records the inputs it read.

R0 value conflict      a claim states a value that differs from the record it is about -> ``contradicts`` edge
                       (rule-derived); if the record is a later system-of-record statement, ``supersedes`` too.
R1 supply exposure     a milestone needing product P is exposed only if an order it relies on now arrives after
                       the milestone's due date plus slack AND inventory on hand plus on-time orders (alternatives)
                       do not cover the quantity needed. Otherwise the milestone is ``covered``.
R2 dependents          a milestone at risk puts its project at risk and asks review of tasks depending on it.
R3 penalty exposure    a milestone at risk that is governed by a penalty requirement -> finance and contract review.
R4 derived content     records derived from a changed record: generated summaries are invalidated, authoritative
                       derived records need review. Transitive over ``derived_from`` only.
R5 unblocking          a completed task unblocks the tasks it blocked once no other open blocker remains.
R6 contract change     records governed by a changed contract or requirement need review.
R7 deletion            records that depend on, or are derived from, a deleted record need review.
R8 revocation          when a record becomes more restricted, derived summaries are invalidated (they could carry
                       its content to a wider audience); cached results are marked stale by the caller.

Termination: impacts are keyed by (target, impact); a rule is applied at most once per (rule, target, trigger),
so cycles in the graph cannot loop and several paths to the same target merge into one impact whose paths are
all kept but whose confidence is not raised.
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from cie.rem import domain
from cie.rem.budget import Budget
from cie.rem.store import GraphReader, GraphWriter, NodeView

CONTENT_FIELDS = ("name", "summary", "attrs", "source_pointers")


@dataclass
class ImpactDraft:
    target: uuid.UUID
    impact: str  # at_risk | covered | needs_review | invalidated | unblocked | resolved | affected
    rule_id: str
    reason: str
    confidence: float
    paths: list[list[dict[str, Any]]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    hypothesis: bool = False
    requires: set[uuid.UUID] = field(default_factory=set)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SuggestionDraft:
    key: str
    title: str
    capability: str
    targets: list[uuid.UUID]
    reason: str
    priority: float
    rule_id: str
    requires: set[uuid.UUID] = field(default_factory=set)
    roots: set[str] = field(default_factory=set)  # milestones whose supply assessment this follows from
    requires_scopes: list[list[Any]] = field(default_factory=list)  # [scope, clearance] of exact values shown


def _hop(kind: str, frm: uuid.UUID, to: uuid.UUID, edge_id=None, provenance: str = "explicit", hypothesis: bool = False):
    return {"edge_id": str(edge_id) if edge_id else None, "kind": kind, "provenance": provenance, "from": str(frm),
            "to": str(to), "hypothesis": hypothesis}


def _ev(node: NodeView, what: str) -> dict[str, Any]:
    return {"node_id": str(node.id), "type": node.type, "key": node.key, "version": node.version, "name": node.name,
            "what": what, "source_pointers": node.source_pointers, "authoritative": node.authoritative}


def _grade(nodes: list[NodeView], hypothesis: bool) -> float:
    """Input-quality grade, not a probability: 1.0 when every input is an authoritative, verified or system-of-record
    record; 0.7 when some input is unverified or rule-derived; 0.4 when an unverified inferred relationship is used."""
    if hypothesis:
        return 0.4
    for n in nodes:
        if not n.authoritative or n.verification in ("disputed", "rejected"):
            return 0.5
        if n.verification != "verified" and str(n.attrs.get("source_system")) not in domain.SYSTEM_OF_RECORD:
            return 0.7
    return 1.0


class RuleEngine:
    def __init__(self, reader: GraphReader, writer: GraphWriter | None, budget: Budget, *, max_derived_depth: int = 4):
        self.r = reader
        self.w = writer
        self.budget = budget
        self.max_derived_depth = max_derived_depth
        self.impacts: dict[tuple[uuid.UUID, str], ImpactDraft] = {}
        self.suggestions: dict[str, SuggestionDraft] = {}
        self.fired: set[tuple[str, uuid.UUID, str]] = set()
        self.queue: deque = deque()
        self.log: list[dict[str, Any]] = []
        self.visited: set[uuid.UUID] = set()
        self.stop: str | None = None
        self.evaluated_roots: set[str] = set()
        self.changed: dict[uuid.UUID, set[str]] = {}  # milestones whose supply assessment was recomputed in this change
        self._cache: dict[uuid.UUID, NodeView] = {}

    # ------------------------------------------------------------------ helpers
    def node(self, nid: uuid.UUID) -> NodeView | None:
        if nid not in self._cache:
            got = self.r.nodes([nid])
            if nid in got:
                self._cache[nid] = got[nid]
                self._count(nid)
        return self._cache.get(nid)

    def _count(self, nid: uuid.UUID) -> None:
        if nid not in self.visited:
            self.visited.add(nid)
            self.budget.usage.visited += 1

    def neighbours(self, nid: uuid.UUID, kind: str, direction: str):
        edges, views, _ = self.r.edges([nid], kinds=(kind,), direction=direction)
        for v in views.values():
            self._cache.setdefault(v.id, v)
            self._count(v.id)
        out = []
        for e in edges:
            other = e.dst if e.src == nid else e.src
            if other in views:
                out.append((e, views[other]))
        return out

    def emit(self, d: ImpactDraft, trigger_path: list[dict[str, Any]]) -> None:
        key = (d.target, d.impact)
        d.paths = [trigger_path] if trigger_path else d.paths
        for step in trigger_path:
            d.requires |= {uuid.UUID(step["from"]), uuid.UUID(step["to"])}
        d.requires.add(d.target)
        d.requires |= {uuid.UUID(e["node_id"]) for e in d.evidence if e.get("node_id")}
        for e in d.evidence:
            d.requires |= {uuid.UUID(x) for x in e.get("requires", [])}
        if key in self.impacts:
            cur = self.impacts[key]
            for p in d.paths:
                if p not in cur.paths and len(cur.paths) < 6:
                    cur.paths.append(p)  # another route to the same consequence: explanation only, no extra weight
            cur.requires |= d.requires
            if d.details.get("roots"):
                cur.details["roots"] = sorted(set(cur.details.get("roots", [])) | set(d.details["roots"]))
            return
        self.impacts[key] = d
        self.log.append({"rule": d.rule_id, "target": str(d.target), "impact": d.impact, "reason": d.reason})
        self.queue.append(("impact", d.target, d.impact, d.paths[0] if d.paths else []))

    def suggest(self, s: SuggestionDraft) -> None:
        if s.key in self.suggestions:
            self.suggestions[s.key].requires |= s.requires
            self.suggestions[s.key].roots |= s.roots
            self.suggestions[s.key].requires_scopes += [x for x in s.requires_scopes if x not in self.suggestions[s.key].requires_scopes]
            return
        self.suggestions[s.key] = s

    # ------------------------------------------------------------------ driver
    def run(self, changed: dict[uuid.UUID, list[str]], extra: list[tuple] | None = None) -> None:
        self.changed = {k: set(v) for k, v in changed.items()}
        for nid, fields in changed.items():
            self.queue.append(("changed", nid, tuple(sorted(set(fields))), []))
        for item in extra or []:
            self.queue.append(item)
        while self.queue:
            self.budget.tick(self.r.counter.db_calls)
            reason = self.budget.exceeded()
            if reason:
                self.stop = reason
                return
            kind, nid, info, path = self.queue.popleft()
            if kind == "changed":
                self._on_changed(nid, info, path)
            elif kind == "deleted":
                self._on_deleted(nid, path)
            elif kind == "restricted":
                self._on_restricted(nid, path)
            elif kind == "impact":
                self._on_impact(nid, info, path)

    def _once(self, rule: str, target: uuid.UUID, trigger: str) -> bool:
        k = (rule, target, trigger)
        if k in self.fired:
            return False
        self.fired.add(k)
        return True

    # ------------------------------------------------------------------ triggers
    def _on_changed(self, nid: uuid.UUID, fields: tuple[str, ...], path) -> None:
        n = self.node(nid)
        if n is None:
            return
        content = any(f == "created" or f.split(".")[0] in CONTENT_FIELDS for f in fields)
        if n.type == "claim" or (content and n.type != "passage"):
            self.r0_value_conflict(n)
        if n.type == "order" and any(f in ("created", "attrs.promised_date", "attrs.qty", "attrs.status", "attrs.product")
                                     for f in fields):
            for e, m in self.neighbours(n.id, "depends_on", "in"):
                if m.type == "milestone":
                    self.r1_supply_exposure(m, trigger=f"order:{n.id}", path=[_hop("depends_on", m.id, n.id, e.id, e.provenance, e.hypothesis)],
                                            changed_order=n)
        if n.type == "milestone" and any(f in ("attrs.due_date", "attrs.slack_days") or f.startswith("edge:") for f in fields):
            self.r1_supply_exposure(n, trigger=f"milestone:{n.id}", path=[])
        if n.type == "product" and "stock" in fields:
            holders = {k for k, f in self.changed.items() if "stock" in f and k != n.id}
            for e, m in self.neighbours(n.id, "depends_on", "in"):
                if m.type == "milestone" and set(m.project_ids) & holders:
                    self.r1_supply_exposure(m, trigger=f"stock:{n.id}", path=[_hop("depends_on", m.id, n.id, e.id, e.provenance)])
        if n.type == "task" and "attrs.status" in fields and str(n.attrs.get("status")) == "done":
            self.r5_unblock(n)
        if n.type in ("contract", "requirement") and content and "created" not in fields:
            self.r6_contract_change(n)
        if content and "created" not in fields:
            self.r4_derived(n, depth=1, path=[], why="changed")

    def _on_deleted(self, nid: uuid.UUID, path) -> None:
        # the node is gone at the new snapshot; read its dependents one snapshot earlier
        prev = GraphReader(self.r.s, self.r.tenant_id, None, seq=self.r.seq - 1, counter=self.r.counter)
        edges, views, _ = prev.edges([nid], kinds=("depends_on", "derived_from", "governed_by"), direction="in")
        gone = prev.nodes([nid]).get(nid)
        for e in edges:
            dep = self.node(e.src)
            if dep is None:
                continue
            if not self._once("R7", dep.id, str(nid)):
                continue
            what = gone.name if gone else "a deleted record"
            if gone is not None and gone.type == "order" and dep.type == "milestone" and e.kind == "depends_on":
                self.r1_supply_exposure(dep, trigger=f"deleted:{nid}", path=[_hop(e.kind, dep.id, nid, e.id, e.provenance)])
            if e.kind == "derived_from" and not dep.authoritative:
                self._invalidate(dep, f"its source {what} was deleted", "R7", [_hop(e.kind, dep.id, nid, e.id, e.provenance)], source=gone)
                continue
            self.emit(ImpactDraft(dep.id, "needs_review", "R7", f"{dep.name} {e.kind.replace('_', ' ')} {what}, which was deleted.",
                                  0.7, evidence=([_ev(gone, "deleted record (as last recorded)")] if gone else [])
                                  + [_ev(dep, "record whose input was deleted")]),
                      [_hop(e.kind, dep.id, nid, e.id, e.provenance)])

    def _on_restricted(self, nid: uuid.UUID, path) -> None:
        src = self.node(nid)
        for e, dep in self.neighbours(nid, "derived_from", "in"):
            if not dep.authoritative and self._once("R8", dep.id, str(nid)):
                self._invalidate(dep, "a record it summarises became more restricted", "R8",
                                 [_hop("derived_from", dep.id, nid, e.id, e.provenance)], source=src)
                if self.w is not None and src is not None:
                    # generated text may carry the source's content: it gets the source's access, never wider
                    cur = self.w.current(dep.id)
                    self.w.revise(dep.id, scope_id=src.scope_id, sensitivity=max(dep.sensitivity, src.sensitivity),
                                  acl=(cur.acl if cur is not None and cur.acl else None) or self._acl_of(nid))
                    self._cache.pop(dep.id, None)

    def _acl_of(self, nid: uuid.UUID) -> dict:
        cur = self.w.current(nid) if self.w is not None else None
        return dict(cur.acl or {}) if cur is not None else {}

    def _on_impact(self, nid: uuid.UUID, impact: str, path) -> None:
        n = self.node(nid)
        if n is None:
            return
        if n.type == "milestone" and impact == "at_risk":
            roots = set(self.impacts[(nid, impact)].details.get("roots", [str(nid)]))
            self.r2_dependents(n, path, roots)
            self.r3_penalty(n, path, roots)

    # ------------------------------------------------------------------ R0
    def r0_value_conflict(self, n: NodeView) -> None:
        claims: list[tuple[NodeView, NodeView]] = []
        if n.type == "claim":
            st, sk = n.attrs.get("subject_type"), n.attrs.get("subject_key")
            if st and sk:
                subj = self.r.node_by_key(str(st), str(sk))
                if subj is not None:
                    self._cache.setdefault(subj.id, subj)
                    claims.append((n, subj))
        else:
            for _, c in self.neighbours(n.id, "contradicts", "in"):
                if c.type == "claim":
                    claims.append((c, n))
            # claims about this record that do not yet contradict it
            for c in self._claims_about(n):
                if (c, n) not in claims:
                    claims.append((c, n))
        for claim, subj in claims:
            if not self._once("R0", claim.id, f"{subj.id}:{subj.version}"):
                continue
            attr = str(claim.attrs.get("attr", ""))
            if not attr or attr not in subj.attrs:
                continue
            cv, sv = claim.attrs.get("value"), subj.attrs.get(attr)
            if str(cv) == str(sv) or self.w is None:
                continue
            deriv = {"rule": "R0", "attr": attr, "claim_value": cv, "record_value": sv, "claim_version": claim.version,
                     "record_version": subj.version}
            self.w.upsert_edge(claim.id, "contradicts", subj.id, provenance="rule", derivation=deriv, source_key=f"R0:{attr}")
            order = domain.later_record(subj.attrs, subj.authoritative, claim.attrs, claim.authoritative)
            if order > 0:
                self.w.upsert_edge(subj.id, "supersedes", claim.id, provenance="rule", source_key=f"R0:{attr}",
                                   derivation={**deriv, "why": "later system-of-record statement"})
            self.log.append({"rule": "R0", "claim": str(claim.id), "record": str(subj.id), "attr": attr,
                             "claim_value": cv, "record_value": sv, "chronology": order})

    def _claims_about(self, n: NodeView) -> list[NodeView]:
        from sqlalchemy import select

        from cie.rem.models import RemNode, RemNodeVersion
        from cie.rem.store import _at

        stmt = (select(RemNodeVersion.node_id).join(RemNode, RemNode.id == RemNodeVersion.node_id)
                .where(RemNode.tenant_id == self.r.tenant_id, RemNode.type == "claim", _at(RemNodeVersion, self.r.seq),
                       RemNodeVersion.attrs["subject_key"].astext == n.key,
                       RemNodeVersion.attrs["subject_type"].astext == n.type))
        ids = [r[0] for r in self.r._run(stmt, label="claims_about")]
        return list(self.r.nodes(ids).values())

    # ------------------------------------------------------------------ R1
    def r1_supply_exposure(self, m: NodeView, *, trigger: str, path, changed_order: NodeView | None = None) -> None:
        if not self._once("R1", m.id, trigger):
            return
        due = domain.effective_due(m.attrs)
        if due is None:
            return
        self.evaluated_roots.add(str(m.id))
        root = {"roots": [str(m.id)]}
        needs = [(e, p) for e, p in self.neighbours(m.id, "depends_on", "out") if p.type == "product"]
        orders = [(e, o) for e, o in self.neighbours(m.id, "depends_on", "out") if o.type == "order"]
        holder = m.project_ids[0] if m.project_ids else None
        base = path or ([_hop("depends_on", m.id, changed_order.id)] if changed_order else [])
        ev = [_ev(m, f"due {m.attrs.get('due_date')} (+{m.attrs.get('slack_days') or 0} days slack)")]
        inputs, hyp, per_product, late_all, short_all = [m], False, [], [], []
        reveals: set[uuid.UUID] = {m.id} | ({holder} if holder else set())  # the reasons name all of these
        stock_scopes: list[list[Any]] = []
        for need_edge, prod in needs:
            qty = float(need_edge.attrs.get("qty") or 0)
            if qty <= 0:
                continue
            mine = [(e, o) for e, o in orders if str(o.attrs.get("product")) == prod.key and domain.is_open_order(o.attrs)]
            late = [(e, o) for e, o in mine if (domain.as_date(o.attrs.get("promised_date")) or due) > due]
            on_time = [(e, o) for e, o in mine if (e, o) not in late]
            stock = self.r.stock(prod.id, [holder]).get(holder) if holder else None
            avail = max(0.0, stock["available"]) if stock else 0.0
            supply = avail + sum(float(o.attrs.get("qty") or 0) for _, o in on_time)
            hyp = hyp or any(e.hypothesis for e, _ in mine) or need_edge.hypothesis
            inputs += [o for _, o in mine]
            reveals |= {prod.id} | {o.id for _, o in mine}
            if stock is not None:
                stock_scopes.append([stock["scope_id"], stock["sensitivity"]])
            ev += [_ev(o, f"{o.attrs.get('qty')} {prod.name} promised {o.attrs.get('promised_date')} "
                          f"({'late' if (e, o) in late else 'on time'})") for e, o in mine]
            if stock is not None:
                ev.append({"kind": "db_value", "table": "rem_stock", "product": prod.key, "holder": str(holder),
                           "what": f"{stock['on_hand']:g} {prod.name} on hand, {stock['reserved']:g} reserved",
                           "source_pointers": stock["source_pointers"], "requires": [str(prod.id), str(holder)]})
            item = {"product": prod.key, "name": prod.name, "id": prod.id, "needed": qty, "available_stock": avail,
                    "on_time_orders": [o.key for _, o in on_time], "late_orders": [o.key for _, o in late],
                    "late_ids": [o.id for _, o in late], "shortfall": max(0.0, qty - supply)}
            per_product.append(item)
            late_all += late
            if item["shortfall"] > 0:
                short_all.append(item)
        if not per_product:
            return
        details = {**root, "effective_due": due.isoformat(), "requires_scopes": stock_scopes,
                   "products": [{k: v for k, v in x.items() if k not in ("id", "late_ids")} for x in per_product]}
        path_ids = {uuid.UUID(st[k]) for st in base for k in ("from", "to") if st.get(k)}
        need_all = reveals | path_ids
        grade = _grade(inputs, hyp)
        late_names = ", ".join(sorted({f"{o.key} ({o.attrs.get('promised_date')})" for _, o in late_all}))
        if short_all:
            # exposed: stock plus orders arriving by the due date (plus slack) do not cover what the milestone needs
            parts = "; ".join(f"{x['name']}: needs {x['needed']:g}, stock {x['available_stock']:g} plus on-time orders "
                              f"{x['needed'] - x['shortfall'] - x['available_stock']:g}, shortfall {x['shortfall']:g}" for x in short_all)
            why = f"{m.name} (due {due.isoformat()}): {parts}." + (f" Late: {late_names}." if late_names else "")
            self.emit(ImpactDraft(m.id, "needs_review" if hyp else "at_risk", "R1", why, grade, evidence=ev, hypothesis=hyp,
                                  requires=set(need_all), details={**details, "shortfall": sum(x["shortfall"] for x in short_all)}), base)
            for x in short_all:
                self.suggest(SuggestionDraft(f"R1:expedite:{m.key}:{x['product']}", f"Expedite or source {x['shortfall']:g} {x['name']} for {m.name}",
                                             "operations", [m.id, x["id"]] + x["late_ids"], why, 0.9, "R1",
                                             set(need_all), {str(m.id)}, list(stock_scopes)))
        elif late_all:
            why = (f"{m.name} (due {due.isoformat()}): {late_names} now arrive late, but stock and on-time orders cover "
                   + ", ".join(f"{x['needed']:g} {x['name']}" for x in per_product) + ".")
            self.emit(ImpactDraft(m.id, "covered", "R1", why, grade, evidence=ev, hypothesis=hyp, requires=set(need_all),
                                  details=details), base)
            for x in per_product:
                if x["late_orders"] and x["available_stock"] > 0:
                    self.suggest(SuggestionDraft(f"R1:reserve:{m.key}:{x['product']}",
                                                 f"Reserve {min(x['needed'], x['available_stock']):g} {x['name']} from stock for {m.name}",
                                                 "operations", [m.id, x["id"]], why, 0.5, "R1", set(need_all), {str(m.id)},
                                                 list(stock_scopes)))
        elif self._open_prior(m.id, "R1"):
            self.emit(ImpactDraft(m.id, "resolved", "R1", f"{m.name}: every need is covered by stock or orders arriving by {due.isoformat()}.",
                                  grade, evidence=ev, hypothesis=hyp, requires=set(need_all), details=details), base)

    def _open_prior(self, target: uuid.UUID, rule: str) -> bool:
        from sqlalchemy import select

        from cie.rem.models import RemImpact

        row = self.r.s.scalar(select(RemImpact.id).where(RemImpact.tenant_id == self.r.tenant_id, RemImpact.target_id == target,
                                                         RemImpact.rule_id == rule, RemImpact.status == "candidate",
                                                         RemImpact.impact.in_(("at_risk", "covered", "needs_review"))).limit(1))
        self.r.counter.db_calls += 1
        return row is not None

    # ------------------------------------------------------------------ R2, R3
    def r2_dependents(self, m: NodeView, path, roots: set[str]) -> None:
        if not self._once("R2", m.id, "at_risk"):
            return
        det = {"roots": sorted(roots)}
        for e, t in self.neighbours(m.id, "depends_on", "in"):
            hop = _hop("depends_on", t.id, m.id, e.id, e.provenance, e.hypothesis)
            if t.type == "project":
                self.emit(ImpactDraft(t.id, "at_risk", "R2", f"{t.name} depends on {m.name}, which is at risk.",
                                      _grade([t, m], e.hypothesis), evidence=[_ev(m, "milestone at risk")], hypothesis=e.hypothesis,
                                      details=dict(det)), path + [hop])
            elif t.type == "task" and str(t.attrs.get("status", "open")) != "done":
                self.emit(ImpactDraft(t.id, "needs_review", "R2", f"{t.name} depends on {m.name}, which is at risk.",
                                      _grade([t, m], e.hypothesis), evidence=[_ev(m, "milestone at risk")], hypothesis=e.hypothesis,
                                      details=dict(det)), path + [hop])
        for pid in m.project_ids:  # membership, when no explicit project edge exists
            p = self.node(pid)
            if p is not None and (p.id, "at_risk") not in self.impacts:
                self.emit(ImpactDraft(p.id, "at_risk", "R2", f"{m.name} belongs to {p.name} and is at risk.", _grade([m], False),
                                      evidence=[_ev(m, "milestone at risk")], details=dict(det)), path)

    def r3_penalty(self, m: NodeView, path, roots: set[str]) -> None:
        if not self._once("R3", m.id, "at_risk"):
            return
        det = {"roots": sorted(roots)}
        for e, req in self.neighbours(m.id, "governed_by", "out"):
            if req.type != "requirement" or str(req.attrs.get("kind")) not in domain.PENALTY_KINDS:
                continue
            hop = _hop("governed_by", m.id, req.id, e.id, e.provenance, e.hypothesis)
            contracts = [c for _, c in self.neighbours(req.id, "derived_from", "out") if c.type == "contract"]
            cname = contracts[0].name if contracts else "the governing contract"
            why = f"{m.name} is at risk and is governed by {req.name} in {cname}."
            req_ids = {req.id} | {c.id for c in contracts}
            self.emit(ImpactDraft(req.id, "needs_review", "R3", why, _grade([m, req], e.hypothesis),
                                  evidence=[_ev(req, "penalty requirement")] + [_ev(c, "contract") for c in contracts],
                                  hypothesis=e.hypothesis, details=dict(det)), path + [hop])
            full = set(self.impacts[(req.id, "needs_review")].requires) | req_ids | {m.id}
            self.suggest(SuggestionDraft(f"R3:finance:{m.key}:{req.key}", f"Estimate penalty exposure for {m.name} under {req.name}",
                                         "finance", [m.id, req.id], why, 0.8, "R3", set(full), set(roots)))
            self.suggest(SuggestionDraft(f"R3:legal:{m.key}:{req.key}", f"Review {cname} ({req.name}) for notice duties and remedies",
                                         "legal", [req.id] + [c.id for c in contracts], why, 0.8, "R3", set(full), set(roots)))

    # ------------------------------------------------------------------ R4
    def r4_derived(self, n: NodeView, depth: int, path, why: str) -> None:
        if depth > self.max_derived_depth:
            self.stop = self.stop or "budget:max_depth"
            return
        for e, d in self.neighbours(n.id, "derived_from", "in"):
            if not self._once("R4", d.id, str(n.id)):
                continue
            hop = path + [_hop("derived_from", d.id, n.id, e.id, e.provenance)]
            if d.type == "claim":
                continue  # a claim quotes its passage; R0 re-checks it against the record instead
            if not d.authoritative:
                self._invalidate(d, f"{n.name} {why}", "R4", hop, source=n)
            else:
                self.emit(ImpactDraft(d.id, "needs_review", "R4", f"{d.name} is derived from {n.name}, which {why}.",
                                      _grade([d], False), evidence=[_ev(n, why)]), hop)
            self.r4_derived(d, depth + 1, hop, f"is derived from {n.name}")

    def _invalidate(self, d: NodeView, why: str, rule: str, path, source: NodeView | None = None) -> None:
        ev = [_ev(source, "changed source")] if source is not None else []
        self.emit(ImpactDraft(d.id, "invalidated", rule, f"Generated content {d.name} is out of date: {why}.", 1.0,
                              evidence=ev + [_ev(d, "generated summary")]), path)
        if self.w is not None and d.review_status != "invalidated":
            self.w.revise(d.id, review_status="invalidated")
            self._cache.pop(d.id, None)

    # ------------------------------------------------------------------ R5, R6
    def r5_unblock(self, t: NodeView) -> None:
        for e, t2 in self.neighbours(t.id, "blocks", "out"):
            if t2.type != "task" or not self._once("R5", t2.id, str(t.id)):
                continue
            blockers = [b for _, b in self.neighbours(t2.id, "blocks", "in") if b.id != t.id]
            if all(str(b.attrs.get("status")) == "done" for b in blockers):
                self.emit(ImpactDraft(t2.id, "unblocked", "R5", f"{t.name} is done and no other open task blocks {t2.name}.",
                                      _grade([t, *blockers], e.hypothesis), evidence=[_ev(t, "completed blocker")],
                                      hypothesis=e.hypothesis), [_hop("blocks", t.id, t2.id, e.id, e.provenance, e.hypothesis)])

    def r6_contract_change(self, c: NodeView) -> None:
        for e, g in self.neighbours(c.id, "governed_by", "in"):
            if not self._once("R6", g.id, str(c.id)):
                continue
            why = f"{g.name} is governed by {c.name}, which changed."
            self.emit(ImpactDraft(g.id, "needs_review", "R6", why, _grade([c], e.hypothesis), evidence=[_ev(c, "changed terms")],
                                  hypothesis=e.hypothesis), [_hop("governed_by", g.id, c.id, e.id, e.provenance, e.hypothesis)])
            self.suggest(SuggestionDraft(f"R6:legal:{g.key}:{c.key}", f"Check {g.name} against the changed terms of {c.name}",
                                         "legal", [g.id, c.id], why, 0.6, "R6", set(self.impacts[(g.id, "needs_review")].requires) | {g.id, c.id}))


def reachability_baseline(reader: GraphReader, changed: list[uuid.UUID], budget: Budget, max_depth: int = 3) -> dict[uuid.UUID, int]:
    """Change-mode baseline (arm B): every record reverse-reachable from a changed record over dependency and
    derivation edges counts as affected. Returns target -> hop distance."""
    kinds = ("depends_on", "blocks", "governed_by", "derived_from")
    seen: dict[uuid.UUID, int] = {n: 0 for n in changed}
    frontier = list(changed)
    for hop in range(1, max_depth + 1):
        if not frontier or budget.exceeded():
            break
        edges, views, _ = reader.edges(frontier, kinds=kinds, direction="both")
        nxt = []
        for e in edges:
            # reverse dependency: X depends_on / governed_by / derived_from Y, Y changed -> X; Y blocks X, Y changed -> X
            if e.kind == "blocks":
                src_side, dst_side = e.src, e.dst
            else:
                src_side, dst_side = e.dst, e.src
            if src_side in frontier and dst_side not in seen and dst_side in views:
                seen[dst_side] = hop
                nxt.append(dst_side)
        budget.usage.visited += len(nxt)
        budget.tick(reader.counter.db_calls)
        frontier = nxt
    return {k: v for k, v in seen.items() if v > 0}
