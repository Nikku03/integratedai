"""Learned explorer: synaptic dynamics, activation budget, permission-filtered pools, packing."""

from __future__ import annotations

import math
import uuid

import numpy as np
import pytest
import torch

from cie.remnet import bluebrain
from cie.remnet.graphs import FEATS, Sample, metrics, pack
from cie.remnet.models import Config, Explorer, Tensors, listwise_loss


def test_tsodyks_markram_efficacy():
    dep = bluebrain.efficacy(0.5, 670, 17, 4)  # excitatory depressing (Blue Brain median)
    fac = bluebrain.efficacy(0.092, 140, 680, 4)  # excitatory facilitating
    assert dep[0] == fac[0] == 1.0
    assert dep[1] < dep[0] and dep[3] < dep[1], "a depressing synapse weakens with repeated release"
    assert fac[1] > 1.0 and fac[3] > fac[1], "a facilitating synapse strengthens"
    # recovery: a long interval restores the resources
    assert math.isclose(bluebrain.efficacy(0.5, 670, 17, 2, dt=1e6)[1], 1.0, rel_tol=1e-3)


def _sample(n=60, e=200, seed=0) -> Sample:
    rng = np.random.default_rng(seed)
    return Sample(qid="q", question="x", qvec=rng.normal(size=384).astype("float32"), node_ids=[str(i) for i in range(n)],
                  keys=[f"k:{i}" for i in range(n)], docs=[f"d{i // 3}" for i in range(n)], emb=rng.normal(size=(n, 384)).astype("float32"),
                  feats=rng.normal(size=(n, FEATS)).astype("float32"), tokens=np.full(n, 30), evidence_ok=np.ones(n, bool),
                  is_start=np.arange(n) < 4, src=rng.integers(0, n, e), dst=rng.integers(0, n, e), rel=rng.integers(0, 19, e),
                  edge_keys=[f"e{i}" for i in range(e)], labels=(np.arange(n) % 9 == 0).astype("float32"), gold=["k:0", "k:9"])


def test_bounded_activation_respects_its_budget_and_ranks_only_touched_records():
    s = _sample()
    for cfg in (Config(kind="rem", k_active=5, steps=3), Config(kind="rem", k_active=5, inhibition=True, stp="bluebrain", failures=True)):
        m = Explorer(cfg)
        scores, stats, _ = m.eval()(Tensors(s, cfg))
        assert stats["updates"] <= 5 * 3
        assert int(torch.isfinite(scores).sum()) == stats["touched"] <= s.n
    dense = Explorer(Config(kind="ggnn"))
    _, st, _ = dense.eval()(Tensors(s, Config(kind="ggnn")))
    assert st["updates"] == s.n * 3


def test_every_variant_learns_a_toy_task():
    s = _sample(seed=1)
    for cfg in (Config(kind="mlp"), Config(kind="ggnn"), Config(kind="rem", inhibition=True, stp="learned")):
        torch.manual_seed(0)
        m, t = Explorer(cfg), Tensors(s, cfg)
        opt = torch.optim.Adam(m.parameters(), 1e-2)
        first = None
        for _ in range(40):
            sc, _, gl = m.train()(t)
            loss = listwise_loss(sc, t.labels)
            loss = loss + (0.3 * gl if gl is not None else 0)
            first = float(loss.detach()) if first is None else first
            opt.zero_grad()
            loss.backward()
            opt.step()
        assert float(loss.detach()) < first


def test_inhibitory_relations_flip_the_message_sign():
    from cie.remnet.models import INHIBITORY_RELS

    s = _sample()
    t = Tensors(s, Config(kind="rem", inhibition=True))
    inh = torch.tensor([int(r) in INHIBITORY_RELS for r in t.rel.tolist()])
    assert bool((t.sign[inh] == -1).all()) and bool((t.sign[~inh] == 1).all())


def test_packing_respects_the_token_budget_and_metrics_use_gold():
    s = _sample()
    chosen = pack(s, list(range(s.n)), 100)
    assert sum(int(s.tokens[i]) for i in chosen) <= 100 and len(chosen) == 3
    m = metrics(s, pack(s, [9, 1, 0], 1000), "key")
    assert m["evidence_recall"] == 1.0 and m["rr"] == 1.0


@pytest.mark.db
def test_candidate_pools_contain_only_records_the_requester_may_see(session, world, embedder):
    from cie.governance.permissions import visible_scopes
    from cie.rem.change import process_event, submit_event
    from cie.rem.store import GraphReader
    from cie.remnet.graphs import extract

    def node(t, k, scope):
        return {"op": "upsert_node", "type": t, "key": k, "name": f"{t} {k}", "scope": scope}

    ops = [node("task", "a", "Finance"), node("task", "b", "Legal"), node("task", "c", "Finance"),
           {"op": "upsert_edge", "src": ["task", "a"], "kind": "depends_on", "dst": ["task", "b"]},
           {"op": "upsert_edge", "src": ["task", "b"], "kind": "depends_on", "dst": ["task", "c"]}]
    ev, _ = submit_event(session, world.tenant.id, kind="ops", payload={"ops": ops}, idempotency_key=uuid.uuid4().hex)
    process_event(session, ev.id, embedder=embedder)
    a = GraphReader(session, world.tenant.id, None).node_by_key("task", "a")
    reader = GraphReader(session, world.tenant.id, visible_scopes(session, world.outsider))
    smp = extract(reader, qid="q", question="task", qvec=embedder.embed(["task"])[0], start_hits=[(a.id, 1.0)], gold=set(),
                  label_of=lambda n: False, doc_of=lambda n: None)
    assert smp.keys == ["task:a"], "the hidden record and everything only reachable through it stay out of the pool"
