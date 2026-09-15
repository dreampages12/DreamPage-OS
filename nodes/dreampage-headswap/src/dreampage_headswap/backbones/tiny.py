from __future__ import annotations
import math
import torch
from torch import nn
from torch.nn import functional as F
from .base import GenerativeBackbone
from ..conditioning import IdentityAdapter, age_features
from ..types import SwapCondition


class TinyFlowBackbone(GenerativeBackbone):
    """CPU-sized trainable pixel-space rectified flow. Infrastructure test, not a face model."""

    def __init__(self, identity_dim: int = 64, structure_dim: int = 16, width: int = 32,
                 geometry_channels: int = 4, geometry_dim: int = 16):
        super().__init__()
        if width % 8:
            raise ValueError("width must be divisible by 8")
        self.geometry_channels, self.geometry_dim = geometry_channels, geometry_dim
        self.input = nn.Conv2d(3 + 3 + 1 + geometry_channels, width, 3, padding=1)
        self.global_condition = nn.Sequential(nn.Linear(geometry_dim + 2 + 8, width), nn.SiLU(), nn.Linear(width, width))
        self.block1 = nn.Sequential(nn.GroupNorm(8, width), nn.SiLU(), nn.Conv2d(width, width, 3, padding=1))
        self.identity_adapter = IdentityAdapter(width, identity_dim, structure_dim)
        self.block2 = nn.Sequential(nn.GroupNorm(8, width), nn.SiLU(), nn.Conv2d(width, width, 3, padding=1), nn.SiLU())
        self.output = nn.Conv2d(width, 3, 3, padding=1)

    def encode_images(self, images: torch.Tensor) -> torch.Tensor:
        return images * 2 - 1

    def decode_latents(self, latents: torch.Tensor) -> torch.Tensor:
        return (latents + 1) / 2

    def predict_velocity(self, sample: torch.Tensor, t: torch.Tensor, condition: SwapCondition) -> torch.Tensor:
        size = sample.shape[-2:]
        mask = F.interpolate(condition.mask, size=size, mode="nearest")
        geometry = F.interpolate(condition.geometry.spatial.to(sample), size=size, mode="bilinear", align_corners=False)
        template = F.interpolate(condition.template.to(sample), size=size, mode="bilinear", align_corners=False) * 2 - 1
        hidden = self.input(torch.cat([sample, template, mask, geometry], dim=1))
        frequencies = sample.new_tensor([1, 2, 4, 8]) * math.pi
        phase = t.to(sample)[:, None] * frequencies
        global_inputs = torch.cat([condition.geometry.vector.to(sample), age_features(condition.age, sample), phase.sin(), phase.cos()], -1)
        hidden = hidden + self.global_condition(global_inputs)[:, :, None, None]
        hidden = hidden + self.block1(hidden)
        hidden = self.identity_adapter(hidden, condition.identity, mask)
        return self.output(hidden + self.block2(hidden))
