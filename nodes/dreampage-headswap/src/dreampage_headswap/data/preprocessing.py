"""CPU integrity/quality checks plus explicit optional learned annotation providers."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image

from .records import IdentityRecord, ImageRecord, file_sha256


class AnnotationProvider(Protocol):
    """Licensed face/head detection, landmarks, pose and segmentation implementations."""
    name: str

    def annotate(self, image: np.ndarray) -> dict[str, Any]:
        """Return values, availability, checkpoint and calibration/provenance metadata."""
        ...


class UnavailableAnnotationProvider:
    name = "unavailable_no_reviewed_weights"

    def annotate(self, image: np.ndarray) -> dict[str, Any]:
        return {"provider": self.name, "available": False, "face_bbox": None,
                "head_bbox": None, "landmarks": None, "yaw": None, "pitch": None,
                "roll": None, "expression": None, "segmentation": None,
                "reason": "No licensed, calibrated annotation provider configured"}


@dataclass(frozen=True)
class PreprocessConfig:
    min_width: int = 64
    min_height: int = 64
    min_laplacian_variance: float = 20.0
    require_headmask: bool = True
    mask_channel: str = "red"


def decoded_pixel_sha256(path: str | Path) -> str:
    with Image.open(path) as image:
        array = np.asarray(image.convert("RGB"))
    digest = hashlib.sha256(str(array.shape).encode())
    digest.update(array.tobytes())
    return digest.hexdigest()


def inspect_image(path: str | Path, config: PreprocessConfig | None = None) -> dict[str, Any]:
    config = config or PreprocessConfig()
    if config.min_width < 3 or config.min_height < 3 or config.min_laplacian_variance < 0:
        raise ValueError("Quality thresholds require dimensions >=3 and nonnegative blur threshold")
    path = Path(path)
    result: dict[str, Any] = {"path": str(path), "accepted": False, "reasons": []}
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            if image.getexif().get(274, 1) != 1:
                result["reasons"].append("noncanonical_exif_orientation_normalize_before_annotation")
            rgb = np.asarray(image.convert("RGB"))
        height, width = rgb.shape[:2]
        gray = np.asarray(Image.fromarray(rgb).convert("L"), dtype=np.float32)
        if min(height, width) >= 3:
            laplacian = gray[1:-1, :-2] + gray[1:-1, 2:] + gray[:-2, 1:-1] + gray[2:, 1:-1] - 4 * gray[1:-1, 1:-1]
            blur = float(laplacian.var())
        else:
            blur = 0.0
        result.update(width=width, height=height, resolution=[width, height],
                      sha256=file_sha256(path), pixel_sha256=decoded_pixel_sha256(path),
                      laplacian_variance=blur)
        if width < config.min_width or height < config.min_height:
            result["reasons"].append("below_minimum_resolution")
        if blur < config.min_laplacian_variance:
            result["reasons"].append("below_configured_blur_threshold")
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        result["reasons"].append(f"image_integrity_error:{type(error).__name__}")
    result["accepted"] = not result["reasons"]
    return result


def inspect_mask(path: Path, image_size: tuple[int, int], *, channel: str = "red") -> dict[str, Any]:
    try:
        from ..masking import load_headmask
        with Image.open(path) as mask:
            mask.load()
            if mask.size != image_size:
                raise ValueError("mask_resolution_mismatch")
            if mask.getexif().get(274, 1) != 1:
                raise ValueError("noncanonical_mask_orientation")
            values = load_headmask(path, channel=channel).values
            if not np.any(values):
                raise ValueError("empty_headmask")
            if np.all(values > 0):
                raise ValueError("headmask_has_no_protected_pixels")
        return {"available": True, "path": str(path), "sha256": file_sha256(path),
                "editable_fraction": float(np.mean(values > 0)), "source": "externally_supplied", "channel": channel}
    except (OSError, ValueError) as error:
        return {"available": False, "path": str(path), "reason": str(error)}


def preprocess_identities(identities: list[IdentityRecord], config: PreprocessConfig | None = None,
                          provider: AnnotationProvider | None = None) -> tuple[list[IdentityRecord], dict]:
    config, provider = config or PreprocessConfig(), provider or UnavailableAnnotationProvider()
    report: dict[str, Any] = {"schema_version": 1, "provider": provider.name, "images": [],
                             "identities_rejected": [], "duplicate_policy": "reject_all_exact_duplicates"}
    inspected: list[tuple[IdentityRecord, ImageRecord, dict]] = []
    groups: dict[str, list[dict]] = {}
    for identity in sorted(identities, key=lambda item: item.identity_id):
        for record in sorted(identity.images, key=lambda item: item.image_id):
            result = inspect_image(record.path, config)
            result.update(identity_id=identity.identity_id, image_id=record.image_id)
            if "pixel_sha256" in result:
                groups.setdefault(result["pixel_sha256"], []).append(result)
            if "resolution" in result:
                result["headmask"] = inspect_mask(record.headmask, tuple(result["resolution"]),
                                                 channel=record.metadata.get("mask_channel", config.mask_channel)) if record.headmask else {
                    "available": False, "reason": "No authoritative headmask supplied"}
                if config.require_headmask and not result["headmask"]["available"]:
                    result["reasons"].append("missing_or_invalid_authoritative_headmask")
            inspected.append((identity, record, result))
    for duplicates in groups.values():
        if len(duplicates) > 1:
            for result in duplicates:
                result["reasons"].append("exact_duplicate_capture")
    accepted: dict[str, list[ImageRecord]] = {}
    for identity, record, result in inspected:
        result["accepted"] = not result["reasons"]
        if result["accepted"]:
            with Image.open(record.path) as image:
                annotations = provider.annotate(np.asarray(image.convert("RGB")))
            result["annotations"] = annotations
            metadata = {**record.metadata, "quality": {key: result[key] for key in (
                "width", "height", "sha256", "pixel_sha256", "laplacian_variance")},
                "annotations": annotations, "mask_channel": record.metadata.get("mask_channel", config.mask_channel)}
            accepted_mask = record.headmask if result.get("headmask", {}).get("available") else None
            accepted.setdefault(identity.identity_id, []).append(ImageRecord(record.image_id, record.path, accepted_mask, metadata))
        report["images"].append(result)
    output = []
    for identity in identities:
        images = accepted.get(identity.identity_id, [])
        if len(images) >= 2:
            output.append(IdentityRecord(identity.identity_id, images, identity.rights, identity.split, identity.age, identity.synthetic))
        else:
            report["identities_rejected"].append({"identity_id": identity.identity_id, "reason": "fewer_than_two_accepted_captures"})
    report["accepted_identity_count"] = len(output)
    report["accepted_image_count"] = sum(len(identity.images) for identity in output)
    return output, report


def identity_to_dict(identity: IdentityRecord) -> dict:
    row = {"identity_id": identity.identity_id, "rights": identity.rights, "synthetic": identity.synthetic,
           "images": [{"image_id": image.image_id, "path": str(image.path),
                       **({"headmask": str(image.headmask)} if image.headmask else {}), **image.metadata}
                      for image in identity.images]}
    if identity.split:
        row["split"] = identity.split
    if identity.age is not None:
        row["age"] = identity.age
    return row
