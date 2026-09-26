"""Blue Brain synapse physiology, reduced to what one network variant uses.

Source: the Neocortical Microcircuit portal pathway factsheets (see ``data/bluebrain/SOURCE.md``). Each pre:post
pathway has a synapse type (excitatory or inhibitory; depressing, facilitating or pseudo-linear) and
Tsodyks-Markram parameters U (utilisation), D (recovery from depression, ms), F (recovery from facilitation, ms)
and a release-failure rate.

The network uses them as follows (all fixed before training):

* each excitatory relation edge draws (U, D, F, failure rate) from one excitatory pathway, and each inhibitory
  relation edge (contradicts, supersedes) from one inhibitory pathway, chosen by a hash of the edge id, so the
  draw is stable and the empirical mixture of classes is preserved;
* one message-passing step is taken as one inter-spike interval of ``DT_MS`` = 50 ms (20 Hz); this mapping is an
  assumption, not a measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

BASE = "https://openbluebrain.s3.amazonaws.com/Portals/nmc-portal/assets/documents/static/Download/"
FILES = {"pathways_physiology_factsheets_simplified.json": "0bf03121af020913fde54e48b6393e08984a7f3b74ecb2cfaccbc9ee211cf728",
         "pathways_anatomy_factsheets_simplified.json": "c75a5fc4ce7cd4def82454352967ecf2f7789b9fd0912ac13aea2dbaae9b3bc6"}
DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "bluebrain"
DT_MS = 50.0


@dataclass(frozen=True)
class Synapse:
    pathway: str
    kind: str  # e.g. "Excitatory, depressing"
    U: float
    D: float  # ms
    F: float  # ms
    failure: float  # probability of release failure, 0..1

    @property
    def inhibitory(self) -> bool:
        return self.kind.lower().startswith("inhibitory")


def fetch(dest: Path = DATA_DIR) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name, sha in FILES.items():
        path = dest / name
        if not path.exists():
            urllib.request.urlretrieve(BASE + name, path)  # noqa: S310 - fixed https source
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != sha:
            raise RuntimeError(f"{name}: sha256 {got} does not match the recorded {sha}")


@lru_cache(maxsize=1)
def synapses(data_dir: str | None = None) -> tuple[list[Synapse], list[Synapse]]:
    """(excitatory, inhibitory) pathways with complete Tsodyks-Markram parameters."""
    path = Path(data_dir or DATA_DIR) / "pathways_physiology_factsheets_simplified.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run: python -m cie.remnet.bluebrain --fetch")
    raw = json.loads(path.read_text())
    exc, inh = [], []
    for name, v in sorted(raw.items()):
        try:
            s = Synapse(name, str(v["synapse_type"]), float(v["u_mean"]), float(v["d_mean"]), float(v["f_mean"]),
                        min(0.95, max(0.0, float(v.get("failures_mean") or 0.0) / 100.0)))
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 < s.U <= 1 and s.D > 0 and s.F > 0):
            continue
        (inh if s.inhibitory else exc).append(s)
    return exc, inh


def pick(edge_key: str, inhibitory: bool) -> Synapse:
    exc, inh = synapses()
    pool = inh if inhibitory else exc
    return pool[int(hashlib.sha1(edge_key.encode()).hexdigest(), 16) % len(pool)]


def efficacy(U: float, D: float, F: float, steps: int, dt: float = DT_MS) -> list[float]:
    """Tsodyks-Markram release efficacy u_n * R_n for a spike train at interval ``dt``, normalised so the first
    release is 1. u_1 = U, R_1 = 1; u_{n+1} = u_n e^{-dt/F} + U (1 - u_n e^{-dt/F});
    R_{n+1} = R_n (1 - u_n) e^{-dt/D} + 1 - e^{-dt/D}."""
    u, r, out = U, 1.0, []
    ef, ed = math.exp(-dt / F), math.exp(-dt / D)
    for _ in range(steps):
        out.append(u * r / U)
        u, r = u * ef + U * (1 - u * ef), r * (1 - u) * ed + 1 - ed
    return out


def summary() -> dict:
    import statistics

    exc, inh = synapses()
    out = {}
    for label, pool in (("excitatory", exc), ("inhibitory", inh)):
        kinds = {}
        for s in pool:
            kinds.setdefault(s.kind, []).append(s)
        out[label] = {k: {"pathways": len(v), "U": round(statistics.median(x.U for x in v), 3), "D_ms": statistics.median(x.D for x in v),
                          "F_ms": statistics.median(x.F for x in v), "failure": round(statistics.median(x.failure for x in v), 3),
                          "efficacy_4_steps": [round(e, 3) for e in efficacy(statistics.median(x.U for x in v), statistics.median(x.D for x in v),
                                                                                statistics.median(x.F for x in v), 4)]}
                      for k, v in sorted(kinds.items())}
    return out


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fetch", action="store_true")
    args = ap.parse_args(argv)
    if args.fetch:
        fetch()
    print(json.dumps(summary(), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
