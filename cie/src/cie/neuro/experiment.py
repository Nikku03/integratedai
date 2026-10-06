"""Does brain wiring help the reasoning neurons, and what does light reveal about them? The experiment fixed in
docs/BRAIN_WIRING_PREREGISTRATION.md.

Arms: the engine's spiking neurons wired as a cortex neighbourhood (``cortex``), the same connections placed at
random (``random``), or swapped keeping every neuron's degrees (``degree``); all-to-all as in the engine (``dense``);
and the engine's plain network (``mlp``).

Tasks:
* **primitives**: the 45 patterns of the five three-valued operations, as the engine trains them (a fit check);
* **compositions**: ``(a op1 b) op2 c`` in one pass, trained on 18 of the 25 operation pairs and tested on the other
  7 (every value combination), so the network must combine operations it never saw combined.

Light (on the primitive networks): NpHR silencing or ChR2 activation of a random quarter of the neurons (20 draws),
and silencing of each cortical layer's neurons and of the inhibitory neurons.

    python -m cie.neuro.experiment --circuit <ToyCircuit-S1-6k> --out docs/benchmarks/brain_wiring
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from cie.neuro import circuit as C
from cie.neuro.neurons import MLP, Neurons, n_params
from cie.neuro.opsins import CHR2_OPSIN, NPHR_OPSIN, drive, kinetics

UNKNOWN, FALSE, TRUE = 0, 1, 2
OPS = ["AND", "OR", "NOT", "XOR", "EXCEPT"]
ARMS = ["cortex", "random", "degree", "dense", "mlp"]
SEEDS = (11, 22, 33)
SPLIT_SEED, HELD_PAIRS = 2026, 7
LIGHT = {"mw_per_mm2": 10.0, "pre_ms": 100.0, "amplitude": 2.0, "fraction": 0.25, "draws": 20}
TICKS, TICK_MS = 6, 20.0


def reference(op: str, a: int, b: int) -> int:
    """Strong Kleene logic, as in the engine; EXCEPT is a and not b; NOT ignores b."""
    def neg(x):
        return {UNKNOWN: UNKNOWN, FALSE: TRUE, TRUE: FALSE}[x]

    def conj(x, y):
        return FALSE if FALSE in (x, y) else (TRUE if x == y == TRUE else UNKNOWN)

    if op == "AND":
        return conj(a, b)
    if op == "OR":
        return TRUE if TRUE in (a, b) else (FALSE if a == b == FALSE else UNKNOWN)
    if op == "NOT":
        return neg(a)
    if op == "XOR":
        return UNKNOWN if UNKNOWN in (a, b) else (TRUE if a != b else FALSE)
    return conj(a, neg(b))


def _onehot(i: int, n: int) -> list[float]:
    return [1.0 if k == i else 0.0 for k in range(n)]


def primitives() -> tuple[torch.Tensor, torch.Tensor, list[str]]:
    rows, ys, ops = [], [], []
    for op, a, b in itertools.product(OPS, range(3), range(3)):
        rows.append(_onehot(a, 3) + _onehot(b, 3) + _onehot(OPS.index(op), 5))
        ys.append(reference(op, a, b))
        ops.append(op)
    return torch.tensor(rows), torch.tensor(ys), ops


def held_out_pairs(seed: int = SPLIT_SEED, k: int = HELD_PAIRS) -> list[tuple[str, str]]:
    """``k`` operation pairs kept out of training; every operation stays in training as both first and second."""
    pairs = list(itertools.product(OPS, OPS))
    rng = np.random.default_rng(seed)
    while True:
        held = [pairs[i] for i in sorted(rng.choice(len(pairs), size=k, replace=False))]
        train = [p for p in pairs if p not in held]
        if {p[0] for p in train} == set(OPS) and {p[1] for p in train} == set(OPS):
            return held


def compositions(held: list[tuple[str, str]]) -> dict[str, tuple[torch.Tensor, torch.Tensor]]:
    out: dict[str, tuple[list, list]] = {"train": ([], []), "test": ([], [])}
    for (o1, o2), (a, b, c) in itertools.product(itertools.product(OPS, OPS), itertools.product(range(3), repeat=3)):
        part = "test" if (o1, o2) in held else "train"
        out[part][0].append(_onehot(a, 3) + _onehot(b, 3) + _onehot(c, 3) + _onehot(OPS.index(o1), 5) + _onehot(OPS.index(o2), 5))
        out[part][1].append(reference(o2, reference(o1, a, b), c))
    return {k: (torch.tensor(x), torch.tensor(y)) for k, (x, y) in out.items()}


def build(arm: str, wirings: dict[str, C.Wiring], n_basal: int, n_apical: int) -> nn.Module:
    if arm == "mlp":
        return MLP(n_basal + n_apical)
    w = wirings[arm]
    return Neurons(n_basal, n_apical, h=w.n, ticks=TICKS, mask=w.mask(), u=w.u, dep_ms=w.dep_ms, fac_ms=w.fac_ms, tick_ms=TICK_MS)


def train(m: nn.Module, x: torch.Tensor, y: torch.Tensor, epochs: int, lr: float = 0.01) -> float:
    """Full-batch Adam, keeping the weights with the lowest training loss (the engine's procedure). Returns seconds."""
    opt = torch.optim.Adam(m.parameters(), lr=lr)
    best, best_loss, t = None, float("inf"), time.perf_counter()
    for _ in range(epochs):
        m.train()
        opt.zero_grad()
        loss = nn.functional.cross_entropy(m(x), y)
        loss.backward()
        nn.utils.clip_grad_norm_(m.parameters(), 2)
        opt.step()
        m.eval()
        with torch.no_grad():
            ev = nn.functional.cross_entropy(m(x), y).item()
        if ev < best_loss:
            best_loss, best = ev, {k: v.clone() for k, v in m.state_dict().items()}
    m.load_state_dict(best)
    m.eval()
    return time.perf_counter() - t


def accuracy(m: nn.Module, x: torch.Tensor, y: torch.Tensor, **kw) -> float:
    with torch.no_grad():
        return float((m(x, **kw).argmax(-1) == y).float().mean()) if kw else float((m(x).argmax(-1) == y).float().mean())


def light(units: np.ndarray, opsin) -> torch.Tensor:
    """(ticks, units) drive for the neurons in ``units`` (a boolean mask) expressing ``opsin`` under the light protocol."""
    d = drive(opsin, mw_per_mm2=LIGHT["mw_per_mm2"], pre_ms=LIGHT["pre_ms"], steps=TICKS, step_ms=TICK_MS) * LIGHT["amplitude"]
    return torch.tensor(np.outer(d, units.astype(float)), dtype=torch.float32)


def populations(w: C.Wiring) -> dict[str, np.ndarray]:
    layer = np.array(w.unit_layer)
    cls = np.array(w.unit_class)
    pops = {"L2/3": np.isin(layer, [2, 3]), "L4": layer == 4, "L5": layer == 5, "L6": layer == 6, "INH": cls == "INH"}
    return {k: v for k, v in pops.items() if v.sum() >= 1}


def opto(m: nn.Module, w: C.Wiring, x: torch.Tensor, y: torch.Tensor, ops: list[str], seed: int) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    n = m.mlp[0].out_features if isinstance(m, MLP) else w.n
    k = int(round(LIGHT["fraction"] * n))
    draws = [np.isin(np.arange(n), rng.choice(n, size=k, replace=False)) for _ in range(LIGHT["draws"])]
    if isinstance(m, MLP):  # no neurons to put opsins in: a quarter of its hidden units set to zero, for reference
        return {"random_off": float(np.mean([accuracy(m, x, y, drop=torch.tensor(~d, dtype=torch.float32)) for d in draws]))}
    out: dict[str, Any] = {
        "random_off": float(np.mean([accuracy(m, x, y, light=light(d, NPHR_OPSIN)) for d in draws])),
        "random_on": float(np.mean([accuracy(m, x, y, light=light(d, CHR2_OPSIN)) for d in draws])),
        "populations": {}}
    ops_arr = np.array(ops)
    for name, units in populations(w).items():
        with torch.no_grad():
            pred = m(x, light=light(units, NPHR_OPSIN)).argmax(-1)
        right = (pred == y).numpy()
        out["populations"][name] = {"neurons": int(units.sum()), "accuracy": float(right.mean()),
                                    "broken_operations": [op for op in OPS if right[ops_arr == op].mean() < 1.0]}
    return out


def ms_per_call(m: nn.Module, x: torch.Tensor, reps: int = 50) -> float:
    with torch.no_grad():
        m(x)
        t = time.perf_counter()
        for _ in range(reps):
            m(x)
    return (time.perf_counter() - t) / reps * 1000


def run(c: C.Circuit, *, seeds=SEEDS, size: int = 64, epochs_primitives: int = 400, epochs_compositions: int = 1000,
        arms=ARMS, log=print) -> dict[str, Any]:
    torch.set_num_threads(2)
    held = held_out_pairs()
    comp = compositions(held)
    xp, yp, ops = primitives()
    runs: list[dict[str, Any]] = []
    topology: dict[str, Any] = {}
    for k, seed in enumerate(seeds):
        center = C.hubs(c, len(seeds))[k]
        w = C.cortex(c, C.neighbourhood(c, center, size))
        wirings = {"cortex": w, "random": C.random_like(w, seed), "degree": C.degree_preserving(w, seed), "dense": C.dense(w)}
        topology[str(seed)] = {"center": center, "neurons": w.n, "connections": len(w.edges),
                               "classes": {x: w.unit_class.count(x) for x in sorted(set(w.unit_class))},
                               "layers": {str(x): w.unit_layer.count(x) for x in sorted(set(w.unit_layer))},
                               "simplices": {a: C.simplices(wirings[a]) for a in ("cortex", "random", "degree")}}
        log(f"seed {seed}: neighbourhood of neuron {center}, {len(w.edges)} connections, simplices {topology[str(seed)]['simplices']}")
        for arm in arms:
            torch.manual_seed(seed)
            m = build(arm, wirings, 6, 5)
            secs = train(m, xp, yp, epochs_primitives)
            r = {"seed": seed, "arm": arm, "params": n_params(m), "primitives": accuracy(m, xp, yp), "train_s_primitives": round(secs, 1),
                 "ms_per_call": round(ms_per_call(m, xp), 3), "light": opto(m, w, xp, yp, ops, seed)}
            torch.manual_seed(seed)
            m2 = build(arm, wirings, 9, 10)
            secs = train(m2, *comp["train"], epochs_compositions)
            r.update({"compositions_train": accuracy(m2, *comp["train"]), "compositions_held_out": accuracy(m2, *comp["test"]),
                      "train_s_compositions": round(secs, 1)})
            runs.append(r)
            log(f"  {arm:7s} primitives {r['primitives']:.3f} held-out {r['compositions_held_out']:.3f} "
                f"(train {r['compositions_train']:.3f}) 25% off {r['light']['random_off']:.3f}")
    return {"held_out_pairs": held, "light": LIGHT, "opsins": [kinetics(CHR2_OPSIN), kinetics(NPHR_OPSIN)], "topology": topology,
            "runs": runs, "summary": summarize(runs, topology)}


def summarize(runs: list[dict[str, Any]], topology: dict[str, Any]) -> dict[str, Any]:
    def per_seed(arm: str, key) -> dict[int, float]:
        return {r["seed"]: key(r) for r in runs if r["arm"] == arm}

    held = lambda r: r["compositions_held_out"]  # noqa: E731
    off = lambda r: r["light"]["random_off"]  # noqa: E731
    arms = sorted({r["arm"] for r in runs}, key=ARMS.index)
    means = {a: {"primitives": float(np.mean(list(per_seed(a, lambda r: r["primitives"]).values()))),
                 "compositions_held_out": float(np.mean(list(per_seed(a, held).values()))),
                 "compositions_train": float(np.mean(list(per_seed(a, lambda r: r["compositions_train"]).values()))),
                 "quarter_silenced": float(np.mean(list(per_seed(a, off).values()))),
                 "ms_per_call": float(np.mean(list(per_seed(a, lambda r: r["ms_per_call"]).values())))} for a in arms}

    def diff(a: str, b: str, key) -> dict[str, Any]:
        if a not in arms or b not in arms:
            return {}
        pa, pb = per_seed(a, key), per_seed(b, key)
        d = [pa[s] - pb[s] for s in sorted(pa)]
        return {"mean": float(np.mean(d)), "per_seed": [round(x, 4) for x in d], "same_sign_all_seeds": all(x > 0 for x in d) or all(x < 0 for x in d)}

    rules = {
        "1_cortex_vs_random_held_out": diff("cortex", "random", held),
        "1_cortex_vs_degree_held_out": diff("cortex", "degree", held),
        "2_cortex_vs_random_quarter_silenced": diff("cortex", "random", off),
        "3_cortex_vs_mlp_held_out": diff("cortex", "mlp", held),
    }
    verdict = {}
    r1a, r1b, r2, r3 = (rules[k] for k in rules)
    if r1a and r1b:
        verdict["1 brain wiring helps composition"] = r1a["mean"] >= 0.05 and r1b["mean"] >= 0.03
    if r2:
        verdict["2 brain wiring is more robust"] = r2["mean"] >= 0.05
    if r3:
        verdict["3 better than a plain network"] = r3["mean"] >= 0.05
    hi = {s: {a: sum(v for d, v in t["simplices"][a].items() if int(d) >= 3) for a in ("cortex", "random", "degree")}
          for s, t in topology.items()}
    verdict["4 the cortex wiring has more cliques of 4+ neurons than both controls"] = all(
        h["cortex"] > h["random"] and h["cortex"] > h["degree"] for h in hi.values())
    return {"means": means, "differences": rules, "rules_met": verdict, "simplices_dim3plus": hi}


def report(res: dict[str, Any]) -> str:
    s = res["summary"]
    lines = ["# Brain wiring results (generated)", "", "| arm | primitives | compositions, trained pairs | compositions, held-out pairs | "
             "a quarter silenced (primitives) | ms per call (45 inputs) |", "|---|---|---|---|---|---|"]
    for a, m in s["means"].items():
        lines.append(f"| {a} | {m['primitives']:.3f} | {m['compositions_train']:.3f} | {m['compositions_held_out']:.3f} | "
                     f"{m['quarter_silenced']:.3f} | {m['ms_per_call']:.2f} |")
    lines += ["", "| difference | mean | per seed | same sign in every seed |", "|---|---|---|---|"]
    for k, d in s["differences"].items():
        if d:
            lines.append(f"| {k} | {d['mean']:+.3f} | {', '.join(f'{x:+.3f}' for x in d['per_seed'])} | {d['same_sign_all_seeds']} |")
    lines += ["", "Rules met:"] + [f"- {k}: **{'yes' if v else 'no'}**" for k, v in s["rules_met"].items()]
    lines += ["", "Cliques of 4 or more neurons (simplices of dimension 3+), per seed: " + json.dumps(s["simplices_dim3plus"])]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m cie.neuro.experiment")
    ap.add_argument("--circuit", help="the extracted ToyCircuit-S1-6k folder; without it, a made-up circuit (tests only)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--quick", action="store_true", help="few epochs, one seed: a plumbing check, not a result")
    a = ap.parse_args(argv)
    c = C.load(a.circuit) if a.circuit else C.synthetic()
    kw = {"seeds": (11,), "epochs_primitives": 20, "epochs_compositions": 20} if a.quick else {}
    res = run(c, **kw)
    res["circuit"] = a.circuit and f"Blue Brain SSCx toy circuit, Zenodo {C.ZENODO_RECORD} (archive sha256 {C.ARCHIVE_SHA256})" or "synthetic"
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(res, indent=2, default=str))
    (out / "report.md").write_text(report(res))
    print(report(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
