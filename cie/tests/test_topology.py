"""Directed flag complex: simplices, sinks, cavities; the recruitment cascade."""

from __future__ import annotations

from cie.topology.cliques import activation_order, betti1, directed_flag_complex


def test_directed_simplices_and_sinks():
    # a directed 3-simplex a->b->c->d (all-to-all, consistently ordered) plus a dangling edge d->e
    edges = [("a", "b"), ("a", "c"), ("a", "d"), ("b", "c"), ("b", "d"), ("c", "d"), ("d", "e")]
    cx = directed_flag_complex(list("abcde"), edges, max_dim=5)
    assert cx.by_dim[3] == 1 and cx.by_dim[2] == 4 and cx.by_dim[1] == 7
    assert cx.max_dim["d"] == 3 and cx.max_dim["e"] == 1
    assert cx.sink_of["d"] == 4 and cx.source_of["a"] == 4  # d ends abd, acd, bcd and abcd; a starts abc, abd, acd and abcd
    assert cx.betti1 == 0  # every cycle is filled by a triangle


def test_cavity_detected_and_filled():
    square = [("a", "b"), ("b", "c"), ("c", "d"), ("d", "a")]
    assert betti1(list("abcd"), square, []) == 1  # a hollow square is a 1-cavity
    # two consistently oriented triangles (a->b->c and a->d->c, both with a->c) fill the square
    filled = [("a", "b"), ("b", "c"), ("a", "c"), ("a", "d"), ("d", "c")]
    cx = directed_flag_complex(list("abcd"), filled, max_dim=3)
    assert cx.by_dim[2] == 2 and cx.betti1 == 0
    # a cycle whose triangles are not consistently oriented is not filled in the *directed* complex
    cx2 = directed_flag_complex(list("abcd"), square + [("a", "c")], max_dim=3)
    assert cx2.by_dim.get(2, 0) == 1 and cx2.betti1 == 1  # a->b->c is a simplex; a->c->d->a is a directed cycle, a cavity


def test_cascade_stages():
    # seeds s1, s2 share a link; x closes a triangle with both; y is the sink of the tetrahedron {s1, s2, x, y}
    edges = [("s1", "s2"), ("s1", "x"), ("s2", "x"), ("s1", "y"), ("s2", "y"), ("x", "y"), ("z", "q")]
    cx = directed_flag_complex(["s1", "s2", "x", "y", "z", "q"], edges, max_dim=5)
    stage = activation_order(cx, {"s1", "s2"})
    assert stage["s1"] == 1 and stage["s2"] == 1
    assert stage["x"] == 2 and stage["y"] == 2  # both join simplices with two seeds
    assert "z" not in stage and "q" not in stage


def test_enumeration_bound_is_reported():
    nodes = [f"n{i}" for i in range(12)]
    edges = [(nodes[i], nodes[j]) for i in range(12) for j in range(i + 1, 12)]  # a directed 11-simplex
    cx = directed_flag_complex(nodes, edges, max_dim=4, max_simplices=500)
    assert cx.truncated and max(cx.by_dim) <= 4


import pytest  # noqa: E402


@pytest.mark.db
def test_clique_cascade_retrieval_keeps_answers_and_reports_topology(session, world, vault, embedder):
    from cie.extraction.pipeline import run_extraction
    from cie.retrieval.pipeline import Retriever
    from tests.fixtures import CONTRACT_SECTIONS, make_pdf

    doc = vault.ingest(session, tenant_id=world.tenant.id, data=make_pdf(CONTRACT_SECTIONS), filename="msa.pdf",
                       scope_id=world.project.id, doc_type="contract").document
    session.commit()
    run_extraction(session, doc, vault=vault, embedder=embedder, ocr=None)
    r = Retriever(session, embedder=embedder)
    q = "What is the monthly fee in the Northwind agreement?"
    rem = r.retrieve(q, world.admin, world.project.id)
    topo = r.retrieve(q, world.admin, world.project.id, graph_mode="cliques+bonus")
    assert topo.trace["topology"]["nodes"] > 0 and topo.trace["topology"]["simplices_by_dim"].get(1, 0) > 0
    top_rem = {it["id"] for it in rem.packet.items[:5]}
    top_topo = {it["id"] for it in topo.packet.items[:5]}
    assert top_rem & top_topo, "the cascade must not lose the records the standard pipeline ranks first"
    assert any(c.clique_dim >= 1 for c in topo.ranked), "activated records carry their clique dimension"
    assert any("clique" in c.reasons for c in topo.ranked)


@pytest.mark.db
def test_plasticity_potentiates_used_links_and_restores(session, world):
    from cie.core.models import LinkKind, RecordType
    from cie.memory.records import create_record, link
    from cie.topology import plasticity

    t = world.tenant.id
    a, b, c = (create_record(session, tenant_id=t, scope_id=world.project.id, type=RecordType.fact, summary=f"r{i}", content={}, detail="x")
               for i in range(3))
    ab = link(session, a, b, LinkKind.relates_to)
    bc = link(session, b, c, LinkKind.relates_to)
    session.flush()
    w_ab, w_bc = float(ab.weight), float(bc.weight)
    upd = plasticity.stdp_update(session, fired=[a.id, b.id], traversed=[(b.id, c.id)])
    assert upd["potentiated"] == 1 and upd["depressed"] == 1
    assert float(ab.weight) > w_ab and float(bc.weight) < w_bc
    assert plasticity.restore(session, upd["previous"]) == 2
    assert float(ab.weight) == w_ab and float(bc.weight) == w_bc


@pytest.mark.db
def test_dynamic_memory_forms_oriented_links_and_shapes(session, world):
    from sqlalchemy import select

    from cie.core.models import LinkKind, RecordLink, RecordType
    from cie.governance.permissions import visible_scopes
    from cie.memory.records import create_record
    from cie.topology import dynamic

    t = world.tenant.id
    recs = [create_record(session, tenant_id=t, scope_id=world.project.id, type=RecordType.fact, summary=f"r{i}", content={}, detail="x") for i in range(5)]
    fired = [r.id for r in recs[:4]]  # ranked best first
    out = dynamic.observe(session, tenant_id=t, principal_id=world.admin.id, fired=fired, query="what is the fee?")
    assert out["formed"] == 6 and out["potentiated"] == 0
    links = list(session.scalars(select(RecordLink).where(RecordLink.kind == LinkKind.coactivated)))
    assert all(link.dst_id == fired[0] for link in links if fired[0] in (link.src_id, link.dst_id)), "the best record is the sink"
    again = dynamic.observe(session, tenant_id=t, principal_id=world.admin.id, fired=fired, query="what is the fee?")
    assert again["potentiated"] == 6 and again["formed"] == 0
    shapes = dynamic.shapes(session, t, visible_scopes(session, world.admin))
    assert shapes["max_dim"] == 3 and shapes["shapes"][0]["sink"]["id"] == str(fired[0])  # a directed tetrahedron with the answer as sink
    # a different group sharing two records: decay and later pruning of the links that stop firing
    other = [recs[4].id, recs[3].id, recs[2].id]
    for _ in range(40):
        dynamic.observe(session, tenant_id=t, principal_id=world.admin.id, fired=other, query="who signed?")
    remaining = list(session.scalars(select(RecordLink).where(RecordLink.kind == LinkKind.coactivated)))
    assert len(remaining) < 6 + 3, "links between records that stopped co-firing were pruned"
    assert dynamic.reset(session, t, world.admin.id) == len(remaining)


def test_fired_records_are_gated_by_the_answer_documents():
    from cie.topology.dynamic import fired_records

    items = [{"id": "a", "kind": "record", "support": 0.9, "document_id": "d1"}, {"id": "b", "kind": "record", "support": 0.8, "document_id": "d2"},
             {"id": "c", "kind": "record", "support": 0.7, "document_id": "d1"}, {"id": "s", "kind": "section", "support": 0.9, "document_id": "d1"},
             {"id": "e", "kind": "record", "support": 0.2, "document_id": "d1"}]
    import uuid

    ids = {k: str(uuid.uuid5(uuid.NAMESPACE_DNS, k)) for k in "abcse"}
    for it in items:
        it["id"] = ids[it["id"]]
    fired = fired_records(items, [{"item_id": ids["a"], "kind": "record"}, {"item_id": ids["b"], "kind": "record"}])
    assert [str(x) for x in fired] == [ids["a"], ids["c"]], "the other document's citation and the weak record do not fire with the answer"
    two = fired_records(items, [{"item_id": ids["a"], "kind": "record"}, {"item_id": ids["b"], "kind": "record"}], max_docs=2)
    assert [str(x) for x in two] == [ids["a"], ids["b"], ids["c"]], "a conflict answer may wire across its two documents"
    assert fired_records(items, []) == [], "nothing cited, nothing wired"
