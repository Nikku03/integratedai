"""The reasoning engine's spiking operator, with its recurrent connections restricted to a wiring and a light input.

Reasoning-Engine-v2's ``Operator(mode="bio")`` (the user's prototype): each unit has a basal input (the evidence), an
apical input (the operation), a spiking soma with a learned threshold and calcium-like adaptation, and
Tsodyks-Markram synapses (release probability U, depression and facilitation) on its recurrent output, run for six
steps of 20 ms. Here:

* the recurrent weights are multiplied by the wiring's mask, so a unit only receives from the units wired to it;
* U, depression and facilitation come per unit from the cortex circuit (the median of each neuron's synapses), the
  same for every wiring arm, so the arms differ in their connections only;
* ``light`` adds an optogenetic drive to each unit's membrane: ``(steps, units)`` in multiples of the unit's
  threshold at steady state (``cie.neuro.opsins.drive`` times the expression mask times the amplitude).

With an all-ones mask, the engine's U/dep/fac/ca and no light, ``forward`` is the engine's computation step for step
(checked against its checkpoints in docs/BRAIN_WIRING_RESULTS.md).
"""

from __future__ import annotations

import math

import numpy as np
import torch
from torch import nn


class Spike(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x):
        ctx.save_for_backward(x)
        return (x > 0).float()

    @staticmethod
    def backward(ctx, g):
        (x,) = ctx.saved_tensors
        return g / (1 + 4 * x.abs()).square()


class Neurons(nn.Module):
    def __init__(self, n_basal: int, n_apical: int, n_out: int = 3, h: int = 64, ticks: int = 6, *, mask: np.ndarray | None = None,
                 u: np.ndarray | None = None, dep_ms: np.ndarray | None = None, fac_ms: np.ndarray | None = None, tick_ms: float = 20.0,
                 tau_ca_ms: float = 278.3):
        super().__init__()
        self.h, self.ticks, self.n_basal = h, ticks, n_basal
        self.basal = nn.Linear(n_basal, h)
        self.apical = nn.Linear(n_apical, h)
        self.recurrent = nn.Linear(h, h, bias=False)
        self.readout = nn.Sequential(nn.Linear(2 * h, h), nn.Tanh(), nn.Linear(h, n_out))
        self.threshold = nn.Parameter(torch.full((h,), 0.35))
        u = np.full(h, 0.5) if u is None else np.asarray(u, dtype=float)
        dep = np.full(h, 600.0) if dep_ms is None else np.asarray(dep_ms, dtype=float)
        fac = np.full(h, 20.0) if fac_ms is None else np.asarray(fac_ms, dtype=float)
        self.register_buffer("U", torch.tensor(u, dtype=torch.float32))
        self.register_buffer("dep", torch.tensor(np.exp(-tick_ms / dep), dtype=torch.float32))
        self.register_buffer("fac", torch.tensor(np.exp(-tick_ms / np.maximum(fac, 1e-3)), dtype=torch.float32))
        self.register_buffer("ca", torch.tensor(math.exp(-tick_ms / tau_ca_ms), dtype=torch.float32))
        self.register_buffer("mask", torch.tensor(np.ones((h, h), np.float32) if mask is None else mask, dtype=torch.float32))

    def forward(self, x: torch.Tensor, light: torch.Tensor | None = None) -> torch.Tensor:
        h = self.h
        state = x.new_zeros((len(x), h))
        v, adapt, trace, basal, apical = state.clone(), state.clone(), state.clone(), state.clone(), state.clone()
        resource = torch.ones_like(state)
        release = self.U.expand_as(state).clone()
        e, c = self.basal(x[:, :self.n_basal]), self.apical(x[:, self.n_basal:])
        w = self.recurrent.weight * self.mask
        thr = self.threshold.clamp(0.05, 1)
        for t in range(self.ticks):
            release = self.U + (release - self.U) * self.fac
            release = release + self.U * (1 - release) * state.detach()
            resource = 1 - (1 - resource) * self.dep
            effective = state * release * resource
            resource = (resource - effective.detach()).clamp(0, 1)
            basal = 0.5 * basal + 0.5 * torch.tanh(e + 0.15 * effective @ w.T)
            apical = 0.8 * apical + 0.2 * torch.tanh(c)
            v = 0.6 * v + basal * (0.75 + torch.sigmoid(apical)) - adapt
            if light is not None:  # steady v = 2.5 x input: a drive of 1 holds the membrane at threshold
                v = v + light[t] * thr / 2.5
            state = Spike.apply(v - thr)
            v = v - state.detach() * thr
            adapt = self.ca * adapt + 0.03 * state
            trace = 0.8 * trace + 0.2 * state
        return self.readout(torch.cat([trace, v], -1))


class MLP(nn.Module):
    """The engine's plain network, for reference."""

    def __init__(self, n_in: int, n_out: int = 3, h: int = 64):
        super().__init__()
        self.mlp = nn.Sequential(nn.Linear(n_in, h), nn.Tanh(), nn.Linear(h, h), nn.Tanh(), nn.Linear(h, n_out))

    def forward(self, x: torch.Tensor, light=None, *, drop: torch.Tensor | None = None) -> torch.Tensor:
        if drop is None:
            return self.mlp(x)
        a = torch.tanh(self.mlp[0](x)) * drop
        a = torch.tanh(self.mlp[2](a)) * drop
        return self.mlp[4](a)


def n_params(m: nn.Module) -> int:
    """Trainable weights that can be non-zero (masked recurrent weights do not count)."""
    total = sum(p.numel() for p in m.parameters())
    if isinstance(m, Neurons):
        total -= int((m.mask == 0).sum())
    return total
