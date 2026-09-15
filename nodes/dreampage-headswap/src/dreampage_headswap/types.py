"""Shared contracts. Image arrays are RGB HWC; model tensors are BCHW in [0, 1]."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import torch


@dataclass
class ChildIdentityInput:
    references: list[np.ndarray]
    age: float | None = None


@dataclass
class TemplateInput:
    image: np.ndarray


@dataclass
class HeadMask:
    """Float HW mask: zero protects; positive values authorize editing."""
    values: np.ndarray
    region: str = "head"


@dataclass(frozen=True)
class CropTransform:
    original_hw: tuple[int, int]
    box_xyxy: tuple[int, int, int, int]
    padding_ltrb: tuple[int, int, int, int]
    model_hw: tuple[int, int]

    @property
    def canvas_hw(self) -> tuple[int, int]:
        x0, y0, x1, y1 = self.box_xyxy
        left, top, right, bottom = self.padding_ltrb
        return y1 - y0 + top + bottom, x1 - x0 + left + right

    @property
    def scale_xy(self) -> tuple[float, float]:
        height, width = self.canvas_hw
        return self.model_hw[1] / width, self.model_hw[0] / height


@dataclass
class MaskSet:
    original: np.ndarray
    generation: np.ndarray
    blend: np.ndarray


@dataclass
class TemplateCrop:
    image: np.ndarray
    mask: np.ndarray
    transform: CropTransform
    masks: MaskSet


@dataclass
class IdentityCondition:
    global_embedding: torch.Tensor
    local_tokens: torch.Tensor
    structure: torch.Tensor


@dataclass
class GeometryCondition:
    """Explicit supplied geometry; missing face estimates must stay unavailable."""
    spatial: torch.Tensor
    vector: torch.Tensor
    measurements: dict[str, Any] = field(default_factory=dict)


@dataclass
class SwapCondition:
    identity: IdentityCondition
    template: torch.Tensor
    mask: torch.Tensor
    geometry: GeometryCondition
    age: torch.Tensor | None = None


@dataclass
class QualityMetrics:
    identity_score: float | None = None
    pose_score: float | None = None
    template_preservation_score: float | None = None
    boundary_score: float | None = None
    face_quality_score: float | None = None
    age_consistency_score: float | None = None
    overall_score: float | None = None
    status: str = "RETRY"
    measurements: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


@dataclass
class SwapOutput:
    image: np.ndarray
    quality: QualityMetrics
    debug: dict[str, Any] = field(default_factory=dict)
