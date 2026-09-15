from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F

from ..backbones.base import GenerativeBackbone
from ..dreamface import DreamFaceEncoder
from ..types import GeometryCondition, IdentityCondition, SwapCondition


class DreamSwap(nn.Module):
    def __init__(self, encoder: DreamFaceEncoder, backbone: GenerativeBackbone):
        super().__init__()
        self.encoder, self.backbone = encoder, backbone

    def make_condition(self, references: torch.Tensor, template: torch.Tensor, mask: torch.Tensor,
                       geometry: GeometryCondition, age: torch.Tensor | None = None) -> SwapCondition:
        references = references.to(dtype=next(self.encoder.parameters()).dtype)
        return SwapCondition(self.encoder(references), template, mask, geometry, age)

    def forward(self, sample: torch.Tensor, t: torch.Tensor, references: torch.Tensor,
                template: torch.Tensor, mask: torch.Tensor, geometry: GeometryCondition,
                age: torch.Tensor | None = None) -> torch.Tensor:
        return self.backbone.predict_velocity(sample, t, self.make_condition(references, template, mask, geometry, age))

    @torch.no_grad()
    def sample(self, references: torch.Tensor, template: torch.Tensor, mask: torch.Tensor,
               geometry: GeometryCondition, age: torch.Tensor | None = None, steps: int = 20,
               seed: int = 0, identity_strength: float = 1.0,
               condition_template: torch.Tensor | None = None) -> torch.Tensor:
        """Return RGB crop; original template is always restored where mask == 0.

        Default neutral replacement removes internal template identity. Callers may
        supply an explicitly degraded condition_template preserving more geometry.
        Learned geometry must be supplied separately, never inferred from zero tensors.
        """
        if steps < 1 or not 0 <= identity_strength <= 5:
            raise ValueError("steps must be positive; identity_strength must be in [0,5]")
        if mask.shape != (template.shape[0], 1, *template.shape[-2:]):
            raise ValueError("mask must be B1HW matching template")
        if not torch.isfinite(mask).all() or mask.min() < 0 or mask.max() > 1:
            raise ValueError("mask must be finite in [0,1]")
        was_training = self.training
        self.eval()
        try:
            if not torch.any(mask > 0):
                return template.clone()
            safe_template = torch.where(mask > 0, 0.5, template) if condition_template is None else condition_template
            condition = self.make_condition(references, safe_template, mask, geometry, age)
            identity = condition.identity
            condition.identity = IdentityCondition(*(x * identity_strength for x in
                                                      (identity.global_embedding, identity.local_tokens, identity.structure)))
            # The clean anchor must also suppress target identity: VAE receptive
            # fields can otherwise leak the template face across the latent mask.
            original_latents = self.backbone.encode_images(safe_template)
            generator = torch.Generator(device=template.device).manual_seed(seed)
            noise = torch.randn(original_latents.shape, generator=generator, device=template.device, dtype=original_latents.dtype)
            latent_mask = F.interpolate(mask, size=original_latents.shape[-2:], mode="nearest")
            latents = noise
            schedule = self.backbone.sampling_schedule(steps, template.device, original_latents.shape[-2:])
            for current_t, next_t in zip(schedule[:-1], schedule[1:]):
                t = current_t.expand(template.shape[0])
                sampling_predictor = getattr(self.backbone, "predict_sampling_velocity", self.backbone.predict_velocity)
                velocity = sampling_predictor(latents, t, condition)
                latents = latents + (next_t-current_t) * velocity
                protected = (1-next_t) * original_latents + next_t * noise
                latents = latents * latent_mask + protected * (1-latent_mask)
            generated = self.backbone.decode_latents(latents).clamp(0, 1)
            generated = F.interpolate(generated, size=template.shape[-2:], mode="bilinear", align_corners=False)
            blended = generated * mask + template * (1-mask)
            return torch.where(mask > 0, blended, template)
        finally:
            self.train(was_training)
