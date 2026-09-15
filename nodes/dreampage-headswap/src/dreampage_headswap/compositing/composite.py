"""Hard final preservation independent of denoiser/VAE behavior."""
from __future__ import annotations

import numpy as np

from dreampage_headswap.masking import validate_mask
from dreampage_headswap.template import restore_crop
from dreampage_headswap.types import TemplateCrop
from dreampage_headswap.utils.images import validate_image


def composite_to_template(template: np.ndarray, generated: np.ndarray, crop: TemplateCrop) -> np.ndarray:
    template = validate_image(template)
    if template.shape[:2] != crop.transform.original_hw:
        raise ValueError("Template resolution no longer matches crop transform")
    allowed = validate_mask(crop.masks.original, crop.transform.original_hw)
    blend = validate_mask(crop.masks.blend, crop.transform.original_hw)
    if np.any(blend > allowed + 1e-7):
        raise ValueError("Blend mask cannot exceed the supplied mask's authority")
    patch = restore_crop(generated, crop.transform)
    x0, y0, x1, y1 = crop.transform.box_xyxy
    result = template.copy()
    alpha = blend[y0:y1, x0:x1][..., None].astype(np.float64)
    base = template[y0:y1, x0:x1].astype(np.float64)
    if template.dtype == np.uint8:
        patch = patch.astype(np.float64) * 255
    mixed = base * (1 - alpha) + patch * alpha
    if template.dtype == np.uint8:
        mixed = np.rint(mixed).clip(0, 255)
    destination = result[y0:y1, x0:x1]
    editable = alpha[..., 0] > 0
    destination[editable] = mixed.astype(template.dtype)[editable]
    # Direct copy, avoiding even floating-point roundoff at protected pixels.
    result[allowed == 0] = template[allowed == 0]
    return result
