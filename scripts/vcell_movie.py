#!/usr/bin/env python3
"""A movie of a protein through mitosis, and the direction it had to travel.

Neither Allen nor OpenCell has a time axis, so this is not a recording of one
cell. What the Allen collection does have is `cell_stage`, a four-value ordered
axis -- interphase, prophase/prometaphase, metaphase, anaphase/telophase -- and
different cells caught at each point. Averaging within a stage and stepping
through the four gives a population trajectory: real measurements, in a real
order, of different cells.

Between consecutive stages `vcell.flux` solves the continuity equation for the
least-cost transport that carries one density into the next, which is the
closest thing to a direction the data can support. The protein's own AlphaFold
structure then says whether free diffusion could have done it.

Outputs per gene: an animated GIF, and the numbers behind it.

    python scripts/vcell_movie.py --data-dir .vcell/vcell_data --out docs/img/movies
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import csv  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from PIL import Image  # noqa: E402
from scipy import ndimage  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vcell.biophysics import (  # noqa: E402
    CYTOPLASM_VISCOSITY_PA_S,
    stokes_einstein,
)
from vcell.flux import diffusive_alignment, diffusive_timescale, solve_flux  # noqa: E402

# The order is the biology, not an alphabetisation: G2 into prophase, then
# metaphase, then anaphase and telophase.
STAGES = ["M0", "M1M2", "M3", "M4M5"]
STAGE_LABEL = {
    "M0": "interphase",
    "M1M2": "prophase / prometaphase",
    "M3": "metaphase",
    "M4M5": "anaphase / telophase",
}
# Nominal durations in hiPSC, used only to turn the diffusive timescale into a
# ratio. Every quantity that depends on them is labelled.
STAGE_SECONDS = {("M0", "M1M2"): 20 * 60, ("M1M2", "M3"): 18 * 60,
                 ("M3", "M4M5"): 12 * 60}


def load_all(data_dir: Path) -> dict:
    """Every framed cell in the directory, interphase and mitotic together."""
    keep = ("target", "reference", "cell_mask", "nuc_mask", "struct_mask",
            "voxel_micron", "gene", "cell_stage", "cell_id")
    parts: dict[str, list] = {k: [] for k in keep}
    for f in sorted(data_dir.glob("frames_*.npz")):
        with np.load(f, allow_pickle=False) as z:
            if "cell_stage" not in z.files:
                continue
            for k in keep:
                parts[k].append(z[k])
    if not parts["target"]:
        raise SystemExit(f"no framed data with stage labels in {data_dir}")
    out = {k: np.concatenate(v, axis=0) for k, v in parts.items()}
    # Separate fetches can land on the same cell, and a duplicate would be
    # counted twice in a stage mean and would make the split-half control look
    # better than it is.
    _, keep = np.unique(out["cell_id"], return_index=True)
    keep.sort()
    if keep.size != out["cell_id"].size:
        print(f"  dropped {out['cell_id'].size - keep.size} duplicate cells")
        out = {k: v[keep] for k, v in out.items()}
    return out


def stage_mean(frames: dict, rows: np.ndarray) -> dict:
    """Mean protein density, reference channels and mask over a set of cells.

    Each cell's protein channel is renormalised to unit mass inside its own
    cell mask before averaging, so a bright cell does not dominate the mean and
    the result is a density rather than an intensity.
    """
    dens = np.zeros(frames["target"].shape[1:], dtype=np.float64)
    for i in rows:
        t = frames["target"][i].astype(np.float64)
        m = frames["cell_mask"][i]
        t = np.where(m, t, 0.0)
        s = t.sum()
        if s > 0:
            dens += t / s
    dens /= max(len(rows), 1)
    ref = frames["reference"][rows].astype(np.float64).mean(axis=0)
    occupancy = frames["cell_mask"][rows].astype(np.float64).mean(axis=0)
    nuc = frames["nuc_mask"][rows].astype(np.float64).mean(axis=0)
    # The single real cell closest to this mean, kept so the movie can show an
    # actual cell beside the average. An average over dozens of differently
    # shaped cells is the right input for the physics and the wrong thing to
    # look at: everything sharp in it has been blurred away.
    best, best_r = int(rows[0]), -2.0
    flat = dens.ravel()
    for i in rows:
        c = np.where(frames["cell_mask"][i],
                     frames["target"][i].astype(np.float64), 0.0)
        s = c.sum()
        if s <= 0:
            continue
        r = float(np.corrcoef(flat, (c / s).ravel())[0, 1])
        if np.isfinite(r) and r > best_r:
            best, best_r = int(i), r
    rep = np.where(frames["cell_mask"][best],
                   frames["target"][best].astype(np.float64), 0.0)
    rs = rep.sum()
    return {"density": dens, "dna": ref[0], "membrane": ref[1],
            "occupancy": occupancy, "nucleus": nuc, "n": int(len(rows)),
            "representative": rep / rs if rs > 0 else rep,
            "representative_dna": frames["reference"][best][0].astype(np.float64),
            "representative_cell_id": str(frames["cell_id"][best]),
            "representative_r": best_r}


def renormalise(dens: np.ndarray, mask: np.ndarray) -> np.ndarray:
    d = np.where(mask, dens, 0.0)
    s = d.sum()
    return d / s if s > 0 else d


def transition(a: dict, b: dict, spacing, d_micron2_per_s: float,
               seconds: float | None) -> dict:
    """Solve for the transport between two stage means, and read the physics."""
    mask = (a["occupancy"] > 0.5) | (b["occupancy"] > 0.5)
    if mask.sum() < 64:
        return {"error": "mask too small"}
    r0, r1 = renormalise(a["density"], mask), renormalise(b["density"], mask)
    if r0.sum() <= 0 or r1.sum() <= 0:
        return {"error": "a stage has no density"}
    f = solve_flux(r0, r1, mask, spacing)
    if not f.converged:
        # A diverged solve returns huge numbers rather than nothing, so it has
        # to be refused here or it lands in the results table looking like a
        # measurement.
        return {"error": f"solver did not converge (residual {f.residual:.2e})"}
    align = diffusive_alignment(f, r0, r1, mask, spacing)
    tau = diffusive_timescale(r0, r1, mask, spacing, d_micron2_per_s)
    out = {
        "displacement_micron": f.mass_weighted_speed,
        "solver_residual": f.residual,
        "solver_converged": bool(f.converged),
        "diffusive_cosine": align["cosine"],
        "uphill_mass_fraction": align["uphill_mass_fraction"],
        "diffusive_tau_seconds": tau["tau_seconds"],
        "n_voxels": int(mask.sum()),
    }
    if seconds:
        out["stage_seconds_assumed"] = seconds
        out["tau_over_stage"] = tau["tau_seconds"] / seconds
        # The reciprocal is the readable one: how many times slower the
        # structure actually redistributes than free diffusion of its own
        # monomer would. Large means the protein is held in an assembly.
        out["slower_than_free_diffusion"] = (
            seconds / tau["tau_seconds"] if tau["tau_seconds"] > 0
            else float("inf"))
        # Distance free diffusion would cover in the same interval, against the
        # distance the density actually had to move.
        out["diffusion_length_micron"] = float(
            np.sqrt(max(2.0 * d_micron2_per_s * seconds, 0.0)))
        out["peclet"] = (f.mass_weighted_speed
                         / max(out["diffusion_length_micron"], 1e-12))
    return out, f, r0, r1, mask


def split_half(frames: dict, rows_a, rows_b, spacing, seed=20260916):
    """Does anything here replicate? Two disjoint halves of the same cells.

    Splits each stage's cells in two, rebuilds both stage means and both flux
    fields from disjoint halves, and reports two agreements:

    * `density` -- Pearson r between the two halves' stage-mean densities. This
      says whether the *pictures* in the movie are reliable.
    * `direction` -- mass-weighted cosine between the two halves' velocity
      fields. This says whether the *arrows* are.

    They can come apart, and which one fails matters: a high density r with a
    near-zero direction cosine means the stage means are solid and the transport
    reconstruction is amplifying noise, not that the movie is wrong.
    """
    rng = np.random.default_rng(seed)
    if len(rows_a) < 4 or len(rows_b) < 4:
        return None
    pa, pb = rng.permutation(rows_a), rng.permutation(rows_b)
    halves = []
    for ha, hb in ((pa[: len(pa) // 2], pb[: len(pb) // 2]),
                   (pa[len(pa) // 2:], pb[len(pb) // 2:])):
        A, B = stage_mean(frames, ha), stage_mean(frames, hb)
        mask = (A["occupancy"] > 0.5) | (B["occupancy"] > 0.5)
        if mask.sum() < 64:
            return None
        r0, r1 = renormalise(A["density"], mask), renormalise(B["density"], mask)
        if r0.sum() <= 0 or r1.sum() <= 0:
            return None
        halves.append((solve_flux(r0, r1, mask, spacing), r0, r1, mask))
    (f1, a1, b1, m1), (f2, a2, b2, m2) = halves
    m = m1 & m2
    dens_r = float(np.corrcoef(
        np.concatenate([a1[m], b1[m]]), np.concatenate([a2[m], b2[m]]))[0, 1])
    w = 0.25 * (a1 + b1 + a2 + b2) * m
    dot = sum(x * y for x, y in zip(f1.velocity, f2.velocity, strict=True))
    n1, n2 = f1.speed, f2.speed
    good = m & (n1 > 1e-12) & (n2 > 1e-12)
    if not good.any() or w[good].sum() <= 0:
        return {"density_r": dens_r, "direction_cosine": None}
    cos = dot[good] / (n1[good] * n2[good])
    return {"density_r": dens_r,
            "direction_cosine": float((w[good] * cos).sum() / w[good].sum()),
            "n_cells_per_half": [len(pa) // 2, len(pb) // 2]}


def _rgb(dna, protein, gamma=0.85, protein_vmax=None, dna_vmax=None):
    """Cool-grey DNA with the protein in amber.

    Both channels are scaled against a value fixed for the whole movie, not
    per frame: rescaling each frame to its own maximum would hide exactly what
    the movie is for, which is the protein's density changing.
    """
    def norm(a, hi):
        hi = float(np.percentile(a, 99.5) if hi is None else hi)
        return np.clip(a / hi, 0, 1) ** gamma if hi > 0 else np.zeros_like(a)
    d, p = norm(dna, dna_vmax), norm(protein, protein_vmax)
    img = np.zeros((*d.shape, 3))
    # DNA as a cool grey-blue ground, the protein added in amber on top, so the
    # two read apart at a glance and neither hides the other.
    img[..., 0] = 0.42 * d
    img[..., 1] = 0.50 * d
    img[..., 2] = 0.66 * d
    img[..., 0] += 1.00 * p
    img[..., 1] += 0.68 * p
    img[..., 2] += 0.12 * p
    return np.clip(img, 0, 1)


def advect(density, velocity, spacing, t):
    """Semi-Lagrangian step: where each voxel's mass came from, t of the way.

    Used only to fill the frames between two measured stages. It is the flux
    reconstruction's own prediction of the in-between, not a measurement, and
    the frames are labelled as such.
    """
    grid = np.indices(density.shape).astype(np.float64)
    back = np.stack([grid[a] - t * velocity[a] / spacing[a]
                     for a in range(3)])
    out = ndimage.map_coordinates(density, back, order=1, mode="nearest")
    out = np.clip(out, 0.0, None)
    s = out.sum()
    return out * (density.sum() / s) if s > 0 else out


def render_frame(gene, stage, means, flux_for, spacing, sub, note,
                 override_density=None, subtitle=None, vmax=None):
    """One GIF frame: max projection, mid slice, and the outgoing direction."""
    m = means[stage]
    dens = m["density"] if override_density is None else override_density
    fig = plt.figure(figsize=(9.6, 3.7), dpi=110, facecolor="#0d1117")
    pv = (vmax or {}).get("rep_proj"), (vmax or {}).get("protein_slice")
    dv = (vmax or {}).get("rep_dna_proj"), (vmax or {}).get("dna_slice")
    zz = m["representative"].shape[0] // 2
    for k, (title, dna, prot) in enumerate((
        (f"one real cell  {m['representative_cell_id']}",
         m["representative_dna"][zz], m["representative"][zz]),
        (f"mean of {m['n']} cells, mid-Z", m["dna"][m["dna"].shape[0] // 2],
         dens[dens.shape[0] // 2]),
    )):
        ax = fig.add_subplot(1, 3, k + 1)
        ax.imshow(_rgb(dna, prot, protein_vmax=pv[k], dna_vmax=dv[k]),
                  interpolation="bilinear")
        ax.set_title(title, color="#c9d1d9", fontsize=8)
        ax.axis("off")
    ax = fig.add_subplot(1, 3, 3)
    if flux_for is None:
        ax.text(0.5, 0.5, "last stage\nno outgoing transport",
                ha="center", va="center", color="#8b949e", fontsize=9)
    else:
        f, r0, r1, mask = flux_for
        w = 0.5 * (r0 + r1)
        # Project the 3D field onto the imaging plane, weighted by density, so
        # the arrows show where the mass is going rather than where the grid is.
        wz = w.sum(0)
        vy = (f.velocity[1] * w).sum(0) / np.maximum(wz, 1e-30)
        vx = (f.velocity[2] * w).sum(0) / np.maximum(wz, 1e-30)
        ax.imshow(_rgb(m["dna"].max(0), w.max(0),
                       dna_vmax=(vmax or {}).get("dna_proj")),
                  interpolation="bilinear")
        yy, xx = np.mgrid[0:w.shape[1], 0:w.shape[2]]
        sel = (wz > np.percentile(wz[wz > 0], 75)) if (wz > 0).any() else wz > 1
        s = slice(None, None, sub)
        q = (sel[s, s], yy[s, s], xx[s, s], vx[s, s], vy[s, s])
        if q[0].any():
            # Scale so the longest arrow spans about `sub` voxels: a fixed
            # scale is meaningless across proteins whose speeds differ tenfold,
            # and an over-long arrow reads as a claim about distance.
            mag = float(np.hypot(q[3][q[0]], q[4][q[0]]).max())
            scale = max(mag, 1e-9) / (1.6 * sub)
            ax.quiver(q[2][q[0]], q[1][q[0]], q[3][q[0]], -q[4][q[0]],
                      color="#58a6ff", scale_units="xy", angles="xy",
                      scale=scale, width=0.005, headwidth=3.2,
                      headlength=4.0, alpha=0.9)
            ax.text(0.02, 0.03, f"peak {mag:.2f} um/stage", color="#58a6ff",
                    fontsize=7, transform=ax.transAxes)
        ax.set_title("transport to next stage", color="#c9d1d9", fontsize=8)
    ax.axis("off")
    head = subtitle or f"{STAGE_LABEL[stage]}   n = {m['n']} cells  (measured)"
    fig.suptitle(f"{gene}   {head}", color="#f0f6fc", fontsize=11, y=0.97)
    fig.text(0.5, 0.03, note, ha="center", color="#8b949e", fontsize=7.5)
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    buf = np.asarray(canvas.buffer_rgba())[..., :3].copy()
    plt.close(fig)
    return Image.fromarray(buf)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--biophysics", default="data/vcell/allen_biophysics.csv")
    ap.add_argument("--min-cells", type=int, default=2)
    ap.add_argument("--genes", default="")
    ap.add_argument("--quiver-stride", type=int, default=3)
    ap.add_argument("--hold-ms", type=int, default=1600)
    ap.add_argument("--tweens", type=int, default=5,
                    help="frames advected along the flux between two stages")
    args = ap.parse_args()

    O = Path(args.out)
    O.mkdir(parents=True, exist_ok=True)
    frames = load_all(Path(args.data_dir))
    spacing = tuple(float(x) for x in frames["voxel_micron"].mean(axis=0))
    print(f"{frames['target'].shape[0]} framed cells, voxel "
          f"{spacing[0]:.3f} x {spacing[1]:.3f} x {spacing[2]:.3f} um")

    bio = {}
    bp = Path(args.biophysics)
    if bp.exists():
        for r in csv.DictReader(open(bp)):
            bio[r["gene"]] = stokes_einstein(float(r["rg_angstrom"]),
                                             float(r["perrin_friction"]))
    print(f"diffusion coefficients for {len(bio)} genes "
          f"(eta = {CYTOPLASM_VISCOSITY_PA_S * 1e3:.1f} cP)")

    wanted = [g for g in args.genes.split(",") if g] or sorted(
        set(frames["gene"].tolist()))
    results = {}
    for gene in wanted:
        rows_by_stage = {}
        for st in STAGES:
            r = np.flatnonzero((frames["gene"] == gene)
                               & (frames["cell_stage"] == st))
            if r.size >= args.min_cells:
                rows_by_stage[st] = r
        present = [s for s in STAGES if s in rows_by_stage]
        if len(present) < 2:
            print(f"{gene}: only {len(present)} usable stage(s), skipped")
            continue
        means = {s: stage_mean(frames, rows_by_stage[s]) for s in present}
        d = bio.get(gene, float("nan"))

        per_transition, flux_for = {}, {}
        for s0, s1 in zip(present, present[1:], strict=False):
            secs = STAGE_SECONDS.get((s0, s1))
            res = transition(means[s0], means[s1], spacing, d, secs)
            if isinstance(res, dict):
                per_transition[f"{s0}->{s1}"] = res
                continue
            out, f, r0, r1, mask = res
            out["n_cells"] = [means[s0]["n"], means[s1]["n"]]
            out["split_half"] = split_half(
                frames, rows_by_stage[s0], rows_by_stage[s1], spacing)
            per_transition[f"{s0}->{s1}"] = out
            flux_for[s0] = (f, r0, r1, mask)

        note = (f"stage means over different cells, not one cell  |  "
                f"D = {d:.1f} um2/s from AlphaFold at eta = "
                f"{CYTOPLASM_VISCOSITY_PA_S * 1e3:.1f} cP  |  "
                f"arrows: least-cost transport between measured stages")
        # Build every frame's density first, then set one brightness scale
        # across all of them. Scaling per frame would hide exactly what the
        # movie is for, and an advected frame can concentrate mass above either
        # stage it sits between, so the tweens have to be in the pool too.
        plan = []
        for k, s in enumerate(present):
            plan.append({"stage": s, "density": means[s]["density"],
                         "flux": flux_for.get(s), "subtitle": None,
                         "hold": args.hold_ms})
            f_next = flux_for.get(s)
            if f_next is None or args.tweens <= 0:
                continue
            f, r0, _, _ = f_next
            for j in range(1, args.tweens + 1):
                frac = j / (args.tweens + 1)
                plan.append({
                    "stage": s,
                    "density": advect(r0, f.velocity, spacing, frac),
                    "flux": f_next,
                    "subtitle": f"{STAGE_LABEL[s]} -> "
                                f"{STAGE_LABEL[present[k + 1]]}"
                                f"   {int(frac * 100)}%  (advected, not measured)",
                    "hold": max(args.hold_ms // 6, 90)})

        def pct(a):
            return float(np.percentile(a, 99.5))

        zc = means[present[0]]["density"].shape[0] // 2
        vmax = {
            "protein_slice": max(
                pct(e["density"][e["density"].shape[0] // 2]) for e in plan),
            "dna_slice": max(
                pct(means[s]["dna"][means[s]["dna"].shape[0] // 2])
                for s in present),
            "rep_proj": max(pct(means[s]["representative"][zc])
                            for s in present),
            "rep_dna_proj": max(pct(means[s]["representative_dna"][zc])
                                for s in present),
            "mean_proj": max(pct(e["density"].max(0)) for e in plan),
        }
        imgs = [render_frame(gene, e["stage"], means, e["flux"], spacing,
                             args.quiver_stride, note,
                             override_density=e["density"],
                             subtitle=e["subtitle"], vmax=vmax) for e in plan]
        durations = [e["hold"] for e in plan]
        gif = O / f"{gene}_mitosis.gif"
        imgs[0].save(gif, save_all=True, append_images=imgs[1:],
                     duration=durations, loop=0, optimize=True)
        results[gene] = {
            "stages": {s: means[s]["n"] for s in present},
            "representative_cells": {s: means[s]["representative_cell_id"]
                                     for s in present},
            "representative_r": {s: means[s]["representative_r"]
                                 for s in present},
            "diffusion_micron2_per_s": d,
            "transitions": per_transition,
            "gif": str(gif),
        }
        print(f"{gene}: {len(present)} stages -> {gif.name}")

    def jsonable(o):
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, np.generic):
            return o.item()
        return float(o)

    (O / "movie_physics.json").write_text(json.dumps(
        {"voxel_micron": list(spacing),
         "viscosity_pa_s": CYTOPLASM_VISCOSITY_PA_S,
         "stage_seconds_assumed": {f"{a}->{b}": v
                                   for (a, b), v in STAGE_SECONDS.items()},
         "genes": results}, indent=1, default=jsonable))

    print(f"\n{'gene':12s} {'transition':12s} {'disp um':>8s} {'cos':>6s} "
          f"{'uphill':>7s} {'slower':>9s} {'dens r':>7s} {'dir cos':>8s}")
    for gene, r in sorted(results.items()):
        for name, t in r["transitions"].items():
            if "error" in t:
                print(f"{gene:12s} {name:12s} {t['error']}")
                continue
            sh = t.get("split_half") or {}
            dr = sh.get("density_r")
            dc = sh.get("direction_cosine")
            print(f"{gene:12s} {name:12s} {t['displacement_micron']:8.3f} "
                  f"{t['diffusive_cosine']:+6.2f} "
                  f"{t['uphill_mass_fraction']:7.2f} "
                  f"{t.get('slower_than_free_diffusion', float('nan')):9.0f} "
                  f"{('%+.3f' % dr) if dr is not None else '     --':>7s} "
                  f"{('%+.3f' % dc) if dc is not None else '      --':>8s}")
    print(f"\nwrote {O/'movie_physics.json'} and {len(results)} GIFs in {O}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
