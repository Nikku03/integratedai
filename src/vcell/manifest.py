"""Turn the Allen dataset manifest into the cell list this study will use.

`metadata.csv` in the hiPSC single-cell image dataset is 1.7 GB and 1,213
columns wide, almost all of them spherical-harmonic shape coefficients this
study does not use. This module streams it once, keeps eleven columns, applies
the registered QC filter, and samples cells **spread across as many distinct
fields of view as possible** -- because the train/test split is by FOV, and a
gene whose 80 cells came from 6 fields cannot be split without the test set
sharing illumination and colony context with training.
"""

from __future__ import annotations

import ast
import csv
import random
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

S3_ROOT = "https://allencell.s3.amazonaws.com/aics/hipsc_single_cell_image_dataset"
METADATA_URL = f"{S3_ROOT}/metadata.csv"

KEEP_COLUMNS = (
    "CellId",
    "FOVId",
    "structure_name",
    "cell_stage",
    "crop_raw",
    "crop_seg",
    "scale_micron",
    "outlier",
    "edge_flag",
    "PlateId",
    "WellId",
)

MITOTIC_STAGES = ("M1M2", "M3", "M4M5")


@dataclass
class CellRef:
    cell_id: str
    fov_id: str
    gene: str
    cell_stage: str
    crop_raw: str
    crop_seg: str
    scale_micron: float
    plate_id: str
    well_id: str

    @property
    def raw_url(self) -> str:
        return f"{S3_ROOT}/{self.crop_raw}"

    @property
    def seg_url(self) -> str:
        return f"{S3_ROOT}/{self.crop_seg}"


def _first_scale(raw: str) -> float:
    """`scale_micron` is stored as a list literal; voxels are isotropic."""
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return float("nan")
    return float(value[0]) if isinstance(value, (list, tuple)) else float(value)


def distil_metadata(metadata_csv: Path, out_csv: Path, genes: set[str] | None = None) -> int:
    """Stream the full manifest, write the eleven columns we use. Runs once."""
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    kept = 0
    with open(metadata_csv, newline="") as fh, open(out_csv, "w", newline="") as out:
        reader = csv.reader(fh)
        header = next(reader)
        index = {name: header.index(name) for name in KEEP_COLUMNS}
        writer = csv.writer(out)
        writer.writerow(KEEP_COLUMNS)
        for row in reader:
            if len(row) != len(header):
                continue
            if genes is not None and row[index["structure_name"]] not in genes:
                continue
            writer.writerow([row[index[name]] for name in KEEP_COLUMNS])
            kept += 1
    return kept


def _passes_qc(row: dict[str, str]) -> bool:
    return row["outlier"] == "No" and row["edge_flag"] in ("0", "False", "false")


def _spread_over_fovs(
    by_fov: dict[str, list[CellRef]], n_cells: int, rng: random.Random
) -> list[CellRef]:
    """Take cells round-robin across fields, so FOV count is maximised."""
    fovs = sorted(by_fov)
    rng.shuffle(fovs)
    for fov in fovs:
        rng.shuffle(by_fov[fov])
    chosen: list[CellRef] = []
    depth = 0
    while len(chosen) < n_cells:
        added = False
        for fov in fovs:
            if depth < len(by_fov[fov]):
                chosen.append(by_fov[fov][depth])
                added = True
                if len(chosen) == n_cells:
                    break
        if not added:
            break
        depth += 1
    return chosen


def sample_cells(
    distilled_csv: Path,
    genes: list[str],
    n_interphase: int,
    n_mitotic: int,
    seed: int,
) -> tuple[list[CellRef], list[CellRef]]:
    """The registered sample: interphase cells for the study, mitotic ones held out."""
    rng = random.Random(seed)
    inter: dict[str, dict[str, list[CellRef]]] = defaultdict(lambda: defaultdict(list))
    mito: dict[str, dict[str, list[CellRef]]] = defaultdict(lambda: defaultdict(list))
    wanted = set(genes)

    with open(distilled_csv, newline="") as fh:
        for row in csv.DictReader(fh):
            gene = row["structure_name"]
            if gene not in wanted or not _passes_qc(row):
                continue
            scale = _first_scale(row["scale_micron"])
            if not scale == scale:  # NaN
                continue
            ref = CellRef(
                cell_id=row["CellId"],
                fov_id=row["FOVId"],
                gene=gene,
                cell_stage=row["cell_stage"],
                crop_raw=row["crop_raw"],
                crop_seg=row["crop_seg"],
                scale_micron=scale,
                plate_id=row["PlateId"],
                well_id=row["WellId"],
            )
            if ref.cell_stage == "M0":
                inter[gene][ref.fov_id].append(ref)
            elif ref.cell_stage in MITOTIC_STAGES:
                mito[gene][ref.fov_id].append(ref)

    interphase: list[CellRef] = []
    mitotic: list[CellRef] = []
    for gene in genes:
        interphase += _spread_over_fovs(inter[gene], n_interphase, rng)
        mitotic += _spread_over_fovs(mito[gene], n_mitotic, rng)
    return interphase, mitotic


def write_manifest(cells: list[CellRef], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(cells[0])))
        writer.writeheader()
        for cell in cells:
            writer.writerow(asdict(cell))


def read_manifest(path: Path) -> list[CellRef]:
    with open(path, newline="") as fh:
        return [
            CellRef(**{**row, "scale_micron": float(row["scale_micron"])})
            for row in csv.DictReader(fh)
        ]
