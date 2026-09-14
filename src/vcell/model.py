"""A small 3D U-Net that predicts one protein's density field from the cell frame.

The architecture is deliberately unremarkable. The only part that matters
scientifically is how protein identity enters: as a **FiLM** modulation
(Perez et al., 2018) of every feature map, driven by the fixed knowledge
vector from `vcell.knowledge`. There is no learned per-structure embedding
table anywhere in this file, and that is the point -- a lookup table cannot
be queried for a structure that was never in training, so a model built
around one could not be asked the leave-one-structure-out question at all.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class FiLM(nn.Module):
    """Per-channel affine modulation conditioned on the knowledge vector."""

    def __init__(self, cond_dim: int, channels: int):
        super().__init__()
        self.to_scale_shift = nn.Linear(cond_dim, 2 * channels)
        # Start as the identity: scale 1, shift 0. Conditioning has to earn
        # its influence during training rather than scrambling early features.
        nn.init.zeros_(self.to_scale_shift.weight)
        nn.init.zeros_(self.to_scale_shift.bias)
        self.channels = channels

    def forward(self, x: torch.Tensor, cond: torch.Tensor) -> torch.Tensor:
        scale, shift = self.to_scale_shift(cond).chunk(2, dim=1)
        shape = (x.shape[0], self.channels) + (1,) * (x.dim() - 2)
        return x * (1.0 + scale.reshape(shape)) + shift.reshape(shape)


class ConditionedBlock(nn.Module):
    """conv -> norm -> FiLM -> act, twice."""

    def __init__(self, in_ch: int, out_ch: int, cond_dim: int):
        super().__init__()
        self.conv1 = nn.Conv3d(in_ch, out_ch, 3, padding=1, bias=False)
        self.norm1 = nn.GroupNorm(num_groups=min(4, out_ch), num_channels=out_ch)
        self.film1 = FiLM(cond_dim, out_ch)
        self.conv2 = nn.Conv3d(out_ch, out_ch, 3, padding=1, bias=False)
        self.norm2 = nn.GroupNorm(num_groups=min(4, out_ch), num_channels=out_ch)
        self.film2 = FiLM(cond_dim, out_ch)

    def forward(self, x: torch.Tensor, cond: torch.Tensor) -> torch.Tensor:
        x = F.silu(self.film1(self.norm1(self.conv1(x)), cond))
        x = F.silu(self.film2(self.norm2(self.conv2(x)), cond))
        return x


class ConditionalUNet3D(nn.Module):
    """Reference channels + protein knowledge vector -> one density field.

    Output is passed through a softplus so densities are non-negative, then
    normalised to unit mean inside the cell mask by the training loss -- the
    model is asked where the protein is, not how much of it there is.
    """

    def __init__(
        self,
        in_channels: int = 2,
        cond_dim: int = 24,
        base: int = 12,
        depth: int = 3,
        cond_hidden: int = 32,
    ):
        super().__init__()
        self.cond_mlp = nn.Sequential(
            nn.Linear(cond_dim, cond_hidden),
            nn.SiLU(),
            nn.Linear(cond_hidden, cond_hidden),
            nn.SiLU(),
        )
        chans = [base * (2**i) for i in range(depth + 1)]

        self.downs = nn.ModuleList()
        prev = in_channels
        for c in chans[:-1]:
            self.downs.append(ConditionedBlock(prev, c, cond_hidden))
            prev = c
        self.bottleneck = ConditionedBlock(prev, chans[-1], cond_hidden)

        self.ups = nn.ModuleList()
        self.upsamples = nn.ModuleList()
        for i in range(depth - 1, -1, -1):
            self.upsamples.append(nn.ConvTranspose3d(chans[i + 1], chans[i], 2, stride=2))
            self.ups.append(ConditionedBlock(2 * chans[i], chans[i], cond_hidden))

        self.head = nn.Conv3d(chans[0], 1, 1)

    def forward(self, x: torch.Tensor, knowledge: torch.Tensor) -> torch.Tensor:
        cond = self.cond_mlp(knowledge)
        skips = []
        for block in self.downs:
            x = block(x, cond)
            skips.append(x)
            x = F.avg_pool3d(x, 2)
        x = self.bottleneck(x, cond)
        for up, block, skip in zip(self.upsamples, self.ups, reversed(skips), strict=True):
            x = up(x)
            x = block(torch.cat([x, skip], dim=1), cond)
        return F.softplus(self.head(x)).squeeze(1)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
