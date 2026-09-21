"""Eksplisitt 9B-kontrakt. Arkitektur, variant og vektenes opphav er ulike kontroller."""
from __future__ import annotations

import json
from pathlib import Path
import struct

KLEIN_9B = "black-forest-labs/FLUX.2-klein-9B"
KLEIN_BASE_9B = "black-forest-labs/FLUX.2-klein-base-9B"
PROFILES = {KLEIN_9B: {"distilled": True, "guidance": 1.0},
            KLEIN_BASE_9B: {"distilled": False, "guidance": 4.0}}
ARCHITECTURE = {"in_channels": 128, "joint_attention_dim": 12288,
                "num_layers": 8, "num_single_layers": 24,
                "attention_head_dim": 128, "num_attention_heads": 32,
                "guidance_embeds": False}


def training_target(config, component="swap"):
    if component != "swap":
        return
    model = config.get("model", {})
    model_id = model.get("model_id")
    if model.get("backbone") != "flux_klein" or model_id not in PROFILES:
        raise ValueError("DreamPage skal trenes paa Klein 9B; eksplisitt 9B model_id kreves. 4B er utgaatt.")
    profile = PROFILES[model_id]
    guidance = float(model.get("text_guidance_scale", profile["guidance"]))
    if profile["distilled"] and guidance != 1.0:
        raise ValueError("Vanlig Klein 9B er distilled og skal bruke text_guidance_scale=1")


def validate_snapshot_config(index, transformer, model_id):
    if model_id not in PROFILES:
        raise ValueError("Bare Klein 9B-varianter er tillatt; ingen fallback til 4B")
    if index.get("_class_name") != "Flux2KleinPipeline" or index.get("is_distilled") is not PROFILES[model_id]["distilled"]:
        raise ValueError("Snapshot-varianten stemmer ikke med eksplisitt model_id/is_distilled")
    for key, expected in ARCHITECTURE.items():
        if transformer.get(key) != expected:
            raise ValueError(f"Klein 9B krever {key}={expected}; fikk {transformer.get(key)}")


def inspect_single_file(path):
    """Les kun safetensors-headeren; ikke last 18 GB vekter eller bruk GPU."""
    path = Path(path)
    with path.open("rb") as stream:
        prefix = stream.read(8)
        if len(prefix) != 8:
            raise ValueError("Ufullstendig safetensors-header")
        length = struct.unpack("<Q", prefix)[0]
        if length > 32 * 1024 * 1024 or length > path.stat().st_size - 8:
            raise ValueError("Ugyldig safetensors-headerlengde")
        header = json.loads(stream.read(length))
    shapes = {"img_in.weight": [4096, 128], "txt_in.weight": [4096, 12288],
              "double_blocks.7.img_attn.qkv.weight": [12288, 4096],
              "single_blocks.23.linear1.weight": [36864, 4096]}
    for key, shape in shapes.items():
        if header.get(key, {}).get("shape") != shape:
            raise ValueError(f"Checkpoint samsvarer ikke med Klein 9B: {key}")
    double = {int(k.split(".")[1]) for k in header if k.startswith("double_blocks.")}
    single = {int(k.split(".")[1]) for k in header if k.startswith("single_blocks.")}
    if double != set(range(8)) or single != set(range(24)):
        raise ValueError("Feil antall transformerblokker for Klein 9B")
    return {"path": str(path.resolve()), "bytes": path.stat().st_size,
            "architecture": "klein-9b", "architecture_verified": True,
            "variant_provenance_verified": False,
            "scope": "header only; distilled/base identity requires source/hash provenance"}
