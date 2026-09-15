from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from dreampage_headswap.evaluation.metrics import preservation_metrics
from dreampage_headswap.types import QualityMetrics


class QualityProvider(Protocol):
    """Calibrated, licensed model providers can return named scores in [0,1]."""
    def score(self, references: list[np.ndarray], template: np.ndarray, output: np.ndarray,
              mask: np.ndarray, age: float | None) -> dict[str, float | None]: ...


@dataclass(frozen=True)
class QualityConfig:
    threshold: float = 0.8
    required: tuple[str, ...] = ("identity_score", "pose_score", "boundary_score", "face_quality_score")
    weights: dict[str, float] = field(default_factory=lambda: {
        "identity_score": 3.0, "pose_score": 1.0, "boundary_score": 1.0,
        "face_quality_score": 2.0, "template_preservation_score": 3.0, "age_consistency_score": 1.0})

    def __post_init__(self):
        fields = {"identity_score", "pose_score", "boundary_score", "face_quality_score", "template_preservation_score", "age_consistency_score"}
        if not np.isfinite(self.threshold) or not 0 <= self.threshold <= 1:
            raise ValueError("Quality threshold must be in [0,1]")
        if set(self.weights) - fields or set(self.required) - fields:
            raise ValueError("Unknown quality metric")
        if not {"identity_score", "face_quality_score"}.issubset(self.required):
            raise ValueError("A headswap quality gate must require identity_score and face_quality_score")
        if any(not np.isfinite(v) or v < 0 for v in self.weights.values()):
            raise ValueError("Quality weights must be nonnegative and finite")


def evaluate_quality(template: np.ndarray, output: np.ndarray, mask: np.ndarray, *,
                     references: list[np.ndarray] | None = None, age: float | None = None,
                     provider: QualityProvider | None = None, config: QualityConfig | None = None,
                     model_validated: bool = False) -> QualityMetrics:
    config = config or QualityConfig()
    measurements = preservation_metrics(template, output, mask)
    result = QualityMetrics(template_preservation_score=1.0 if measurements["outside_mask_exact"] else 0.0,
                            measurements=measurements)
    if provider is not None:
        values = provider.score(references or [], template, output, mask, age)
        for name, value in values.items():
            if name not in config.weights or name == "template_preservation_score":
                continue
            if value is not None and (not np.isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"Quality provider returned invalid {name}")
            setattr(result, name, value)
    if not measurements["outside_mask_exact"]:
        result.status = "FAIL"
        result.reasons.append("Protected template pixels changed")
        return result
    required = set(config.required)
    if age is not None:
        required.add("age_consistency_score")
    missing = sorted(name for name in required if getattr(result, name) is None)
    if missing:
        result.reasons.append("Uncalibrated or unavailable metrics: " + ", ".join(missing))
    if not model_validated:
        result.reasons.append("Model has not passed a held-out headswap benchmark")
    if missing:
        # Never manufacture a high overall score from preservation alone.
        return result
    available = [(getattr(result, name), weight) for name, weight in config.weights.items()
                 if getattr(result, name) is not None and weight > 0]
    if not available:
        result.reasons.append("No weighted quality measurements")
        return result
    result.overall_score = sum(value * weight for value, weight in available) / sum(weight for _, weight in available)
    low = sorted(name for name in required if getattr(result, name) < config.threshold)
    if low:
        result.reasons.append("Below threshold: " + ", ".join(low))
    result.status = "PASS" if model_validated and not low and result.overall_score >= config.threshold else "RETRY"
    return result
