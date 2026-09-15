from __future__ import annotations

import numpy as np
from scipy.ndimage import binary_dilation, binary_erosion

from dreampage_headswap.masking import validate_mask
from dreampage_headswap.utils.images import validate_image


def measurement_float(image: np.ndarray) -> np.ndarray:
    """Normalize to [0,1] in float64. Measurement must not round away a real change.

    `float_image` casts to float32 for model input, where a difference below its
    resolution is irrelevant. Here it would report a changed protected pixel as zero.
    """
    array = validate_image(image)
    return array.astype(np.float64) / (255 if array.dtype == np.uint8 else 1)


def preservation_metrics(template: np.ndarray, output: np.ndarray, mask: np.ndarray) -> dict:
    template, output = validate_image(template), validate_image(output)
    if template.shape != output.shape:
        raise ValueError("Output must have exactly the template dimensions; no implicit benchmark resizing")
    original = validate_mask(mask, template.shape[:2])
    outside = original == 0
    delta = np.abs(measurement_float(output) - measurement_float(template))
    # Exact equality checks use native arrays, before float32 metric normalization.
    changed = np.any(output != template, axis=-1)
    unexpected = changed & outside
    exterior_count = int(outside.sum())
    ring = binary_dilation(original > 0, iterations=2) & ~binary_erosion(original > 0, iterations=2, border_value=0)
    return {
        "outside_mask_mae": float(delta[outside].mean()) if exterior_count else 0.0,
        "outside_mask_max": float(delta[outside].max()) if exterior_count else 0.0,
        "outside_mask_exact": bool(not unexpected.any()),
        "outside_mask_changed_percentage": float(unexpected.sum() * 100 / exterior_count) if exterior_count else 0.0,
        "unexpected_altered_region_percentage": float(unexpected.mean() * 100),
        "outside_mask_pixel_count": exterior_count,
        "outside_mask_perceptual_difference": None,
        "perceptual_metric_available": False,
        "boundary_band_mae": float(delta[ring].mean()) if ring.any() else None,
        "boundary_band_note": "Change magnitude, not a calibrated realism or seam-quality score",
    }


def outside_difference_image(template: np.ndarray, output: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if template.shape != output.shape:
        raise ValueError("Image shapes differ")
    outside = validate_mask(mask, template.shape[:2]) == 0
    return np.abs(measurement_float(template) - measurement_float(output)) * outside[..., None]
