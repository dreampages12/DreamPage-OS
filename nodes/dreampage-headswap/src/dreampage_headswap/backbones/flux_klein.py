"""FLUX.2 Klein 9B bridge, based on upstream Diffusers APIs.

No implicit downloads, variant switching or 4B fallback. Upstream
pipeline is used for loading, VAE mechanics and schedules, never its no-grad
generation call. The actual transformer forward remains differentiable.
"""
from __future__ import annotations

import inspect
import json
import math
from pathlib import Path
import weakref

import torch
from torch import nn
from torch.nn import functional as F

from .base import GenerativeBackbone
from ..conditioning import IdentityAdapter, age_features, conditioning_tokens
from ..types import IdentityCondition, SwapCondition
from ..model_target import KLEIN_9B, PROFILES, validate_snapshot_config, inspect_single_file


class FluxKleinBackbone(GenerativeBackbone):
    MODEL_ID = KLEIN_9B

    def __init__(self, pipeline, identity_dim: int = 64, structure_dim: int = 16,
                 adapter_width: int = 64, train_transformer: bool = False,
                 prompt: str = "Realistic head matching the supplied identity, template pose, expression and lighting.",
                 text_guidance_scale: float = 1.0, prompt_max_sequence_length: int = 512,
                 prompt_embeddings: torch.Tensor | None = None,
                 negative_prompt_embeddings: torch.Tensor | None = None):
        super().__init__()
        self.is_distilled = bool(getattr(pipeline.config, "is_distilled", False))
        if self.is_distilled and text_guidance_scale != 1.0:
            raise ValueError("Distilled Klein 9B requires text_guidance_scale=1")
        if not math.isfinite(text_guidance_scale) or text_guidance_scale < 1:
            raise ValueError("text_guidance_scale must be finite and >=1 (1 disables BASE text CFG)")
        self.text_guidance_scale = float(text_guidance_scale)
        self.transformer, self.vae = pipeline.transformer, pipeline.vae
        self.transformer.requires_grad_(train_transformer)
        self.vae.requires_grad_(False).eval()
        if pipeline.text_encoder is not None:
            pipeline.text_encoder.requires_grad_(False).eval()
        self.train_transformer = train_transformer
        # Pipeline is not a torch Module. Register its trained components above.
        self._pipeline = pipeline
        channels = self.transformer.config.in_channels
        context_dim = self.transformer.config.joint_attention_dim
        self.latent_input = nn.Conv2d(channels + 1 + 4, adapter_width, 1)
        self.identity_adapter = IdentityAdapter(adapter_width, identity_dim, structure_dim)
        self.latent_output = nn.Conv2d(adapter_width, channels, 1)
        self.structure_projection = nn.Linear(structure_dim, identity_dim)
        self.identity_context = nn.Linear(identity_dim, context_dim)
        self.geometry_context = nn.Linear(16 + 2, context_dim)
        nn.init.normal_(self.latent_output.weight, std=0.001)
        nn.init.zeros_(self.latent_output.bias)
        nn.init.normal_(self.identity_context.weight, std=0.001)
        nn.init.zeros_(self.identity_context.bias)
        nn.init.normal_(self.geometry_context.weight, std=0.001)
        nn.init.zeros_(self.geometry_context.bias)
        with torch.no_grad():
            if prompt_embeddings is None:
                if pipeline.text_encoder is None:
                    raise ValueError("A text encoder or cached prompt_embeddings is required")
                text_device = next(pipeline.text_encoder.parameters()).device
                prompt_embeddings, _ = pipeline.encode_prompt(prompt=prompt, device=text_device,
                                                        max_sequence_length=prompt_max_sequence_length)
            if negative_prompt_embeddings is None and text_guidance_scale == 1:
                negative_prompt_embeddings = prompt_embeddings.clone()
            if negative_prompt_embeddings is None:
                if pipeline.text_encoder is None:
                    if text_guidance_scale > 1:
                        raise ValueError("BASE text CFG requires a text encoder or cached negative_prompt_embeddings")
                    negative_prompt_embeddings = prompt_embeddings.clone()
                else:
                    negative_prompt_embeddings, _ = pipeline.encode_prompt(prompt="",
                        device=next(pipeline.text_encoder.parameters()).device,
                        max_sequence_length=prompt_max_sequence_length)
        for name, embeddings in (("prompt", prompt_embeddings), ("negative prompt", negative_prompt_embeddings)):
            if embeddings.ndim != 3 or embeddings.shape[0] != 1 or embeddings.shape[-1] != context_dim:
                raise ValueError(f"Cached {name} embeddings must be [1,sequence,{context_dim}]")
            if not torch.isfinite(embeddings).all():
                raise ValueError(f"Cached {name} embeddings must be finite")
        self.register_buffer("prompt_embeddings", prompt_embeddings.detach(), persistent=True)
        self.register_buffer("negative_prompt_embeddings", negative_prompt_embeddings.detach(), persistent=True)
        self.vae_scale_factor = pipeline.vae_scale_factor * 2
        self._reference_cache = None

    @classmethod
    def from_local_pretrained(cls, model_path: str | Path, *, identity_dim: int = 64,
                              structure_dim: int = 16, device: str = "cuda",
                              dtype: torch.dtype = torch.bfloat16, train_transformer: bool = False,
                              gradient_checkpointing: bool = True, model_id: str = KLEIN_9B,
                              transformer_checkpoint: str | None = None, **kwargs) -> "FluxKleinBackbone":
        path = Path(model_path).expanduser().resolve()
        if not path.is_dir() or not (path / "model_index.json").is_file():
            raise FileNotFoundError("Supply a reviewed local Diffusers component snapshot of " + model_id +
                                    "; the ComfyUI transformer alone lacks text encoder/tokenizer/scheduler components. No download attempted.")
        index = json.loads((path / "model_index.json").read_text(encoding="utf-8"))
        transformer_config = json.loads((path / "transformer" / "config.json").read_text(encoding="utf-8"))
        validate_snapshot_config(index, transformer_config, model_id)
        provenance_path = path / "dreampage_provenance.json"
        if not provenance_path.is_file():
            raise ValueError("9B snapshot mangler dreampage_provenance.json med verifiserte kildefiler")
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        if (provenance.get("model_id") != model_id or not provenance.get("revision") or
                not provenance.get("license") or provenance.get("commercial_use_reviewed") is not True):
            raise ValueError("9B kilde, revisjon og bruksrettigheter maa vaere gjennomgaatt; 4B-kvitteringer gjelder ikke")
        from ..data.records import file_sha256
        entries = provenance.get("files", [])
        required_configs = {"model_index.json", "transformer/config.json", "scheduler/scheduler_config.json",
                            "vae/config.json", "text_encoder/config.json"}
        declared = {entry["path"] for entry in entries}
        if not required_configs <= declared or not all(any(p.startswith(folder + "/") and p.endswith(".safetensors")
                for p in declared) for folder in ("vae", "text_encoder")):
            raise ValueError("9B snapshot-kvitteringen mangler komponenter")
        if not transformer_checkpoint and not any(p.startswith("transformer/") and p.endswith(".safetensors") for p in declared):
            raise ValueError("9B transformer-vekter mangler i snapshot")
        for entry in entries:
            asset = (path / entry["path"]).resolve()
            if (not asset.is_relative_to(path) or not asset.is_file() or asset.stat().st_size != entry["bytes"]
                    or file_sha256(asset) != entry["sha256"]):
                raise ValueError("Snapshot-fil mangler eller er endret: " + entry["path"])
        overrides = {}
        if transformer_checkpoint:
            inspect_single_file(transformer_checkpoint)
            receipt = provenance.get("transformer_source", {})
            if receipt.get("sha256") != file_sha256(transformer_checkpoint):
                raise ValueError("Den lokale 9B-transformeren mangler matchende kildehash")
        try:
            from diffusers import Flux2KleinPipeline
        except (ImportError, RuntimeError) as exc:
            raise RuntimeError("Optional Flux bridge requires Diffusers with Flux2KleinPipeline and compatible Transformers. "
                               "Use a separate reviewed training environment; do not upgrade ComfyUI in place.") from exc
        if transformer_checkpoint:
            from diffusers import Flux2Transformer2DModel
            overrides["transformer"] = Flux2Transformer2DModel.from_single_file(
                transformer_checkpoint, config=str(path), subfolder="transformer",
                torch_dtype=dtype, local_files_only=True)
        pipeline = Flux2KleinPipeline.from_pretrained(str(path), torch_dtype=dtype, local_files_only=True, **overrides)
        kwargs.setdefault("text_guidance_scale", PROFILES[model_id]["guidance"])
        required = {"hidden_states", "encoder_hidden_states", "timestep", "img_ids", "txt_ids"}
        if not required.issubset(inspect.signature(pipeline.transformer.forward).parameters):
            raise RuntimeError("Installed Diffusers transformer API differs from the audited Flux2 API")
        model = cls(pipeline, identity_dim, structure_dim, train_transformer=train_transformer, **kwargs)
        # Prompt embeddings are cached. Keep large frozen text encoder on CPU.
        if pipeline.text_encoder is not None:
            pipeline.text_encoder.to("cpu")
        model.to(device=device, dtype=dtype)
        if gradient_checkpointing:
            model.transformer.enable_gradient_checkpointing()
        return model

    def train(self, mode: bool = True):
        super().train(mode)
        self._reference_cache = None
        self.vae.eval()
        if not self.train_transformer:
            self.transformer.eval()
        return self

    def encode_images(self, images: torch.Tensor) -> torch.Tensor:
        if any(d % self.vae_scale_factor for d in images.shape[-2:]):
            raise ValueError(f"FLUX crop H,W must be divisible by {self.vae_scale_factor}")
        vae_parameter = next(self.vae.parameters())
        images = images.to(device=vae_parameter.device, dtype=vae_parameter.dtype)
        # Differentiable even though VAE weights are frozen; deterministic posterior mode.
        z = self.vae.encode(images * 2 - 1).latent_dist.mode()
        z = self._pipeline._patchify_latents(z)
        mean = self.vae.bn.running_mean[None, :, None, None].to(z)
        std = (self.vae.bn.running_var[None, :, None, None].to(z) + self.vae.config.batch_norm_eps).sqrt()
        return (z - mean) / std

    def decode_latents(self, latents: torch.Tensor) -> torch.Tensor:
        vae_parameter = next(self.vae.parameters())
        latents = latents.to(device=vae_parameter.device, dtype=vae_parameter.dtype)
        mean = self.vae.bn.running_mean[None, :, None, None].to(latents)
        std = (self.vae.bn.running_var[None, :, None, None].to(latents) + self.vae.config.batch_norm_eps).sqrt()
        z = self._pipeline._unpatchify_latents(latents * std + mean)
        return (self.vae.decode(z, return_dict=False)[0] + 1) / 2

    def _reference_latents(self, condition: SwapCondition) -> torch.Tensor:
        """Encode once per inference condition, while keeping every training graph fresh."""
        if torch.is_grad_enabled():
            return self.encode_images(condition.template)
        try:
            version = condition.template._version
        except RuntimeError:  # Tensors created inside inference_mode have no mutation counter.
            return self.encode_images(condition.template)
        vae_parameter = next(self.vae.parameters())
        key = (version, vae_parameter.device, vae_parameter.dtype)
        cached = self._reference_cache
        if cached is not None and cached[0]() is condition and cached[1]() is condition.template and cached[2] == key:
            return cached[3]
        latents = self.encode_images(condition.template)
        self._reference_cache = (weakref.ref(condition), weakref.ref(condition.template), key, latents)
        return latents

    def predict_velocity(self, sample: torch.Tensor, t: torch.Tensor, condition: SwapCondition) -> torch.Tensor:
        """Conditional velocity for training/validation; CFG is exclusively a sampling operation."""
        return self._predict_velocity(sample, t, condition, self.prompt_embeddings)

    def predict_sampling_velocity(self, sample: torch.Tensor, t: torch.Tensor, condition: SwapCondition) -> torch.Tensor:
        """BASE text CFG: v_empty + scale*(v_prompt-v_empty), guidance embedding=None.

        Identity, geometry and template remain present in both branches, just as
        upstream reference-image conditioning remains present in both branches.
        This does not implement identity CFG or imply calibrated identity strength.
        """
        conditional = self.predict_velocity(sample, t, condition)
        if self.text_guidance_scale == 1:
            return conditional
        unconditional = self._predict_velocity(sample, t, condition, self.negative_prompt_embeddings)
        return unconditional + self.text_guidance_scale * (conditional-unconditional)

    def _predict_velocity(self, sample: torch.Tensor, t: torch.Tensor, condition: SwapCondition,
                          prompt_embeddings: torch.Tensor) -> torch.Tensor:
        output_dtype = sample.dtype
        # Float32 t * bf16 latents promotes training samples to fp32. Cast explicitly
        # instead of relying on a caller's autocast context; gradients survive .to().
        sample = sample.to(device=self.latent_input.weight.device, dtype=self.latent_input.weight.dtype)
        b, c, h, w = sample.shape
        if t.shape != (b,):
            raise ValueError("FLUX continuous timesteps must have shape [batch]")
        mask = F.interpolate(condition.mask.to(sample), size=(h, w), mode="nearest")
        spatial = F.interpolate(condition.geometry.spatial.to(sample), size=(h, w), mode="bilinear", align_corners=False)
        identity = IdentityCondition(*(tensor.to(sample) for tensor in
            (condition.identity.global_embedding, condition.identity.local_tokens, condition.identity.structure)))
        features = self.latent_input(torch.cat([sample, mask, spatial], dim=1))
        features = self.identity_adapter(features, identity, mask)
        adapted = sample + self.latent_output(features) * mask
        reference = self._reference_latents(condition)
        packed = self._pipeline._pack_latents(adapted)
        reference_packed = self._pipeline._pack_latents(reference)
        ids = self._pipeline._prepare_latent_ids(sample).to(sample.device)
        # Batched templates stay paired with their own target; upstream reference helper assumes batch 1.
        reference_ids = self._pipeline._prepare_image_ids([reference[:1]]).to(sample.device).expand(b, -1, -1)
        identity_tokens = self.identity_context(conditioning_tokens(identity, self.structure_projection))
        geometry_token = self.geometry_context(torch.cat([condition.geometry.vector.to(sample), age_features(condition.age, sample)], -1))[:, None]
        prompt = prompt_embeddings.to(sample).expand(b, -1, -1)
        context = torch.cat([prompt, identity_tokens, geometry_token], dim=1)
        text_ids = self._pipeline._prepare_text_ids(context).to(sample.device)
        velocity = self.transformer(hidden_states=torch.cat([packed, reference_packed], dim=1),
                                    encoder_hidden_states=context, timestep=t.to(sample), guidance=None,
                                    img_ids=torch.cat([ids, reference_ids], dim=1), txt_ids=text_ids,
                                    return_dict=False)[0][:, :h*w]
        return velocity.transpose(1, 2).reshape(b, c, h, w).to(dtype=output_dtype)

    def sampling_schedule(self, steps: int, device: torch.device, spatial_shape: tuple[int, int]) -> torch.Tensor:
        if steps < 1 or len(spatial_shape) != 2 or min(spatial_shape) < 1:
            raise ValueError("Positive step count and latent spatial dimensions required")
        from diffusers.pipelines.flux2.pipeline_flux2_klein import compute_empirical_mu
        import numpy as np
        scheduler = self._pipeline.scheduler
        kwargs = {"sigmas": np.linspace(1.0, 1 / steps, steps), "mu": compute_empirical_mu(spatial_shape[0]*spatial_shape[1], steps)}
        if getattr(scheduler.config, "use_flow_sigmas", False):
            kwargs.pop("sigmas")
        scheduler.set_timesteps(steps, device=device, **kwargs)
        # Euler update uses sigma deltas. This follows scheduler's native shifted schedule.
        sigmas = scheduler.sigmas.to(device=device)
        if sigmas.numel() != steps + 1 or not torch.isfinite(sigmas).all() or not torch.all(sigmas[:-1] >= sigmas[1:]):
            raise RuntimeError("Unsupported FLUX scheduler: expected finite descending steps+1 sigma schedule")
        return sigmas
