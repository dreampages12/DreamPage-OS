from __future__ import annotations
import torch
from ..backbones import FluxKleinBackbone, TinyFlowBackbone
from ..dreamface import DreamFaceEncoder
from ..dreamswap import DreamSwap


def build_model(config: dict, device: str | torch.device = "cpu") -> DreamSwap:
    spec = config.get("model", config)
    identity_dim = int(spec.get("identity_dim", 64))
    structure_dim = int(spec.get("structure_dim", 16))
    encoder = DreamFaceEncoder(identity_dim, structure_dim, int(spec.get("token_grid", 4)))
    if spec.get("identity_checkpoint"):
        from ..dreamface.checkpoints import load_encoder_checkpoint
        pretrained, _ = load_encoder_checkpoint(spec["identity_checkpoint"])
        encoder.load_state_dict(pretrained.state_dict(), strict=True)
    if spec.get("freeze_encoder", False):
        if not spec.get("identity_checkpoint"):
            raise ValueError("freeze_encoder requires an independently trained identity_checkpoint")
        encoder.requires_grad_(False)
    if spec.get("backbone", "tiny") == "tiny":
        backbone = TinyFlowBackbone(identity_dim, structure_dim, int(spec.get("width", 32)))
    elif spec["backbone"] == "flux_klein":
        if not spec.get("weights_path"):
            raise ValueError("model.weights_path must identify a reviewed complete local BASE 4B Diffusers snapshot")
        dtype_name = spec.get("dtype", "bf16")
        if dtype_name not in ("bf16", "fp32"):
            raise ValueError("FLUX model.dtype must be bf16 or fp32")
        dtype = torch.bfloat16 if dtype_name == "bf16" else torch.float32
        backbone = FluxKleinBackbone.from_local_pretrained(spec["weights_path"], identity_dim=identity_dim,
                    structure_dim=structure_dim, device=str(device), dtype=dtype,
                    train_transformer=bool(spec.get("train_transformer", False)),
                    text_guidance_scale=float(spec.get("text_guidance_scale", 4.0)),
                    gradient_checkpointing=bool(spec.get("gradient_checkpointing", True)))
        encoder.to(dtype=dtype)
    else:
        raise ValueError(f"Unsupported backbone {spec['backbone']!r}")
    return DreamSwap(encoder, backbone).to(device)
