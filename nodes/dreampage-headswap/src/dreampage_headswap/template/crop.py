"""Exact integer crop/padding metadata and center-aligned pixel transforms."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from dreampage_headswap.masking import validate_mask
from dreampage_headswap.types import CropTransform, MaskSet, TemplateCrop
from dreampage_headswap.utils.images import float_image, resize_array, validate_image


@dataclass(frozen=True)
class CropConfig:
    resolution: int | tuple[int, int] = 512
    context: float = 1.5
    min_side: int = 16

    def __post_init__(self):
        hw = (self.resolution, self.resolution) if isinstance(self.resolution, int) else self.resolution
        if len(hw) != 2 or any(not isinstance(v, int) or v < 8 or v > 4096 for v in hw):
            raise ValueError("Model crop dimensions must be integers in [8,4096]")
        if not np.isfinite(self.context) or not 1 <= self.context <= 8:
            raise ValueError("Context factor must be in [1,8]")
        if self.min_side < 1:
            raise ValueError("min_side must be positive")

    @property
    def model_hw(self) -> tuple[int, int]:
        return (self.resolution, self.resolution) if isinstance(self.resolution, int) else tuple(self.resolution)


def extract_crop(template: np.ndarray, masks: MaskSet, config: CropConfig | None = None) -> TemplateCrop:
    config = config or CropConfig()
    template = validate_image(template)
    h, w = template.shape[:2]
    generation = validate_mask(masks.generation, (h, w))
    validate_mask(masks.original, (h, w))
    validate_mask(masks.blend, (h, w))
    yy, xx = np.nonzero((generation > 0) | (masks.original > 0))
    if not len(xx):
        raise ValueError("Cannot crop an empty mask; pipeline should return original unchanged")
    bx0, bx1 = int(xx.min()), int(xx.max()) + 1
    by0, by1 = int(yy.min()), int(yy.max()) + 1
    target_h, target_w = config.model_hw
    aspect = target_w / target_h
    crop_w = max((bx1 - bx0) * config.context, config.min_side)
    crop_h = max((by1 - by0) * config.context, config.min_side)
    crop_w = max(crop_w, crop_h * aspect)
    crop_h = max(crop_h, crop_w / aspect)
    cw, ch = math.ceil(crop_w), math.ceil(crop_h)
    rx0 = math.floor((bx0 + bx1 - cw) / 2)
    ry0 = math.floor((by0 + by1 - ch) / 2)
    rx1, ry1 = rx0 + cw, ry0 + ch
    x0, y0, x1, y1 = max(0, rx0), max(0, ry0), min(w, rx1), min(h, ry1)
    padding = (x0 - rx0, y0 - ry0, rx1 - x1, ry1 - y1)
    left, top, right, bottom = padding
    image = np.pad(float_image(template)[y0:y1, x0:x1], ((top, bottom), (left, right), (0, 0)), mode="edge")
    mask = np.pad(generation[y0:y1, x0:x1], ((top, bottom), (left, right)), mode="constant")
    transform = CropTransform((h, w), (x0, y0, x1, y1), padding, config.model_hw)
    return TemplateCrop(resize_array(image, config.model_hw), resize_array(mask, config.model_hw, mask=True), transform, masks)


def restore_crop(generated: np.ndarray, transform: CropTransform) -> np.ndarray:
    """Restore only the valid rectangular crop, not an interpolated full page."""
    generated = float_image(generated)
    if generated.shape[:2] != transform.model_hw:
        raise ValueError(f"Generated shape {generated.shape[:2]} differs from model crop {transform.model_hw}")
    restored = resize_array(generated, transform.canvas_hw)
    left, top, _, _ = transform.padding_ltrb
    x0, y0, x1, y1 = transform.box_xyxy
    return restored[top:top + y1 - y0, left:left + x1 - x0]


def transform_mask_to_crop(mask: np.ndarray, transform: CropTransform) -> np.ndarray:
    """Apply an existing crop transform to another co-registered mask."""
    mask = validate_mask(mask, transform.original_hw)
    x0, y0, x1, y1 = transform.box_xyxy
    left, top, right, bottom = transform.padding_ltrb
    canvas = np.pad(mask[y0:y1, x0:x1], ((top, bottom), (left, right)))
    return resize_array(canvas, transform.model_hw, mask=True)


def map_points_to_model(points_xy: np.ndarray, transform: CropTransform) -> np.ndarray:
    points = np.asarray(points_xy, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise ValueError("Points must be finite Nx2 xy coordinates")
    x0, y0, _, _ = transform.box_xyxy
    left, top, _, _ = transform.padding_ltrb
    # Pixel centers, matching interpolate(..., align_corners=False).
    return (points - [x0 - left, y0 - top] + 0.5) * transform.scale_xy - 0.5


def map_points_to_original(points_xy: np.ndarray, transform: CropTransform) -> np.ndarray:
    points = np.asarray(points_xy, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise ValueError("Points must be finite Nx2 xy coordinates")
    x0, y0, _, _ = transform.box_xyxy
    left, top, _, _ = transform.padding_ltrb
    return (points + 0.5) / transform.scale_xy - 0.5 + [x0 - left, y0 - top]
