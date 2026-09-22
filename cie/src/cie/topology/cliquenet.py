"""A clique-cascade network and the deep network it is compared with.

The clique network copies the sandcastle cascade as an architecture:

* rods and planks (1D-2D): linear feature detectors over the input;
* cubes and polytopes (3D-5D): coincidence units, each the product of the gated
  activities of 4-6 detectors, so a unit fires only when all its inputs do;
* high-dimensional simplices (6D-11D): sink units, each a steep threshold on the
  mean of 7-12 coincidence units, firing only when nearly all converge;
* the output reads the sinks.

Every unit's fan-in is a fixed random simplex of the layer below (sparse
connectivity, dimension by layer), so parameters live only on those links.

Two ways to learn: back-propagation (the same optimiser as the deep network) and
a reward-modulated Hebbian rule standing in for STDP, purely local: a link is
potentiated when pre- and post-synaptic units are co-active on a positive
example and depressed on a negative one, with decay and per-unit normalisation.

The deep network is an ordinary multilayer perceptron trained by back-propagation.
"""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np
import torch
from torch import nn


class CliqueNet(nn.Module):
    def __init__(self, n_in: int, n_rods: int = 32, n_cubes: int = 32, n_sinks: int = 16, cube_fanin=(4, 6), sink_fanin=(7, 12),
                 seed: int = 0, beta: float = 12.0, theta: float = 0.7):
        super().__init__()
        g = torch.Generator().manual_seed(seed)
        self.rods = nn.Linear(n_in, n_rods)
        # fixed sparse fan-in: which rods each cube listens to, which cubes each sink listens to
        cube_mask = torch.zeros(n_cubes, n_rods)
        for j in range(n_cubes):
            k = int(torch.randint(cube_fanin[0], cube_fanin[1] + 1, (1,), generator=g))
            cube_mask[j, torch.randperm(n_rods, generator=g)[:k]] = 1.0
        sink_mask = torch.zeros(n_sinks, n_cubes)
        for j in range(n_sinks):
            k = int(torch.randint(sink_fanin[0], min(sink_fanin[1], n_cubes) + 1, (1,), generator=g))
            sink_mask[j, torch.randperm(n_cubes, generator=g)[:k]] = 1.0
        self.register_buffer("cube_mask", cube_mask)
        self.register_buffer("sink_mask", sink_mask)
        self.cube_w = nn.Parameter(torch.randn(n_cubes, n_rods, generator=g) * 0.5)
        self.cube_b = nn.Parameter(torch.zeros(n_cubes))
        self.sink_w = nn.Parameter(torch.ones(n_sinks, n_cubes))
        self.beta, self.theta = beta, theta
        self.out = nn.Linear(n_sinks, 1)

    def layers(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        rods = torch.tanh(self.rods(x))  # signal reception
        # coincidence: product over the unit's fan-in of gated rod activity (log-space for stability)
        gate = torch.sigmoid(rods.unsqueeze(1) * (self.cube_w * self.cube_mask).unsqueeze(0) + self.cube_b.view(1, -1, 1))
        log_gate = torch.log(gate + 1e-6) * self.cube_mask.unsqueeze(0)
        cubes = torch.exp(log_gate.sum(-1) / self.cube_mask.sum(-1).clamp(min=1))  # geometric mean of the gates in [0, 1]
        # sinks: steep threshold on the weighted mean of their fan-in; all inputs must converge
        w = torch.relu(self.sink_w) * self.sink_mask
        conv = (cubes.unsqueeze(1) * w.unsqueeze(0)).sum(-1) / w.sum(-1).clamp(min=1e-6).unsqueeze(0)
        sinks = torch.sigmoid(self.beta * (conv - self.theta))
        return rods, cubes, sinks

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.out(self.layers(x)[2]).squeeze(-1)


class MLP(nn.Module):
    def __init__(self, n_in: int, width: int = 64, depth: int = 4, dropout: float = 0.1):
        super().__init__()
        layers: list[nn.Module] = []
        d = n_in
        for _ in range(depth):
            layers += [nn.Linear(d, width), nn.ReLU(), nn.Dropout(dropout)]
            d = width
        layers.append(nn.Linear(d, 1))
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


def n_params(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def train_backprop(model: nn.Module, X: np.ndarray, y: np.ndarray, epochs: int = 40, lr: float = 3e-3, batch: int = 256,
                   seed: int = 0) -> dict[str, Any]:
    torch.manual_seed(seed)
    Xt, yt = torch.tensor(X, dtype=torch.float32), torch.tensor(y, dtype=torch.float32)
    pos = float(yt.mean().clamp(min=1e-4))
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor((1 - pos) / pos))  # candidates are mostly negatives
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    t0 = time.perf_counter()
    n = len(Xt)
    for _ in range(epochs):
        model.train()
        perm = torch.randperm(n)
        for i in range(0, n, batch):
            idx = perm[i:i + batch]
            opt.zero_grad()
            loss = loss_fn(model(Xt[idx]), yt[idx])
            loss.backward()
            opt.step()
    model.eval()
    return {"train_seconds": round(time.perf_counter() - t0, 2), "epochs": epochs, "rule": "backprop (Adam, weighted BCE)"}


def train_hebbian(model: CliqueNet, X: np.ndarray, y: np.ndarray, epochs: int = 10, lr: float = 0.02, decay: float = 1e-3,
                  seed: int = 0) -> dict[str, Any]:
    """Reward-modulated Hebbian learning, local to each link: dw = lr * r * pre * post,
    r = +1 on positives and -1 on negatives, followed by decay and row normalisation.
    No gradient crosses a layer; the rods' input weights learn the same way from x."""
    torch.manual_seed(seed)
    Xt, yt = torch.tensor(X, dtype=torch.float32), torch.tensor(y, dtype=torch.float32)
    r_all = torch.where(yt > 0.5, torch.full_like(yt, 1.0), torch.full_like(yt, -1.0))
    pos = float(yt.mean().clamp(min=1e-4))
    r_all = torch.where(yt > 0.5, r_all / pos, r_all / (1 - pos)) / 2  # balance the two classes' pull
    t0 = time.perf_counter()
    n = len(Xt)
    with torch.no_grad():
        for _ in range(epochs):
            perm = torch.randperm(n)
            for i in range(0, n, 128):
                idx = perm[i:i + 128]
                xb, rb = Xt[idx], r_all[idx]
                rods, cubes, sinks = model.layers(xb)
                # three-factor rule on every layer: reward x pre x post, averaged over the batch
                model.rods.weight += lr * (rb.view(-1, 1, 1) * rods.unsqueeze(2) * xb.unsqueeze(1)).mean(0)
                model.cube_w += lr * ((rb.view(-1, 1, 1) * cubes.unsqueeze(2) * rods.unsqueeze(1)).mean(0)) * model.cube_mask
                model.sink_w += lr * ((rb.view(-1, 1, 1) * sinks.unsqueeze(2) * cubes.unsqueeze(1)).mean(0)) * model.sink_mask
                model.out.weight += lr * (rb.view(-1, 1) * sinks).mean(0).view(1, -1)
                for w in (model.rods.weight, model.cube_w, model.sink_w, model.out.weight):
                    w -= decay * w
                    w /= w.norm(dim=-1, keepdim=True).clamp(min=1e-6) / math.sqrt(w.shape[-1])  # keep each unit's fan-in bounded
            # the read-out bias: place the decision threshold at the midpoint of the two classes' mean drive
            logits = model(Xt)
            model.out.bias.fill_(-(float(logits[yt > 0.5].mean()) + float(logits[yt <= 0.5].mean())) / 2 + float(model.out.bias))
    model.eval()
    return {"train_seconds": round(time.perf_counter() - t0, 2), "epochs": epochs, "rule": "reward-modulated Hebbian (local, three-factor)"}


def predict(model: nn.Module, X: np.ndarray) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        return model(torch.tensor(X, dtype=torch.float32)).numpy()


def auc(scores: np.ndarray, y: np.ndarray) -> float:
    """Area under the ROC curve by rank statistic (ties averaged)."""
    order = np.argsort(scores)
    ranks = np.empty(len(scores), dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1)
    # average ranks for ties
    s_sorted = scores[order]
    i = 0
    while i < len(s_sorted):
        j = i
        while j + 1 < len(s_sorted) and s_sorted[j + 1] == s_sorted[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + 1 + j + 1) / 2
        i = j + 1
    n_pos = int((y > 0.5).sum())
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    return float((ranks[y > 0.5].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def ranking_quality(scores: np.ndarray, y: np.ndarray, groups: np.ndarray) -> dict[str, float]:
    """Per-query ranking of candidates by score: hit@1, hit@5, MRR over queries that have a positive."""
    hits1 = hits5 = 0
    rr = []
    for g in np.unique(groups):
        m = groups == g
        if not (y[m] > 0.5).any():
            continue
        order = np.argsort(-scores[m])
        pos = int(np.argmax(y[m][order] > 0.5))
        hits1 += pos == 0
        hits5 += pos < 5
        rr.append(1.0 / (pos + 1))
    n = max(len(rr), 1)
    return {"queries": len(rr), "hit@1": round(hits1 / n, 3), "hit@5": round(hits5 / n, 3), "mrr": round(float(np.mean(rr)) if rr else 0.0, 3)}
