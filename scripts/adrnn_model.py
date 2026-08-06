"""ADRNN: attention over a residual recurrent stack, with two heads.

Architecture is exactly as frozen in ``docs/PREREGISTRATION_ADRNN.md``:
d_model 128, three residual GRU blocks, four-head self-attention over the time
axis, attention pooling, then a magnitude head and a direction head.

The two heads exist to make a specific failure legible. Magnitude and direction
are different questions -- ``P(|move| >= 20%)`` and ``P(the move was up | it was
big)`` -- and this project has four independent results saying the second one is
not answerable from filing data. Training them jointly on a shared encoder means
the direction head either finds something the magnitude head's representation
already contains, or it returns 0.5 and says so. A single-output model would
have hidden that behind an averaged metric.

The direction loss is masked to rows where a big move actually happened. Asking
which way a stock broke when it never broke is asking the model to fit noise,
and it would happily do it.
"""

from __future__ import annotations

import torch
import torch.nn as nn


class ResidualGRU(nn.Module):
    """``h = h + GRU(LayerNorm(h))``.

    Pre-norm rather than post-norm: with three stacked recurrent blocks the
    residual path has to stay clean or the gradient through 60 timesteps decays
    before it reaches the early ones.
    """

    def __init__(self, d_model: int, dropout: float = 0.1) -> None:
        super().__init__()
        self.norm = nn.LayerNorm(d_model)
        self.gru = nn.GRU(d_model, d_model, batch_first=True)
        self.drop = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h, _ = self.gru(self.norm(x))
        return x + self.drop(h)


class AttentionPool(nn.Module):
    """Learned query pooling over time.

    Mean-pooling a 60-day window would weight a filing on day 3 the same as one
    on day 59. A learned query lets the model decide which days mattered, which
    is the point of putting attention in this thing at all.
    """

    def __init__(self, d_model: int) -> None:
        super().__init__()
        self.q = nn.Parameter(torch.randn(1, 1, d_model) * 0.02)
        self.attn = nn.MultiheadAttention(d_model, 4, batch_first=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        q = self.q.expand(x.size(0), -1, -1)
        pooled, _ = self.attn(q, x, x, need_weights=False)
        return pooled.squeeze(1)


class ADRNN(nn.Module):
    def __init__(self, n_features: int, d_model: int = 128, n_blocks: int = 3,
                 n_heads: int = 4, dropout: float = 0.1) -> None:
        super().__init__()
        self.inp = nn.Sequential(
            nn.Linear(n_features, d_model), nn.LayerNorm(d_model), nn.GELU())
        self.blocks = nn.ModuleList(
            [ResidualGRU(d_model, dropout) for _ in range(n_blocks)])
        self.tnorm = nn.LayerNorm(d_model)
        self.tattn = nn.MultiheadAttention(d_model, n_heads, dropout=dropout,
                                           batch_first=True)
        self.pool = AttentionPool(d_model)
        self.head_mag = nn.Sequential(
            nn.Linear(d_model, d_model // 2), nn.GELU(),
            nn.Dropout(dropout), nn.Linear(d_model // 2, 1))
        self.head_dir = nn.Sequential(
            nn.Linear(d_model, d_model // 2), nn.GELU(),
            nn.Dropout(dropout), nn.Linear(d_model // 2, 1))

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        h = self.inp(x)
        for b in self.blocks:
            h = b(h)
        n = self.tnorm(h)
        a, _ = self.tattn(n, n, n, need_weights=False)
        h = h + a
        z = self.pool(h)
        return self.head_mag(z).squeeze(-1), self.head_dir(z).squeeze(-1)


def two_head_loss(logit_mag: torch.Tensor, logit_dir: torch.Tensor,
                  y_mag: torch.Tensor, y_dir: torch.Tensor,
                  pos_weight: torch.Tensor, lam: float = 1.0
                  ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """BCE on magnitude, plus direction BCE masked to real moves.

    ``pos_weight`` handles class imbalance without resampling, which keeps the
    predicted probabilities calibrated against the true base rate -- resampling
    would have shifted it and made the precision numbers unreadable.
    """
    lm = nn.functional.binary_cross_entropy_with_logits(
        logit_mag, y_mag, pos_weight=pos_weight)

    mask = y_mag > 0.5
    if mask.any():
        ld = nn.functional.binary_cross_entropy_with_logits(
            logit_dir[mask], y_dir[mask])
    else:
        ld = torch.zeros((), device=logit_mag.device, dtype=logit_mag.dtype)
    return lm + lam * ld, lm.detach(), ld.detach()
