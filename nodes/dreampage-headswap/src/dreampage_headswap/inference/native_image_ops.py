"""Inference-only image operations for native ComfyUI FLUX reference editing.

These are deterministic compositing heuristics, not learned identity/quality models.
The retained template and external mask remain authoritative throughout the graph.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json

import numpy as np
from scipy.ndimage import binary_dilation, binary_erosion, distance_transform_edt, gaussian_filter, sobel

from ..compositing import composite_to_template
from ..evaluation.metrics import measurement_float, preservation_metrics
from ..masking import MaskConfig, process_mask, validate_mask
from ..template import CropConfig, extract_crop
from ..template.crop import transform_mask_to_crop
from ..template.degradation import prepare_condition_crop
from ..types import MaskSet
from ..utils.images import float_image, validate_image


def _bounded_number(name, value, low, high):
    if isinstance(value, (bool, np.bool_)) or not np.isscalar(value):
        raise ValueError(f"{name} must be a finite number in [{low},{high}]")
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number in [{low},{high}]") from exc
    if not np.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be a finite number in [{low},{high}]")
    return value


def edge_adaptive_masks(template, authority, expand=0, feather=8.0, edge_protection=0.65):
    """Return masks with inward feathering that becomes firmer at visible edges.

    A smoothed luminance gradient modulates only the final blend, never the external
    authority or generation support. This can retain sharper hair boundaries, but
    a strong scene edge is not necessarily hair and no segmentation is inferred.
    Feather and expansion are measured in original-template pixels.
    """
    image = float_image(template)
    original = validate_mask(authority, image.shape[:2])
    feather = _bounded_number("feather", feather, 0, 512)
    protection = _bounded_number("edge_protection", edge_protection, 0, 1)
    masks = process_mask(original, MaskConfig(expand=expand, feather=0))
    active = masks.blend > 0
    if feather > 0 and active.any():
        distance = distance_transform_edt(np.pad(active, 1))[1:-1, 1:-1]
        weight = np.clip(distance / (feather + 1.0), 0, 1).astype(np.float32)
        if protection > 0:
            luminance = image @ np.array([0.2126, 0.7152, 0.0722], np.float32)
            smooth = gaussian_filter(luminance, sigma=0.65, mode="nearest")
            gradient = np.hypot(sobel(smooth, axis=0, mode="nearest"),
                                sobel(smooth, axis=1, mode="nearest"))
            boundary = active & (distance <= feather + 1.0)
            positive = gradient[boundary & (gradient > 1e-6)]
            scale = max(float(np.percentile(positive, 90)) if positive.size else 0.0, 0.05)
            edge = np.clip(gradient / scale, 0, 1)
            weight += protection * edge * (1.0 - weight)
        blend = np.minimum(masks.blend * weight, original).astype(np.float32)
        blend[original == 0] = 0
        masks = MaskSet(masks.original, masks.generation, blend)
    report = {
        "method": "inward_distance_feather_with_luminance_edges",
        "heuristic_only": True,
        "hair_segmentation_available": False,
        "feather_native_pixels": feather,
        "expand_native_pixels": expand,
        "edge_protection": protection,
        "editable_pixel_count": int(np.count_nonzero(original)),
        "generation_pixel_count": int(np.count_nonzero(masks.generation)),
        "blend_within_supplied_authority": bool(np.all(masks.blend <= original)),
        "note": "Visible edges firm up the inward blend; this is not a learned hair or quality score.",
    }
    return masks, report


def _scene_binding(template, crop):
    digest = hashlib.sha256()
    for value in (template, crop.image, crop.mask, crop.masks.original,
                  crop.masks.generation, crop.masks.blend):
        array = np.asarray(value)
        digest.update(str((array.shape, array.dtype.str)).encode("ascii"))
        digest.update(np.ascontiguousarray(array).tobytes())
    digest.update(json.dumps(asdict(crop.transform), sort_keys=True).encode("ascii"))
    return digest.hexdigest()


def prepare_native_scene(template, mask, resolution=1024, context=1.5, expand=0,
                         feather=8.0, edge_protection=0.65, scene_mode="original"):
    """Bind the full template, exact crop and masks for native pretrained editing.

    ``safe_anchor`` always suppresses native target RGB before padding and resizing.
    ``scene_reference`` may retain the target head for pose/expression context when
    the operator selects original or blur; the report makes this tradeoff explicit.
    """
    if scene_mode not in {"original", "blur", "neutral"}:
        raise ValueError("scene_mode must be original, blur, or neutral")
    crop_config = CropConfig(resolution=resolution, context=context)
    if any(size % 32 != 0 for size in crop_config.model_hw):
        raise ValueError("Native FLUX crop dimensions must be multiples of 32")
    base = validate_image(template).copy()
    masks, mask_report = edge_adaptive_masks(base, mask, expand, feather, edge_protection)
    if not masks.original.any():
        raise ValueError("Empty headmask: no authorized head region to prepare")
    if not masks.generation.any():
        raise ValueError("Mask contraction removed the entire generation region")
    crop = extract_crop(base, masks, crop_config)
    if not crop.mask.any():
        raise ValueError("Generation region vanished at crop resolution; enlarge mask or resolution")
    safe_anchor = prepare_condition_crop(base, crop, "neutral")
    scene_reference = (crop.image.copy() if scene_mode == "original" else
                       safe_anchor.copy() if scene_mode == "neutral" else
                       prepare_condition_crop(base, crop, "blur"))
    # Cached graph objects must not acquire edits from downstream array operations.
    for array in (base, crop.image, crop.mask, masks.original, masks.generation,
                  masks.blend, safe_anchor, scene_reference):
        array.setflags(write=False)
    binding = _scene_binding(base, crop)
    report = {
        "crop_transform": asdict(crop.transform),
        "scene_mode": scene_mode,
        "safe_anchor_mode": "neutral_before_resize_and_padding",
        "scene_reference_retains_target_identity": scene_mode != "neutral",
        "pose_extracted": False,
        "mask": mask_report,
        "scene_binding_sha256": binding,
        "note": ("Original scene reference preserves visible pose/expression context and also retains target identity."
                 if scene_mode == "original" else
                 "Blurred scene reference can still retain target identity; blur is not anonymization."
                 if scene_mode == "blur" else
                 "Neutral scene reference suppresses masked head RGB; facial pose/expression are not separately recovered."),
    }
    return {"crop": crop, "template": base, "safe_anchor": safe_anchor,
            "scene_reference": scene_reference, "report": report, "_binding_sha256": binding}


def _trusted_exterior_ring(crop):
    # Original support is included even when generation was contracted. A two-pixel
    # moat protects against crop resampling mixing editable RGB into a ring pixel.
    authority = ((crop.masks.original > 0) | (crop.masks.generation > 0)).astype(np.float32)
    support = transform_mask_to_crop(authority, crop.transform) > 0
    valid = transform_mask_to_crop(np.ones(crop.transform.original_hw, np.float32), crop.transform) > 0
    valid = binary_erosion(valid, iterations=2, border_value=0)
    return (binary_dilation(support, iterations=10)
            & ~binary_dilation(support, iterations=2) & valid)


def finish_native_crop(generated, scene, color_strength=0.0, max_shift=0.04):
    """Optionally correct bounded exterior-ring drift, then composite the bound page.

    The median RGB residual uses only valid unedited context outside both masks.
    It estimates shared rendering drift, not skin tone or identity. Small/absent
    exterior rings cannot support that estimate and cause an explicit no-op.
    """
    strength = _bounded_number("color_strength", color_strength, 0, 1)
    bound = _bounded_number("max_shift", max_shift, 0, 0.25)
    if not isinstance(scene, dict) or not {"template", "crop", "_binding_sha256"}.issubset(scene):
        raise ValueError("Expected the scene bundle returned by prepare_native_scene")
    base, crop = scene["template"], scene["crop"]
    if _scene_binding(base, crop) != scene["_binding_sha256"]:
        raise ValueError("Scene template, crop, masks, or geometry changed after preparation")
    patch = float_image(generated)
    if patch.shape[:2] != crop.transform.model_hw:
        raise ValueError(f"Generated crop is {patch.shape[:2]}, expected {crop.transform.model_hw}; no implicit resizing")
    ring = _trusted_exterior_ring(crop)
    count = int(ring.sum())
    offset = np.zeros(3, np.float32)
    estimate = np.zeros(3, np.float32)
    reason = "disabled_by_operator"
    if strength > 0 and bound > 0:
        if count < 16:
            reason = "insufficient_unedited_exterior_ring"
        else:
            estimate = np.median(crop.image[ring] - patch[ring], axis=0).astype(np.float32)
            offset = np.clip(estimate, -bound, bound) * strength
            patch = np.clip(patch + offset, 0, 1)
            reason = "bounded_exterior_ring_median"
    elif strength > 0:
        reason = "zero_max_shift"
    final = composite_to_template(base, patch, crop)
    report = preservation_metrics(base, final, crop.masks.original)
    report.update({
        "scene_binding_sha256": scene["_binding_sha256"],
        "color_correction": {
            "method": reason,
            "strength": strength,
            "max_shift_per_channel": bound,
            "exterior_ring_pixel_count": count,
            "estimated_rgb_shift": estimate.tolist(),
            "applied_rgb_shift": offset.tolist(),
            "heuristic_only": True,
            "note": "Uses only exterior context; does not estimate skin color or certify lighting/identity quality.",
        },
        "identity_score": None,
        "face_quality_score": None,
        "semantic_quality_validated": False,
    })
    return final, report


def review_diagnostics(template, final, authority):
    """Measure visible failure cues inside the editable region without judging faces.

    Constant colors and heavy clipping can occur in legitimate images too. Warnings
    therefore request inspection; they never certify or reject identity/realism.
    Fractions count pixels equally wherever the supplied authority is positive.
    """
    before = measurement_float(template)
    after = measurement_float(final)
    if before.shape != after.shape:
        raise ValueError("Review images must have exactly the same dimensions; no implicit resizing")
    editable = validate_mask(authority, before.shape[:2]) > 0
    count = int(editable.sum())
    thresholds = {"near_black": 0.01, "near_white": 0.99,
                  "nearly_constant_max_channel_variance": 1e-4,
                  "mostly_near_black_or_white_fraction": 0.5}
    report = {
        "editable_pixel_count": count,
        "masked_changed_fraction": None,
        "masked_channel_variance": None,
        "masked_near_black_fraction": None,
        "masked_near_white_fraction": None,
        "masked_near_black_or_white_fraction": None,
        "warnings": [],
        "thresholds": thresholds,
        "heuristic_only": True,
        "note": "Numerical inspection cues only; no identity, anatomy, or photorealism score. Fractions are in [0,1].",
    }
    if count == 0:
        report["warnings"].append("The headmask has no editable pixels; no head replacement can be inspected.")
        return report
    pixels = after[editable]
    changed = np.any(pixels != before[editable], axis=-1)
    variance = np.var(pixels, axis=0)
    near_black = np.all(pixels <= thresholds["near_black"], axis=-1)
    near_white = np.all(pixels >= thresholds["near_white"], axis=-1)
    clipped_fraction = float(np.mean(near_black | near_white))
    report.update({
        "masked_changed_fraction": float(changed.mean()),
        "masked_channel_variance": variance.tolist(),
        "masked_near_black_fraction": float(near_black.mean()),
        "masked_near_white_fraction": float(near_white.mean()),
        "masked_near_black_or_white_fraction": clipped_fraction,
    })
    if not changed.any():
        report["warnings"].append("The editable region is identical to the original; no visible head replacement occurred.")
    if float(variance.max()) <= thresholds["nearly_constant_max_channel_variance"]:
        report["warnings"].append("The editable region is nearly a constant color; inspect the generated head.")
    if clipped_fraction >= thresholds["mostly_near_black_or_white_fraction"]:
        report["warnings"].append("At least half of editable pixels are near black or white; inspect clipping or a missing head.")
    return report
