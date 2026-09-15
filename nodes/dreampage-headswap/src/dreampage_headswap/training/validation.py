"""Deterministic held-out validation, isolated from the training random stream."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from ..data.records import file_sha256
from ..types import GeometryCondition
from ..utils.checkpoint import rng_state, restore_rng, seed_everything


def dataset_fingerprint(*datasets) -> str:
    """Bind exact resume to actual enrolled records AND asset bytes, not just path strings."""
    rows, paths = [], set()
    for dataset in datasets:
        if dataset is None:
            continue
        for row in dataset.rows:
            rows.append(row)
            paths.update(row["sources"])
            paths.update(row.get("source_headmasks", []))
            paths.update(row[k] for k in ("template", "ground_truth", "headmask"))
            if row.get("generated"):
                paths.add(row["generated"])
    payload = {"records": rows, "files": {str(path): file_sha256(path) for path in sorted(paths)}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


@torch.no_grad()
def validate_flow(model, dataset, loss_suite, *, settings: dict, device, dtype,
                  degradation="neutral", sample_directory: str | Path | None = None) -> dict[str, float]:
    from .loop import flow_objective, move_batch
    previous_rng, was_training = rng_state(), model.training
    totals, seen = {}, 0
    seed = int(settings.get("seed", 4321))
    batch_size = int(settings.get("batch_size", 1))
    max_batches = int(settings.get("max_batches", 8))
    if batch_size < 1 or max_batches < 1:
        raise ValueError("Validation batch_size/max_batches must be positive")
    try:
        seed_everything(seed)
        model.eval()
        loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=0,
                            generator=torch.Generator().manual_seed(seed))
        for index, batch in enumerate(loader):
            if index >= max_batches:
                break
            batch = move_batch(batch, device, dtype)
            _, metrics = flow_objective(model, batch, loss_suite, degradation=degradation, seed=seed + index)
            count = batch["target"].shape[0]
            for name, value in metrics.items():
                totals[name] = totals.get(name, 0.0) + value * count
            seen += count
            if sample_directory is not None and index == 0:
                _sample_grid(model, batch, sample_directory, degradation, seed, int(settings.get("sampling_steps", 8)))
        if not seen:
            raise ValueError("Validation dataset is empty")
        result = {"validation/" + name: value / seen for name, value in totals.items()}
        result["validation/pairs"] = seen
        return result
    finally:
        model.train(was_training)
        restore_rng(previous_rng)


@torch.no_grad()
def _sample_grid(model, batch, directory, degradation, seed, steps):
    from PIL import Image, ImageDraw
    import numpy as np

    from .loop import condition_template

    template, mask = batch["template"], (batch["mask"] > 0).to(batch["template"])
    geometry = GeometryCondition(batch["geometry_spatial"], batch["geometry_vector"])
    generated = model.sample(batch["references"], template, mask, geometry, batch.get("age"),
                             steps=steps, seed=seed,
                             condition_template=condition_template(batch, mask, degradation, seed))
    panels = [batch["references"][0, 0], template[0], generated[0], batch["target"][0]]
    h, w = template.shape[-2:]
    canvas = Image.new("RGB", (4 * w, h + 24), "white")
    draw = ImageDraw.Draw(canvas)
    for index, (panel, title) in enumerate(zip(panels, ("Reference", "Template", "Sample", "Target"))):
        array = np.rint(panel.detach().float().cpu().permute(1, 2, 0).numpy().clip(0, 1) * 255).astype(np.uint8)
        canvas.paste(Image.fromarray(array).resize((w, h)), (index * w, 24))
        draw.text((index * w + 2, 4), title, fill="black")
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    canvas.save(path / "sample.png")
