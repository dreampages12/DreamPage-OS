"""Add procedural corruption artifacts to a synthetic corpus for refiner mechanics tests."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import yaml

from dreampage_headswap.data.records import validate_pair_manifests, write_jsonl, file_sha256
from dreampage_headswap.masking import load_headmask
from dreampage_headswap.utils.images import load_rgb, save_rgb


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs-dir", required=True)
    parser.add_argument("--teacher-checkpoint", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    pairs = Path(args.pairs_dir).resolve()
    manifests = [pairs / f"pairs.{split}.jsonl" for split in ("train", "validation", "test")]
    rows = validate_pair_manifests(manifests, allow_synthetic=True)
    if not rows or any(row.get("synthetic") is not True for row in rows):
        raise ValueError("This tool may only generate artifacts for explicitly synthetic fixtures")
    if not Path(args.teacher_checkpoint).is_file():
        raise FileNotFoundError("Run the separate identity trainer before creating this refiner fixture")
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    recipe = {"kind": "procedural_fixture", "seed": 1234, "color_bias": [0.035, -0.02, 0.025],
              "noise_std": 0.005, "scope": "Synthetic perturbations; not DreamSwap face outputs"}
    encoded = json.dumps(recipe, sort_keys=True).encode()
    recipe_hash = hashlib.sha256(encoded).hexdigest()
    (output / "recipe.json").write_bytes(encoded)
    artifacts = []
    for index, row in enumerate(rows):
        template = load_rgb(row["ground_truth"])
        mask = load_headmask(row["headmask"], channel=row.get("mask_channel", "red")).values
        rng = np.random.default_rng(recipe["seed"] + index)
        changed = template.astype(np.float32) / 255 + recipe["color_bias"] + rng.normal(0, recipe["noise_std"], template.shape)
        generated = template.copy()
        generated[mask > 0] = np.rint(changed.clip(0, 1) * 255).astype(np.uint8)[mask > 0]
        path = output / "images" / (row["pair_id"] + ".png")
        save_rgb(path, generated)
        artifacts.append({"pair_id": row["pair_id"], "generated": str(path), "sha256": file_sha256(path),
                          "generator": {"kind": "procedural_fixture", "recipe_sha256": recipe_hash}})
    write_jsonl(output / "artifacts.jsonl", artifacts)
    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root / "configs/training/refiner.yaml").read_text(encoding="utf-8"))
    config["teacher"] = {"checkpoint": str(Path(args.teacher_checkpoint).resolve()), "allow_unvalidated_for_synthetic": True}
    config["dataset"].update(manifest=str(manifests[0]), peer_manifests=[str(p) for p in manifests[1:]],
                              artifacts_manifest=str(output / "artifacts.jsonl"), allow_synthetic=True,
                              registry_path=str(pairs / "dataset_registry.json"))
    config["training"].update(max_steps=6, checkpoint_every=3, log_every=1, output_dir=str(output / "training_run"))
    config["validation"].update(manifest=str(manifests[1]), every=3, max_batches=2)
    path = output / "refiner_smoke.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    print(json.dumps({"artifacts": len(artifacts), "training_config": str(path), "scope": recipe["scope"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
