"""Image conventions and lossless output. No implicit orientation or mask rotation."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
import torch
import torch.nn.functional as F


def validate_image(image: np.ndarray) -> np.ndarray:
    a = np.asarray(image)
    if a.ndim != 3 or a.shape[2] != 3 or min(a.shape[:2]) < 1:
        raise ValueError("Expected non-empty RGB HWC image")
    if a.dtype != np.uint8 and not np.issubdtype(a.dtype, np.floating):
        raise TypeError("RGB images must be uint8 or floating point [0,1]")
    if not np.isfinite(a).all():
        raise ValueError("Image contains non-finite values")
    if a.dtype != np.uint8 and (a.min() < 0 or a.max() > 1):
        raise ValueError("Floating point images must be in [0,1]")
    return a


def float_image(image: np.ndarray) -> np.ndarray:
    a = validate_image(image)
    return a.astype(np.float32) / 255 if a.dtype == np.uint8 else a.astype(np.float32)


def to_tensor(image: np.ndarray, device: str | torch.device = "cpu") -> torch.Tensor:
    return torch.from_numpy(np.ascontiguousarray(float_image(image))).permute(2, 0, 1).unsqueeze(0).to(device)


def from_tensor(image: torch.Tensor) -> np.ndarray:
    if image.ndim != 4 or image.shape[0] != 1 or image.shape[1] != 3:
        raise ValueError("Expected one BCHW RGB image")
    out = image.detach().float().cpu().squeeze(0).permute(1, 2, 0).numpy()
    return validate_image(out)


def resize_array(array: np.ndarray, hw: tuple[int, int], *, mask: bool = False) -> np.ndarray:
    a = np.asarray(array, dtype=np.float32)
    if min(hw) < 1:
        raise ValueError("Resize dimensions must be positive")
    t = torch.from_numpy(np.ascontiguousarray(a))
    t = t[None, None] if a.ndim == 2 else t.permute(2, 0, 1)[None]
    if mask:
        out = F.interpolate(t, size=hw, mode="nearest-exact")
    else:
        out = F.interpolate(t, size=hw, mode="bilinear", align_corners=False, antialias=True)
    result = out[0, 0].numpy() if a.ndim == 2 else out[0].permute(1, 2, 0).numpy()
    # Positive interpolation weights should stay within the input range; fp32
    # accumulation can overshoot saturated white by ~1e-7. Clamp internal roundoff.
    return np.clip(result, a.min(), a.max())


def load_rgb(path: str | Path, *, orient: bool = False) -> np.ndarray:
    """Templates/masks are already co-registered; orient only standalone references."""
    with Image.open(path) as image:
        if orient:
            image = ImageOps.exif_transpose(image)
        return np.array(image.convert("RGB"))


def save_rgb(path: str | Path, image: np.ndarray) -> None:
    path = Path(path)
    if path.suffix.lower() != ".png":
        raise ValueError("Use lossless .png for pixel-preserving output")
    a = validate_image(image)
    if a.dtype != np.uint8:
        a = np.rint(a * 255).astype(np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(a).save(path)
