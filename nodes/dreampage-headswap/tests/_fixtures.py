"""Deterministic synthetic fixtures.

These are procedural noise and rectangles. They exercise software behavior only, and no test in
this repository may be read as evidence about identity, realism or any other output quality.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPOSITORY = Path(__file__).resolve().parent.parent
SCRIPTS = REPOSITORY / "scripts"


def rights(**overrides) -> dict:
    """Minimal record that satisfies the rights gate. Synthetic fixtures, not people."""
    value = {"provenance": "procedurally generated test fixture",
             "license": "internal test fixture, no third-party rights",
             "consent": {"status": "granted", "reference": "fixture://no-human-subject",
                         "training_permitted": True},
             "training_permitted": True, "commercial_use_permitted": True,
             "customer_data": False}
    value.update(overrides)
    return value


def write_image(path: Path, seed: int, size: tuple[int, int] = (64, 64)) -> Path:
    """Structured noise: high enough Laplacian variance to pass the blur threshold."""
    path.parent.mkdir(parents=True, exist_ok=True)
    generator = np.random.default_rng(seed)
    array = generator.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)
    Image.fromarray(array).save(path)
    return path


def write_mask(path: Path, size: tuple[int, int] = (64, 64), box=(16, 12, 48, 44)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    array = np.zeros((size[1], size[0]), np.uint8)
    x0, y0, x1, y1 = box
    array[y0:y1, x0:x1] = 255
    Image.fromarray(array, mode="L").save(path)
    return path


def identity_row(root: Path, identity_id: str, seed: int, *, images: int = 2, split: str | None = None,
                 age: float | None = None, masked_from: int = 0, size=(64, 64)) -> dict:
    """One identity with `images` captures; captures from index `masked_from` carry a headmask.

    Enrollment expects a headmask on every capture, so the default masks all of them.
    """
    records = []
    for index in range(images):
        name = f"image_{index:03d}"
        image_path = write_image(root / identity_id / f"{name}.png", seed * 1000 + index, size)
        record = {"image_id": name, "path": str(image_path)}
        if index >= masked_from:
            record["headmask"] = str(write_mask(root / identity_id / f"{name}_mask.png", size))
        records.append(record)
    row = {"identity_id": identity_id, "rights": rights(), "synthetic": True, "images": records}
    if split:
        row["split"] = split
    if age is not None:
        row["age"] = age
    return row


def load_script(name: str):
    """Import a file in scripts/ as a module so its main(argv) can be called directly."""
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"dreampage_scripts_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def template_and_mask(size=(64, 48), box=(18, 10, 46, 38)):
    """Float RGB template plus an HW mask, matching the in-memory pipeline contract."""
    width, height = size
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    template = np.stack([xx / width, yy / height, np.full_like(xx, 0.4)], axis=-1).astype(np.float32)
    mask = np.zeros((height, width), np.float32)
    x0, y0, x1, y1 = box
    mask[y0:y1, x0:x1] = 1.0
    return template, mask


def reference_image(seed: int, size: int = 32) -> np.ndarray:
    generator = np.random.default_rng(seed)
    return generator.random((size, size, 3), dtype=np.float32)


def training_corpus(root: Path, *, identities: int = 4, resolution: int = 32, size=(96, 96),
                    validation: dict | None = None, validation_identities: int = 1) -> dict:
    """Write a small enrolled corpus and return a runnable tiny-backbone training config.

    Every identity is procedural noise, so a run over this corpus tests the loop and nothing else.
    """
    from dreampage_headswap.data.pairing import generate_pairs
    from dreampage_headswap.data.records import load_identities, write_jsonl

    manifest = root / "identities.jsonl"
    splits = ["train"] * identities + ["validation"] * validation_identities + ["test"]
    write_jsonl(manifest, [identity_row(root / "images", f"id_{index}", index + 1, split=split, size=size)
                           for index, split in enumerate(splits)])
    rows = generate_pairs(load_identities(manifest, allow_synthetic=True), seed=1, max_pairs_per_identity=1)
    written = {}
    for split in sorted({row["split"] for row in rows}):
        path = root / f"pairs.{split}.jsonl"
        write_jsonl(path, [row for row in rows if row["split"] == split])
        written[split] = str(path)
    return {"model": {"backbone": "tiny", "identity_dim": 32, "structure_dim": 16, "width": 24},
            "dataset": {"manifest": written["train"],
                        "peer_manifests": [written["validation"], written["test"]],
                        "resolution": resolution, "reference_count": 1, "allow_synthetic": True,
                        "degradation": "neutral"},
            "optimizer": {"name": "adamw", "lr": 0.001, "betas": [0.9, 0.999], "weight_decay": 0.01},
            "scheduler": {"name": "constant", "warmup_steps": 2},
            "training": {"device": "cpu", "precision": "fp32", "seed": 1234, "batch_size": 2,
                         "accumulation_steps": 1, "max_steps": 4, "gradient_clip": 1.0,
                         "checkpoint_every": 0, "log_every": 1000, "cpu_threads": 2,
                         "tracker": "jsonl", "output_dir": str(root / "run")},
            "losses": {"flow_matching": 1.0, "reconstruction": 1.0, "outside_mask": 3.0, "boundary": 1.0},
            **({"validation": {"manifest": written["validation"], "split": "validation", "every": 2,
                               "seed": 4321, "batch_size": 1, "max_batches": 4, "sampling_steps": 3,
                               **validation}} if validation is not None else {})}
