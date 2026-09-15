from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F

from ..types import IdentityCondition


class DreamFaceEncoder(nn.Module):
    """Multi-reference encoder with learned view pooling and spatial identity tokens.

    The 4x4 tokens are learned spatial features, not certified eye/nose landmarks.
    The structure vector is a learned bottleneck, not measured 3D geometry.
    Random initialization provides no identity recognition guarantee.
    """

    def __init__(self, dim: int = 64, structure_dim: int = 16, token_grid: int = 4):
        super().__init__()
        if dim < 8 or dim % 8 or structure_dim < 1 or token_grid < 1:
            raise ValueError("dim must be >=8 and divisible by 8; other dimensions positive")
        self.dim, self.structure_dim, self.token_grid = dim, structure_dim, token_grid
        self.features = nn.Sequential(
            nn.Conv2d(3, dim // 2, 5, stride=2, padding=2), nn.GroupNorm(4, dim // 2), nn.SiLU(),
            nn.Conv2d(dim // 2, dim, 3, stride=2, padding=1), nn.GroupNorm(8, dim), nn.SiLU(),
            nn.Conv2d(dim, dim, 3, padding=1), nn.GroupNorm(8, dim), nn.SiLU(),
        )
        self.view_score = nn.Linear(dim, 1)
        self.global_projection = nn.Linear(dim, dim)
        self.local_norm = nn.LayerNorm(dim)
        self.structure_projection = nn.Sequential(nn.Linear(dim * token_grid**2, dim), nn.SiLU(), nn.Linear(dim, structure_dim))

    def forward(self, references: torch.Tensor, reference_valid: torch.Tensor | None = None) -> IdentityCondition:
        if references.ndim != 5 or references.shape[2] != 3 or references.shape[1] < 1:
            raise ValueError("references must have shape B,R,3,H,W with at least one view")
        b, r, _, h, w = references.shape
        features = self.features(references.reshape(b*r, 3, h, w))
        pooled = features.mean((-2, -1)).reshape(b, r, self.dim)
        logits = self.view_score(pooled).squeeze(-1)
        if reference_valid is not None:
            if reference_valid.shape != (b, r) or not reference_valid.any(dim=1).all():
                raise ValueError("Every identity requires at least one valid reference")
            logits = logits.masked_fill(~reference_valid.bool(), -torch.inf)
        weights = logits.softmax(dim=1)
        global_embedding = F.normalize(self.global_projection((pooled * weights[..., None]).sum(1)), dim=-1)
        grids = F.adaptive_avg_pool2d(features, self.token_grid).reshape(b, r, self.dim, -1).transpose(-1, -2)
        local = self.local_norm((grids * weights[:, :, None, None]).sum(1))
        structure = self.structure_projection(local.flatten(1))
        return IdentityCondition(global_embedding, local, structure)
