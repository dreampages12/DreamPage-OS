"""ComfyUI tensor conventions in one place: IMAGE is BHWC float [0,1], MASK is BHW float.

Batches are rejected rather than silently reduced to their first element, and masks are
never inverted or resized implicitly: the supplied headmask is the authority.
"""
from __future__ import annotations

import numpy as np
import torch

# One 8-bit step is 1/255. Anything inside this band is upstream float roundoff and is
# clamped; anything beyond it means a different range or colour space, which is a graph
# wiring mistake worth surfacing rather than silently flattening into a valid image.
RANGE_TOLERANCE = 1e-3


def image_to_array(image) -> np.ndarray:
    """One ComfyUI IMAGE to an RGB HWC float array in [0,1]."""
    if image is None:
        raise ValueError("Missing IMAGE input")
    tensor = image.detach().float().cpu() if hasattr(image, "detach") else torch.as_tensor(image).float()
    if tensor.ndim == 3:
        tensor = tensor[None]
    if tensor.ndim != 4 or tensor.shape[0] != 1 or tensor.shape[-1] not in (3, 4):
        raise ValueError("Expected a single RGB IMAGE; batch this node instead of passing an image batch")
    array = tensor[0, ..., :3].numpy()
    if not np.isfinite(array).all():
        raise ValueError("IMAGE contains non-finite values")
    low, high = float(array.min()), float(array.max())
    if low < -RANGE_TOLERANCE or high > 1 + RANGE_TOLERANCE:
        raise ValueError(f"IMAGE values must lie in [0,1]; received [{low:.6g}, {high:.6g}]. "
                         "Convert the upstream output instead of letting it be clipped here")
    return np.ascontiguousarray(array.clip(0, 1).astype(np.float32))


def images_to_arrays(image) -> list[np.ndarray]:
    """A ComfyUI IMAGE batch to a list of arrays; used for multiple child references."""
    tensor = image.detach().float().cpu() if hasattr(image, "detach") else torch.as_tensor(image).float()
    if tensor.ndim == 3:
        tensor = tensor[None]
    if tensor.ndim != 4 or tensor.shape[-1] not in (3, 4):
        raise ValueError("Expected an IMAGE or IMAGE batch")
    return [image_to_array(tensor[index:index + 1]) for index in range(tensor.shape[0])]


def array_to_image(array: np.ndarray):
    array = np.asarray(array)
    if array.dtype == np.uint8:
        array = array.astype(np.float32) / 255.0
    if array.ndim != 3 or array.shape[-1] != 3:
        raise ValueError("Expected an RGB HWC array")
    return torch.from_numpy(np.ascontiguousarray(array.astype(np.float32)))[None]


def mask_to_array(mask) -> np.ndarray:
    """One ComfyUI MASK to an HW float array in [0,1], white meaning editable."""
    if mask is None:
        raise ValueError("Missing MASK input; this pipeline requires an authoritative headmask")
    tensor = mask.detach().float().cpu() if hasattr(mask, "detach") else torch.as_tensor(mask).float()
    if tensor.ndim == 2:
        tensor = tensor[None]
    if tensor.ndim == 4 and tensor.shape[-1] == 1:
        tensor = tensor[..., 0]
    if tensor.ndim != 3 or tensor.shape[0] != 1:
        raise ValueError("Expected a single MASK; mask batches are not reduced silently")
    array = tensor[0].numpy()
    if not np.isfinite(array).all() or array.min() < 0 or array.max() > 1:
        raise ValueError("MASK must be finite and within [0,1]")
    return np.ascontiguousarray(array.astype(np.float32))


def array_to_mask(array: np.ndarray):
    array = np.asarray(array, dtype=np.float32)
    if array.ndim != 2:
        raise ValueError("Expected an HW mask array")
    # Scene arrays are deliberately read-only. Exposed MASK outputs must own memory
    # so downstream nodes cannot mutate the authority retained in a scene bundle.
    return torch.from_numpy(np.array(array, dtype=np.float32, order="C", copy=True))[None]
