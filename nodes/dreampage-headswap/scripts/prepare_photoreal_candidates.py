"""Inference-only candidate acquisition. Never enrolls data or runs an optimizer.

Encode prompts first, release the Qwen model, then load the image model.
Every image remains pending visual review and explicit user dataset approval.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import hashlib
import html
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from dreampage_headswap.data.records import file_sha256

MODEL_ID = "black-forest-labs/FLUX.2-klein-base-4B"
REVISION = "a3b4f4849157f664bdbc776fd7453c2783562f4d"
PHOTO = ("An unretouched, lifelike camera photograph, head and shoulders with the entire head, "
         "hair, ears and chin inside the frame and comfortable space above the hair. "
         "Ordinary natural appearance, age-appropriate skin texture, believable individual "
         "features and natural facial asymmetry, individual hair strands, realistic eyes and "
         "anatomy, sharp facial detail, natural photographic color. ")


def prompts(config):
    result = {"negative": ""}
    for identity in config["identities"]:
        for view in config["views"]:
            result[identity["id"] + "_" + view["id"]] = (
                PHOTO + "The subject is " + identity["description"] + ". " + view["instruction"])
    return result


def verify_snapshot(model_path, *, text_only=False):
    """Check downloaded files even for prompt encoding during acquisition."""
    from huggingface_hub import HfApi
    info = HfApi().model_info(MODEL_ID, revision=REVISION, files_metadata=True, token=False)
    selected = [f for f in info.siblings if
                f.rfilename.startswith(("text_encoder/", "tokenizer/")) or
                (not text_only and f.rfilename.startswith(("transformer/", "vae/", "scheduler/")))]
    if info.sha != REVISION or info.card_data.get("license") != "apache-2.0":
        raise RuntimeError("Unexpected upstream model provenance")
    for entry in selected:
        path = model_path / entry.rfilename
        if not path.is_file() or path.stat().st_size != entry.size:
            raise RuntimeError("Wait for the verified download to finish: " + entry.rfilename)
        if entry.lfs:
            valid = file_sha256(path) == entry.lfs.sha256
        else:
            valid = hashlib.sha1(f"blob {entry.size}\0".encode() + path.read_bytes()).hexdigest() == entry.blob_id
        if not valid:
            raise RuntimeError("Model file content mismatch: " + entry.rfilename)


def encode(config, model_path, output, config_hash, device="cpu"):
    import torch
    from diffusers import Flux2KleinPipeline
    from transformers import Qwen3ForCausalLM, Qwen2TokenizerFast
    from safetensors.torch import save_file
    verify_snapshot(model_path, text_only=True)
    torch.set_num_threads(4)
    torch.set_grad_enabled(False)
    if device == "cuda" and torch.cuda.mem_get_info()[0] < 10 * 1024**3:
        raise RuntimeError("Prompt inference requires at least 10 GiB free GPU memory")
    tokenizer = Qwen2TokenizerFast.from_pretrained(model_path / "tokenizer", local_files_only=True)
    encoder = Qwen3ForCausalLM.from_pretrained(model_path / "text_encoder", torch_dtype=torch.bfloat16,
                                              low_cpu_mem_usage=True, local_files_only=True).eval().to(device)
    encoder.requires_grad_(False)
    encoded = {}
    with torch.inference_mode():
        for key, prompt in prompts(config).items():
            started = time.perf_counter()
            encoded[key] = Flux2KleinPipeline._get_qwen3_prompt_embeds(
                encoder, tokenizer, prompt, device=torch.device(device), dtype=torch.bfloat16,
                max_sequence_length=int(config["max_sequence_length"])).cpu().contiguous()
            print(json.dumps({"event": "prompt_encoded", "key": key,
                              "seconds": time.perf_counter() - started}), flush=True)
    save_file(encoded, output / "prompts.safetensors",
              metadata={"config_sha256": config_hash, "model_revision": REVISION})
    del encoder, tokenizer, encoded
    gc.collect()


def write_review(output, records, config_hash):
    manifest = {"status": "pending_user_approval", "training_approved": False,
        "photorealism_review_complete": False, "identity_consistency_review_complete": False,
        "model_id": MODEL_ID, "model_revision": REVISION, "model_license": "Apache-2.0",
        "source": f"https://huggingface.co/{MODEL_ID}/blob/{REVISION}/LICENSE.md",
        "config_sha256": config_hash, "synthetic": True, "real_person_references_used": False,
        "training_executed": False, "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Twelve proposed images of four fictional children; a source-quality pilot, not sufficient training data",
        "limitations": ["Generated variants may drift in identity or apparent age; review every image",
                       "Prompted age and pose are intentions, not measured ground truth",
                       "No reviewed headmasks or training pairs exist yet",
                       "Synthetic data cannot establish real-child generalization"], "images": records}
    (output / "candidates.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    panels = []
    for row in records:
        panels.append(f'<figure><img src="{html.escape(row["path"])}"><figcaption>'
                      f'{html.escape(row["identity_id"])} / {html.escape(row["view"])}<br>'
                      'Uavklart: fotorealisme og samme identitet</figcaption></figure>')
    page = ('<!doctype html><html lang="nb"><meta charset="utf-8"><title>Datasettkandidater</title>'
            '<style>body{font:17px system-ui;max-width:1500px;margin:40px auto;background:#f4f4f1;padding:20px}'
            '.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}figure{margin:0;background:white;padding:12px}'
            'img{width:100%;display:block}figcaption{padding-top:8px;font-size:14px}'
            '@media(max-width:800px){.grid{grid-template-columns:1fr}}</style>'
            '<h1>Bildekandidater til gjennomgang</h1><p><strong>Ikke godkjent for trening.</strong> '
            'AI-genererte, fiktive personer. Ingen trening er startet.</p>'
            '<p>Vurder fotorealisme, øyne/tenner/hår og om alle tre bilder viser samme barn. '
            'Alder og positur i promptene er mål, ikke verifiserte etiketter. '
            'Dette er en liten vurdering av datakilden; et komplett datasett må gjennomgås og godkjennes separat.</p>'
            f'<div class="grid">{"".join(panels)}</div></html>')
    (output / "review.html").write_text(page, encoding="utf-8")


def sample(config, model_path, output, config_hash):
    import torch
    from diffusers import Flux2KleinPipeline
    from PIL import Image
    from safetensors import safe_open
    from safetensors.torch import load_file
    verify_snapshot(model_path)
    cache = output / "prompts.safetensors"
    with safe_open(cache, framework="pt") as handle:
        if handle.metadata() != {"config_sha256": config_hash, "model_revision": REVISION}:
            raise RuntimeError("Prompt cache belongs to another candidate configuration")
    free, _ = torch.cuda.mem_get_info()
    if free < 11 * 1024**3:
        raise RuntimeError("Candidate inference requires at least 11 GiB currently free GPU memory; do not interrupt active jobs")
    torch.set_num_threads(4)
    torch.set_grad_enabled(False)
    pipeline = Flux2KleinPipeline.from_pretrained(model_path, text_encoder=None, tokenizer=None,
                                                 torch_dtype=torch.bfloat16, local_files_only=True)
    pipeline.transformer.requires_grad_(False).eval()
    pipeline.vae.requires_grad_(False).eval()
    pipeline.to("cuda")
    embeddings = load_file(cache, device="cuda")
    records, all_prompts = [], prompts(config)
    (output / "images").mkdir(exist_ok=True)
    for identity_index, identity in enumerate(config["identities"]):
        base_image = None
        for view_index, view in enumerate(config["views"]):
            key = identity["id"] + "_" + view["id"]
            destination = output / "images" / (key + ".png")
            if destination.exists():
                raise RuntimeError("Use a fresh output directory; candidate image already exists: " + str(destination))
            seed = int(config["seed"]) + identity_index * 100 + view_index
            started = time.perf_counter()
            with torch.inference_mode():
                generated = pipeline(image=base_image, prompt_embeds=embeddings[key],
                    negative_prompt_embeds=embeddings["negative"], height=int(config["resolution"]),
                    width=int(config["resolution"]), num_inference_steps=int(config["steps"]),
                    guidance_scale=float(config["guidance_scale"]),
                    generator=torch.Generator("cuda").manual_seed(seed)).images[0]
            generated.save(destination)
            if base_image is None:
                base_image = Image.open(destination).convert("RGB")
            records.append({"identity_id": identity["id"], "view": view["id"],
                "path": destination.relative_to(output).as_posix(), "sha256": file_sha256(destination),
                "prompt": all_prompts[key], "intended_age": identity["intended_age"], "seed": seed,
                "reference": None if view_index == 0 else f'images/{identity["id"]}_{config["views"][0]["id"]}.png',
                "seconds": time.perf_counter() - started, "approved_for_training": False})
            write_review(output, records, config_hash)
            print(json.dumps({"event": "candidate_saved", "path": str(destination),
                              "seconds": records[-1]["seconds"], "training_executed": False}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/data/photoreal_candidates.json")
    parser.add_argument("--stage", required=True, choices=["encode", "sample"])
    parser.add_argument("--text-device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()
    raw = Path(args.config).read_bytes()
    config, config_hash = json.loads(raw), hashlib.sha256(raw).hexdigest()
    model_path, output = (ROOT / config["model_path"]).resolve(), (ROOT / config["output_dir"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "candidate_config.json").write_bytes(raw)
    if args.stage == "encode":
        encode(config, model_path, output, config_hash, args.text_device)
    else:
        sample(config, model_path, output, config_hash)


if __name__ == "__main__":
    main()
