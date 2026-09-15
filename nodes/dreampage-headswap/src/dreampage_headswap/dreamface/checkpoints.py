"""Portable independently trained DreamFace checkpoints, separate from ComfyUI."""
from pathlib import Path

import torch

from .encoder import DreamFaceEncoder
from ..data.records import file_sha256


def load_encoder_checkpoint(path, *, device="cpu"):
    """Load a trusted local training checkpoint. This does not certify recognition quality."""
    state = torch.load(path, map_location="cpu", weights_only=False)
    if state.get("format_version") != 1 or state.get("metadata", {}).get("component") != "dreamface_encoder":
        raise ValueError("Expected an independently trained DreamFace encoder checkpoint")
    if state.get("step", 0) < 1:
        raise ValueError("Encoder checkpoint has no recorded training steps")
    spec = state["config"]["model"]
    encoder = DreamFaceEncoder(int(spec.get("identity_dim", 64)), int(spec.get("structure_dim", 16)),
                               int(spec.get("token_grid", 4)))
    encoder.load_state_dict(state["model"], strict=True)
    metadata = {**state["metadata"], "checkpoint_sha256": file_sha256(path),
                "checkpoint": str(Path(path).resolve()), "step": state["step"], "model": spec,
                "quality_claim": state.get("quality_claim")}
    return encoder.to(device), metadata
