"""Reference preparation for pretrained edit models; no recognition model or training.

Mask-guided cropping removes irrelevant source context without stretching the head.
Each view remains a separate reference token sequence; we never average identities.
"""
from __future__ import annotations

import hashlib
import math
import numpy as np
from scipy.ndimage import laplace

from ..masking import validate_mask
from ..utils.images import float_image, resize_array


def prepare_references(images, masks=None, *, resolution=768, context=1.25,
                       background_strength=0.0):
    if not 1 <= len(images) <= 3:
        raise ValueError("Supply one to three views of the SAME person; split larger sets explicitly")
    if not isinstance(resolution, int) or resolution < 128 or resolution > 1536 or resolution % 32:
        raise ValueError("Reference resolution must be a multiple of 32 in [128,1536]")
    if not np.isfinite(context) or not 1 <= context <= 3:
        raise ValueError("Reference context must be in [1,3]")
    if not np.isfinite(background_strength) or not 0 <= background_strength <= 1:
        raise ValueError("Background suppression must be in [0,1]")
    masks = [None] * len(images) if masks is None else masks
    if len(masks) != len(images):
        raise ValueError("Each reference needs its own corresponding mask or None")
    prepared, reports, seen = [], [], set()
    for index, (image, mask) in enumerate(zip(images, masks)):
        original = float_image(image)
        digest = hashlib.sha256(str(original.shape).encode() + original.tobytes()).hexdigest()
        if digest in seen:
            raise ValueError("Duplicate reference: use a distinct view, not repeated copies of one photo")
        seen.add(digest)
        h, w = original.shape[:2]
        box = (0, 0, w, h)
        pixels = original.copy()
        if mask is not None:
            mask = validate_mask(mask, (h, w))
            yy, xx = np.nonzero(mask > 0)
            if not len(xx):
                raise ValueError(f"Reference {index + 1} headmask is empty")
            cx, cy = (xx.min() + xx.max() + 1) / 2, (yy.min() + yy.max() + 1) / 2
            bw, bh = (xx.max() - xx.min() + 1) * context, (yy.max() - yy.min() + 1) * context
            box = (max(0, math.floor(cx - bw / 2)), max(0, math.floor(cy - bh / 2)),
                   min(w, math.ceil(cx + bw / 2)), min(h, math.ceil(cy + bh / 2)))
            if background_strength:
                alpha = (1 - mask[..., None]) * background_strength
                pixels = pixels * (1 - alpha) + 0.5 * alpha
        x0, y0, x1, y1 = box
        pixels = pixels[y0:y1, x0:x1]
        ph, pw = pixels.shape[:2]
        scale = resolution / max(ph, pw)
        rh, rw = max(1, round(ph * scale)), max(1, round(pw * scale))
        fitted = resize_array(pixels, (rh, rw))
        # Pad to model stride, not to a square. No aspect distortion or center crop.
        th, tw = max(32, math.ceil(rh / 32) * 32), max(32, math.ceil(rw / 32) * 32)
        py, px = (th - rh) // 2, (tw - rw) // 2
        fitted = np.pad(fitted, ((py, th-rh-py), (px, tw-rw-px), (0, 0)), mode="edge")
        prepared.append(fitted.astype(np.float32))
        reports.append({"view": index + 1, "source_hw": [h, w], "crop_xyxy": box,
                        "model_hw": [th, tw], "headmask_supplied": mask is not None,
                        "upsample_factor": round(scale, 3), "source_sha256": digest,
                        "laplacian_variance": float(laplace(pixels.mean(axis=-1)).var()),
                        "warning": "Reference is enlarged more than 2x" if scale > 2 else None})
    return {"images": prepared, "report": {"reference_count": len(prepared), "views": reports,
            "identity_consistency_verified": False, "mode": "separate pretrained visual references",
            "background_strength": float(background_strength)}}


def reference_contact_sheet(images, *, tile_size=256):
    tiles = []
    for pixels in images:
        h, w = pixels.shape[:2]
        scale = tile_size / max(h, w)
        rh, rw = max(1, round(h * scale)), max(1, round(w * scale))
        tile = np.full((tile_size, tile_size, 3), 0.08, np.float32)
        y, x = (tile_size-rh)//2, (tile_size-rw)//2
        tile[y:y+rh, x:x+rw] = resize_array(pixels, (rh, rw))
        tiles.append(tile)
    return np.concatenate(tiles, axis=1)
