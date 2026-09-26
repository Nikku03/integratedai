"""Learned explorers over a question's candidate pool.

All models share the encoder and scorer; they differ only in how node states are updated.

* ``mlp``   no message passing: each record is scored from its own features and the question (control: does the
            graph help at all?).
* ``ggnn``  ordinary gated graph network: every record in the pool is updated at every step,
            h_i <- GRU(h_i, sum_j alpha_ij(q, t) W_{r_ij} h_j)  (relation-typed weights, question-conditioned attention).
* ``rem``   REM-inspired bounded activation: computation starts at the search hits; at each step the records
            adjacent to the active set are loaded ("touched") and a learned gate activates at most K of them; only
            active records are updated, and only touched records can be returned. Routing shortcuts are an extra
            relation when present.
* ``rem`` options, all fixed before training:
    - ``inhibition``: contradicts / supersedes edges carry negative messages (Dale's law: sign fixed by the
      relation, as a neuron's outputs are either excitatory or inhibitory).
    - ``stp="bluebrain"``: each edge has Tsodyks-Markram short-term plasticity with (U, D, F) and a release-failure
      rate drawn from a Blue Brain microcircuit pathway of the matching sign; message strength follows the
      synapse's efficacy over successive transmissions (see ``cie.remnet.bluebrain``).
    - ``stp="random"``: the same mechanism with parameters drawn uniformly (log scale) over the Blue Brain ranges.
    - ``stp="learned"``: the same mechanism with (U, D, F) learned per relation, no failures.
  Comparing these isolates whether the biological *values* matter, beyond the mechanism.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import torch
from torch import nn

from cie.rem.models import BUSINESS_EDGE_KINDS
from cie.remnet import bluebrain
from cie.remnet.graphs import FEATS, INHIBITORY_KINDS, N_RELS, ROUTING_REL, R, Sample

INHIBITORY_RELS = {BUSINESS_EDGE_KINDS.index(k) for k in INHIBITORY_KINDS} | {BUSINESS_EDGE_KINDS.index(k) + R for k in INHIBITORY_KINDS}


@dataclass
class Config:
    kind: str = "rem"  # mlp | ggnn | rem
    d: int = 64
    steps: int = 3
    k_active: int = 16
    inhibition: bool = False
    stp: str | None = None  # None | bluebrain | random | learned
    failures: bool = False
    routing: bool = True
    gate_aux: float = 0.3

    @property
    def name(self) -> str:
        if self.kind != "rem":
            return self.kind
        parts = ["rem"]
        if self.inhibition:
            parts.append("inh")
        if self.stp:
            parts.append(f"stp-{self.stp}")
        if self.failures:
            parts.append("fail")
        if not self.routing:
            parts.append("norouting")
        return "+".join(parts)


class Tensors:
    """A ``Sample`` as tensors, with the per-edge synaptic parameters the config needs."""

    def __init__(self, s: Sample, cfg: Config):
        self.s = s
        self.emb = torch.from_numpy(s.emb)
        self.feats = torch.from_numpy(s.feats)
        self.q = torch.from_numpy(s.qvec)
        keep = torch.ones(len(s.rel), dtype=torch.bool) if cfg.routing else torch.from_numpy(s.rel != ROUTING_REL)
        self.src = torch.from_numpy(s.src)[keep]
        self.dst = torch.from_numpy(s.dst)[keep]
        self.rel = torch.from_numpy(s.rel)[keep]
        keys = [k for k, m in zip(s.edge_keys, keep.tolist(), strict=True) if m]
        self.labels = torch.from_numpy(s.labels)
        self.is_start = torch.from_numpy(s.is_start)
        self.sign = torch.ones(len(self.rel))
        inh = torch.tensor([int(r) in INHIBITORY_RELS for r in self.rel.tolist()], dtype=torch.bool)
        if cfg.inhibition:
            self.sign[inh] = -1.0
        self.U = self.D = self.F = self.pfail = None
        if cfg.stp in ("bluebrain", "random"):
            U, D, F, P = [], [], [], []
            for key, is_inh in zip(keys, inh.tolist(), strict=True):
                if cfg.stp == "bluebrain":
                    syn = bluebrain.pick(key, is_inh)
                    U.append(syn.U), D.append(syn.D), F.append(syn.F), P.append(syn.failure)
                else:
                    h = int(hashlib.sha1(key.encode()).hexdigest(), 16)
                    r = [((h >> (16 * i)) & 0xFFFF) / 65535.0 for i in range(4)]
                    U.append(math.exp(math.log(0.05) + r[0] * (math.log(0.7) - math.log(0.05))))
                    D.append(math.exp(math.log(50) + r[1] * (math.log(1500) - math.log(50))))
                    F.append(math.exp(math.log(10) + r[2] * (math.log(1000) - math.log(10))))
                    P.append(0.5 * r[3])
            self.U, self.D, self.F, self.pfail = (torch.tensor(x, dtype=torch.float32) for x in (U, D, F, P))


def segment_softmax(logits: torch.Tensor, index: torch.Tensor, n: int) -> torch.Tensor:
    if logits.numel() == 0:
        return logits
    mx = torch.full((n,), -1e9).scatter_reduce(0, index, logits, reduce="amax", include_self=True)
    ex = torch.exp(logits - mx[index])
    den = torch.zeros(n).index_add(0, index, ex)
    return ex / (den[index] + 1e-9)


class Explorer(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        d = cfg.d
        self.enc_e = nn.Linear(384, d)
        self.enc_f = nn.Linear(FEATS, d)
        self.enc_q = nn.Linear(384, d)
        self.norm = nn.LayerNorm(d)
        self.score = nn.Sequential(nn.Linear(3 * d, d), nn.ReLU(), nn.Linear(d, 1))
        if cfg.kind in ("ggnn", "rem"):
            self.W = nn.Parameter(torch.randn(N_RELS, d, d) * (1.0 / math.sqrt(d)))
            self.rel_emb = nn.Embedding(N_RELS, d)
            self.att_h, self.att_s, self.att_q = nn.Linear(d, d, bias=False), nn.Linear(d, d, bias=False), nn.Linear(d, d)
            self.att_v = nn.Linear(d, 1, bias=False)
            self.gru = nn.GRUCell(d, d)
        if cfg.kind == "rem":
            self.gate = nn.Linear(3 * d, 1)
        if cfg.stp == "learned":  # per relation: U in (0,1), D and F in ms (log-parametrised)
            self.stp_u = nn.Parameter(torch.full((N_RELS,), -0.5))
            self.stp_logd = nn.Parameter(torch.full((N_RELS,), math.log(300.0)))
            self.stp_logf = nn.Parameter(torch.full((N_RELS,), math.log(100.0)))

    # ------------------------------------------------------------------
    def _efficacy(self, t: Tensors, count: torch.Tensor) -> torch.Tensor:
        """Release efficacy of each edge at its ``count``-th transmission (0-based), normalised to the first."""
        cfg = self.cfg
        if cfg.stp is None:
            return torch.ones_like(count, dtype=torch.float32)
        if cfg.stp == "learned":
            U = torch.sigmoid(self.stp_u)[t.rel]
            D, F = torch.exp(self.stp_logd)[t.rel], torch.exp(self.stp_logf)[t.rel]
        else:
            U, D, F = t.U, t.D, t.F
        dt = bluebrain.DT_MS
        ef, ed = torch.exp(-dt / F), torch.exp(-dt / D)
        u, r = U.clone(), torch.ones_like(U)
        out = u * r / U
        for n in range(1, int(count.max().item()) + 1 if count.numel() else 1):
            u_next = u * ef + U * (1 - u * ef)
            r_next = r * (1 - u) * ed + 1 - ed
            u, r = u_next, r_next
            out = torch.where(count >= n, u * r / U, out)
        return out

    def _messages(self, t: Tensors, h: torch.Tensor, q: torch.Tensor, count: torch.Tensor, src_ok: torch.Tensor) -> torch.Tensor:
        n = h.shape[0]
        if t.src.numel() == 0:
            return torch.zeros_like(h)
        hs, hd = h[t.src], h[t.dst]
        msg = torch.einsum("ed,edk->ek", hs, self.W[t.rel])
        logit = self.att_v(torch.tanh(self.att_h(hd) + self.att_s(hs) + self.att_q(q) + self.rel_emb(t.rel))).squeeze(-1)
        logit = logit.masked_fill(~src_ok, -1e9)
        alpha = segment_softmax(logit, t.dst, n) * src_ok.float()
        w = alpha * t.sign * self._efficacy(t, count)
        if self.cfg.failures and t.pfail is not None:
            w = w * (torch.bernoulli(1 - t.pfail) if self.training else (1 - t.pfail))
        return torch.zeros_like(h).index_add(0, t.dst, w.unsqueeze(-1) * msg)

    def forward(self, t: Tensors) -> tuple[torch.Tensor, dict, torch.Tensor | None]:
        """Returns (scores [N] with -inf for records never touched, stats, gate loss or None)."""
        cfg = self.cfg
        h = torch.tanh(self.norm(self.enc_e(t.emb) + self.enc_f(t.feats)))
        q = torch.tanh(self.enc_q(t.q))
        n = h.shape[0]
        qn = q.expand(n, -1)
        stats = {"updates": 0, "touched": n}
        gate_loss = None
        if cfg.kind == "ggnn":
            count = torch.zeros(len(t.rel), dtype=torch.long)
            ok = torch.ones(len(t.rel), dtype=torch.bool)
            for _ in range(cfg.steps):
                h = self.gru(self._messages(t, h, q, count, ok), h)
                count = count + 1
            stats["updates"] = n * cfg.steps
        elif cfg.kind == "rem":
            touched = t.is_start.clone()
            if not bool(touched.any()):
                touched[0] = True
            active = touched.clone()
            count = torch.zeros(len(t.rel), dtype=torch.long)
            losses = []
            updates = 0
            for _ in range(cfg.steps):
                # load the records next to the active ones; only loaded records can send messages or be activated
                if t.src.numel():
                    nb = torch.zeros(n, dtype=torch.bool)
                    nb[t.dst[active[t.src]]] = True
                    touched = touched | nb
                cand = touched
                g = self.gate(torch.cat([h, qn, h * qn], -1)).squeeze(-1)
                soft = torch.sigmoid(g)
                k = min(cfg.k_active, int(cand.sum()))
                hard = torch.zeros(n)
                idx = torch.topk(g.masked_fill(~cand, -1e9), k).indices
                hard[idx] = 1.0
                mask = (hard - soft.detach() + soft) * cand.float()  # straight-through estimator
                if self.training and cfg.gate_aux > 0:
                    losses.append(nn.functional.binary_cross_entropy_with_logits(g[cand], t.labels[cand]))
                ok = touched[t.src] if t.src.numel() else torch.zeros(0, dtype=torch.bool)
                m = self._messages(t, h, q, count, ok)
                h_new = self.gru(m, h)
                h = h + mask.unsqueeze(-1) * (h_new - h)
                active = hard.bool()
                if t.src.numel():
                    count = count + active[t.src].long()  # a synapse advances its dynamics when its source fires
                updates += k
            stats = {"updates": updates, "touched": int(touched.sum())}
            gate_loss = torch.stack(losses).mean() if losses else None
            s = self.score(torch.cat([h, qn, h * qn], -1)).squeeze(-1)
            return s.masked_fill(~touched, float("-inf")), stats, gate_loss
        s = self.score(torch.cat([h, qn, h * qn], -1)).squeeze(-1)
        return s, stats, gate_loss


def listwise_loss(scores: torch.Tensor, labels: torch.Tensor) -> torch.Tensor | None:
    """-log (probability mass the softmax over reachable records puts on gold records)."""
    ok = torch.isfinite(scores)
    pos = (labels > 0) & ok
    if not bool(pos.any()):
        return None
    s = scores[ok]
    return torch.logsumexp(s, 0) - torch.logsumexp(scores[pos], 0)
