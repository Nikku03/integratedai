#!/usr/bin/env python3
"""Run H4 -- the joint virtual cell -- from the saved `seen` checkpoint.

Separate from `vcell train` because the joint check was added to the protocol
after the run had already started, so the training process was executing the
earlier module and never produced `joint.json`. Nothing about the model
changes: this loads the same checkpoint the `seen` fold saved.

    python scripts/vcell_joint.py --data-dir .vcell
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vcell.dataset import load_frames, split_by_fov  # noqa: E402
from vcell.joint import joint_consistency  # noqa: E402
from vcell.knowledge import KNOWLEDGE_DIM, POC_STRUCTURES  # noqa: E402
from vcell.model import ConditionalUNet3D  # noqa: E402
from vcell.train import _predict  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=".vcell")
    parser.add_argument("--results", default=None)
    parser.add_argument("--seed", type=int, default=20260914)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()

    torch.set_num_threads(args.threads)
    data_dir = Path(args.data_dir)
    results = Path(args.results or (data_dir / "results"))
    frames = load_frames(data_dir / "frames_interphase.npz")
    train_idx, test_idx = split_by_fov(frames, test_fraction=0.2, seed=args.seed)

    model = ConditionalUNet3D(in_channels=2, cond_dim=KNOWLEDGE_DIM, base=12, depth=3)
    model.load_state_dict(torch.load(results / "model_seen.pt", map_location="cpu"))
    model.eval()

    joint = joint_consistency(
        lambda ref, know, mask: _predict(model, ref, know, mask),
        frames,
        train_idx,
        test_idx,
        list(POC_STRUCTURES),
    )
    (results / "joint.json").write_text(json.dumps(joint, indent=1))
    genes = joint["genes"]
    print(f"{joint['n_virtual_cells']} virtual cells, {len(genes)} structures each")
    print(f"pairwise arrangement correlation: {joint['pairwise_correlation']:.3f}")
    print(f"mean absolute error: {joint['pairwise_mean_abs_error_micron']:.3f} micron")
    print("\nper-structure radial profile W1 against the measured population profile:")
    for gene, value in sorted(joint["profile_w1_micron"].items(), key=lambda kv: kv[1]):
        print(f"  {gene:8s} {value:.3f} um")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
