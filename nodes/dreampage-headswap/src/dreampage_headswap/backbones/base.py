from __future__ import annotations
from abc import ABC, abstractmethod

import torch
from torch import nn
from ..types import SwapCondition


class GenerativeBackbone(nn.Module, ABC):
    """BCHW latent velocity v=epsilon-x0 at t in [0,1]; inference integrates 1 to 0."""

    @abstractmethod
    def encode_images(self, images: torch.Tensor) -> torch.Tensor: ...

    @abstractmethod
    def decode_latents(self, latents: torch.Tensor) -> torch.Tensor: ...

    @abstractmethod
    def predict_velocity(self, sample: torch.Tensor, t: torch.Tensor, condition: SwapCondition) -> torch.Tensor: ...

    def sampling_schedule(self, steps: int, device: torch.device, spatial_shape: tuple[int, int]) -> torch.Tensor:
        return torch.linspace(1, 0, steps + 1, device=device)

    def forward(self, sample: torch.Tensor, t: torch.Tensor, condition: SwapCondition) -> torch.Tensor:
        return self.predict_velocity(sample, t, condition)
