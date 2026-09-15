"""Match a protein's data fingerprint against its image fingerprint.

The screen before this asked the question the hard way: predict a protein's
36-dimensional image descriptor from its description, then check whether the
right protein ranks first. Predicting 36 numbers dilutes a shared signal across
36 regressions, and it forces the description to explain image variation that no
description could -- exposure, cell density, how many cells happened to be in
the tile.

Identification by fingerprint is a different and easier problem. Put both views
into one shared space and match there. That is what **canonical correlation
analysis** does: it finds the directions along which the two views co-vary most,
symmetrically, in closed form. If even one shared direction exists, CCA finds
it; a 36-output regression can miss it entirely.

Two things make it usable at this sample size (109 training proteins against
description blocks of up to a thousand dimensions):

* **Reduce first.** Each view is projected onto its own principal components
  before the CCA, with the number of components treated as a hyperparameter.
  Unregularised CCA on p > n views returns correlations of exactly 1 and means
  nothing.
* **Select inside the training set, and inside every permutation.** The number
  of components and the ridge are chosen by k-fold on training proteins only --
  and the whole selection is repeated inside each permutation of the null, so
  the null absorbs the selection's optimism instead of the result claiming it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Fingerprint:
    """A fitted shared space between a description view and an image view."""

    x_mean: np.ndarray
    y_mean: np.ndarray
    x_basis: np.ndarray       # description PCA basis
    y_basis: np.ndarray       # image PCA basis
    wx: np.ndarray            # canonical directions in reduced description space
    wy: np.ndarray            # canonical directions in reduced image space
    correlations: np.ndarray  # training canonical correlations
    n_components: int

    def embed_description(self, X: np.ndarray) -> np.ndarray:
        return ((X - self.x_mean) @ self.x_basis) @ self.wx

    def embed_image(self, Y: np.ndarray) -> np.ndarray:
        return ((Y - self.y_mean) @ self.y_basis) @ self.wy


def _pca_basis(X: np.ndarray, k: int) -> np.ndarray:
    """Top-k right singular vectors of the centred matrix."""
    k = max(1, min(k, min(X.shape) - 1))
    _, _, vt = np.linalg.svd(X, full_matrices=False)
    return vt[:k].T


def _inv_sqrt(S: np.ndarray, ridge: float) -> np.ndarray:
    d = S.shape[0]
    S = S + ridge * np.trace(S) / max(d, 1) * np.eye(d)
    vals, vecs = np.linalg.eigh(S)
    vals = np.clip(vals, 1e-12, None)
    return vecs @ np.diag(vals**-0.5) @ vecs.T


def fit_cca(
    X: np.ndarray, Y: np.ndarray, k_x: int, k_y: int, ridge: float,
    n_components: int = 4,
) -> Fingerprint:
    x_mean, y_mean = X.mean(axis=0), Y.mean(axis=0)
    Xc, Yc = X - x_mean, Y - y_mean
    x_basis, y_basis = _pca_basis(Xc, k_x), _pca_basis(Yc, k_y)
    A, B = Xc @ x_basis, Yc @ y_basis
    n = A.shape[0]
    Sxx = A.T @ A / n
    Syy = B.T @ B / n
    Sxy = A.T @ B / n
    M = _inv_sqrt(Sxx, ridge) @ Sxy @ _inv_sqrt(Syy, ridge)
    U, S, Vt = np.linalg.svd(M, full_matrices=False)
    m = min(n_components, S.shape[0])
    return Fingerprint(
        x_mean=x_mean, y_mean=y_mean, x_basis=x_basis, y_basis=y_basis,
        wx=_inv_sqrt(Sxx, ridge) @ U[:, :m],
        wy=_inv_sqrt(Syy, ridge) @ Vt[:m].T,
        correlations=S[:m], n_components=m,
    )


def held_out_correlations(fp: Fingerprint, X: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """Correlation of each canonical pair on data the fit never saw.

    This is the number that matters. Training canonical correlations are
    guaranteed to look good -- CCA maximises them by construction.
    """
    A, B = fp.embed_description(X), fp.embed_image(Y)
    out = []
    for k in range(fp.n_components):
        a, b = A[:, k], B[:, k]
        if a.std() < 1e-12 or b.std() < 1e-12:
            out.append(0.0)
        else:
            out.append(float(np.corrcoef(a, b)[0, 1]))
    return np.array(out)


def select_and_fit(
    X: np.ndarray, Y: np.ndarray, grid_x, grid_y, grid_ridge,
    n_components: int, folds: int, seed: int,
) -> tuple[Fingerprint, dict]:
    """Choose (k_x, k_y, ridge) by k-fold on these rows, then refit on all of them."""
    rng = np.random.default_rng(seed)
    order = rng.permutation(X.shape[0])
    parts = np.array_split(order, folds)
    best, best_cfg = -np.inf, None
    for k_x in grid_x:
        for k_y in grid_y:
            for ridge in grid_ridge:
                scores = []
                for i in range(folds):
                    va = parts[i]
                    tr = np.concatenate([parts[j] for j in range(folds) if j != i])
                    if tr.size <= max(k_x, k_y) + 2 or va.size < 3:
                        continue
                    fp = fit_cca(X[tr], Y[tr], k_x, k_y, ridge, n_components)
                    r = held_out_correlations(fp, X[va], Y[va])
                    scores.append(float(np.mean(np.abs(r[:n_components]))))
                if scores:
                    s = float(np.mean(scores))
                    if s > best:
                        best, best_cfg = s, (k_x, k_y, ridge)
    if best_cfg is None:  # pragma: no cover - degenerate input
        best_cfg = (grid_x[0], grid_y[0], grid_ridge[0])
    k_x, k_y, ridge = best_cfg
    fp = fit_cca(X, Y, k_x, k_y, ridge, n_components)
    return fp, {"k_x": k_x, "k_y": k_y, "ridge": ridge, "cv_score": best}


def retrieve_in_shared_space(
    fp: Fingerprint, X: np.ndarray, Y: np.ndarray, genes: np.ndarray,
    candidate_sets: list[list[str]], weight_by_correlation: bool = True,
) -> list[tuple[int, int]]:
    """Rank candidates by distance between fingerprints in the shared space.

    Components are weighted by their training canonical correlation, so a
    direction the fit believes in counts for more than one it does not.
    """
    A, B = fp.embed_description(X), fp.embed_image(Y)
    # Standardise each shared dimension so one does not dominate by scale.
    for M in (A, B):
        sd = M.std(axis=0)
        sd[sd < 1e-12] = 1.0
        M /= sd
    w = fp.correlations.copy() if weight_by_correlation else np.ones(fp.n_components)
    w = w / max(w.sum(), 1e-12)
    index = {str(g): i for i, g in enumerate(genes)}
    from vcell.retrieval import rank_of_truth

    out = []
    for cands in candidate_sets:
        present = [c for c in cands if c in index]
        if len(present) < 2:
            continue
        for truth in present:
            scores = {
                c: -float(np.sum(w * (A[index[c]] - B[index[truth]]) ** 2))
                for c in present
            }
            out.append(rank_of_truth(scores, truth))
    return out
