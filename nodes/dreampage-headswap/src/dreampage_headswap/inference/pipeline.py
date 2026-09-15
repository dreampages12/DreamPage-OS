"""Standalone orchestration. The untouched full-resolution template is always the base."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
import yaml

from dreampage_headswap.compositing import composite_to_template
from dreampage_headswap.evaluation.metrics import outside_difference_image
from dreampage_headswap.evaluation.quality import QualityConfig, QualityProvider, evaluate_quality
from dreampage_headswap.geometry import GeometryExtractor, MaskContextGeometry
from dreampage_headswap.masking import MaskConfig, process_mask, validate_mask
from dreampage_headswap.template import CropConfig, extract_crop
from dreampage_headswap.template.crop import transform_mask_to_crop
from dreampage_headswap.template.degradation import prepare_condition_crop
from dreampage_headswap.types import ChildIdentityInput, HeadMask, QualityMetrics, SwapOutput, TemplateInput
from dreampage_headswap.utils.images import float_image, from_tensor, resize_array, save_rgb, to_tensor, validate_image


@dataclass(frozen=True)
class InferenceConfig:
    crop: CropConfig = field(default_factory=CropConfig)
    mask: MaskConfig = field(default_factory=MaskConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    steps: int = 20
    seed: int = 0
    identity_strength: float = 1.0
    refine_strength: float = 0.0
    reference_resolution: int = 128
    degradation: str = "neutral"
    debug: bool = False

    def __post_init__(self):
        if not isinstance(self.steps, int) or not 1 <= self.steps <= 1000:
            raise ValueError("Inference steps must be an integer from 1 to 1000")
        if not np.isfinite(self.identity_strength) or not 0 <= self.identity_strength <= 5:
            raise ValueError("identity_strength must be in [0,5]")
        if not np.isfinite(self.refine_strength) or not 0 <= self.refine_strength <= 1:
            raise ValueError("refine_strength must be in [0,1]")
        if not isinstance(self.seed, int) or not 0 <= self.seed < 2**63:
            raise ValueError("Seed must be an integer in [0,2**63)")
        if not 16 <= self.reference_resolution <= 1024:
            raise ValueError("Reference resolution must be in [16,1024]")
        if self.degradation not in {"neutral", "blur", "noise", "none", "internal"}:
            raise ValueError("Unsupported degradation strategy")


class HeadSwapPipeline:
    def __init__(self, model, *, config: InferenceConfig | None = None,
                 geometry: GeometryExtractor | None = None, refiner=None,
                 quality_provider: QualityProvider | None = None, model_validated: bool = False,
                 checkpoint_metadata: dict | None = None):
        self.model = model.eval()
        self.config = config or InferenceConfig()
        self.geometry = geometry or MaskContextGeometry()
        self.refiner = refiner.eval() if refiner is not None else None
        self.quality_provider = quality_provider
        self.model_validated = model_validated
        self.checkpoint_metadata = checkpoint_metadata or {}

    @property
    def device(self):
        return next(self.model.parameters()).device

    @property
    def dtype(self):
        return next(self.model.parameters()).dtype

    def encode_references(self, references: list[np.ndarray], resolution: int | None = None) -> torch.Tensor:
        resolution = resolution or self.config.reference_resolution
        if not references:
            raise ValueError("At least one child reference is required")
        if not isinstance(resolution, int) or not 16 <= resolution <= 1024:
            raise ValueError("Reference resolution must be an integer in [16,1024]")
        tensors = [to_tensor(resize_array(float_image(ref), (resolution, resolution)), self.device) for ref in references]
        return torch.stack(tensors, dim=1).to(dtype=self.dtype)

    @torch.inference_mode()
    def __call__(self, child: ChildIdentityInput, template: TemplateInput, headmask: HeadMask, *,
                 config: InferenceConfig | None = None, geometry_metadata: dict[str, Any] | None = None,
                 internal_face_mask: np.ndarray | None = None) -> SwapOutput:
        config = config or self.config
        base = validate_image(template.image)
        original_mask = validate_mask(headmask, base.shape[:2])
        if not child.references:
            raise ValueError("At least one child reference is required")
        for reference in child.references:
            validate_image(reference)
        if child.age is not None and (not np.isfinite(child.age) or not 0 <= child.age <= 120):
            raise ValueError("Optional supplied age must be finite and between 0 and 120")
        if not original_mask.any():
            quality = QualityMetrics(template_preservation_score=1.0, status="FAIL",
                                     reasons=["Empty headmask: returned unchanged template; no headswap performed"])
            return SwapOutput(base.copy(), quality, {"no_op": True})
        masks = process_mask(original_mask, config.mask)
        crop = extract_crop(base, masks, config.crop)
        template_t = to_tensor(crop.image, self.device).to(dtype=self.dtype)
        # Alpha is applied only in the final full-resolution composite, not repeatedly in denoising.
        mask_t = torch.from_numpy((crop.mask > 0).astype(np.float32))[None, None].to(device=self.device, dtype=self.dtype)
        refs = self.encode_references(child.references, config.reference_resolution)
        safe_geometry_crop = prepare_condition_crop(base, crop, "neutral")
        original_crop_mask = transform_mask_to_crop(original_mask, crop.transform)
        geometry_mask_t = torch.from_numpy((original_crop_mask > 0).astype(np.float32))[None, None].to(mask_t)
        geometry = self.geometry.extract(to_tensor(safe_geometry_crop, self.device).to(self.dtype), geometry_mask_t, geometry_metadata)
        condition_template = to_tensor(prepare_condition_crop(base, crop, config.degradation,
                                       seed=config.seed, internal_face_mask=internal_face_mask), self.device).to(self.dtype)
        age = None if child.age is None else template_t.new_tensor([child.age])
        if config.refine_strength > 0 and self.refiner is None:
            raise ValueError("refine_strength > 0 requires an explicitly loaded DreamRefine checkpoint")
        generated = self.model.sample(references=refs, template=template_t, mask=mask_t,
                                      geometry=geometry, age=age, steps=config.steps, seed=config.seed,
                                      identity_strength=config.identity_strength, condition_template=condition_template)
        raw = from_tensor(generated)
        refined = generated
        if config.refine_strength > 0:
            if hasattr(self.refiner, "refine"):
                candidate = self.refiner.refine(generated, template_t, mask_t, refs)
            else:
                identity = self.model.encoder(refs)
                candidate = self.refiner(generated, template_t, mask_t, identity)
            refined = generated.lerp(candidate, config.refine_strength).clamp(0, 1)
        refined_array = from_tensor(refined)
        final = composite_to_template(base, refined_array, crop)
        quality = evaluate_quality(base, final, original_mask, references=child.references, age=child.age,
                                   provider=self.quality_provider, config=config.quality, model_validated=self.model_validated)
        debug: dict[str, Any] = {"crop_transform": asdict(crop.transform), "config": asdict(config),
                                 "checkpoint_metadata": self.checkpoint_metadata, "geometry": geometry.measurements}
        if config.debug:
            debug.update({"child_images": [image.copy() for image in child.references], "template": base.copy(),
                          "original_headmask": masks.original, "generation_mask": masks.generation,
                          "blend_mask": masks.blend, "head_crop": crop.image, "crop_mask": crop.mask,
                          "geometry_spatial": geometry.spatial.detach().float().cpu().numpy(),
                          "identity_suppressed_template": from_tensor(condition_template),
                          "dreamswap_raw": raw, "dreamrefine_output": refined_array,
                          "final_composite": final, "outside_mask_difference": outside_difference_image(base, final, original_mask)})
        return SwapOutput(final, quality, debug)


def load_pipeline(config_path: str | Path, *, checkpoint: str | Path | None = None,
                  device: str = "cpu", allow_untrained: bool = False) -> HeadSwapPipeline:
    """Load a complete trusted-local research checkpoint; never silently fall back to random weights."""
    from dreampage_headswap.training import build_model
    from dreampage_headswap.utils.checkpoint import load_checkpoint, seed_everything

    path = Path(config_path).resolve()
    with path.open(encoding="utf-8") as handle:
        values = yaml.safe_load(handle)
    if not isinstance(values, dict):
        raise ValueError("Config must be a YAML mapping")
    options = dict(values.get("inference", {}))
    options["crop"] = CropConfig(**options.get("crop", {}))
    options["mask"] = MaskConfig(**options.get("mask", {}))
    options["quality"] = QualityConfig(**options.get("quality", {}))
    config = InferenceConfig(**options)
    checkpoint = checkpoint or values.get("checkpoint")
    if not checkpoint and not allow_untrained:
        raise ValueError("A trained DreamSwap checkpoint is required. --allow-untrained is for mechanics smoke tests only")
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    seed_everything(config.seed)
    model_values = {**values, "model": dict(values.get("model", {}))}
    if checkpoint:
        # Full DreamSwap checkpoints contain their encoder; serving does not need
        # the original independent pretraining file path.
        model_values["model"].pop("identity_checkpoint", None)
        model_values["model"]["freeze_encoder"] = False
    model = build_model(model_values, device=device)
    metadata = {"untrained": not bool(checkpoint)}
    if checkpoint:
        state = load_checkpoint(checkpoint, model, restore_random=False, map_location=device)
        metadata.update({"step": state["step"], "metadata": state.get("metadata", {}),
                         "quality_claim": state.get("quality_claim"), "checkpoint": str(Path(checkpoint).resolve())})
    refiner = None
    refiner_config = values.get("refiner", {})
    if refiner_config.get("checkpoint"):
        from dreampage_headswap.training.refiner import load_refinement_system
        refiner = load_refinement_system(refiner_config["checkpoint"], device=device, dtype=next(model.parameters()).dtype)
    return HeadSwapPipeline(model, config=config, refiner=refiner, checkpoint_metadata=metadata)


def save_debug(output: SwapOutput, directory: str | Path) -> None:
    """Explicit opt-in only; debug artifacts may contain child references."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    metadata = {"quality": asdict(output.quality)}
    for name, value in output.debug.items():
        if isinstance(value, np.ndarray):
            if value.ndim == 3 and value.shape[-1] == 3:
                save_rgb(directory / f"{name}.png", value)
            elif value.ndim == 2:
                from PIL import Image
                Image.fromarray(np.rint(value * 255).clip(0, 255).astype(np.uint8)).save(directory / f"{name}.png")
            else:
                np.save(directory / f"{name}.npy", value)
        elif name == "child_images":
            for index, image in enumerate(value):
                save_rgb(directory / f"child_{index}.png", image)
        else:
            metadata[name] = value
    (directory / "debug.json").write_text(json.dumps(metadata, indent=2, allow_nan=False), encoding="utf-8")
