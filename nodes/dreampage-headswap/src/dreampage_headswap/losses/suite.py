from __future__ import annotations
from collections.abc import Callable, Mapping
import math

import torch
from torch import nn
from torch.nn import functional as F


def masked_mean(value: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    expanded = mask.expand_as(value)
    return (value * expanded).sum() / expanded.sum().clamp_min(1)


def supervised_identity_contrastive(first: torch.Tensor, second: torch.Tensor,
                                    identity_ids: list[str], temperature: float = 0.1) -> torch.Tensor:
    """Multi-positive cross-view identity objective; separate identities supply negatives."""
    if len(set(identity_ids)) < 2:
        raise ValueError("Identity contrastive training requires at least two distinct identities per batch")
    logits = F.normalize(first, dim=-1) @ F.normalize(second, dim=-1).T / temperature
    positive = torch.tensor([[a == b for b in identity_ids] for a in identity_ids], device=first.device)
    log_prob = logits.log_softmax(dim=1)
    reverse_log_prob = logits.T.log_softmax(dim=1)
    return -0.5 * ((log_prob * positive).sum(1) / positive.sum(1)).mean() - 0.5 * ((reverse_log_prob * positive.T).sum(1) / positive.T.sum(1)).mean()


class LossSuite(nn.Module):
    """YAML-weighted objectives; unavailable estimators fail when enabled.

    Providers must be licensed, frozen, independently validated differentiable
    estimators: callable(prediction_rgb, target_rgb, batch)->scalar tensor.
    Training DreamFace is deliberately not reused as its own identity teacher.
    Lighting/texture below are pixel statistics, not semantic quality scores.
    """
    BUILTINS = {"flow_matching", "reconstruction", "outside_mask", "boundary", "lighting", "local_texture"}
    ESTIMATORS = {"global_identity", "local_identity", "facial_perceptual", "pose", "landmark", "gaze", "expression", "age_consistency"}

    def __init__(self, weights: Mapping[str, float], providers: Mapping[str, Callable] | None = None):
        super().__init__()
        self.weights = {name: float(weight) for name, weight in weights.items()}
        self.providers = dict(providers or {})
        for name, weight in self.weights.items():
            if name not in self.BUILTINS | self.ESTIMATORS or not math.isfinite(weight) or weight < 0:
                raise ValueError(f"Unknown loss or negative weight: {name}={weight}")
            if weight and name in self.ESTIMATORS and name not in self.providers:
                raise ValueError(f"{name} requires a licensed frozen differentiable estimator provider; no proxy is silently substituted")
        if not any(self.weights.values()):
            raise ValueError("At least one loss weight must be positive")

    @property
    def needs_images(self) -> bool:
        return any(weight and name != "flow_matching" for name, weight in self.weights.items())

    def forward(self, *, velocity: torch.Tensor, target_velocity: torch.Tensor,
                predicted_image: torch.Tensor | None, target: torch.Tensor,
                template: torch.Tensor, mask: torch.Tensor, batch: dict | None = None) -> tuple[torch.Tensor, dict[str, float]]:
        values: dict[str, torch.Tensor] = {}
        for name, weight in self.weights.items():
            if not weight:
                continue
            if name == "flow_matching":
                value = F.mse_loss(velocity.float(), target_velocity.float())
            else:
                if predicted_image is None:
                    raise ValueError("Image-space losses require a differentiable decoded prediction")
                pred, truth = predicted_image.float(), target.float()
                if name == "reconstruction":
                    value = masked_mean((pred-truth).abs(), mask)
                elif name == "outside_mask":
                    value = masked_mean((pred-template.float()).abs(), (mask == 0).float())
                elif name == "boundary":
                    outer = F.max_pool2d(mask, 3, 1, 1)
                    inner = -F.max_pool2d(-mask, 3, 1, 1)
                    value = masked_mean((pred-truth).abs(), (outer-inner).clamp(0, 1))
                elif name == "lighting":
                    value = masked_mean((F.avg_pool2d(pred, 7, 1, 3)-F.avg_pool2d(truth, 7, 1, 3)).abs(), mask)
                elif name == "local_texture":
                    pred_hi = pred - F.avg_pool2d(pred, 3, 1, 1)
                    truth_hi = truth - F.avg_pool2d(truth, 3, 1, 1)
                    value = masked_mean((pred_hi-truth_hi).abs(), mask)
                else:
                    value = self.providers[name](pred, truth, batch or {})
            if value.ndim != 0 or not torch.isfinite(value):
                raise FloatingPointError(f"{name} returned non-scalar or non-finite loss")
            values[name] = value
        total = sum(self.weights[name] * value for name, value in values.items())
        if not torch.isfinite(total):
            raise FloatingPointError("Non-finite weighted total loss")
        metrics = {name: float(value.detach()) for name, value in values.items()}
        metrics["total"] = float(total.detach())
        return total, metrics
