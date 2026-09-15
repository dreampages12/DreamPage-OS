from __future__ import annotations

import torch
from torch import nn
from ..types import IdentityCondition


def age_features(age: torch.Tensor | None, like: torch.Tensor) -> torch.Tensor:
    """Age plus explicit availability; unknown (-1/None) cannot equal a newborn."""
    if age is None:
        return like.new_zeros((like.shape[0], 2))
    age = age.to(like).reshape(-1)
    available = torch.isfinite(age) & (age >= 0)
    return torch.stack([torch.where(available, age.clamp(0, 100) / 100, 0), available.to(like)], dim=-1)


def conditioning_tokens(identity: IdentityCondition, structure_projection: nn.Module) -> torch.Tensor:
    return torch.cat([identity.global_embedding[:, None], identity.local_tokens,
                      structure_projection(identity.structure)[:, None]], dim=1)


class IdentityAdapter(nn.Module):
    """Own cross-attention residual adapter usable independently of a diffusion vendor."""

    def __init__(self, channels: int, identity_dim: int = 64, structure_dim: int = 16, heads: int = 4):
        super().__init__()
        self.structure_projection = nn.Linear(structure_dim, identity_dim)
        self.query_norm = nn.LayerNorm(channels)
        self.attention = nn.MultiheadAttention(channels, heads, kdim=identity_dim, vdim=identity_dim, batch_first=True)
        self.output = nn.Linear(channels, channels)
        nn.init.normal_(self.output.weight, std=0.01)
        nn.init.zeros_(self.output.bias)

    def forward(self, features: torch.Tensor, identity: IdentityCondition, mask: torch.Tensor | None = None) -> torch.Tensor:
        b, c, h, w = features.shape
        queries = features.flatten(2).transpose(1, 2)
        tokens = conditioning_tokens(identity, self.structure_projection)
        attended, _ = self.attention(self.query_norm(queries), tokens, tokens, need_weights=False)
        residual = self.output(attended).transpose(1, 2).reshape(b, c, h, w)
        return features + residual * (1 if mask is None else mask)
