"""Training and evaluation of the learned explorers."""

from __future__ import annotations

import copy
import random
import statistics
import time
from typing import Any

import numpy as np
import torch

from cie.remnet.graphs import Sample, metrics, pack
from cie.remnet.models import Config, Explorer, Tensors, listwise_loss


def rank(model: Explorer, t: Tensors) -> tuple[list[int], dict, float]:
    model.eval()
    t0 = time.perf_counter()
    with torch.no_grad():
        scores, stats, _ = model(t)
    ms = (time.perf_counter() - t0) * 1000
    s = scores.numpy()
    order = [int(i) for i in np.argsort(-s) if np.isfinite(s[i])]
    return order, stats, ms


def evaluate(model: Explorer, samples: list[Sample], tensors: list[Tensors], budgets: dict[str, int], unit: str) -> list[dict[str, Any]]:
    rows = []
    for smp, t in zip(samples, tensors, strict=True):
        order, stats, ms = rank(model, t)
        for bname, tokens in budgets.items():
            m = metrics(smp, pack(smp, order, tokens), unit)
            rows.append({"qid": smp.qid, "kind": smp.kind, "budget": bname, **m, "infer_ms": ms, **stats, "pool": smp.n})
    return rows


def val_score(rows: list[dict[str, Any]], primary_budget: str, primary: str) -> float:
    sub = [r[primary] for r in rows if r["budget"] == primary_budget and r[primary] is not None]
    return statistics.mean(sub) if sub else 0.0


def train(cfg: Config, seed: int, train_s: list[Sample], val_s: list[Sample], budgets: dict[str, int], unit: str,
          primary_budget: str, primary: str, epochs: int = 20, patience: int = 4, lr: float = 2e-3) -> tuple[Explorer, dict[str, Any]]:
    torch.manual_seed(seed)
    random.seed(seed)
    np.random.seed(seed)
    model = Explorer(cfg)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    tr = [Tensors(s, cfg) for s in train_s]
    va = [Tensors(s, cfg) for s in val_s]
    best, best_state, bad, history = -1.0, None, 0, []
    t0 = time.perf_counter()
    for epoch in range(epochs):
        model.train()
        order = list(range(len(tr)))
        random.shuffle(order)
        losses = []
        for i in order:
            scores, _, gate_loss = model(tr[i])
            loss = listwise_loss(scores, tr[i].labels)
            if gate_loss is not None:
                loss = gate_loss * cfg.gate_aux if loss is None else loss + cfg.gate_aux * gate_loss
            if loss is None:
                continue
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            losses.append(float(loss.detach()))
        v = val_score(evaluate(model, val_s, va, budgets, unit), primary_budget, primary)
        history.append({"epoch": epoch, "loss": round(statistics.mean(losses), 4) if losses else None, "val": round(v, 4)})
        if v > best + 1e-4:
            best, best_state, bad = v, copy.deepcopy(model.state_dict()), 0
        else:
            bad += 1
            if bad >= patience:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    info = {"config": cfg.name, "seed": seed, "epochs": len(history), "best_val": round(best, 4), "train_s": round(time.perf_counter() - t0, 1),
            "params": sum(p.numel() for p in model.parameters()), "history": history}
    return model, info


def baseline_rows(samples: list[Sample], unit: str) -> list[dict[str, Any]]:
    """Metrics of the non-learned arms from the packets recorded when the samples were built."""
    rows = []
    for smp in samples:
        for bname, arms in smp.baselines.items():
            for arm, b in arms.items():
                seen = b["units"]
                gold = set(smp.gold)
                hit = gold & set(seen)
                first = next((r for r, x in enumerate(seen) if x in gold), None)
                rows.append({"qid": smp.qid, "kind": smp.kind, "budget": bname, "arm": arm,
                             "evidence_recall": len(hit) / len(gold) if gold else None,
                             "evidence_precision": len(hit) / len(seen) if seen else 0.0,
                             "recall10": len(gold & set(seen[:10])) / len(gold) if gold else None,
                             "rr": 1.0 / (first + 1) if first is not None else 0.0, "returned": len(seen),
                             "ms": b["ms"], "db_calls": b["db_calls"], "visited": b["visited"]})
    return rows


def bootstrap_diff(a: dict[str, float], b: dict[str, float], n: int = 1000, seed: int = 0) -> dict[str, float]:
    """Mean paired difference a - b over shared question ids, with a 95% bootstrap interval."""
    keys = sorted(set(a) & set(b))
    if not keys:
        return {"diff": float("nan"), "lo": float("nan"), "hi": float("nan"), "n": 0}
    d = np.array([a[k] - b[k] for k in keys])
    rng = np.random.default_rng(seed)
    boots = [float(d[rng.integers(0, len(d), len(d))].mean()) for _ in range(n)]
    return {"diff": round(float(d.mean()), 4), "lo": round(float(np.percentile(boots, 2.5)), 4),
            "hi": round(float(np.percentile(boots, 97.5)), 4), "n": len(keys)}
