"""Training and test samples for the learned explorer, with the non-learned baselines computed on the same hits.

Controlled dataset (``cie.eval.rem_dataset``): each seed is loaded as a tenant through the ordinary event path,
its change events are applied, a routing overlay is added, and its questions are asked by the ``ops`` principal
(cannot read Legal). Gold evidence comes from the generator. Seeds: training 1000-1059, validation = the REM dev
seeds 1-4, test 201-210 (fresh; never used before).

EnterpriseRAG-Bench: the 5k tenant built by ``cie.eval.bench_enterprise`` and its REM graph (``rem_erb``).
Training and validation come from the dev split (80/20 by question id), test from the held-out split. Gold
units are documents.

For every question the baselines A (search order), B (typed traversal) and C (REM priority policy) run through
``run_query`` with the same start hits and token budgets, so every arm answers from identical inputs.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from cie.rem.query import QueryRequest, run_query
from cie.rem.store import GraphReader
from cie.remnet.graphs import Sample, extract

CONTROLLED_SEEDS = {"train": list(range(1000, 1060)), "val": [1, 2, 3, 4], "test": list(range(201, 211))}
CONTROLLED_BUDGETS = {"t350": 350, "t1000": 1000}
ERB_BUDGETS = {"t2000": 2000, "t6000": 6000}
POOL = {"max_nodes": 300, "max_depth": 2}
BASELINES = {"A": "search", "B": "traversal", "C": "rem"}


def _baselines(session, tenant_id, vis, principal_id, question, hits, budgets, embedder, unit_of) -> dict[str, dict[str, list[str]]]:
    """Packet order (list of evaluated units) for each baseline arm and budget."""
    out: dict[str, dict[str, list[str]]] = {}
    for bname, tokens in budgets.items():
        out[bname] = {}
        for arm, policy in BASELINES.items():
            t = time.perf_counter()
            o = run_query(session, tenant_id, vis, QueryRequest(question=question, policy=policy, start_hits=hits, save=False,
                                                                limits={"max_tokens": tokens, "max_visited": POOL["max_nodes"],
                                                                        "max_depth": POOL["max_depth"], "max_db_calls": 400,
                                                                        "max_ms": 60000}),
                          embedder=embedder, principal_id=principal_id)
            units: list[str] = []
            for e in o["evidence"]:
                u = unit_of(e)
                if u and u not in units:
                    units.append(u)
            out[bname][arm] = {"units": units, "ms": (time.perf_counter() - t) * 1000,
                               "db_calls": o["budget"]["used"]["db_calls"], "visited": o["budget"]["used"]["visited"]}
            session.rollback()
    return out


# ---------------------------------------------------------------------------------------------- controlled
def build_controlled(seed: int, out_dir: Path, embedder, factory) -> Path:
    from cie.eval.bench_rem import build_routing, make_tenant
    from cie.eval.rem_dataset import World
    from cie.governance.permissions import visible_scopes
    from cie.rem.change import process_event, submit_event

    path = out_dir / f"controlled-{seed}.pkl"
    if path.exists():
        return path
    world0, world1 = World(seed), World(seed)
    events = world1.events()
    restricted = {f"{t}:{k}" for t, k in world1.restricted_keys()}
    deleted = {f"order:{o.key}" for o in world1.orders.values() if o.deleted} | {f"passage:{o.key}#text" for o in world1.orders.values() if o.deleted}
    questions = [dict(e["question"], kind="delay_projects") for e in events if "question" in e] + world1.extra_questions()
    samples: list[Sample] = []
    with factory() as s:
        tenant, people, _, _ = make_tenant(s, world0, embedder, f"remnet-{seed}-{uuid.uuid4().hex[:4]}")
        for ev in events:
            e, _ = submit_event(s, tenant.id, kind=ev["kind"], payload=ev["payload"], idempotency_key=ev["key"])
            process_event(s, e.id, embedder=embedder)
        build_routing(s, tenant.id, seed=seed)
        s.commit()
        vis = visible_scopes(s, people["ops"])
        for qi, q in enumerate(questions):
            gold = set(q["gold_evidence"]) - deleted - restricted
            if not gold:
                continue
            reader = GraphReader(s, tenant.id, vis)
            qvec = embedder.embed([q["text"]])[0]
            hits = [(nid, sc) for nid, sc, _ in reader.search(q["text"], qvec, k=10)]
            smp = extract(reader, qid=f"{seed}-{qi}", question=q["text"], qvec=qvec, start_hits=hits, gold=gold,
                          label_of=lambda n, g=gold: f"{n.type}:{n.key}" in g, doc_of=lambda n: f"{n.type}:{n.key}", **POOL)
            smp.baselines = _baselines(s, tenant.id, vis, people["ops"].id, q["text"], hits, CONTROLLED_BUDGETS, embedder,
                                       lambda e: f"{e['node']['type']}:{e['node']['key']}")
            smp.kind = q["kind"]
            samples.append(smp)
            s.rollback()
    path.write_bytes(pickle.dumps(samples))
    return path


# ---------------------------------------------------------------------------------------------- ERB
def erb_split(qid: str) -> str:
    from cie.eval.rem_erb import split_of

    if split_of(qid) == "heldout":
        return "test"
    return "val" if int(hashlib.sha1(("val" + qid).encode()).hexdigest(), 16) % 5 == 0 else "train"


def build_erb(root: Path, tenant_name: str, out_dir: Path, embedder, factory, limit: int | None = None, log=print) -> Path:
    from cie.core.models import Document, Principal, Tenant
    from cie.core.settings import get_settings
    from cie.eval.rem_erb import start_hits as hybrid_hits
    from cie.governance.permissions import visible_scopes
    from cie.rem.models import RemNode, RemNodeVersion
    from cie.retrieval.pipeline import Retriever

    path = out_dir / "erb.pkl"
    if path.exists():
        return path
    questions = [json.loads(line) for line in (root / "questions.jsonl").read_text().splitlines() if line.strip()]
    questions = [q for q in questions if q["expected_doc_ids"]][: limit or None]
    samples: list[Sample] = []
    with factory() as s:
        t = s.scalar(select(Tenant).where(Tenant.name == tenant_name))
        company = s.scalar(select(text("id")).select_from(text("scopes")).where(text("tenant_id = :t AND parent_id IS NULL")).params(t=t.id))
        admin = s.scalar(select(Principal).where(Principal.tenant_id == t.id, Principal.name == "admin"))
        vis = visible_scopes(s, admin)
        dsid_of_doc = {str(i): e.get("dsid") for i, e in s.execute(select(Document.id, Document.extra).where(Document.tenant_id == t.id))}
        nodes = s.execute(select(RemNode.id, RemNode.type, RemNode.key).where(RemNode.tenant_id == t.id)).all()
        key_node = {k: i for i, _t, k in nodes}
        dsid_node = {doc: key_node[d] for doc, d in dsid_of_doc.items() if d in key_node}
        doc_of_node: dict[str, str] = {}
        for i, typ, k in nodes:
            if typ == "document":
                doc_of_node[str(i)] = k
        for nid, d in s.execute(select(RemNodeVersion.node_id, RemNodeVersion.attrs["document"].astext)
                                .where(RemNodeVersion.tenant_id == t.id, RemNodeVersion.sys_to.is_(None))):
            if d:
                doc_of_node[str(nid)] = d
        retriever = Retriever(s, get_settings(), embedder=embedder)
        t0 = time.perf_counter()
        for qi, q in enumerate(questions):
            gold = set(q["expected_doc_ids"])
            hits, search_ms = hybrid_hits(s, retriever, admin, company, q["question"], dsid_node, key_node)
            s.rollback()
            reader = GraphReader(s, t.id, vis)
            qvec = embedder.embed([q["question"]])[0]
            smp = extract(reader, qid=q["question_id"], question=q["question"], qvec=qvec, start_hits=hits, gold=gold,
                          label_of=lambda n, g=gold: doc_of_node.get(str(n.id)) in g, doc_of=lambda n: doc_of_node.get(str(n.id)), **POOL)
            smp.search_ms = search_ms
            smp.baselines = _baselines(s, t.id, vis, admin.id, q["question"], hits, ERB_BUDGETS, embedder,
                                       lambda e: doc_of_node.get(e["node"]["id"]))
            smp.kind = q["question_type"]
            smp.split = erb_split(q["question_id"])
            samples.append(smp)
            s.rollback()
            if (qi + 1) % 50 == 0:
                log(f"  {qi + 1}/{len(questions)} ERB questions, {time.perf_counter() - t0:.0f} s")
    path.write_bytes(pickle.dumps(samples))
    return path


def load(paths) -> list[Sample]:
    out: list[Sample] = []
    for p in paths:
        out += pickle.loads(Path(p).read_bytes())
    return out


def describe(samples: list[Sample]) -> dict[str, Any]:
    import statistics

    if not samples:
        return {}
    return {"questions": len(samples), "pool_nodes_p50": statistics.median(s.n for s in samples),
            "edges_p50": statistics.median(len(s.src) for s in samples),
            "gold_in_pool": round(statistics.mean(len({s.keys[i] if s.docs[i] is None else s.docs[i] for i in range(s.n)
                                                       if s.labels[i] > 0} & set(s.gold)) / len(s.gold) for s in samples), 3),
            "extract_ms_p50": round(statistics.median(s.extract_ms for s in samples), 1)}
