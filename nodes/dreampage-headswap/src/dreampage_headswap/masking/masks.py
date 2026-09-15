"""The supplied mask is the authority. Generation context never expands write permission."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, maximum_filter, minimum_filter

from dreampage_headswap.types import HeadMask, MaskSet


@dataclass(frozen=True)
class MaskConfig:
    expand: int = 0
    feather: float = 0.0

    def __post_init__(self):
        if not isinstance(self.expand, int) or abs(self.expand) > 512:
            raise ValueError("Mask expand must be an integer from -512 to 512 pixels")
        if not np.isfinite(self.feather) or not 0 <= self.feather <= 512:
            raise ValueError("Mask feather must be between 0 and 512 pixels")


def validate_mask(mask: np.ndarray | HeadMask, hw: tuple[int, int] | None = None) -> np.ndarray:
    a = np.asarray(mask.values if isinstance(mask, HeadMask) else mask)
    if a.ndim != 2 or min(a.shape) < 1:
        raise ValueError("Headmask must be a non-empty HW array; channel must be explicit")
    if hw is not None and a.shape != hw:
        raise ValueError(f"Headmask shape {a.shape} does not match template {hw}; resize explicitly")
    if a.dtype.kind not in "bufi" or not np.isfinite(a).all() or a.min() < 0 or a.max() > 1:
        raise ValueError("Headmask must contain finite values in [0,1], with white editable")
    converted = a.astype(np.float32)
    if np.any((a > 0) & (converted == 0)):
        raise ValueError("Headmask positive values underflow float32; normalize explicitly")
    return converted.copy()


def load_headmask(path: str | Path, *, channel: str = "luminance", region: str = "head") -> HeadMask:
    """No ComfyUI alpha inversion. Explicit red supports the legacy workflow's red masks."""
    if region not in {"face-only", "head", "head+margin"}:
        raise ValueError("Unknown headmask region")
    with Image.open(path) as image:
        if channel == "luminance":
            if image.mode.startswith("I"):
                raise ValueError("16/32-bit masks require explicit normalization before loading")
            a = np.array(image.convert("L"), dtype=np.float32) / 255
        elif channel in {"red", "green", "blue"}:
            a = np.array(image.convert("RGB"), dtype=np.float32)[..., {"red": 0, "green": 1, "blue": 2}[channel]] / 255
        elif channel == "alpha":
            if "A" not in image.getbands():
                raise ValueError("Mask has no alpha channel")
            a = np.array(image.getchannel("A"), dtype=np.float32) / 255
        else:
            raise ValueError("Mask channel must be luminance, red, green, blue, or alpha")
    return HeadMask(validate_mask(a), region)


def process_mask(mask: np.ndarray | HeadMask, config: MaskConfig | None = None) -> MaskSet:
    config = config or MaskConfig()
    original = validate_mask(mask)
    radius = config.expand
    if radius > 0:
        generation = maximum_filter(original, size=2 * radius + 1, mode="constant", cval=0)
    elif radius < 0:
        generation = minimum_filter(original, size=2 * abs(radius) + 1, mode="constant", cval=0)
    else:
        generation = original.copy()
    blend = np.minimum(original, generation)
    if config.feather > 0:
        # Distance is evaluated inside the authorized support, including image edges.
        distance = distance_transform_edt(np.pad(blend > 0, 1))[1:-1, 1:-1]
        blend *= np.clip(distance / (config.feather + 1), 0, 1).astype(np.float32)
    blend[original == 0] = 0
    return MaskSet(original, generation.astype(np.float32), blend.astype(np.float32))
