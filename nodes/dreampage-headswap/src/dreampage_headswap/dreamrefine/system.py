"""Refiner bundle includes its frozen identity representation to prevent serving-time drift."""
from __future__ import annotations

import math

import torch
from torch import nn
from torch.nn import functional as F

from .model import DreamRefine
from ..losses import LossSuite


class RefinementSystem(nn.Module):
    def __init__(self, identity_encoder, refiner: DreamRefine):
        super().__init__()
        self.identity_encoder = identity_encoder.requires_grad_(False).eval()
        self.refiner = refiner

    def train(self, mode=True):
        super().train(mode)
        self.identity_encoder.eval()
        return self

    def forward(self, generated, template, mask, references):
        with torch.no_grad():
            condition = self.identity_encoder(references)
        return self.refiner(generated, template, mask, condition)

    def refine(self, generated, template, mask, references):
        return self(generated, template, mask, references)


class RefinementObjective(nn.Module):
    """Pixel reconstruction plus fixed-encoder source and identity-drift constraints.

    A frozen teacher can still be wrong; its distances are optimization diagnostics,
    not calibrated headswap quality scores. No learning signal from the target head
    is passed into refiner conditioning, only ground-truth losses.
    """
    IDENTITY_TERMS = {"identity_source", "identity_anchor", "residual_penalty"}

    def __init__(self, weights):
        super().__init__()
        self.weights = {key: float(value) for key, value in weights.items()}
        permitted = (LossSuite.BUILTINS - {"flow_matching"}) | self.IDENTITY_TERMS
        if any(name not in permitted or not math.isfinite(w) or w < 0 for name, w in self.weights.items()):
            raise ValueError("Unknown, negative or non-finite refinement loss weight")
        if any(self.weights.get(name, 0) <= 0 for name in ("identity_source", "identity_anchor")):
            raise ValueError("Refinement requires positive identity_source and identity_anchor weights")
        pixels = {name: weight for name, weight in self.weights.items() if name not in self.IDENTITY_TERMS}
        if not any(pixels.values()):
            raise ValueError("Refinement requires at least one reconstruction/texture objective")
        self.pixels = LossSuite(pixels)

    def forward(self, system: RefinementSystem, batch):
        generated, template = batch["generated"], batch["template"]
        mask = (batch["mask"] > 0).to(generated)
        # Enforce identical protected context for all three teacher comparisons.
        anchored = torch.where(mask > 0, generated, template)
        prediction = system(anchored, template, mask, batch["references"])
        dummy = prediction.new_zeros(())
        loss, metrics = self.pixels(velocity=dummy, target_velocity=dummy, predicted_image=prediction,
                                   target=batch["target"], template=template, mask=mask, batch=batch)
        teacher = system.identity_encoder
        with torch.no_grad():
            source = teacher(batch["references"]).global_embedding
            anchor = teacher(anchored[:, None]).global_embedding
        output = teacher(prediction[:, None]).global_embedding
        values = {
            "identity_source": (1 - F.cosine_similarity(output.float(), source.float())).clamp_min(0).mean(),
            "identity_anchor": (1 - F.cosine_similarity(output.float(), anchor.float())).clamp_min(0).mean(),
            "residual_penalty": ((prediction - anchored).square() * mask).sum() / (mask.sum() * 3).clamp_min(1),
        }
        for name, value in values.items():
            if not torch.isfinite(value):
                raise FloatingPointError(f"Non-finite refiner objective: {name}")
            loss = loss + self.weights.get(name, 0.0) * value
            metrics[name] = float(value.detach())
        if not torch.isfinite(loss):
            raise FloatingPointError("Non-finite weighted refiner objective")
        metrics["total"] = float(loss.detach())
        metrics["protected_max_difference"] = float(((prediction - template).abs() * (mask == 0)).max().detach())
        return loss, metrics, prediction
