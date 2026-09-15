from __future__ import annotations
import torch
from torch import nn
from ..conditioning import IdentityAdapter
from ..types import IdentityCondition


class DreamRefine(nn.Module):
    """Separate trainable, bounded residual refiner; zero-initialized to identity.

    A small RGB residual limits changes but does not prove identity preservation.
    Production training additionally requires a validated frozen identity teacher.
    """
    def __init__(self, identity_dim: int = 64, structure_dim: int = 16, width: int = 32, max_delta: float = 0.08):
        super().__init__()
        if not 0 < max_delta <= 0.2:
            raise ValueError("max_delta must be in (0,0.2]")
        self.max_delta = max_delta
        self.features = nn.Sequential(nn.Conv2d(7, width, 3, padding=1), nn.SiLU(), nn.Conv2d(width, width, 3, padding=1), nn.SiLU())
        self.identity_adapter = IdentityAdapter(width, identity_dim, structure_dim)
        self.residual = nn.Conv2d(width, 3, 3, padding=1)
        nn.init.zeros_(self.residual.weight)
        nn.init.zeros_(self.residual.bias)

    def forward(self, generated: torch.Tensor, template: torch.Tensor, mask: torch.Tensor,
                identity: IdentityCondition) -> torch.Tensor:
        context = template * (1-mask) + generated * mask
        hidden = self.features(torch.cat([generated, context, mask], dim=1))
        hidden = self.identity_adapter(hidden, identity, mask)
        refined = (generated + self.max_delta * self.residual(hidden).tanh() * mask).clamp(0, 1)
        return torch.where(mask > 0, refined, template)
