"""Direction from two measured densities: the continuity equation, solved.

Allen and OpenCell are both fixed-cell collections, so nothing here observes
motion. What it does observe is the same protein's density in cells caught at
different points of mitosis, and between two such densities there is a
well-defined question with a unique answer: **what transport would carry the
first into the second, at least cost?**

Continuity says only that

    drho/dt + div J = 0,

which for a given density change has infinitely many solutions for J -- any
divergence-free field can be added. The minimum-dissipation solution is the
curl-free one, J = -rho grad(phi), which turns the problem into a single
variable-coefficient Poisson equation

    div (rho grad phi) = -drho/dt,

with no flux through the cell boundary. That is the standard Helmholtz/Darcy
projection and it is the field this module returns. It is the least-committed
reading of the data: any other flux consistent with the same two densities
needs strictly more kinetic energy.

The physics then enters twice more. Diffusion alone would give
J_diff = -D grad(rho), so the **angle** between the reconstructed flux and the
down-gradient direction says whether the protein went where diffusion would have
taken it, and the **diffusive timescale** says whether diffusion is fast enough
to have done it at all. Both are computed here; the diffusion coefficient comes
from the protein's own AlphaFold structure.

What this cannot do is turn a population average into a trajectory. Each stage
is a different set of cells, so the flux is the transport that carries the
*population mean* forward, not the path any molecule took.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage, sparse
from scipy.sparse.linalg import cg


def gradient(field: np.ndarray, spacing) -> list[np.ndarray]:
    """Central-difference gradient with per-axis spacing, edge-safe."""
    return list(np.gradient(field, *spacing, edge_order=1))


@dataclass
class Flux:
    """The reconstructed transport between two densities."""

    potential: np.ndarray          # phi, zero-mean within each component
    velocity: tuple[np.ndarray, ...]   # v = -grad(phi), microns per interval
    speed: np.ndarray              # |v|
    mass_weighted_speed: float     # sum(rho_bar * |v|), microns per interval
    residual: float                # worst relative residual over components
    converged: bool
    n_components: int = 1          # connected pieces of the mask
    unmoveable_mass_fraction: float = 0.0   # mass flux cannot account for


def _solve_component(rho0, rho1, comp, spacing, tol, maxiter):
    """The Poisson solve on one connected piece of the domain.

    Returns (phi over the whole grid, relative residual, mass the solve could
    not account for). Kept separate because a Neumann problem is singular once
    per connected component, and a mitotic cell's mask really does come apart.
    """
    idx = np.flatnonzero(comp.ravel())
    n = idx.size
    order = -np.ones(comp.size, dtype=np.int64)
    order[idx] = np.arange(n)

    # Face conductance follows the mean density, so the solve stays where the
    # protein is. It needs a floor: with exactly zero conductance over a large
    # region the system is singular, and with a floor many orders below the
    # peak it is merely ill-conditioned, which is worse -- the solver returns
    # large numbers instead of failing. The floor here is a thousandth of the
    # density a perfectly uniform protein would have, which bounds the
    # conductance ratio at about 1e3 x the real density contrast and is also a
    # fair physical statement: there is always a little of the protein
    # everywhere.
    rho_bar = 0.5 * (rho0 + rho1)
    uniform = float(rho_bar[comp].sum()) / max(n, 1)
    floor = 1e-3 * max(uniform, 1e-30)
    cond = np.where(comp, np.maximum(rho_bar, floor), 0.0)

    shape = comp.shape
    lin = np.arange(comp.size).reshape(shape)
    rows, cols, vals = [], [], []
    diag = np.zeros(n)
    for axis, h in enumerate(spacing):
        sl_a = [slice(None)] * 3
        sl_b = [slice(None)] * 3
        sl_a[axis] = slice(0, shape[axis] - 1)
        sl_b[axis] = slice(1, shape[axis])
        a_lin = lin[tuple(sl_a)].ravel()
        b_lin = lin[tuple(sl_b)].ravel()
        both = comp.ravel()[a_lin] & comp.ravel()[b_lin]
        a_lin, b_lin = a_lin[both], b_lin[both]
        if a_lin.size == 0:
            continue
        # Harmonic face conductance, the correct averaging for a flux that must
        # be continuous across the face.
        ca, cb = cond.ravel()[a_lin], cond.ravel()[b_lin]
        face = 2.0 * ca * cb / np.maximum(ca + cb, 1e-300) / (h * h)
        ia, ib = order[a_lin], order[b_lin]
        rows.extend([ia, ib])
        cols.extend([ib, ia])
        vals.extend([face, face])
        np.add.at(diag, ia, -face)
        np.add.at(diag, ib, -face)
    rows.append(np.arange(n))
    cols.append(np.arange(n))
    vals.append(diag)
    A = sparse.coo_matrix(
        (np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
        shape=(n, n)).tocsr()

    # Continuity over a unit interval gives rho1 - rho0 = -div J, and the
    # minimum-dissipation flux is J = -rho grad(phi), so the equation to solve
    # is div(rho grad phi) = rho1 - rho0, which is what `A` implements.
    b = (rho1 - rho0).ravel()[idx]
    # A Neumann problem is solvable only for a source that integrates to zero
    # over the component. Whatever has to be subtracted here is mass that
    # entered or left this piece of the cell without crossing its boundary --
    # transport cannot do that, so it is reported rather than hidden.
    imbalance = float(b.sum())
    b = b - b.mean()

    # A is a variable-coefficient Laplacian: symmetric with a negative
    # diagonal, so it is negative semidefinite and CG does not apply to it.
    # -A is positive semidefinite with the constants as its null space, and
    # pinning one unknown removes exactly that -- the reduced system is
    # positive definite, and its solution satisfies every dropped equation too
    # because the right-hand side now sums to zero. That is exact, unlike
    # over-writing a row, and unlike projecting the constant out inside the
    # iteration, which makes the Jacobi preconditioner non-symmetric and
    # breaks CG down silently into values orders of magnitude too large.
    if n < 2:
        return np.zeros(comp.shape), 0.0, abs(imbalance)
    K = (-A)[1:, 1:].tocsr()
    rhs = -b[1:]
    d = np.abs(np.asarray(K.diagonal()))
    inv = np.ones_like(d)
    np.divide(1.0, d, out=inv, where=d > 0)
    P = sparse.linalg.LinearOperator(K.shape, matvec=lambda v: inv * v)
    sol, info = cg(K, rhs, rtol=tol, maxiter=maxiter, M=P)
    sol = np.nan_to_num(sol)
    resid = float(np.linalg.norm(K @ sol - rhs) / max(np.linalg.norm(rhs), 1e-300))

    phi_flat = np.concatenate([[0.0], sol])
    phi_flat -= phi_flat.mean()
    phi = np.zeros(comp.size)
    phi[idx] = phi_flat
    return phi.reshape(shape), resid, abs(imbalance)


def solve_flux(rho0: np.ndarray, rho1: np.ndarray, mask: np.ndarray,
               spacing, tol: float = 1e-10, maxiter: int = 20000,
               min_component: int = 32) -> Flux:
    """Minimum-dissipation flux carrying `rho0` into `rho1` inside `mask`.

    Both densities must be non-negative and carry the same total mass inside
    the mask -- transport cannot create or destroy any. The interval is taken as
    1, so velocities are microns per interval and scale linearly with whatever
    real duration the interval turns out to have.

    The mask is solved one connected component at a time. A mitotic cell mask
    genuinely comes apart, and segmentation leaves single-voxel specks besides;
    each piece adds a null direction to the Neumann problem, and solving the
    whole thing at once diverges. Components below `min_component` voxels are
    dropped and the mass they hold is reported.
    """
    if rho0.shape != rho1.shape or rho0.shape != mask.shape:
        raise ValueError("densities and mask must have the same shape")
    if mask.sum() < 8:
        raise ValueError("mask is too small to solve on")

    labels, k = ndimage.label(mask)
    rho_bar = 0.5 * (rho0 + rho1)
    total = float(rho_bar[mask].sum())
    phi = np.zeros(mask.shape)
    worst, unmoveable, solved = 0.0, 0.0, 0
    for i in range(1, k + 1):
        comp = labels == i
        if comp.sum() < min_component:
            unmoveable += float(rho_bar[comp].sum())
            continue
        p, resid, imbalance = _solve_component(rho0, rho1, comp, spacing,
                                               tol, maxiter)
        phi += p
        worst = max(worst, resid)
        unmoveable += imbalance
        solved += 1

    g = gradient(phi, spacing)
    keep = mask & (labels > 0)
    big = np.zeros_like(mask)
    for i in range(1, k + 1):
        if (labels == i).sum() >= min_component:
            big |= labels == i
    keep &= big
    v = tuple(np.where(keep, -gi, 0.0) for gi in g)
    speed = np.sqrt(sum(vi**2 for vi in v))
    w = rho_bar * keep
    wsum = float(w.sum())
    mws = float((w * speed).sum() / wsum) if wsum > 0 else float("nan")
    return Flux(phi, v, speed, mws, worst,
                bool(solved > 0 and worst < 1e-4), int(k),
                float(unmoveable / total) if total > 0 else 0.0)


def diffusive_alignment(flux: Flux, rho0: np.ndarray, rho1: np.ndarray,
                        mask: np.ndarray, spacing) -> dict:
    """How much of the reconstructed transport is diffusion going downhill?

    Diffusion moves mass down the concentration gradient, so the mass-weighted
    cosine between the reconstructed velocity and `-grad(rho)` answers the
    question without needing to know the diffusion coefficient or the duration
    of the interval. Near +1 means the protein went where diffusion would have
    taken it; near 0 means sideways to the gradient; negative means *up* the
    gradient, which diffusion cannot do and something has to be paying for.
    """
    rho_bar = 0.5 * (rho0 + rho1)
    g = gradient(rho_bar, spacing)
    down = tuple(-gi for gi in g)
    gnorm = np.sqrt(sum(gi**2 for gi in down))
    vnorm = flux.speed
    dot = sum(vi * di for vi, di in zip(flux.velocity, down, strict=True))
    good = mask & (gnorm > 1e-12) & (vnorm > 1e-12)
    if not good.any():
        return {"cosine": float("nan"), "n_voxels": 0,
                "uphill_mass_fraction": float("nan")}
    cos = np.zeros_like(dot)
    cos[good] = dot[good] / (gnorm[good] * vnorm[good])
    w = (rho_bar * good).astype(np.float64)
    total = float(w.sum())
    return {
        "cosine": float((w * cos).sum() / total) if total > 0 else float("nan"),
        "uphill_mass_fraction": float(w[cos < 0].sum() / total) if total > 0
        else float("nan"),
        "n_voxels": int(good.sum()),
    }


def diffusive_timescale(rho0: np.ndarray, rho1: np.ndarray, mask: np.ndarray,
                        spacing, d_micron2_per_s: float) -> dict:
    """How long free diffusion would need to produce the observed change.

    Linearise the diffusion equation over the interval: drho ~ D tau lap(rho).
    Taking the mass-weighted magnitude of each side gives one number,

        tau = <|rho1 - rho0|> / (D <|lap(rho_bar)|>),

    which is the time diffusion at that coefficient would take to move as much
    density as was actually moved. Compared against how long the interval really
    lasts, tau > interval means diffusion is too slow to explain the change and
    directed transport is required; tau << interval means diffusion is fast
    enough to have erased the pattern, so holding it takes work too.
    """
    rho_bar = 0.5 * (rho0 + rho1)
    lap = np.zeros_like(rho_bar)
    for axis, h in enumerate(spacing):
        lap += (np.roll(rho_bar, 1, axis) + np.roll(rho_bar, -1, axis)
                - 2.0 * rho_bar) / (h * h)
    w = (rho_bar * mask).astype(np.float64)
    total = float(w.sum())
    if total <= 0 or d_micron2_per_s <= 0:
        return {"tau_seconds": float("nan")}
    change = float((w * np.abs(rho1 - rho0)).sum() / total)
    curve = float((w * np.abs(lap)).sum() / total)
    tau = change / (d_micron2_per_s * curve) if curve > 0 else float("inf")
    return {"tau_seconds": tau, "mean_abs_change": change,
            "mean_abs_laplacian": curve}
