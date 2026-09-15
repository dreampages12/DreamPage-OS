"""Where an enrolled capture's headmask comes from, and what it is allowed to claim.

Every capture needs a headmask before it can become a training target. This module is the
single place that decides how one is obtained, because that decision carries two risks that
are easy to hide:

* **Rights.** A segmentation model's repository licence is not its weights' licence. Several
  popular face-parsing checkpoints carry an MIT repository while their weights were trained on
  a dataset whose terms forbid commercial use of derived data. A provider therefore has to
  state its licence, and an unstated one is refused.
* **Authority.** A mask drawn from a bounding box is a coarse geometric stand-in, not the
  carefully prepared production mask the pipeline treats as authoritative. Providers record
  what they produced, so a corpus can be counted and a coarse mask is never quietly promoted.

The default provider produces nothing and says why. That is deliberate: an invented mask is
worse than a missing one, because the missing one stops the run.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

import numpy as np

from ..masking import load_headmask, validate_mask

# A mask this provider drew itself, versus one a person prepared and reviewed.
AUTHORITY_LEVELS = ("reviewed_external", "derived_geometric", "derived_model")


@dataclass(frozen=True)
class MaskResult:
    """A mask plus the provenance needed to audit it later."""

    values: np.ndarray | None
    provider: str
    authority: str | None = None
    license: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self):
        if self.values is None:
            if not self.reason:
                raise ValueError("A provider that returns no mask must give a reason")
            return
        validate_mask(self.values)
        if self.authority not in AUTHORITY_LEVELS:
            raise ValueError(f"authority must be one of {AUTHORITY_LEVELS}")
        if not self.license or not str(self.license).strip():
            raise ValueError("A produced mask must carry the licence of whatever produced it")

    def as_metadata(self) -> dict[str, Any]:
        return {"provider": self.provider, "authority": self.authority, "license": self.license,
                **(self.metadata or {})}


class HeadMaskProvider(Protocol):
    name: str

    def mask(self, image: np.ndarray, metadata: dict[str, Any]) -> MaskResult:
        """Return a mask for this capture, or a MaskResult explaining why there is none."""
        ...


class UnavailableMaskProvider:
    """The default. Produces nothing, so enrolment fails loudly instead of inventing masks."""

    name = "unavailable"

    def mask(self, image: np.ndarray, metadata: dict[str, Any]) -> MaskResult:
        return MaskResult(None, self.name,
                          reason="No headmask provider configured; supply reviewed masks or choose one explicitly")


class SidecarMaskProvider:
    """Reviewed masks that already exist next to the image. The preferred source.

    A human prepared it, so it is the only provider that claims reviewed authority.
    """

    name = "sidecar_file"

    def __init__(self, suffix: str = "_mask.png", channel: str = "luminance",
                 license: str = "Owned by the enrolling organization with the capture"):
        self.suffix, self.channel, self.license = suffix, channel, license

    def path_for(self, image_path: str | Path) -> Path:
        path = Path(image_path)
        return path.with_name(path.stem + self.suffix)

    def mask(self, image: np.ndarray, metadata: dict[str, Any]) -> MaskResult:
        source = metadata.get("headmask_path") or (self.path_for(metadata["path"]) if metadata.get("path") else None)
        if not source or not Path(source).is_file():
            return MaskResult(None, self.name, reason=f"No reviewed mask found at {source}")
        values = load_headmask(source, channel=metadata.get("mask_channel", self.channel)).values
        if values.shape != image.shape[:2]:
            return MaskResult(None, self.name, reason="Reviewed mask does not match the capture's dimensions")
        if not values.any() or np.all(values > 0):
            return MaskResult(None, self.name, reason="Reviewed mask is empty or covers the whole frame")
        return MaskResult(values, self.name, authority="reviewed_external", license=self.license,
                          metadata={"path": str(source)})


class SuppliedBoxMaskProvider:
    """An ellipse or rectangle from a head box that the caller supplies.

    The box is supplied, never estimated here, so this introduces no detection weights and no
    rights question of its own. What it does introduce is imprecision: a head is not an
    ellipse, and hair, ears and chin will be cut or over-covered at the boundary. Good enough
    to bootstrap enrolment and to train on, clearly not good enough to be the authoritative
    mask on a printed page. Masks are marked `derived_geometric` so a corpus report can count
    how much of it was never reviewed by a person.
    """

    name = "supplied_box_geometry"

    def __init__(self, shape: str = "ellipse", padding: float = 0.08, feather: float = 0.0):
        if shape not in ("ellipse", "rectangle"):
            raise ValueError("shape must be ellipse or rectangle")
        if not np.isfinite(padding) or not -0.5 <= padding <= 1.0:
            raise ValueError("padding must be a finite fraction in [-0.5,1]")
        if not np.isfinite(feather) or feather < 0:
            raise ValueError("feather must be a nonnegative number of pixels")
        self.shape, self.padding, self.feather = shape, float(padding), float(feather)

    def mask(self, image: np.ndarray, metadata: dict[str, Any]) -> MaskResult:
        box = metadata.get("head_bbox") or metadata.get("face_bbox")
        if box is None:
            return MaskResult(None, self.name, reason="No supplied head_bbox or face_bbox for this capture")
        values = box_mask(image.shape[:2], box, shape=self.shape, padding=self.padding, feather=self.feather)
        if not values.any():
            return MaskResult(None, self.name, reason="Supplied box lies outside the capture")
        return MaskResult(values, self.name, authority="derived_geometric",
                          license="Project-owned geometry from an operator-supplied box",
                          metadata={"shape": self.shape, "padding": self.padding, "box": list(box),
                                    "note": "Coarse geometric approximation, not a reviewed production mask"})


class CallableMaskProvider:
    """Wrap a licensed segmentation model the operator supplies and has checked.

    The licence string is mandatory and is recorded per capture, because the whole point is to
    make a later audit able to answer "what produced this mask, and were we allowed to use it".
    Nothing is downloaded here and no model is chosen for you.
    """

    def __init__(self, function: Callable[[np.ndarray, dict], np.ndarray | None], *, name: str,
                 license: str, authority: str = "derived_model"):
        if not name or not str(license).strip():
            raise ValueError("A model-backed provider must name itself and state its weights' licence")
        if authority not in AUTHORITY_LEVELS:
            raise ValueError(f"authority must be one of {AUTHORITY_LEVELS}")
        self.function, self.name, self.license, self.authority = function, name, license, authority

    def mask(self, image: np.ndarray, metadata: dict[str, Any]) -> MaskResult:
        values = self.function(image, metadata)
        if values is None:
            return MaskResult(None, self.name, reason="Provider returned no mask for this capture")
        values = validate_mask(np.asarray(values, dtype=np.float32))
        if values.shape != image.shape[:2]:
            return MaskResult(None, self.name, reason="Provider mask does not match the capture's dimensions")
        if not values.any() or np.all(values > 0):
            return MaskResult(None, self.name, reason="Provider mask is empty or covers the whole frame")
        return MaskResult(values, self.name, authority=self.authority, license=self.license)


class FirstAvailableProvider:
    """Try reviewed masks first, then fall back. Records which one actually produced each mask."""

    def __init__(self, *providers: HeadMaskProvider):
        if not providers:
            raise ValueError("Supply at least one provider")
        self.providers = providers
        self.name = "first_available(" + ", ".join(provider.name for provider in providers) + ")"

    def mask(self, image: np.ndarray, metadata: dict[str, Any]) -> MaskResult:
        reasons = []
        for provider in self.providers:
            result = provider.mask(image, metadata)
            if result.values is not None:
                return result
            reasons.append(f"{provider.name}: {result.reason}")
        return MaskResult(None, self.name, reason="; ".join(reasons))


def box_mask(hw: tuple[int, int], box, *, shape: str = "ellipse", padding: float = 0.0,
             feather: float = 0.0) -> np.ndarray:
    """Rasterize a supplied xyxy box as a float mask, clipped to the image."""
    height, width = hw
    if height < 1 or width < 1:
        raise ValueError("Image dimensions must be positive")
    values = np.asarray(box, dtype=np.float64)
    if values.shape != (4,) or not np.isfinite(values).all():
        raise ValueError("Box must be four finite xyxy values")
    x0, y0, x1, y1 = values
    if x1 <= x0 or y1 <= y0:
        raise ValueError("Box must have positive width and height")
    grow_x, grow_y = (x1 - x0) * padding, (y1 - y0) * padding
    x0, x1, y0, y1 = x0 - grow_x, x1 + grow_x, y0 - grow_y, y1 + grow_y
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float64)
    yy, xx = yy + 0.5, xx + 0.5
    if shape == "rectangle":
        inside = (xx >= x0) & (xx <= x1) & (yy >= y0) & (yy <= y1)
    else:
        center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
        radius_x, radius_y = max((x1 - x0) / 2, 1e-6), max((y1 - y0) / 2, 1e-6)
        inside = ((xx - center_x) / radius_x) ** 2 + ((yy - center_y) / radius_y) ** 2 <= 1
    mask = inside.astype(np.float32)
    if feather > 0 and mask.any():
        from scipy.ndimage import distance_transform_edt
        distance = distance_transform_edt(np.pad(mask > 0, 1))[1:-1, 1:-1]
        mask = np.clip(distance / (feather + 1), 0, 1).astype(np.float32) * mask
    return mask


def build_provider(name: str, **options) -> HeadMaskProvider:
    """Named providers for command line use. Model-backed providers stay code-only on purpose."""
    if name in ("none", "unavailable"):
        return UnavailableMaskProvider()
    if name == "sidecar":
        return SidecarMaskProvider(**options)
    if name == "supplied-box":
        return SuppliedBoxMaskProvider(**options)
    if name == "sidecar-then-box":
        geometry = {key: options[key] for key in ("shape", "padding", "feather") if key in options}
        sidecar = {key: options[key] for key in ("suffix", "channel") if key in options}
        return FirstAvailableProvider(SidecarMaskProvider(**sidecar), SuppliedBoxMaskProvider(**geometry))
    raise ValueError(f"Unknown headmask provider {name!r}; a model-backed provider is wired in code "
                     "with CallableMaskProvider so its licence is stated explicitly")
