"""ComfyUI nodes over the standalone core. No model logic lives here.

Every node is a thin adapter: convert ComfyUI tensors, call the library, convert back. The
package must stay importable without ComfyUI so the node contract can be tested in isolation.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path

import numpy as np
import torch

from dreampage_headswap.compositing import composite_to_template
from dreampage_headswap.evaluation.metrics import preservation_metrics
from dreampage_headswap.evaluation.quality import QualityConfig, evaluate_quality
from dreampage_headswap.inference.pipeline import load_pipeline, save_debug
from dreampage_headswap.masking import MaskConfig, process_mask, validate_mask
from dreampage_headswap.template import CropConfig, extract_crop
from dreampage_headswap.types import ChildIdentityInput, HeadMask, TemplateInput

from .conversion import array_to_image, array_to_mask, image_to_array, images_to_arrays, mask_to_array

CATEGORY = "DreamPage/HeadSwap"
DEGRADATIONS = ["neutral", "blur", "noise", "none"]


def _json(value) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str, allow_nan=False)


class DP_LoadHeadSwapModel:
    """Load a config and a trusted local checkpoint. Never silently falls back to random weights."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"config_path": ("STRING", {"default": "configs/inference/tiny_smoke.yaml"}),
                             "device": (["cpu", "cuda"], {"default": "cpu"})},
                "optional": {"checkpoint_path": ("STRING", {"default": ""}),
                             "allow_untrained": ("BOOLEAN", {"default": False})}}

    RETURN_TYPES = ("DP_PIPELINE", "STRING")
    RETURN_NAMES = ("pipeline", "checkpoint_metadata")
    FUNCTION = "load"
    CATEGORY = CATEGORY

    def load(self, config_path, device, checkpoint_path="", allow_untrained=False):
        pipeline = load_pipeline(config_path, checkpoint=checkpoint_path.strip() or None,
                                 device=device, allow_untrained=allow_untrained)
        return pipeline, _json(pipeline.checkpoint_metadata)


class DP_UseHeadMask:
    """Derive the generation and blend masks from the supplied headmask.

    Expansion widens context for generation only. It never widens write permission: the blend
    mask is clamped to the supplied mask, so protected pixels stay protected.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"headmask": ("MASK",),
                             "expand": ("INT", {"default": 0, "min": -512, "max": 512}),
                             "feather": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 512.0, "step": 0.5})}}

    RETURN_TYPES = ("MASK", "MASK", "MASK", "STRING")
    RETURN_NAMES = ("original", "generation", "blend", "report")
    FUNCTION = "process"
    CATEGORY = CATEGORY

    def process(self, headmask, expand, feather):
        masks = process_mask(mask_to_array(headmask), MaskConfig(expand=int(expand), feather=float(feather)))
        report = {"editable_fraction": float(np.mean(masks.original > 0)),
                  "generation_fraction": float(np.mean(masks.generation > 0)),
                  "blend_fraction": float(np.mean(masks.blend > 0)),
                  "blend_within_supplied_authority": bool(np.all(masks.blend <= masks.original + 1e-7))}
        return array_to_mask(masks.original), array_to_mask(masks.generation), array_to_mask(masks.blend), _json(report)


class DP_PrepareTemplateCrop:
    """Extract the padded head crop and keep the exact transform needed to map it back."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"template": ("IMAGE",), "headmask": ("MASK",),
                             "resolution": ("INT", {"default": 512, "min": 8, "max": 4096, "step": 8}),
                             "context": ("FLOAT", {"default": 1.5, "min": 1.0, "max": 8.0, "step": 0.05}),
                             "expand": ("INT", {"default": 0, "min": -512, "max": 512}),
                             "feather": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 512.0, "step": 0.5})}}

    RETURN_TYPES = ("DP_CROP", "IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("crop", "crop_image", "crop_mask", "transform")
    FUNCTION = "prepare"
    CATEGORY = CATEGORY

    def prepare(self, template, headmask, resolution, context, expand, feather):
        base = image_to_array(template)
        mask = validate_mask(mask_to_array(headmask), base.shape[:2])
        if not mask.any():
            raise ValueError("Empty headmask: there is no authorized region to crop")
        masks = process_mask(mask, MaskConfig(expand=int(expand), feather=float(feather)))
        crop = extract_crop(base, masks, CropConfig(resolution=int(resolution), context=float(context)))
        bundle = {"crop": crop, "template": base}
        return bundle, array_to_image(crop.image), array_to_mask(crop.mask), _json(asdict(crop.transform))


class DP_CompositeToTemplate:
    """Composite a generated crop back into the untouched template.

    The full-resolution template stays the authoritative base, and pixels the supplied mask
    protects are copied straight from it, so no denoiser or VAE can drift them.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"template": ("IMAGE",), "generated_crop": ("IMAGE",), "crop": ("DP_CROP",)}}

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "report")
    FUNCTION = "composite"
    CATEGORY = CATEGORY

    def composite(self, template, generated_crop, crop):
        base = image_to_array(template)
        generated = image_to_array(generated_crop)
        bundle = crop["crop"]
        if generated.shape[:2] != bundle.transform.model_hw:
            raise ValueError(f"Generated crop is {generated.shape[:2]}, expected {bundle.transform.model_hw}")
        result = composite_to_template(base, generated, bundle)
        return array_to_image(result), _json(preservation_metrics(base, result, bundle.masks.original))


class DP_EncodeChildIdentity:
    """Encode one or more child references into the identity condition.

    Random or untrained weights carry no recognition guarantee. The summary reports shapes and
    norms, which shows that the encoder ran, not that identity was preserved.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"pipeline": ("DP_PIPELINE",), "child_images": ("IMAGE",),
                             "reference_resolution": ("INT", {"default": 128, "min": 16, "max": 1024, "step": 8})}}

    RETURN_TYPES = ("DP_IDENTITY", "STRING")
    RETURN_NAMES = ("identity", "summary")
    FUNCTION = "encode"
    CATEGORY = CATEGORY

    def encode(self, pipeline, child_images, reference_resolution):
        references = images_to_arrays(child_images)
        tensor = pipeline.encode_references(references, int(reference_resolution))
        with torch.inference_mode():
            condition = pipeline.model.encoder(tensor)
        summary = {"reference_count": len(references),
                   "reference_resolution": int(reference_resolution),
                   "global_embedding_dim": int(condition.global_embedding.shape[-1]),
                   "local_token_count": int(condition.local_tokens.shape[1]),
                   "structure_dim": int(condition.structure.shape[-1]),
                   "global_embedding_norm": float(condition.global_embedding.float().norm()),
                   "identity_quality_validated": False}
        return {"condition": condition, "references": tensor, "count": len(references)}, _json(summary)


class DP_QualityCheck:
    """Measure a result against its template.

    Identity, pose, realism and age stay unavailable until a licensed calibrated provider is
    configured, so this node cannot report PASS on preservation alone.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"template": ("IMAGE",), "result": ("IMAGE",), "headmask": ("MASK",),
                             "threshold": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 1.0, "step": 0.01})},
                "optional": {"model_validated": ("BOOLEAN", {"default": False})}}

    RETURN_TYPES = ("STRING", "STRING", "FLOAT")
    RETURN_NAMES = ("report", "status", "template_preservation_score")
    FUNCTION = "check"
    CATEGORY = CATEGORY

    def check(self, template, result, headmask, threshold, model_validated=False):
        base = image_to_array(template)
        output = image_to_array(result)
        mask = mask_to_array(headmask)
        metrics = evaluate_quality(base, output, mask, config=QualityConfig(threshold=float(threshold)),
                                   model_validated=bool(model_validated))
        return _json(asdict(metrics)), metrics.status, float(metrics.template_preservation_score or 0.0)


class DP_HeadSwapPipeline:
    """Child references plus template plus authoritative headmask, in one node.

    Handles identity encoding, crop, geometry, generation, optional refinement, compositing and
    the quality gate. Leave age at -1 when it is unknown; the age is never guessed.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"pipeline": ("DP_PIPELINE",), "child_images": ("IMAGE",),
                             "template": ("IMAGE",), "headmask": ("MASK",),
                             "identity_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0, "step": 0.05}),
                             "refine_strength": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05}),
                             "mask_expand": ("INT", {"default": 0, "min": -512, "max": 512}),
                             "mask_feather": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 512.0, "step": 0.5}),
                             "steps": ("INT", {"default": 20, "min": 1, "max": 1000}),
                             "seed": ("INT", {"default": 0, "min": 0, "max": 2**31 - 1}),
                             "quality_threshold": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 1.0, "step": 0.01})},
                "optional": {"crop_resolution": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 8}),
                             "crop_context": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 8.0, "step": 0.05}),
                             "degradation": (DEGRADATIONS, {"default": "neutral"}),
                             "age": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 120.0, "step": 1.0}),
                             "debug": ("BOOLEAN", {"default": False}),
                             "debug_dir": ("STRING", {"default": ""})}}

    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "FLOAT")
    RETURN_NAMES = ("image", "quality", "debug", "template_preservation_score")
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, pipeline, child_images, template, headmask, identity_strength, refine_strength,
            mask_expand, mask_feather, steps, seed, quality_threshold, crop_resolution=0,
            crop_context=0.0, degradation="neutral", age=-1.0, debug=False, debug_dir=""):
        base = pipeline.config
        crop = replace(base.crop,
                       resolution=int(crop_resolution) if crop_resolution else base.crop.resolution,
                       context=float(crop_context) if crop_context else base.crop.context)
        config = replace(base, crop=crop,
                         mask=MaskConfig(expand=int(mask_expand), feather=float(mask_feather)),
                         quality=replace(base.quality, threshold=float(quality_threshold)),
                         steps=int(steps), seed=int(seed), identity_strength=float(identity_strength),
                         refine_strength=float(refine_strength), degradation=degradation,
                         debug=bool(debug) or bool(debug_dir.strip()))
        child = ChildIdentityInput(images_to_arrays(child_images), None if age < 0 else float(age))
        output = pipeline(child, TemplateInput(image_to_array(template)),
                          HeadMask(mask_to_array(headmask)), config=config)
        if debug_dir.strip():
            save_debug(output, Path(debug_dir.strip()))
        summary = {key: value for key, value in output.debug.items() if not isinstance(value, (np.ndarray, list))}
        summary["debug_images_written_to"] = debug_dir.strip() or None
        return (array_to_image(output.image), _json(asdict(output.quality)), _json(summary),
                float(output.quality.template_preservation_score or 0.0))


NODE_CLASS_MAPPINGS = {
    "DP_LoadHeadSwapModel": DP_LoadHeadSwapModel,
    "DP_UseHeadMask": DP_UseHeadMask,
    "DP_PrepareTemplateCrop": DP_PrepareTemplateCrop,
    "DP_CompositeToTemplate": DP_CompositeToTemplate,
    "DP_EncodeChildIdentity": DP_EncodeChildIdentity,
    "DP_QualityCheck": DP_QualityCheck,
    "DP_HeadSwapPipeline": DP_HeadSwapPipeline,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DP_LoadHeadSwapModel": "DP Load HeadSwap Model",
    "DP_UseHeadMask": "DP Use HeadMask",
    "DP_PrepareTemplateCrop": "DP Prepare Template Crop",
    "DP_CompositeToTemplate": "DP Composite To Template",
    "DP_EncodeChildIdentity": "DP Encode Child Identity",
    "DP_QualityCheck": "DP Quality Check",
    "DP_HeadSwapPipeline": "DP HeadSwap Pipeline",
}

# ComfyUI viser `DESCRIPTION` i noden, ikke `__doc__`. Disse sju nodene hadde
# bare docstring, saa /object_info rapporterte tom beskrivelse og operatoeren
# saa ingenting i grensesnittet - mens de ni Studio-nodene, som setter
# DESCRIPTION eksplisitt, viste sin. Vi speiler docstringen i stedet for aa
# skrive teksten to ganger: da kan de ikke drifte fra hverandre.
for _name, _cls in NODE_CLASS_MAPPINGS.items():
    if not getattr(_cls, "DESCRIPTION", None) and _cls.__doc__:
        _cls.DESCRIPTION = " ".join(_cls.__doc__.split())
