"""Wiring for the reasoning neurons: a piece of Blue Brain's cortex model, and controls with the same number of
connections.

Source: "SSCx toy circuit with 6k neurons in SONATA format" (Blue Brain Project, Zenodo record 12202781, CC-BY 4.0):
5,924 neurons of the rat somatosensory cortex, all six layers, and 568,717 synapses (123,636 connected pairs), built at
7% of biological density. Each synapse carries its Tsodyks-Markram release probability ``u_syn``, depression and
facilitation times.

* ``cortex``: a topological neighbourhood (Reimann et al.): a hub neuron and the partners with the most connections
  among its partners, kept with every connection between them, in their own direction.
* ``random``: the same neurons and the same number of connections, placed at random.
* ``degree``: the cortex wiring with its connections swapped pairwise (a->b, c->d to a->d, c->b), so every neuron keeps
  its in- and out-degree but the higher-order structure (the directed cliques) is broken.
* ``dense``: every neuron to every other, as in the original reasoning engine.

The "dimensions" are those of Reimann et al. 2017 (Front. Comput. Neurosci. 11:48): a directed n-simplex is n+1
neurons in which each earlier one connects to every later one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ZENODO_RECORD = "12202781"
ARCHIVE_SHA256 = "e2bb3057ea8346718c35940387cb291e5726defe61208aba7634af6292bb5334"


@dataclass
class Circuit:
    n: int
    pairs: np.ndarray  # (connections, 2): pre, post
    synapse_class: np.ndarray  # "EXC" / "INH" per neuron
    layer: np.ndarray
    mtype: np.ndarray
    u: np.ndarray  # per neuron: median over its outgoing synapses (release probability)
    dep_ms: np.ndarray
    fac_ms: np.ndarray


@dataclass
class Wiring:
    name: str
    n: int
    edges: np.ndarray  # (E, 2) local indices: pre, post
    unit_class: list[str] = field(default_factory=list)
    unit_layer: list[int] = field(default_factory=list)
    unit_mtype: list[str] = field(default_factory=list)
    u: np.ndarray | None = None
    dep_ms: np.ndarray | None = None
    fac_ms: np.ndarray | None = None
    source: str = ""

    def mask(self) -> np.ndarray:
        """``mask[post, pre]``: the layout of a recurrent weight matrix (row = receiving neuron)."""
        m = np.zeros((self.n, self.n), dtype=np.float32)
        if len(self.edges):
            m[self.edges[:, 1], self.edges[:, 0]] = 1.0
        return m

    def like(self, name: str, edges: np.ndarray) -> Wiring:
        return Wiring(name, self.n, edges, self.unit_class, self.unit_layer, self.unit_mtype, self.u, self.dep_ms, self.fac_ms, self.source)


def load(root: str | Path) -> Circuit:
    """Read the nodes and connections of the toy circuit's SONATA files (``root`` holds ``networks/``)."""
    import h5py

    root = Path(root)
    with h5py.File(root / "networks/nodes/All/nodes.h5", "r") as f:
        g, lib = f["nodes/All/0"], f["nodes/All/0/@library"]
        cls = np.array(lib["synapse_class"][:]).astype(str)[g["synapse_class"][:]]
        mtype = np.array(lib["mtype"][:]).astype(str)[g["mtype"][:]]
        layer = g["layer"][:]
    with h5py.File(root / "networks/edges/functional/All/edges.h5", "r") as f:
        e = f["edges/default"]
        src, tgt = e["source_node_id"][:], e["target_node_id"][:]
        u, dep, fac = e["0/u_syn"][:], e["0/depression_time"][:], e["0/facilitation_time"][:]
    n = len(cls)
    pairs = np.unique(np.stack([src, tgt], 1), axis=0)
    order = np.argsort(src, kind="stable")
    bounds = np.searchsorted(src[order], np.arange(n + 1))
    med = np.zeros((3, n))
    for i in range(n):
        idx = order[bounds[i]:bounds[i + 1]]
        if len(idx):
            med[:, i] = np.median(u[idx]), np.median(dep[idx]), np.median(fac[idx])
    for row in med:  # neurons with no outgoing synapse: the circuit's median
        row[row == 0] = np.median(row[row > 0])
    return Circuit(n, pairs, cls, layer, mtype, med[0], med[1], med[2])


def neighbourhood(c: Circuit, center: int, size: int = 64) -> np.ndarray:
    """``center`` and the ``size - 1`` partners with the most connections inside its neighbourhood."""
    partners = np.unique(np.r_[c.pairs[c.pairs[:, 0] == center, 1], c.pairs[c.pairs[:, 1] == center, 0]])
    nb = np.r_[center, partners[partners != center]]
    inside = np.isin(c.pairs[:, 0], nb) & np.isin(c.pairs[:, 1], nb)
    deg = np.bincount(c.pairs[inside].ravel(), minlength=c.n)[nb]
    rest = nb[1:][np.argsort(-deg[1:], kind="stable")][: size - 1]
    return np.r_[center, np.sort(rest)]


def hubs(c: Circuit, k: int) -> list[int]:
    deg = np.bincount(c.pairs.ravel(), minlength=c.n)
    return [int(i) for i in np.argsort(-deg, kind="stable")[:k]]


def cortex(c: Circuit, ids: np.ndarray, name: str = "cortex") -> Wiring:
    pos = {int(g): i for i, g in enumerate(ids)}
    keep = np.isin(c.pairs[:, 0], ids) & np.isin(c.pairs[:, 1], ids)
    edges = np.array([[pos[int(a)], pos[int(b)]] for a, b in c.pairs[keep]], dtype=np.int64).reshape(-1, 2)
    return Wiring(name, len(ids), edges, [str(x) for x in c.synapse_class[ids]], [int(x) for x in c.layer[ids]],
                  [str(x) for x in c.mtype[ids]], c.u[ids], c.dep_ms[ids], c.fac_ms[ids],
                  source=f"Blue Brain SSCx toy circuit (Zenodo {ZENODO_RECORD}), neighbourhood of neuron {int(ids[0])}")


def random_like(w: Wiring, seed: int) -> Wiring:
    """The same number of connections between the same neurons, placed uniformly (no self-connections)."""
    rng = np.random.default_rng(seed)
    possible = np.array([(a, b) for a in range(w.n) for b in range(w.n) if a != b])
    return w.like("random", possible[np.sort(rng.choice(len(possible), size=len(w.edges), replace=False))])


def degree_preserving(w: Wiring, seed: int, swaps_per_edge: int = 10) -> Wiring:
    """Swap the targets of random pairs of connections, keeping every in- and out-degree."""
    rng = np.random.default_rng(seed)
    edges = w.edges.copy()
    have = {(int(a), int(b)) for a, b in edges}
    for _ in range(swaps_per_edge * len(edges)):
        i, j = rng.integers(len(edges), size=2)
        (a, b), (c, d) = edges[i], edges[j]
        if a == d or c == b or (a, d) in have or (c, b) in have or i == j:
            continue
        have -= {(a, b), (c, d)}
        have |= {(a, d), (c, b)}
        edges[i], edges[j] = (a, d), (c, b)
    return w.like("degree", edges)


def dense(w: Wiring) -> Wiring:
    return w.like("dense", np.array([(a, b) for a in range(w.n) for b in range(w.n) if a != b]))


def simplices(w: Wiring, max_dim: int = 8) -> dict[int, int]:
    """Directed simplices of the wiring by dimension (1 = connections)."""
    from cie.topology.cliques import directed_flag_complex

    cx = directed_flag_complex(list(range(w.n)), [(int(a), int(b)) for a, b in w.edges], max_dim=max_dim, max_simplices=5_000_000)
    if cx.truncated:
        raise RuntimeError("too many simplices to count")
    return dict(sorted(cx.by_dim.items()))


def synthetic(n: int = 500, seed: int = 0) -> Circuit:
    """A small made-up circuit for tests: distance-dependent wiring, which is rich in directed cliques."""
    rng = np.random.default_rng(seed)
    xyz = rng.uniform(0, 1, (n, 3))
    d = np.linalg.norm(xyz[:, None] - xyz[None], axis=-1)
    p = 0.5 * np.exp(-d / 0.15)
    np.fill_diagonal(p, 0)
    pre, post = np.nonzero(rng.uniform(size=(n, n)) < p)
    cls = np.where(rng.uniform(size=n) < 0.88, "EXC", "INH")
    layer = 1 + (xyz[:, 2] * 6).astype(int)
    return Circuit(n, np.stack([pre, post], 1), cls, layer, np.array([f"L{x}" for x in layer]),
                   rng.uniform(0.2, 0.8, n), rng.uniform(100, 900, n), rng.uniform(1, 50, n))
