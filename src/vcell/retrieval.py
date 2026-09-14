"""The registered measurement: given the compartment, pick the protein.

Every candidate identity is scored on the *same* tile with the *same* reference
channel, so the only thing that varies across a ranking is the knowledge vector.
That is what makes this a clean test of conditioning, and it is also why the
comparison is paired per tile rather than across tiles.

Chance is 1 / (number of candidates), printed alongside every accuracy, because
a retrieval number without its chance level is meaningless.
"""

from __future__ import annotations

import numpy as np

EPS = 1e-8


def unit_mass(field: np.ndarray) -> np.ndarray:
    out = np.clip(field.astype(np.float32), 0.0, None)
    total = out.sum()
    return out / total if total > 0 else out


def score_match(prediction: np.ndarray, truth: np.ndarray) -> float:
    """Pearson correlation between a prediction and the measured tile.

    Continuous and threshold-free, so a ranking cannot be manufactured by a
    threshold choice. Both fields are over the whole tile: OpenCell gives no
    cell mask, so there is nothing to restrict to.
    """
    p = prediction.ravel().astype(np.float64)
    t = truth.ravel().astype(np.float64)
    if p.std() < 1e-12 or t.std() < 1e-12:
        return float("nan")
    return float(np.corrcoef(p, t)[0, 1])


def rank_of_truth(scores: dict[str, float], truth_gene: str) -> tuple[int, int]:
    """(1-based rank of the true protein, number of candidates ranked).

    Ties are broken pessimistically -- every candidate scoring at least as well
    as the truth counts as ahead of it -- so a model that emits an identical
    field for every identity scores the worst possible rank rather than a
    lucky first place.
    """
    usable = {g: s for g, s in scores.items() if np.isfinite(s)}
    if truth_gene not in usable:
        return 0, len(usable)
    mine = usable[truth_gene]
    ahead = sum(1 for g, s in usable.items() if g != truth_gene and s >= mine)
    return ahead + 1, len(usable)


def retrieval_summary(ranks: list[tuple[int, int]]) -> dict[str, float]:
    valid = [(r, n) for r, n in ranks if r > 0 and n > 1]
    if not valid:
        return {"n": 0, "top1": float("nan"), "top2": float("nan"),
                "mrr": float("nan"), "chance_top1": float("nan"),
                "chance_mrr": float("nan"), "mean_rank": float("nan")}
    r = np.array([x[0] for x in valid], dtype=float)
    n = np.array([x[1] for x in valid], dtype=float)
    # Chance MRR for a uniform random ranking over n candidates is H_n / n.
    chance_mrr = float(np.mean([np.sum(1.0 / np.arange(1, int(k) + 1)) / k for k in n]))
    return {
        "n": int(r.size),
        "top1": float((r == 1).mean()),
        "top2": float((r <= 2).mean()),
        "mrr": float((1.0 / r).mean()),
        "mean_rank": float(r.mean()),
        "chance_top1": float((1.0 / n).mean()),
        "chance_mrr": chance_mrr,
        "n_candidates": float(n.mean()),
    }


def protein_clustered_bootstrap(
    values: np.ndarray, genes: np.ndarray, n_resamples: int = 1000, seed: int = 0
) -> tuple[float, float, float]:
    """(mean, lo, hi), resampling proteins rather than tiles.

    Sixteen tiles of one protein are one observation. The previous study's
    FOV clustering turned out to be a no-op because it drew one cell per field;
    here the clustering is real and it matters -- tiles from one protein share
    its expression level, its clone and its imaging session.
    """
    ok = np.isfinite(values)
    values, genes = values[ok], genes[ok]
    if values.size == 0:
        return float("nan"), float("nan"), float("nan")
    groups = [values[genes == g] for g in np.unique(genes)]
    rng = np.random.default_rng(seed)
    draws = np.empty(n_resamples)
    for i in range(n_resamples):
        pick = rng.integers(0, len(groups), size=len(groups))
        draws[i] = np.concatenate([groups[j] for j in pick]).mean()
    return (float(values.mean()), float(np.percentile(draws, 2.5)),
            float(np.percentile(draws, 97.5)))


def descriptor_retrieval(
    descriptors: np.ndarray,
    genes: np.ndarray,
    fovs: np.ndarray,
    candidate_genes: list[str],
) -> list[tuple[int, int]]:
    """Gate 1: nearest-neighbour retrieval on the fixed descriptor.

    Tiles from the same field of view are excluded from a tile's own candidate
    pool. Without that, two tiles cut from one image would match each other on
    shared illumination and cell layout, and the gate would pass on every
    compartment for a reason that has nothing to do with the protein.
    """
    sel = np.flatnonzero(np.isin(genes, candidate_genes))
    if sel.size < 2:
        return []
    X = descriptors[sel]
    g = genes[sel]
    f = fovs[sel]
    # Squared euclidean distance, all pairs.
    sq = (X**2).sum(axis=1)
    d2 = sq[:, None] + sq[None, :] - 2.0 * (X @ X.T)
    out = []
    for i in range(sel.size):
        pool = np.flatnonzero(f != f[i])
        if pool.size == 0:
            continue
        # Score each candidate protein by its nearest tile to this one, so the
        # ranking is over proteins rather than over tiles.
        scores = {}
        for cand in candidate_genes:
            rows = pool[g[pool] == cand]
            if rows.size:
                scores[cand] = -float(d2[i, rows].min())
        out.append(rank_of_truth(scores, str(g[i])))
    return out
