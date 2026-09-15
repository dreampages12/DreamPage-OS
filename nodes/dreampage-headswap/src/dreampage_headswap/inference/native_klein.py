"""Lazy, native ComfyUI bridge for existing FLUX.2 Klein 9B weights.

ComfyUI owns model loading, offload, tokenization, VAE and sampling. No optimizer,
Diffusers pipeline, random encoder, implicit LoRA or face restoration is used.
"""
from __future__ import annotations

import time
import torch


def _image(array):
    return torch.from_numpy(array.copy()).float().unsqueeze(0)


def _check_vae(vae):
    if getattr(vae, "latent_channels", None) != 128 or vae.spacial_compression_encode() != 16:
        raise ValueError("DreamPage Klein requires the FLUX.2 VAE (128 packed channels, stride 16)")


def _encode(vae, image):
    latent = vae.encode(_image(image))
    if latent.ndim != 4 or latent.shape[:2] != (1, 128) or tuple(latent.shape[-2:]) != (image.shape[0]//16, image.shape[1]//16):
        raise ValueError("Unexpected FLUX.2 latent geometry; image must be aligned to model stride")
    return latent


@torch.inference_mode()
def encode_identity(vae, references):
    _check_vae(vae)
    latents = [_encode(vae, image) for image in references["images"]]
    return {"latents": latents, "vae": vae, "references": references,
            "report": {"mode": "FLUX.2 pretrained VAE reference encoding",
                       "reference_count": len(latents), "latent_shapes": [list(x.shape) for x in latents],
                       "dreamface_checkpoint_loaded": False, "identity_quality_validated": False}}


def build_swap_prompt(count, scene_mode, extra_instructions=""):
    if not 1 <= count <= 3:
        raise ValueError("Expected one to three identity references")
    source = "image 2" if count == 1 else "images " + ", ".join(str(i) for i in range(2, count+2))
    pose = ("Match the head rotation, tilt, gaze and expression in image 1. "
            if scene_mode == "original" else
            "Place the head naturally on the visible neck and body in image 1. ")
    return (f"Use image 1 as the base scene. Replace only its head and hair with the person from {source}. "
            f"{source.capitalize()} show the same person and provide identity, not scene composition. "
            "Preserve that person's facial proportions, distinctive features, ears, hairline and hair texture. "
            "Keep the base head position, head-to-body proportions, neck, body, clothing and background. "
            + pose + "Match the scene's light direction, exposure, color temperature, shadows, focus and grain. "
            "Create a natural connection at the neck and jaw. Photorealistic skin and hair, natural anatomy. "
            + extra_instructions.strip())


@torch.inference_mode()
def condition_klein(clip, vae, identity, scene, prompt):
    _check_vae(vae)
    if identity["vae"] is not vae:
        raise ValueError("Use the SAME VAE loader for identity and scene conditioning")
    import node_helpers
    conditioning = clip.encode_from_tokens_scheduled(clip.tokenize(prompt))
    if not conditioning or any(c[0].shape[-1] != 12288 for c in conditioning):
        raise ValueError("Klein 9B requires Qwen3-8B text conditioning (12288 features)")
    reference = _encode(vae, scene["scene_reference"])
    anchor = _encode(vae, scene["safe_anchor"])
    # Exact native ReferenceLatent semantics: scene first, then individual identity views.
    ordered = [reference, *identity["latents"]]
    positive = node_helpers.conditioning_set_values(conditioning, {"reference_latents": ordered})
    # CFG is fixed to 1 for the distilled 9B path; negative is not a quality control.
    negative = [[torch.zeros_like(c[0]), {**c[1], "reference_latents": ordered}] for c in conditioning]
    noise_mask = torch.from_numpy(scene["crop"].mask.copy()).unsqueeze(0)
    latent = {"samples": anchor, "noise_mask": noise_mask}
    return positive, negative, latent, {"reference_order": ["scene", *[f"person_view_{i+1}" for i in range(len(ordered)-1)]],
            "text_features": 12288, "anchor": "identity-suppressed before crop and VAE", "cfg": 1.0}


@torch.inference_mode()
def sample_klein(model, positive, negative, latent, *, seed=0, steps=4, sampler="euler",
                 scheduler="simple", engine="native", lanpaint_steps=2):
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**64:
        raise ValueError("Seed must be an integer in [0, 2**64)")
    if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 30:
        raise ValueError("Steps must be an integer in [1,30]")
    if isinstance(lanpaint_steps, bool) or not isinstance(lanpaint_steps, int) or not 1 <= lanpaint_steps <= 10:
        raise ValueError("LanPaint steps must be an integer in [1,10]")
    if sampler not in {"euler", "heun"} or scheduler not in {"simple", "beta"} or engine not in {"native", "lanpaint"}:
        raise ValueError("Unsupported DreamSwap sampler, scheduler or engine")
    import nodes
    config = getattr(getattr(model, "model", None), "model_config", None)
    config = getattr(config, "unet_config", {})
    if config.get("image_model") != "flux2" or config.get("context_in_dim") != 12288 or config.get("guidance_embed", False):
        raise ValueError("DreamSwap requires FLUX.2 Klein 9B architecture; select the distilled 9B checkpoint for this preset")
    if "noise_mask" not in latent or latent["samples"].ndim != 4 or tuple(latent["samples"].shape[:2]) != (1,128):
        raise ValueError("Connect the masked latent from DP Klein Conditioning")
    mask = latent["noise_mask"]
    if mask.ndim == 3:
        mask = mask.unsqueeze(1)
    if mask.ndim != 4 or tuple(mask.shape[:2]) != (1, 1) or not torch.isfinite(mask).all() or (mask < 0).any() or (mask > 1).any():
        raise ValueError("Expected a finite single headmask in [0,1]")
    if not torch.isfinite(latent["samples"]).all():
        raise ValueError("Latent contains non-finite values")
    if engine == "lanpaint":
        effective = torch.nn.functional.interpolate(mask.float(), size=latent["samples"].shape[-2:], mode="nearest-exact") > 0.5
    else:
        effective = torch.nn.functional.interpolate(mask.float(), size=latent["samples"].shape[-2:], mode="bilinear", align_corners=False) > 0
    editable_cells = int(effective.sum())
    if not editable_cells:
        raise ValueError("Headmask disappears at latent resolution; enlarge it or increase crop resolution")
    start = time.perf_counter()
    # Clone the patcher before any optional sampler extension touches model options.
    safe_model = model.clone()
    if engine == "lanpaint":
        cls = nodes.NODE_CLASS_MAPPINGS.get("LanPaint_KSampler")
        if cls is None:
            raise RuntimeError("LanPaint is not installed; select native or install LanPaint explicitly")
        sampled = cls().sample(safe_model, seed, steps, 1.0, sampler, scheduler,
                               positive, negative, latent, denoise=1.0,
                               LanPaint_NumSteps=lanpaint_steps, LanPaint_PromptMode="Image First")
    elif engine == "native":
        sampled = nodes.common_ksampler(safe_model, seed, steps, 1.0, sampler, scheduler,
                                        positive, negative, latent, denoise=1.0)
    else:
        raise ValueError("Unknown DreamSwap sampler engine")
    return sampled[0], {"engine": engine, "steps": steps, "seed": seed, "cfg": 1.0,
                        "elapsed_seconds": time.perf_counter()-start,
                        "editable_latent_cells": editable_cells,
                        "architecture": "FLUX.2 Klein 9B", "preset": "distilled 4-step inference",
                        "distillation_verified": False, "adapter_provenance_verified": False}
