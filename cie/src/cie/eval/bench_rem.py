"""REM benchmarks.

``dependency``: the controlled, versioned dependency dataset (``cie.eval.rem_dataset``), answer keys computed by
an independent oracle and written outside the searchable corpus. Change mode compares
    A  search: records returned by searching for the changed records' names are flagged
    B  typed reachability: every record reverse-reachable over dependency edges (3 hops) is flagged
    C  REM rules R0-R8 (the change mode of this module)
    D  C with routing shortcuts: identical to C by construction, because rules never use routing edges
Query mode compares policies search / traversal / rem / rem+routing (arms A-D) at three budgets.

``erb``: EnterpriseRAG-Bench retrieval on a tenant loaded by ``cie.eval.bench_enterprise`` (see ``rem_erb``).

All arms of one seed read the same tenant, snapshot, permissions, embedding model and hardware.
"""

from __future__ import annotations

import json
import random
import statistics
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text

BUDGETS = {"tight": {"max_visited": 20, "max_tokens": 350, "max_db_calls": 30, "max_ms": 5000},
           "medium": {"max_visited": 60, "max_tokens": 1000, "max_db_calls": 60, "max_ms": 5000},
           "loose": {"max_visited": 400, "max_tokens": 4000, "max_db_calls": 300, "max_ms": 10000}}
QUERY_ARMS = {"A": "search", "B": "traversal", "C": "rem", "D": "rem+routing"}


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))], 1)


def prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    return {"precision": round(p, 3) if p is not None else None, "recall": round(r, 3) if r is not None else None,
            "tp": tp, "fp": fp, "fn": fn}


# ---------------------------------------------------------------------------------------------- setup
def make_tenant(session, world, embedder, name: str):
    from cie.core.models import Permission, Principal, PrincipalKind, Scope, Tenant
    from cie.governance.permissions import ensure_role, grant_role
    from cie.rem.change import process_event, submit_event
    from cie.rem.ingest import ensure_scopes

    t = Tenant(name=name)
    session.add(t)
    session.flush()
    ensure_scopes(session, t.id, world.scopes())
    company = session.scalar(select(Scope).where(Scope.tenant_id == t.id, Scope.name == world.company))
    people = {}
    for pname, (perm, clearance) in {"ops": (Permission.read, 2), "counsel": (Permission.read, 3), "admin": (Permission.admin, 4)}.items():
        role = ensure_role(session, t.id, f"bench-{pname}", perm, clearance)
        p = Principal(tenant_id=t.id, kind=PrincipalKind.user, name=pname, attributes={})
        session.add(p)
        session.flush()
        grant_role(session, tenant_id=t.id, principal=p, role=role, scope=company)
        people[pname] = p
    t0 = time.perf_counter()
    ev, _ = submit_event(session, t.id, kind="ops", payload={"ops": world.ops()}, idempotency_key=f"corpus-{world.seed}")
    summary = process_event(session, ev.id, embedder=embedder)
    build_s = time.perf_counter() - t0
    session.commit()
    return t, people, summary, build_s


def keys_by_id(session, tenant_id) -> dict[uuid.UUID, str]:
    from cie.rem.models import RemNode

    return {i: f"{t}:{k}" for i, t, k in session.execute(select(RemNode.id, RemNode.type, RemNode.key).where(RemNode.tenant_id == tenant_id))}


def rem_table_bytes(session) -> int:
    rows = session.execute(text("SELECT sum(pg_total_relation_size(c.oid)) FROM pg_class c WHERE c.relname LIKE 'rem\\_%' AND c.relkind = 'r'"))
    return int(rows.scalar() or 0)


# ---------------------------------------------------------------------------------------------- change mode
def search_arm(reader, names: list[str], k: int = 20) -> set[uuid.UUID]:
    out: set[uuid.UUID] = set()
    for n in names:
        for nid, _sc, _how in reader.search(n, None, k=k):
            out.add(nid)
    return out


def run_change_seed(session, world_events, tenant, embedder, keymap) -> dict[str, Any]:
    from cie.rem.budget import Budget, Limits
    from cie.rem.change import process_event, submit_event, visible_impacts
    from cie.rem.models import RemImpact
    from cie.rem.rules import reachability_baseline
    from cie.rem.store import GraphReader

    per_event, b_current = [], set()
    for ev_spec in world_events:
        ev, _ = submit_event(session, tenant.id, kind=ev_spec["kind"], payload=ev_spec["payload"], idempotency_key=ev_spec["key"])
        summary = process_event(session, ev.id, embedder=embedder)
        seq = summary["seq"]
        keymap.update(keys_by_id(session, tenant.id))
        op_changed = [uuid.UUID(x) for x in summary["op_changed"]]
        deleted = [uuid.UUID(x) for x in summary["deleted"]]
        # C: the module's rules
        rows = session.scalars(select(RemImpact).where(RemImpact.event_id == ev.id)).all()
        pred_c = {(keymap[r.target_id], r.impact, r.hypothesis) for r in rows}
        # B: typed reachability from the records the operations changed (deleted ones: one snapshot earlier)
        t = time.perf_counter()
        bud = Budget(Limits(max_visited=100000, max_db_calls=100000, max_ms=600000))
        now = GraphReader(session, tenant.id, None, seq=seq)
        prev = GraphReader(session, tenant.id, None, seq=seq - 1, counter=now.counter)
        reach = reachability_baseline(now, [x for x in op_changed if x not in deleted], bud)
        if deleted:
            reach.update(reachability_baseline(prev, deleted, bud))
        b_ms = (time.perf_counter() - t) * 1000
        b_calls = now.counter.db_calls
        pred_b = {keymap[x] for x in reach if x in keymap}
        # A: search for the changed records' names
        t = time.perf_counter()
        names = [n.name for n in GraphReader(session, tenant.id, None, seq=seq).nodes(op_changed).values()]
        if deleted:
            names += [n.name for n in prev.nodes(deleted).values()]
        hits = search_arm(GraphReader(session, tenant.id, None, seq=seq), names)
        a_ms = (time.perf_counter() - t) * 1000
        changed_keys = {keymap[x] for x in op_changed + deleted if x in keymap}
        pred_a = {keymap[x] for x in hits if x in keymap} - changed_keys
        expected = {tuple(e.split("|")) for e in ev_spec["expected"]}
        # current assessments after the event
        cur, _ = visible_impacts(session, GraphReader(session, tenant.id, None, seq=seq))
        c_current = {f"{i['target']['type']}:{i['target']['key']}" for i in cur if i["rule"] == "R1" and i["impact"] == "at_risk"}
        b_current |= {k for k in pred_b if k.startswith("milestone:")}
        per_event.append({"key": ev_spec["key"], "kind": ev_spec["kind"], "expected": sorted("|".join(x) for x in expected),
                          "C": sorted(f"{k}|{i}{'|hyp' if h else ''}" for k, i, h in pred_c), "B": sorted(pred_b), "A": sorted(pred_a),
                          "truth_current_at_risk": ev_spec["current_at_risk"], "C_current_at_risk": sorted(c_current),
                          "B_current_flagged": sorted(b_current),
                          "ms": {"C_detect": summary["detect_ms"], "C_ops": summary["ops_ms"], "B": round(b_ms, 1), "A": round(a_ms, 1)},
                          "db_calls": {"C": summary["budget"]["used"]["db_calls"], "B": b_calls},
                          "visited": {"C": summary["budget"]["used"]["visited"], "B": bud.usage.visited},
                          "status": summary["status"]})
        session.commit()
    return {"events": per_event}


def score_change(runs: list[dict[str, Any]]) -> dict[str, Any]:
    arms: dict[str, dict[str, int]] = {a: {"tp": 0, "fp": 0, "fn": 0} for a in ("A", "B", "C")}
    c_nohyp = {"tp": 0, "fp": 0, "fn": 0}
    hyp_fp, hyp_tp, cls_ok, cls_n, covered_ok, covered_n = 0, 0, 0, 0, 0, 0
    stale = {"C": [0, 0, 0], "B": [0, 0, 0]}  # stale, missed, predicted
    lat = {"C_detect": [], "C_ops": [], "B": [], "A": []}
    calls, visited, incomplete = {"C": [], "B": []}, {"C": [], "B": []}, 0
    for run in runs:
        for e in run["events"]:
            exp = {tuple(x.split("|")) for x in e["expected"]}
            exp_t = {t for t, i in exp if i != "covered"}
            c = [tuple(x.split("|")) for x in e["C"]]
            c_t = {x[0] for x in c if x[1] not in ("covered",)}
            c_t_nohyp = {x[0] for x in c if x[1] != "covered" and len(x) < 3}
            for arm, pred in (("A", set(e["A"])), ("B", set(e["B"])), ("C", c_t)):
                arms[arm]["tp"] += len(pred & exp_t)
                arms[arm]["fp"] += len(pred - exp_t)
                arms[arm]["fn"] += len(exp_t - pred)
            c_nohyp["tp"] += len(c_t_nohyp & exp_t)
            c_nohyp["fp"] += len(c_t_nohyp - exp_t)
            c_nohyp["fn"] += len(exp_t - c_t_nohyp)
            for x in c:
                if len(x) == 3:
                    hyp_fp += x[0] not in exp_t
                    hyp_tp += x[0] in exp_t
            exp_cls = {t: i for t, i in exp}
            for x in c:
                if x[0] in exp_cls:
                    cls_n += 1
                    cls_ok += exp_cls[x[0]] == x[1] or (len(x) == 3 and x[1] == "needs_review")
            for t, i in exp:
                if i == "covered":
                    covered_n += 1
                    covered_ok += (t, "covered") in {(x[0], x[1]) for x in c}
            truth = set(e["truth_current_at_risk"])
            for arm, cur in (("C", set(e["C_current_at_risk"])), ("B", set(e["B_current_flagged"]))):
                stale[arm][0] += len(cur - truth)
                stale[arm][1] += len(truth - cur)
                stale[arm][2] += len(cur)
            for k, v in e["ms"].items():
                lat[k].append(v)
            for k in ("C", "B"):
                calls[k].append(e["db_calls"][k])
                visited[k].append(e["visited"][k])
            incomplete += e["status"] != "complete"
    n_events = sum(len(r["events"]) for r in runs)
    out = {"events": n_events, "impact_detection": {a: prf(**v) for a, v in arms.items()},
           "C_excluding_hypothesis_flagged": prf(**c_nohyp),
           "C_hypothesis_flagged": {"correct": hyp_tp, "wrong": hyp_fp},
           "incorrect_propagation_per_event": {a: round(v["fp"] / max(1, n_events), 2) for a, v in arms.items()},
           "C_impact_class_accuracy": round(cls_ok / cls_n, 3) if cls_n else None,
           "C_covered_identified": f"{covered_ok}/{covered_n}",
           "current_assessment": {a: {"stale": v[0], "missed": v[1], "flagged": v[2],
                                      "stale_rate": round(v[0] / v[2], 3) if v[2] else None} for a, v in stale.items()},
           "latency_ms": {k: {"p50": pct(v, 0.5), "p95": pct(v, 0.95)} for k, v in lat.items()},
           "db_calls_p50": {k: pct(v, 0.5) for k, v in calls.items()}, "visited_p50": {k: pct(v, 0.5) for k, v in visited.items()},
           "C_incomplete_events": incomplete, "D": "identical to C: change rules never read routing shortcuts"}
    return out


# ---------------------------------------------------------------------------------------------- query mode
def build_routing(session, tenant_id, degree: int = 4, seed: int = 0) -> dict[str, Any]:
    """Random sparse routing shortcuts (an expander-style overlay): each node links to ``degree // 2`` random
    others in both directions. Navigation only."""
    from cie.rem.models import RemNode
    from cie.rem.store import GraphWriter

    ids = [r[0] for r in session.execute(select(RemNode.id).where(RemNode.tenant_id == tenant_id, RemNode.deleted_seq.is_(None)))]
    rng = random.Random(seed)
    t = time.perf_counter()
    w = GraphWriter(session, tenant_id)
    w.begin()
    n = 0
    for a in ids:
        for b in rng.sample(ids, min(len(ids), degree // 2)):
            if a != b:
                w.add_routing(a, b, f"random-d{degree}")
                w.add_routing(b, a, f"random-d{degree}")
                n += 2
    session.flush()
    return {"edges": n, "build_s": round(time.perf_counter() - t, 2)}


def run_queries_seed(session, world_final, events, tenant, people, embedder, keymap, restricted: set[str]) -> list[dict[str, Any]]:
    from cie.governance.permissions import visible_scopes
    from cie.rem.query import QueryRequest, requires_of, run_query

    deleted = {f"order:{o.key}" for o in world_final.orders.values() if o.deleted} | {f"passage:{o.key}#text" for o in world_final.orders.values() if o.deleted}
    questions = [dict(e["question"], kind="delay_projects") for e in events if "question" in e]
    questions += world_final.extra_questions()
    vis = visible_scopes(session, people["ops"])
    rows = []
    for qi, q in enumerate(questions):
        gold = set(q["gold_evidence"]) - deleted - restricted
        for budget_name, limits in BUDGETS.items():
            for arm, policy in QUERY_ARMS.items():
                out = run_query(session, tenant.id, vis, QueryRequest(question=q["text"], policy=policy, limits=limits, start_k=10, save=False),
                                embedder=embedder, principal_id=people["ops"].id)
                ev_keys = [f"{e['node']['type']}:{e['node']['key']}" for e in out["evidence"]]
                got = set(ev_keys)
                all_ids = requires_of(out)
                disclosed = sorted({keymap.get(uuid.UUID(i), i) for i in all_ids} & restricted)
                leak_text = "CONFIDENTIAL-CLAUSE" in json.dumps(out, default=str)
                row = {"q": qi, "kind": q["kind"], "budget": budget_name, "arm": arm, "gold": len(gold),
                       "evidence_recall": len(gold & got) / len(gold) if gold else None,
                       "evidence_precision": len(gold & got) / len(got) if got else 0.0,
                       "returned": len(got), "status": out["status"], "stopping_reason": out["stopping_reason"],
                       "ms": out["budget"]["used"]["ms"], "visited": out["budget"]["used"]["visited"],
                       "db_calls": out["budget"]["used"]["db_calls"], "tokens": out["budget"]["used"]["tokens"],
                       "model_calls": out["budget"]["used"]["model_calls"], "disclosed": len(disclosed) + int(leak_text)}
                if q["kind"] == "delay_projects":
                    pred = {p["key"] for p in out["candidate_affected"]["projects"]}
                    gp = set(q["gold_projects"])
                    row["project_recall"] = len(pred & gp) / len(gp) if gp else None
                    row["project_precision"] = len(pred & gp) / len(pred) if pred else 0.0
                    row["answer_exact"] = pred == gp
                    # citation support: each correctly named project has an order of it (or its passage) in the evidence
                    sup = 0
                    for p in pred & gp:
                        orders = {f"order:{o.key}" for o in world_final.orders.values() if o.project == p}
                        passages = {f"passage:{o.key}#text" for o in world_final.orders.values() if o.project == p}
                        sup += bool((orders | passages) & got & set(q["gold_evidence"]))
                    row["citation_support"] = sup / len(pred & gp) if pred & gp else None
                rows.append(row)
    return rows


def score_queries(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for budget in BUDGETS:
        out[budget] = {}
        for arm in QUERY_ARMS:
            sub = [r for r in rows if r["budget"] == budget and r["arm"] == arm]
            if not sub:
                continue
            m = lambda k, s=sub: round(statistics.mean([r[k] for r in s if r.get(k) is not None]), 3) if any(r.get(k) is not None for r in s) else None  # noqa: E731
            dq = [r for r in sub if r["kind"] == "delay_projects"]
            out[budget][arm] = {"questions": len(sub), "evidence_recall": m("evidence_recall"), "evidence_precision": m("evidence_precision"),
                                "project_recall": m("project_recall"), "project_precision": m("project_precision"),
                                "answer_exact": round(sum(r["answer_exact"] for r in dq) / len(dq), 3) if dq else None,
                                "citation_support": m("citation_support"),
                                "incomplete": sum(r["status"] != "complete" for r in sub), "unauthorized_disclosures": sum(r["disclosed"] for r in sub),
                                "latency_ms_p50": pct([r["ms"] for r in sub], 0.5), "latency_ms_p95": pct([r["ms"] for r in sub], 0.95),
                                "visited_p50": pct([r["visited"] for r in sub], 0.5), "db_calls_p50": pct([r["db_calls"] for r in sub], 0.5),
                                "tokens_p50": pct([r["tokens"] for r in sub], 0.5), "model_calls": sum(r["model_calls"] for r in sub)}
    return out


def stale_check(session, tenant, people, embedder, world_events_after) -> dict[str, Any]:
    """Cached results must be marked stale when a record version they used is replaced or deleted."""
    from cie.rem.models import RemNodeVersion, RemResult, RemResultDep

    rows = session.execute(select(RemResult.id, RemResult.stale).where(RemResult.tenant_id == tenant.id)).all()
    must, flagged = 0, 0
    for rid, is_stale in rows:
        deps = session.execute(select(RemResultDep.node_id, RemResultDep.version).where(RemResultDep.result_id == rid)).all()
        cur = dict(session.execute(select(RemNodeVersion.node_id, func.max(RemNodeVersion.version))
                                   .where(RemNodeVersion.node_id.in_([d[0] for d in deps]), RemNodeVersion.sys_to.is_(None))
                                   .group_by(RemNodeVersion.node_id)).all()) if deps else {}
        outdated = any(cur.get(n) != v for n, v in deps)
        must += outdated
        flagged += bool(outdated and is_stale)
    return {"cached_results": len(rows), "used_an_outdated_version": must, "marked_stale": flagged,
            "served_stale_unmarked": must - flagged}


# ---------------------------------------------------------------------------------------------- driver
def run_dependency(split: str, out_dir: Path, embedder, session_factory) -> dict[str, Any]:
    from cie.eval.rem_dataset import World, split_seeds
    from cie.governance.permissions import visible_scopes
    from cie.rem.query import QueryRequest, run_query

    keys_dir = out_dir / "keys" / split  # answer keys: never loaded into the corpus
    keys_dir.mkdir(parents=True, exist_ok=True)
    change_runs, query_rows, builds, stale_checks, routing = [], [], [], [], []
    for seed in split_seeds(split):
        world0 = World(seed)
        world1 = World(seed)
        events = world1.events()
        (keys_dir / f"seed-{seed}.json").write_text(json.dumps({"events": [{k: v for k, v in e.items() if k != "payload"} for e in events],
                                                                "questions": world1.extra_questions()}, indent=1, default=str))
        with session_factory() as s:
            before = rem_table_bytes(s)
            tenant, people, summary, build_s = make_tenant(s, world0, embedder, f"rem-bench-{split}-{seed}-{uuid.uuid4().hex[:4]}")
            after = rem_table_bytes(s)
            builds.append({"seed": seed, "ops": summary["operations"], "build_s": round(build_s, 2), "rem_bytes": after - before})
            keymap = keys_by_id(s, tenant.id)
            # cached results to be invalidated: one saved query per event, as the ops user
            vis = visible_scopes(s, people["ops"])
            for ev in events[: len(events) // 2]:
                if "question" in ev:
                    run_query(s, tenant.id, vis, QueryRequest(question=ev["question"]["text"], policy="traversal"), embedder=embedder,
                              principal_id=people["ops"].id)
            s.commit()
            change_runs.append(run_change_seed(s, events, tenant, embedder, keymap))
            stale_checks.append(stale_check(s, tenant, people, embedder, events))
            routing.append(build_routing(s, tenant.id, seed=seed))
            s.commit()
            keymap = keys_by_id(s, tenant.id)
            restricted = {f"{t}:{k}" for t, k in world1.restricted_keys()}
            query_rows += [dict(r, seed=seed) for r in run_queries_seed(s, world1, events, tenant, people, embedder, keymap, restricted)]
            s.commit()
    result = {"split": split, "seeds": split_seeds(split), "change": score_change(change_runs), "query": score_queries(query_rows),
              "stale_cached_results": {k: sum(x[k] for x in stale_checks) for k in stale_checks[0]},
              "build": builds, "routing_overlay": routing}
    (out_dir / f"dependency-{split}.json").write_text(json.dumps(result, indent=2, default=str))
    (out_dir / f"dependency-{split}-events.json").write_text(json.dumps(change_runs, indent=1, default=str))
    (out_dir / f"dependency-{split}-queries.json").write_text(json.dumps(query_rows, indent=1, default=str))
    return result


def main(args) -> int:
    from cie.core.db import session_factory
    from cie.memory.embeddings import get_embedding_provider

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    emb = get_embedding_provider()
    factory = session_factory()
    results = {}
    if args.which in ("dependency", "all"):
        results["dependency"] = run_dependency(args.split, out, emb, factory)
    if args.which in ("erb", "all"):
        from cie.eval import rem_erb

        results["erb"] = rem_erb.run(args, out, emb, factory)
    print(json.dumps(results, indent=2, default=str)[:20000])
    return 0
