"""Train the conditional model on OpenCell tiles and run the retrieval test.

One thing here is worth stating plainly, because it decides how the result
should be read. Gate 1's descriptor retrieval gets to look at *real images* of
every candidate protein and match a test tile against them. The model gets no
images of the held-out proteins at all -- it has to produce a field from
annotation alone and be matched against the truth. Those are not the same
difficulty, so gate 1 is a statement about how much protein-specific signal
exists in the pixels, not a bar the model is expected to reach.

The comparison that *is* fair is `ridge_descriptor_retrieval`: a ridge
regression from the knowledge vector to the fixed descriptor, fitted on training
proteins only. Like the model it maps annotation to image properties and sees no
held-out image; unlike the model it only has to predict 36 numbers rather than a
36,864-pixel field. If even that fails, the failure is in the annotation, not in
the architecture.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

from vcell.model import ConditionalUNet2D, count_parameters
from vcell.opencell import KNOWLEDGE_BLOCKS, Target, knowledge_vector
from vcell.retrieval import (
    protein_clustered_bootstrap,
    rank_of_truth,
    retrieval_summary,
    score_match,
    unit_mass,
)

EPS = 1e-8


def training_families(sample: dict[str, dict[str, list[Target]]]) -> list[str]:
    """Family vocabulary from training targets only -- see opencell.knowledge_blocks."""
    return sorted({t.family for d in sample.values() for t in d["train"] if t.family})


class TileDataset(Dataset):
    def __init__(self, tiles, rows, vectors: dict[str, np.ndarray],
                 augment: bool = False, seed: int = 0):
        self.tiles = tiles
        self.rows = np.asarray(rows)
        self.vectors = vectors
        self.augment = augment
        self.rng = np.random.default_rng(seed)

    def __len__(self) -> int:
        return int(self.rows.size)

    def __getitem__(self, i: int):
        row = int(self.rows[i])
        ref = self.tiles["reference"][row].astype(np.float32)
        tgt = unit_mass(self.tiles["target"][row].astype(np.float32))
        if self.augment:
            # A projected field has no privileged in-plane direction, so flips
            # and 90-degree rotations are all label-preserving here -- unlike
            # the volumetric study, where Z is the optical axis.
            k = int(self.rng.integers(0, 4))
            if k:
                ref = np.rot90(ref, k, axes=(1, 2)).copy()
                tgt = np.rot90(tgt, k).copy()
            if self.rng.random() < 0.5:
                ref = np.flip(ref, 2).copy()
                tgt = np.flip(tgt, 1).copy()
        gene = str(self.tiles["gene"][row])
        return (torch.from_numpy(ref),
                torch.from_numpy(self.vectors[gene].astype(np.float32)),
                torch.from_numpy(tgt))


def cross_entropy_loss(pred: torch.Tensor, target: torch.Tensor):
    p = pred / pred.sum(dim=(1, 2), keepdim=True).clamp_min(EPS)
    ce = -(target * (p + EPS).log()).sum(dim=(1, 2))
    ent = -(target * (target + EPS).log()).sum(dim=(1, 2))
    return ce.mean(), (ce - ent).mean().detach()


def train(tiles, rows, vectors, cond_dim, epochs, batch_size, seed, threads=4,
          base=24, depth=4, log_prefix=""):
    torch.manual_seed(seed)
    torch.set_num_threads(threads)
    model = ConditionalUNet2D(in_channels=1, cond_dim=cond_dim, base=base, depth=depth)
    loader = DataLoader(
        TileDataset(tiles, rows, vectors, augment=True, seed=seed),
        batch_size=batch_size, shuffle=True, drop_last=False,
    )
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    print(f"{log_prefix}training on {len(rows)} tiles, cond_dim {cond_dim}, "
          f"{count_parameters(model)/1e6:.2f}M parameters", flush=True)
    model.train()
    for epoch in range(1, epochs + 1):
        t0, total, n = time.time(), 0.0, 0
        for ref, know, tgt in loader:
            opt.zero_grad(set_to_none=True)
            loss, kl = cross_entropy_loss(model(ref, know), tgt)
            loss.backward()
            opt.step()
            total += float(kl)
            n += 1
        if epoch == 1 or epoch % 5 == 0 or epoch == epochs:
            print(f"{log_prefix}  epoch {epoch:3d}/{epochs}  KL {total/max(n,1):.4f}"
                  f"  {time.time()-t0:.0f}s", flush=True)
    model.eval()
    return model


def predict(model, reference: np.ndarray, vector: np.ndarray) -> np.ndarray:
    with torch.no_grad():
        out = model(torch.from_numpy(reference.astype(np.float32))[None],
                    torch.from_numpy(vector.astype(np.float32))[None])
    return unit_mass(out[0].numpy())


def model_retrieval(model, tiles, rows, candidates: list[str],
                    vectors: dict[str, np.ndarray],
                    mismatch_reference: bool = False, seed: int = 0):
    """Rank the candidate identities for each held-out tile.

    With `mismatch_reference`, every candidate is scored using a reference tile
    from a *different* field of view. If accuracy survives that, the model is
    matching a per-protein template and ignoring the cell in front of it -- H4.
    """
    rng = np.random.default_rng(seed)
    rows = np.asarray(rows)
    ranks, records = [], []
    for row in rows:
        row = int(row)
        truth = unit_mass(tiles["target"][row].astype(np.float32))
        if mismatch_reference:
            other = rows[tiles["fov_id"][rows] != tiles["fov_id"][row]]
            if other.size == 0:
                continue
            ref_row = int(other[rng.integers(0, other.size)])
        else:
            ref_row = row
        reference = tiles["reference"][ref_row].astype(np.float32)
        scores = {c: score_match(predict(model, reference, vectors[c]), truth)
                  for c in candidates}
        gene = str(tiles["gene"][row])
        rank, n = rank_of_truth(scores, gene)
        ranks.append((rank, n))
        records.append({"gene": gene, "fov_id": str(tiles["fov_id"][row]),
                        "rank": rank, "n_candidates": n,
                        "score_true": scores.get(gene),
                        "score_best_other": max(
                            (s for g, s in scores.items() if g != gene and np.isfinite(s)),
                            default=float("nan"))})
    return ranks, records


def ridge_descriptor_retrieval(
    descriptors: np.ndarray, tiles, train_rows, test_rows,
    candidates: list[str], vectors: dict[str, np.ndarray], ridge: float = 1.0
):
    """The fair annotation-only baseline: knowledge -> descriptor, by ridge.

    Fitted on training tiles only. Predicts 36 descriptor numbers instead of a
    whole field, so it is a strictly easier version of the model's job.
    """
    K = np.stack([vectors[str(tiles["gene"][r])] for r in train_rows]).astype(np.float64)
    Y = descriptors[train_rows].astype(np.float64)
    mu, sd = Y.mean(0), Y.std(0)
    sd[sd < 1e-8] = 1.0
    Yz = (Y - mu) / sd
    K1 = np.hstack([K, np.ones((K.shape[0], 1))])
    W = np.linalg.solve(K1.T @ K1 + ridge * np.eye(K1.shape[1]), K1.T @ Yz)
    ranks = []
    for row in test_rows:
        row = int(row)
        target_z = (descriptors[row].astype(np.float64) - mu) / sd
        scores = {}
        for c in candidates:
            k1 = np.concatenate([vectors[c].astype(np.float64), [1.0]])
            scores[c] = -float(np.sum((k1 @ W - target_z) ** 2))
        ranks.append(rank_of_truth(scores, str(tiles["gene"][row])))
    return ranks


def summarise_with_interval(ranks, genes, seed: int = 0) -> dict:
    s = retrieval_summary(ranks)
    hit = np.array([1.0 if r == 1 else 0.0 for r, n in ranks if r > 0 and n > 1])
    g = np.array([genes[i] for i, (r, n) in enumerate(ranks) if r > 0 and n > 1])
    if hit.size:
        m, lo, hi = protein_clustered_bootstrap(hit, g, seed=seed)
        s["top1_lo"], s["top1_hi"] = lo, hi
    else:
        s["top1_lo"] = s["top1_hi"] = float("nan")
    return s


def build_vectors(
    sample, families, blocks=KNOWLEDGE_BLOCKS, compartment_form: str = "graded"
) -> dict[str, np.ndarray]:
    out = {}
    for d in sample.values():
        for group in d.values():
            for t in group:
                out[t.gene] = knowledge_vector(
                    t, families, blocks=blocks, compartment_form=compartment_form
                )
    return out


def save_json(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=float))
