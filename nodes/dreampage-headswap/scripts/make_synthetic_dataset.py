"""Create procedural colored shapes for data/training plumbing; NEVER real training identities."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw

from dreampage_headswap.data import generate_pairs, load_identities, validate_pair_manifests
from dreampage_headswap.data.records import write_jsonl
from dreampage_headswap.data.registry import create_registry


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, help="A fresh directory; nothing is overwritten")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--resolution", type=int, default=64)
    parser.add_argument("--captures", type=int, default=3)
    parser.add_argument("--identities", type=int, default=4,
                        help="Half go to train, a quarter each to validation and test. "
                             "The contrastive identity objective needs at least two per split")
    args = parser.parse_args(argv)
    if args.resolution < 32 or args.captures < 2:
        parser.error("resolution must be >=32 and captures >=2")
    if args.identities < 4:
        parser.error("at least four identities are required to fill three splits")
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    rng = np.random.default_rng(args.seed)
    identities = []
    held_out = max(1, args.identities // 4)
    splits = (["train"] * (args.identities - 2 * held_out) + ["validation"] * held_out + ["test"] * held_out)
    for index, split in enumerate(splits):
        identity_id = f"synthetic_shape_{index:03d}"
        image_records = []
        color = tuple(int(value) for value in rng.integers(45, 220, 3))
        for capture in range(args.captures):
            size = args.resolution
            # Fine deterministic texture keeps this fixture useful for image-integrity/blur plumbing.
            pixels = rng.integers(20, 75, (size, size, 3), dtype=np.uint8)
            image = Image.fromarray(pixels)
            draw = ImageDraw.Draw(image)
            offset = capture - args.captures // 2
            box = (size // 4 + offset, size // 5, 3 * size // 4 + offset, 4 * size // 5)
            draw.ellipse(box, fill=color)
            draw.rectangle((size // 3, size // 2, size // 3 + 3, size // 2 + 3), fill=(255, 255, 255))
            mask = Image.new("RGB", (size, size), (0, 0, 0))
            ImageDraw.Draw(mask).ellipse(box, fill=(255, 0, 0))
            directory = output / "images" / identity_id
            directory.mkdir(parents=True, exist_ok=True)
            image_path, mask_path = directory / f"capture_{capture:02d}.png", directory / f"capture_{capture:02d}_mask.png"
            image.save(image_path)
            mask.save(mask_path)
            image_records.append({"image_id": f"capture_{capture:02d}", "path": str(image_path),
                                  "headmask": str(mask_path), "mask_channel": "red"})
        identities.append({"identity_id": identity_id, "split": split, "synthetic": True,
                           "rights": {"provenance": "Procedural shapes; no people, customer images or external assets",
                                      "license": "Project-owned procedural fixture",
                                      "consent": {"status": "granted", "reference": "fixture://no-human-subject",
                                                  "training_permitted": True},
                                      "training_permitted": True, "commercial_use_permitted": True, "customer_data": False},
                           "images": image_records})
    identity_manifest = output / "identities.jsonl"
    write_jsonl(identity_manifest, identities)
    rows = generate_pairs(load_identities(identity_manifest, allow_synthetic=True), seed=args.seed)
    manifests = {}
    for split in ("train", "validation", "test"):
        path = output / f"pairs.{split}.jsonl"
        write_jsonl(path, [row for row in rows if row["split"] == split])
        manifests[split] = path
    validate_pair_manifests(manifests.values(), allow_synthetic=True)
    registry_path = output / "dataset_registry.json"
    create_registry(manifests.values(), registry_path, identity_manifest=identity_manifest)
    repository = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((repository / "configs" / "training" / "tiny.yaml").read_text(encoding="utf-8"))
    config["dataset"].update(manifest=str(manifests["train"]),
                             peer_manifests=[str(manifests["validation"]), str(manifests["test"])],
                             registry_path=str(registry_path), resolution=args.resolution,
                             allow_synthetic=True, mask_channel="red")
    config["training"].update(max_steps=6, checkpoint_every=3, log_every=1,
                              output_dir=str(output / "training_run"))
    config["validation"].update(manifest=str(manifests["validation"]), every=3, max_batches=2, samples=True)
    config_path = output / "training_smoke.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    identity_path = output / "identity_smoke.yaml"
    identity_path.write_text(yaml.safe_dump(_identity_config(repository, config, manifests, splits, output),
                                            sort_keys=False), encoding="utf-8")
    notice = "SYNTHETIC SOFTWARE FIXTURE: NOT FACE TRAINING IDENTITIES AND NOT A QUALITY BENCHMARK.\n"
    (output / "SYNTHETIC_FIXTURE.txt").write_text(notice, encoding="utf-8")
    print(json.dumps({"scope": notice.strip(), "identities": str(identity_manifest), "pair_count": len(rows),
                      "registry": str(registry_path), "training_config": str(config_path),
                      "identity_encoder_config": str(identity_path)}, indent=2))
    return 0


def _identity_config(repository, training_config, manifests, splits, output) -> dict:
    """The same fixture, shaped for the DreamFace encoder trainer.

    The contrastive objective needs several distinct identities per batch, so the validation
    section is written only when the held-out split actually holds two of them.
    """
    config = yaml.safe_load((repository / "configs" / "training" / "identity_encoder_tiny.yaml").read_text(encoding="utf-8"))
    config["dataset"].update(training_config["dataset"])
    config["dataset"]["source_crops"] = True
    config["objective"]["identities_per_batch"] = min(2, splits.count("train"))
    config["training"].update(max_steps=4, checkpoint_every=2, log_every=1,
                              output_dir=str(output / "identity_run"))
    if splits.count("validation") >= 2:
        config["validation"].update(manifest=str(manifests["validation"]), every=2,
                                    identities_per_batch=2, max_batches=2)
    else:
        config.pop("validation")
    return config


if __name__ == "__main__":
    raise SystemExit(main())
