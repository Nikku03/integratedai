"""Benchmark of the learned explorers against the non-learned REM arms (rules in docs/REMNET_PREREGISTRATION.md).

    python -m cie.eval.bench_remnet --dataset controlled|erb|all --eval val|test

``--eval val`` reports on the validation questions only (for development); ``--eval test`` is the pre-registered
single test run.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

OUT = Path("eval_out/remnet")
SEEDS = (0, 1, 2)


def configs(k: int):
    from cie.remnet.models import Config

    base = Config(kind="rem", k_active=k)
    return [Config(kind="mlp", k_active=k), Config(kind="ggnn", k_active=k), base, replace(base, routing=False),
            replace(base, inhibition=True), replace(base, inhibition=True, stp="bluebrain", failures=True),
            replace(base, inhibition=True, stp="random", failures=True), replace(base, inhibition=True, stp="learned")]


def dataset(name: str) -> dict[str, Any]:
    from cie.remnet import data

    if name == "controlled":
        split = {k: data.load([OUT / f"controlled-{s}.pkl" for s in seeds]) for k, seeds in data.CONTROLLED_SEEDS.items()}
        # amendment 1 (docs/REMNET_PREREGISTRATION.md): recall@10, because evidence recall at 350 tokens hit the pool ceiling
        return {**split, "budgets": data.CONTROLLED_BUDGETS, "unit": "key", "primary_budget": "t350", "primary": "recall10", "k": 16}
    samples = data.load([OUT / "erb.pkl"])
    split = {k: [s for s in samples if s.split == k] for k in ("train", "val", "test")}
    return {**split, "budgets": data.ERB_BUDGETS, "unit": "doc", "primary_budget": "t2000", "primary": "rr", "k": 32}


def _job(args) -> dict[str, Any]:
    import torch

    torch.set_num_threads(1)
    from cie.remnet.models import Config
    from cie.remnet.train import evaluate, train

    name, cfg_dict, seed, which = args
    ds = dataset(name)
    cfg = Config(**cfg_dict)
    model, info = train(cfg, seed, ds["train"], ds["val"], ds["budgets"], ds["unit"], ds["primary_budget"], ds["primary"])
    from cie.remnet.models import Tensors

    target = ds[which]
    rows = evaluate(model, target, [Tensors(s, cfg) for s in target], ds["budgets"], ds["unit"])
    for r in rows:
        r.update({"arm": cfg.name, "seed": seed})
    import resource

    info["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)  # worker process peak (Linux: KiB)
    info["weights_kb"] = round(info["params"] * 4 / 1024, 1)
    return {"info": info, "rows": rows}


def aggregate(name: str, which: str, learned: list[dict[str, Any]]) -> dict[str, Any]:
    from cie.remnet.data import describe
    from cie.remnet.train import baseline_rows, bootstrap_diff

    ds = dataset(name)
    target = ds[which]
    pb, pm = ds["primary_budget"], ds["primary"]
    rows = [r for job in learned for r in job["rows"]]
    base = baseline_rows(target, ds["unit"])
    arms = ["A", "B", "C"] + list(dict.fromkeys(r["arm"] for r in rows))
    table: dict[str, dict[str, Any]] = {}
    per_q: dict[str, dict[str, float]] = {}
    for arm in arms:
        table[arm] = {}
        src = [r for r in base if r["arm"] == arm] if arm in ("A", "B", "C") else [r for r in rows if r["arm"] == arm]
        for bname in ds["budgets"]:
            sub = [r for r in src if r["budget"] == bname]
            if not sub:
                continue
            entry: dict[str, Any] = {}
            for m in ("evidence_recall", "evidence_precision", "recall10", "rr"):
                vals = [r[m] for r in sub if r[m] is not None]
                entry[m] = round(statistics.mean(vals), 4) if vals else None
                if arm not in ("A", "B", "C"):  # spread across training seeds
                    seeds = sorted({r["seed"] for r in sub})
                    per_seed = [statistics.mean([r[m] for r in sub if r["seed"] == s and r[m] is not None]) for s in seeds]
                    entry[m + "_seed_std"] = round(statistics.pstdev(per_seed), 4) if len(per_seed) > 1 else 0.0
            if arm in ("A", "B", "C"):
                entry["latency_ms_p50"] = round(statistics.median(r["ms"] for r in sub), 1)
                entry["db_calls_p50"] = statistics.median(r["db_calls"] for r in sub)
            else:
                ms = sorted(r["infer_ms"] for r in sub)
                entry["infer_ms_p50"] = round(ms[len(ms) // 2], 2)
                entry["infer_ms_p95"] = round(ms[int(0.95 * (len(ms) - 1))], 2)
                entry["updates_mean"] = round(statistics.mean(r["updates"] for r in sub), 1)
                entry["touched_mean"] = round(statistics.mean(r["touched"] for r in sub), 1)
            table[arm][bname] = entry
        prim = [r for r in src if r["budget"] == pb and r[pm] is not None]
        acc: dict[str, list[float]] = {}
        for r in prim:
            acc.setdefault(r["qid"], []).append(r[pm])
        per_q[arm] = {q: statistics.mean(v) for q, v in acc.items()}
    best_base = max(("A", "B", "C"), key=lambda a: table[a][pb][pm] or 0)
    comps = {}
    for a, b in [("mlp", best_base), ("ggnn", best_base), ("rem", best_base), ("ggnn", "mlp"), ("rem", "mlp"), ("rem", "ggnn"),
                 ("rem", "rem+norouting"), ("rem+inh+stp-bluebrain+fail", "rem+inh"),
                 ("rem+inh+stp-bluebrain+fail", "rem+inh+stp-random+fail"), ("rem+inh+stp-bluebrain+fail", "rem+inh+stp-learned"),
                 ("rem+inh", "rem"), ("rem+inh+stp-bluebrain+fail", best_base)]:
        if a in per_q and b in per_q:
            comps[f"{a} vs {b}"] = bootstrap_diff(per_q[a], per_q[b])
    infos = [j["info"] for j in learned]
    cost = {}
    for arm in dict.fromkeys(i["config"] for i in infos):
        sub = [i for i in infos if i["config"] == arm]
        cost[arm] = {"params": sub[0]["params"], "weights_kb": sub[0].get("weights_kb"),
                     "peak_rss_mb_max": max(i.get("peak_rss_mb", 0) for i in sub),
                     "train_s_mean": round(statistics.mean(i["train_s"] for i in sub), 1),
                     "epochs_mean": round(statistics.mean(i["epochs"] for i in sub), 1), "best_val": [i["best_val"] for i in sub]}
    return {"dataset": name, "evaluated_on": which, "primary": f"{pm} at {pb}", "best_baseline": best_base,
            "data": {k: describe(ds[k]) for k in ("train", "val", "test")}, "table": table, "comparisons": comps, "cost": cost}


def run(name: str, which: str, workers: int) -> dict[str, Any]:
    ds = dataset(name)
    jobs = [(name, asdict(c), s, which) for c in configs(ds["k"]) for s in SEEDS]
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        learned = list(pool.map(_job, jobs))
    res = aggregate(name, which, learned)
    res["wall_s"] = round(time.time() - t0, 1)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"results-{name}-{which}.json").write_text(json.dumps(res, indent=2, default=str))
    (OUT / f"rows-{name}-{which}.json").write_text(json.dumps([r for j in learned for r in j["rows"]], default=str))
    (OUT / f"train-{name}-{which}.json").write_text(json.dumps([j["info"] for j in learned], indent=1, default=str))
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", default="all", choices=["controlled", "erb", "all"])
    ap.add_argument("--eval", default="val", choices=["val", "test"])
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args(argv)
    for name in (["controlled", "erb"] if args.dataset == "all" else [args.dataset]):
        res = run(name, args.eval, args.workers)
        print(json.dumps({k: res[k] for k in ("dataset", "evaluated_on", "primary", "best_baseline", "data", "comparisons", "wall_s")}, indent=1))
        for arm, t in res["table"].items():
            print(f"  {arm:30s}", {b: {m: v for m, v in e.items() if m in ('evidence_recall', 'evidence_precision', 'rr', 'recall10')} for b, e in t.items()})
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
