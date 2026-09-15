"""Ablatable target-identity suppression. None of these is a proven anonymizer."""
from __future__ import annotations

import torch
import torch.nn.functional as F


def prepare_condition_crop(template, crop, strategy="neutral", *, seed=0, internal_face_mask=None):
    """Suppress native face RGB BEFORE interpolation can spread it outside the mask.

    Border padding follows suppression too, so a face touching a page edge cannot
    reappear in replicated context. The raw template crop remains the final base.
    Neutral/noise conditions are invariant to original RGB anywhere in the supplied
    headmask; blur/none are deliberately identity-retaining experimental ablations.
    """
    import numpy as np
    from ..masking import validate_mask
    from ..utils.images import float_image, resize_array, to_tensor, from_tensor

    image = float_image(template)
    if image.shape[:2] != crop.transform.original_hw:
        raise ValueError("Template dimensions differ from crop transform")
    x0, y0, x1, y1 = crop.transform.box_xyxy
    left, top, right, bottom = crop.transform.padding_ltrb
    authority = validate_mask(crop.masks.original, image.shape[:2])
    generation = validate_mask(crop.masks.generation, image.shape[:2])
    region = ((authority > 0) | (generation > 0))[y0:y1, x0:x1]
    mask = torch.from_numpy(region.astype(np.float32))[None, None]
    face = None
    if internal_face_mask is not None:
        values = validate_mask(internal_face_mask, image.shape[:2])
        if np.any((values > 0) & (authority == 0)):
            raise ValueError("Internal face mask must lie within the original headmask")
        face = torch.from_numpy(values[y0:y1, x0:x1].copy())[None, None]
    suppressed = suppress_template(to_tensor(image[y0:y1, x0:x1]), mask, strategy,
                                   seed=seed, face_mask=face)
    native = np.pad(from_tensor(suppressed), ((top, bottom), (left, right), (0, 0)), mode="edge")
    return resize_array(native, crop.transform.model_hw)


def suppress_template(template: torch.Tensor, mask: torch.Tensor, strategy: str = "neutral", *,
                      seed: int = 0, face_mask: torch.Tensor | None = None,
                      blur_kernel: int = 31) -> torch.Tensor:
    if template.ndim != 4 or template.shape[1] != 3 or mask.shape != (template.shape[0], 1, *template.shape[2:]):
        raise ValueError("Expected template B3HW and mask B1HW")
    if not torch.isfinite(template).all() or not torch.isfinite(mask).all() or torch.any((mask < 0) | (mask > 1)):
        raise ValueError("Template/mask must be finite, mask in [0,1]")
    if strategy == "none":
        return template.clone()  # Explicit leakage control for ablations only.
    region = mask > 0
    if strategy == "internal":
        if face_mask is None or face_mask.shape != mask.shape:
            raise ValueError("internal suppression requires a supplied, aligned B1HW internal-face mask")
        if not torch.isfinite(face_mask).all() or torch.any((face_mask < 0) | (face_mask > 1)):
            raise ValueError("Internal face mask must be finite and in [0,1]")
        if torch.any((face_mask > 0) & ~region):
            raise ValueError("Internal face mask must be contained in the supplied headmask")
        region = face_mask > 0
        strategy = "neutral"
    protected = (~region).to(template.dtype)
    count = protected.sum(dim=(2, 3), keepdim=True)
    mean = (template * protected).sum(dim=(2, 3), keepdim=True) / count.clamp_min(1)
    mean = torch.where(count > 0, mean, torch.full_like(mean, 0.5))
    if strategy == "neutral":
        replacement = mean.expand_as(template)
    elif strategy == "noise":
        generator = torch.Generator(device=template.device).manual_seed(seed)
        replacement = (mean + torch.randn(template.shape, device=template.device, dtype=template.dtype, generator=generator) * 0.2).clamp(0, 1)
    elif strategy == "blur":
        if blur_kernel < 3 or blur_kernel % 2 == 0:
            raise ValueError("blur_kernel must be odd and at least 3")
        padded = F.pad(template, (blur_kernel // 2,) * 4, mode="replicate")
        replacement = F.avg_pool2d(padded, blur_kernel, stride=1)
    else:
        raise ValueError(f"Unsupported template suppression strategy: {strategy}")
    return torch.where(region, replacement, template)
