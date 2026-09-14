"""A virtual-cell proof of concept: predict a protein's 3D density field from
the two reference channels every Allen WTC-11 cell shares, plus public
annotation about the protein -- including for proteins the model never saw.

The experiment is registered in `docs/PREREG_VIRTUAL_CELL.md` and the outcome
is in `docs/RESULT_VIRTUAL_CELL.md`.
"""

__all__ = ["knowledge", "frame", "manifest", "fetch", "dataset", "model", "metrics",
           "baselines", "train", "synthetic", "demo"]
