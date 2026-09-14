"""Fetch OpenCell projections and cut them into tiles at native resolution.

The choice that matters here is *not resampling*. The previous study mapped each
cell into a shape-normalised frame, because the question was where an organelle
sits in a cell. This question is whether two proteins in the same compartment
look different, and the difference between them is texture -- tubular against
sheet-like ER, fine against coarse punctae. Resampling a 600x600 field down to a
fixed grid would blur exactly the signal under test, so instead each field is cut
into 192x192 tiles at the native 0.2 micron pixel, and the tile is the unit.

There is no membrane channel and no cell segmentation in OpenCell, so there is
no cell mask to normalise inside. A tile with no cells in it is therefore not
harmless -- it would be pure noise normalised to unit mass -- and is dropped by
a nucleus-occupancy check.
"""

from __future__ import annotations

import os
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import requests
import tifffile

from vcell.opencell import S3, Target

TILE = 192
TILES_PER_SIDE = 2
CENTRAL = TILE * TILES_PER_SIDE  # 384 of the 600 available pixels
NUCLEUS_CHANNEL = 0
TARGET_CHANNEL = 1
MIN_NUCLEUS_FRACTION = 0.03


def _download(url: str, dest: Path, timeout: int = 300) -> None:
    last: Exception | None = None
    for attempt, wait in enumerate((0, 2, 4, 8, 16)):
        if wait:
            time.sleep(wait)
        try:
            with requests.get(url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                with open(dest, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        fh.write(chunk)
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt == 4:
                break
    raise RuntimeError(f"failed to download {url}: {last}")


def _normalise(tile: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(tile, [1.0, 99.7])
    if hi <= lo:
        hi = lo + 1.0
    return np.clip((tile.astype(np.float32) - lo) / (hi - lo), 0.0, 1.0)


def tiles_from_projection(
    image: np.ndarray, tile: int = TILE, per_side: int = TILES_PER_SIDE
) -> list[dict]:
    """Cut the central region into per_side x per_side tiles, dropping empty ones."""
    if image.ndim != 3 or image.shape[0] < 2:
        raise ValueError(f"expected (C, Y, X) with C >= 2, got {image.shape}")
    nucleus_full = image[NUCLEUS_CHANNEL].astype(np.float32)
    # A field-level threshold, so the occupancy test does not adapt to each tile
    # and quietly keep a tile that is only noise.
    threshold = np.percentile(nucleus_full, 50) + 2.0 * (
        np.percentile(nucleus_full, 75) - np.percentile(nucleus_full, 25)
    )
    side = tile * per_side
    y0 = (image.shape[1] - side) // 2
    x0 = (image.shape[2] - side) // 2
    out = []
    for iy in range(per_side):
        for ix in range(per_side):
            sy = slice(y0 + iy * tile, y0 + (iy + 1) * tile)
            sx = slice(x0 + ix * tile, x0 + (ix + 1) * tile)
            nucleus = nucleus_full[sy, sx]
            if float((nucleus > threshold).mean()) < MIN_NUCLEUS_FRACTION:
                continue
            out.append({
                "reference": _normalise(nucleus)[None],
                "target": _normalise(image[TARGET_CHANNEL][sy, sx].astype(np.float32)),
                "tile_index": iy * per_side + ix,
            })
    return out


def _one_fov(args: tuple[str, str, str, str]) -> list[dict] | None:
    key, gene, ensg, compartment = args
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "proj.tif"
        try:
            _download(f"{S3}/{key}", path)
            image = tifffile.imread(path)
            tiles = tiles_from_projection(image)
        except Exception as exc:  # noqa: BLE001
            print(f"  drop {gene} {Path(key).name}: {type(exc).__name__}: {exc}", flush=True)
            return None
    fov_id = Path(key).name.split("_FID")[-1].split("_")[0]
    for t in tiles:
        t.update(gene=gene, ensg=ensg, compartment=compartment, fov_id=fov_id)
    return tiles


def fetch_tiles(
    jobs: list[tuple[str, Target]],
    out_path: Path,
    workers: int | None = None,
) -> dict[str, int]:
    """Download every (s3 key, target) job, tile it, and write one npz."""
    workers = workers or max(1, min(8, (os.cpu_count() or 2) * 2))
    payload = [(key, t.gene, t.ensg, t.compartment) for key, t in jobs]
    tiles: list[dict] = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one_fov, item) for item in payload]
        for done, fut in enumerate(as_completed(futures), start=1):
            got = fut.result()
            if got:
                tiles.extend(got)
            if done % 50 == 0 or done == len(futures):
                print(f"  {done}/{len(futures)} fields, {len(tiles)} tiles, "
                      f"{done/max(time.time()-t0,1e-9)*60:.0f} fields/min", flush=True)
    if not tiles:
        raise RuntimeError("no tiles survived")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_path,
        reference=np.stack([t["reference"] for t in tiles]).astype(np.float16),
        target=np.stack([t["target"] for t in tiles]).astype(np.float16),
        gene=np.array([t["gene"] for t in tiles]),
        ensg=np.array([t["ensg"] for t in tiles]),
        compartment=np.array([t["compartment"] for t in tiles]),
        fov_id=np.array([t["fov_id"] for t in tiles]),
        tile_index=np.array([t["tile_index"] for t in tiles]),
    )
    counts: dict[str, int] = {}
    for t in tiles:
        counts[t["gene"]] = counts.get(t["gene"], 0) + 1
    return counts


def load_tiles(path: Path) -> dict[str, np.ndarray]:
    keys = ("reference", "target", "gene", "ensg", "compartment", "fov_id", "tile_index")
    with np.load(path, allow_pickle=False) as d:
        out = {k: d[k] for k in keys}
    for k in ("gene", "ensg", "compartment", "fov_id"):
        out[k] = out[k].astype(str)
    return out
