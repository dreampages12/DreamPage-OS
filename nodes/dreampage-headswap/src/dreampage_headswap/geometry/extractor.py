"""Geometry provider contract and a weights-free mask/context baseline.

This baseline does not infer face landmarks, expression, pose, gaze, or lighting direction.
Supplied measurements can be used; pretrained licensed providers may implement the protocol.
"""
from __future__ import annotations

from typing import Any, Protocol

import torch

from dreampage_headswap.types import GeometryCondition


class GeometryExtractor(Protocol):
    def extract(self, template: torch.Tensor, mask: torch.Tensor,
                metadata: dict[str, Any] | None = None) -> GeometryCondition: ...


class MaskContextGeometry:
    """4 spatial channels + 16-vector; RGB inside the mask is never read into context."""
    def extract(self, template: torch.Tensor, mask: torch.Tensor,
                metadata: dict[str, Any] | None = None) -> GeometryCondition:
        if template.ndim != 4 or template.shape[1] != 3 or mask.shape != (template.shape[0], 1, *template.shape[2:]):
            raise ValueError("Geometry expects template B3HW and mask B1HW")
        if not torch.isfinite(template).all() or not torch.isfinite(mask).all() or torch.any((mask < 0) | (mask > 1)):
            raise ValueError("Invalid geometry image/mask")
        b, _, h, w = template.shape
        metadata = metadata or {}
        yy, xx = torch.meshgrid(torch.linspace(-1, 1, h, device=template.device, dtype=template.dtype),
                                torch.linspace(-1, 1, w, device=template.device, dtype=template.dtype), indexing="ij")
        outside = (mask == 0).to(template.dtype)
        luminance = (template * template.new_tensor([0.2126, 0.7152, 0.0722])[None, :, None, None]).sum(1, keepdim=True) * outside
        spatial = torch.cat([xx[None, None].expand(b, 1, h, w) * mask,
                             yy[None, None].expand(b, 1, h, w) * mask, mask, luminance], dim=1)
        vector = template.new_zeros((b, 16))
        for i in range(b):
            points = torch.nonzero(mask[i, 0] > 0)
            if len(points):
                low, high = points.amin(0), points.amax(0) + 1
                vector[i, :4] = torch.stack([(low[1] + high[1]) / (2 * w), (low[0] + high[0]) / (2 * h),
                                             (high[1] - low[1]) / w, (high[0] - low[0]) / h])
        count = outside.sum((2, 3))
        vector[:, 4:7] = (template * outside).sum((2, 3)) / count.clamp_min(1)
        vector[:, 7] = (count[:, 0] > 0).to(template.dtype)
        keys = ("yaw", "pitch", "roll", "gaze_x", "gaze_y", "eye_openness", "mouth_openness")
        supplied = {}
        for j, key in enumerate(keys, start=8):
            if key in metadata:
                value = template.new_tensor(metadata[key])
                if value.numel() not in (1, b) or not torch.isfinite(value).all():
                    raise ValueError(f"Invalid supplied geometry {key}")
                normalized = value / 180 if key in {"yaw", "pitch", "roll"} else value
                vector[:, j] = normalized.reshape(-1)
                supplied[key] = metadata[key]
        # A single flag means complete face metadata. Partial availability stays in measurements.
        vector[:, 15] = float(all(k in metadata for k in keys))
        measurements = {"provider": "mask_context", "face_geometry_available": bool(supplied),
                        "available_fields": list(supplied), "supplied": supplied,
                        "landmarks": metadata.get("landmarks"), "pose_estimated": False,
                        "lighting_direction": None}
        return GeometryCondition(spatial, vector, measurements)
