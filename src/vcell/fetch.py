"""Download Allen per-cell crops, map them into the canonical frame, discard the raw.

Each `crop_raw` file is ~28 MB of 16-bit voxels and each canonical frame is
~0.2 MB, so the raw image is deleted as soon as the frame is built. That is what
makes the study runnable on a laptop-sized disk: 580 cells is 16 GB of download
but only ~120 MB of retained data, and none of the discarded bytes are needed
again -- the frame is the registered representation.
"""

from __future__ import annotations

import os
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

import numpy as np
import requests
import tifffile

from vcell.frame import CANONICAL_GRID, build_frame
from vcell.manifest import CellRef

RETRY_WAITS = (2, 4, 8, 16)


def _download(url: str, dest: Path, timeout: int = 300) -> None:
    """Fetch one file, retrying network failures with exponential backoff."""
    last: Exception | None = None
    for attempt, wait in enumerate((0, *RETRY_WAITS)):
        if wait:
            time.sleep(wait)
        try:
            with requests.get(url, stream=True, timeout=timeout) as response:
                response.raise_for_status()
                with open(dest, "wb") as fh:
                    for chunk in response.iter_content(chunk_size=1 << 20):
                        fh.write(chunk)
            return
        except Exception as exc:  # noqa: BLE001 - retry anything transport-shaped
            last = exc
            if attempt == len(RETRY_WAITS):
                break
    raise RuntimeError(f"failed to download {url}: {last}")


def _one_cell(args: tuple[dict, tuple[int, int, int]]) -> dict | None:
    """Download, frame, delete. Returns the frame as plain arrays, or None."""
    row, grid = args
    cell = CellRef(**row)
    with tempfile.TemporaryDirectory() as tmp:
        raw_path = Path(tmp) / "raw.tif"
        seg_path = Path(tmp) / "seg.tif"
        try:
            _download(cell.raw_url, raw_path)
            _download(cell.seg_url, seg_path)
            frame = build_frame(
                tifffile.imread(raw_path),
                tifffile.imread(seg_path),
                scale_micron=cell.scale_micron,
                grid=grid,
                cell_id=cell.cell_id,
                fov_id=cell.fov_id,
                gene=cell.gene,
                cell_stage=cell.cell_stage,
            )
        except Exception as exc:  # noqa: BLE001
            # A cell that cannot be framed is dropped, loudly, and the count of
            # dropped cells is reported -- silent attrition would bias the sample.
            print(f"  drop {cell.gene}/{cell.cell_id}: {type(exc).__name__}: {exc}", flush=True)
            return None
    return {
        "reference": frame.reference.astype(np.float16),
        "target": frame.target.astype(np.float16),
        "struct_mask": frame.struct_mask,
        "nuc_mask": frame.nuc_mask,
        "cell_mask": frame.cell_mask,
        "voxel_micron": frame.voxel_micron,
        "cell_id": frame.cell_id,
        "fov_id": frame.fov_id,
        "gene": frame.gene,
        "cell_stage": frame.cell_stage,
    }


def fetch_frames(
    cells: list[CellRef],
    out_path: Path,
    grid: tuple[int, int, int] = CANONICAL_GRID,
    workers: int | None = None,
) -> dict[str, int]:
    """Fetch every cell in `cells` and write one compressed npz of frames."""
    workers = workers or max(1, min(4, (os.cpu_count() or 2)))
    payload = [(asdict(c), grid) for c in cells]
    frames: list[dict] = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one_cell, item) for item in payload]
        for done, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            if result is not None:
                frames.append(result)
            if done % 25 == 0 or done == len(futures):
                rate = done / max(time.time() - t0, 1e-9)
                print(
                    f"  {done}/{len(futures)} cells, {len(frames)} kept, "
                    f"{rate*60:.0f}/min",
                    flush=True,
                )
    if not frames:
        raise RuntimeError("no cells survived framing")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_path,
        reference=np.stack([f["reference"] for f in frames]),
        target=np.stack([f["target"] for f in frames]),
        struct_mask=np.stack([f["struct_mask"] for f in frames]),
        nuc_mask=np.stack([f["nuc_mask"] for f in frames]),
        cell_mask=np.stack([f["cell_mask"] for f in frames]),
        voxel_micron=np.stack([f["voxel_micron"] for f in frames]),
        cell_id=np.array([f["cell_id"] for f in frames]),
        fov_id=np.array([f["fov_id"] for f in frames]),
        gene=np.array([f["gene"] for f in frames]),
        cell_stage=np.array([f["cell_stage"] for f in frames]),
    )
    counts: dict[str, int] = {}
    for f in frames:
        counts[f["gene"]] = counts.get(f["gene"], 0) + 1
    return counts
