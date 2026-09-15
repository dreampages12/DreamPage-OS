"""Train a bounded DreamRefine model using paired artifacts and a separate frozen teacher."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import time

import torch
from torch.utils.data import DataLoader
import yaml

from ..data.refinement import RefinementDataset
from ..data.records import file_sha256
from ..dreamface.checkpoints import load_encoder_checkpoint
from ..dreamface import DreamFaceEncoder
from ..dreamrefine import DreamRefine
from ..dreamrefine.system import RefinementSystem, RefinementObjective
from ..utils.checkpoint import load_checkpoint, save_checkpoint, seed_everything, rng_state, restore_rng
from ..utils.tracking import JsonlTracker, NullTracker, TensorBoardTracker
from .loop import make_optimizer, make_scheduler, move_batch, pair_dataset_options, _epoch_batches
from .validation import dataset_fingerprint


def verify_teacher(teacher_config, metadata, datasets):
    """A synthetic-only escape hatch cannot authorize an unvalidated teacher on real people."""
    smoke = teacher_config.get("allow_unvalidated_for_synthetic", False)
    if not isinstance(smoke, bool):
        raise ValueError("allow_unvalidated_for_synthetic must be a boolean")
    if smoke:
        if metadata.get("synthetic") is not True or any(row.get("synthetic") is not True
                for dataset in datasets if dataset is not None for row in dataset.rows):
            raise ValueError("Unvalidated teacher smoke mode is restricted to synthetic teacher and synthetic data")
        return {"validated": False, "scope": "synthetic mechanics only"}
    path = teacher_config.get("review")
    if not path:
        raise ValueError("Real refinement training requires teacher.review with independent validation and commercial-use evidence")
    identities = metadata.get("training_identity_ids")
    if not isinstance(identities, list) or not identities or any(not isinstance(value, str) for value in identities):
        raise ValueError("Real refinement requires the teacher's training identity inventory for validation leakage checks")
    path = Path(path).resolve()
    review = json.loads(path.read_text(encoding="utf-8"))
    if review.get("checkpoint_sha256") != metadata["checkpoint_sha256"] or review.get("commercial_use_reviewed") is not True:
        raise ValueError("Teacher review must bind this exact checkpoint and its reviewed commercial use")
    report = review.get("independent_validation_report")
    if not isinstance(report, str) or not report:
        raise ValueError("Teacher review needs an independent validation report")
    report = (path.parent / report).resolve()
    if not report.is_file() or review.get("independent_validation_sha256") != file_sha256(report):
        raise ValueError("Independent teacher validation report is missing or its hash differs")
    return {"validated": True, "review_sha256": file_sha256(path), "report_sha256": file_sha256(report),
            "scope": "Review-backed frozen training teacher; not an automatic output-quality certification"}


def build_refinement_system(config, *, device="cpu"):
    teacher_spec = config.get("teacher", {})
    if not teacher_spec.get("checkpoint"):
        raise ValueError("teacher.checkpoint must be an independently trained DreamFace checkpoint")
    teacher, metadata = load_encoder_checkpoint(teacher_spec["checkpoint"], device=device)
    model_spec = config.get("model", {})
    refiner = DreamRefine(teacher.dim, teacher.structure_dim, int(model_spec.get("width", 32)),
                          float(model_spec.get("max_delta", 0.08))).to(device)
    return RefinementSystem(teacher, refiner), metadata


def load_refinement_system(path, *, device="cpu", dtype=torch.float32):
    """Serving loads the exact frozen encoder bundled with the refiner, never a different generator encoder."""
    state = torch.load(path, map_location="cpu", weights_only=False)
    meta = state.get("metadata", {})
    if state.get("format_version") != 1 or meta.get("component") != "dreamrefine_system":
        raise ValueError("Expected a complete DreamRefine system checkpoint with its frozen encoder")
    encoder_spec = meta["teacher"]["model"]
    encoder = DreamFaceEncoder(int(encoder_spec.get("identity_dim", 64)), int(encoder_spec.get("structure_dim", 16)),
                                int(encoder_spec.get("token_grid", 4)))
    spec = state["config"].get("model", {})
    system = RefinementSystem(encoder, DreamRefine(encoder.dim, encoder.structure_dim,
                              int(spec.get("width", 32)), float(spec.get("max_delta", 0.08))))
    system.load_state_dict(state["model"], strict=True)
    return system.to(device=device, dtype=dtype).eval()


@torch.no_grad()
def validate_refiner(system, dataset, objective, *, settings, device, dtype, sample_directory=None):
    saved_rng, was_training = rng_state(), system.training
    totals, count = {}, 0
    try:
        seed_everything(int(settings.get("seed", 4321)))
        system.eval()
        loader = DataLoader(dataset, batch_size=int(settings.get("batch_size", 1)), shuffle=False,
                            generator=torch.Generator().manual_seed(4321))
        for index, batch in enumerate(loader):
            if index >= int(settings.get("max_batches", 8)):
                break
            batch = move_batch(batch, device, dtype)
            _, metrics, prediction = objective(system, batch)
            n = batch["template"].shape[0]
            for name, value in metrics.items():
                totals[name] = totals.get(name, 0) + value * n
            count += n
            if sample_directory and index == 0:
                from ..utils.images import save_rgb, from_tensor
                for name, tensor in (("generated", batch["generated"]), ("refined", prediction), ("target", batch["target"])):
                    save_rgb(Path(sample_directory) / (name + ".png"), from_tensor(tensor[:1]))
        if not count:
            raise ValueError("Refiner validation produced no batches")
        return {"validation/" + name: value / count for name, value in totals.items()}
    finally:
        system.train(was_training)
        restore_rng(saved_rng)


def train_refiner(config, resume=None):
    if int(os.getenv("WORLD_SIZE", "1")) != 1:
        raise ValueError("Refiner trainer currently supports a single process; distributed refinement is not validated")
    settings, data, validation = config.get("training", {}), config["dataset"], config.get("validation", {})
    seed = int(settings.get("seed", 1234))
    seed_everything(seed)
    torch.set_num_threads(int(settings.get("cpu_threads", 2)))
    device = torch.device(settings.get("device", "cpu"))
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    precision = settings.get("precision", "fp32")
    if precision not in {"fp32", "bf16"}:
        raise ValueError("Refiner precision must be fp32 or bf16")
    if precision == "bf16" and device.type == "cuda" and not torch.cuda.is_bf16_supported():
        raise ValueError("Selected GPU does not support bf16")
    batch_size, accumulation = int(settings.get("batch_size", 2)), int(settings.get("accumulation_steps", 1))
    steps, log_every = int(settings.get("max_steps", 1000)), int(settings.get("log_every", 20))
    interval, val_interval = int(settings.get("checkpoint_every", 100)), int(validation.get("every", 0))
    clip = float(settings.get("gradient_clip", 1.0))
    if min(batch_size, accumulation, steps, log_every) < 1 or min(interval, val_interval) < 0 or not math.isfinite(clip) or clip <= 0:
        raise ValueError("Invalid refiner training intervals, batch size or gradient clip")
    options = {**pair_dataset_options(data), "resolution": int(data.get("resolution", 64)),
               "reference_count": int(data.get("reference_count", 1)), "artifacts_manifest": data["artifacts_manifest"]}
    train_data = RefinementDataset(data["manifest"], split="train", peer_manifests=data.get("peer_manifests", []), **options)
    val_data = (RefinementDataset(validation.get("manifest", data["manifest"]), split="validation",
                peer_manifests=[data["manifest"], *data.get("peer_manifests", [])], **options) if validation else None)
    per_epoch = len(train_data) // batch_size
    if not per_epoch:
        raise ValueError("Refiner dataset is smaller than one batch")
    system, teacher_meta = build_refinement_system(config, device=device)
    review = verify_teacher(config["teacher"], teacher_meta, [train_data, val_data])
    if val_data is not None and set(teacher_meta.get("training_identity_ids", [])) & {r["identity_id"] for r in val_data.rows}:
        raise ValueError("Refiner validation identities overlap the teacher's training identities")
    objective = RefinementObjective(config["losses"])
    optimizer, scheduler = make_optimizer(system, config), None
    scheduler = make_scheduler(optimizer, config)
    fingerprint = dataset_fingerprint(train_data, val_data)
    output = Path(settings.get("output_dir", "runs/refiner"))
    checkpoint, best_path = output / "checkpoint.pt", output / "checkpoint.best.pt"
    step, cursor, best = 0, 0, None
    if resume:
        state = load_checkpoint(resume, system, optimizer, scheduler, expected_config=config, map_location=device)
        meta = state["metadata"]
        if meta.get("dataset_fingerprint") != fingerprint or meta.get("teacher", {}).get("checkpoint_sha256") != teacher_meta["checkpoint_sha256"]:
            raise ValueError("Cannot exactly resume: refiner data or frozen teacher changed")
        step, cursor, best = state["step"], state["data_cursor"], meta.get("best_score")
    tracker_name = settings.get("tracker", "jsonl")
    if tracker_name not in {"none", "jsonl", "tensorboard"}:
        raise ValueError("Unknown refiner tracker")
    output.mkdir(parents=True, exist_ok=True)
    tracker = (NullTracker() if tracker_name == "none" else TensorBoardTracker(output / "tensorboard")
               if tracker_name == "tensorboard" else JsonlTracker(output / "metrics.jsonl"))
    history, val_history = [], []
    epoch, offset = divmod(cursor, per_epoch)
    iterator = iter(_epoch_batches(train_data, batch_size, seed, epoch, 0, 1))
    for _ in range(offset):
        next(iterator)
    system.train()
    dtype = next(system.parameters()).dtype
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    try:
        while step < steps:
            started = time.perf_counter()
            optimizer.zero_grad(set_to_none=True)
            metrics = {}
            for micro in range(accumulation):
                epoch, offset = divmod(cursor, per_epoch)
                if offset == 0 and cursor > 0:
                    iterator = iter(_epoch_batches(train_data, batch_size, seed, epoch, 0, 1))
                batch = move_batch(next(iterator), device, dtype)
                with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=precision == "bf16"):
                    loss, measured, _ = objective(system, batch)
                (loss / accumulation).backward()
                for name, value in measured.items():
                    metrics[name] = metrics.get(name, 0) + value / accumulation
                cursor += 1
            norm = torch.nn.utils.clip_grad_norm_(system.refiner.parameters(), clip)
            if not torch.isfinite(norm):
                raise FloatingPointError("Non-finite refiner gradient; no optimizer step taken")
            optimizer.step()
            scheduler.step()
            step += 1
            if device.type == "cuda":
                torch.cuda.synchronize(device)
            metrics.update(lr=optimizer.param_groups[0]["lr"], pairs_per_second=batch_size * accumulation / (time.perf_counter() - started))
            if device.type == "cuda":
                metrics["peak_vram_bytes"] = torch.cuda.max_memory_allocated(device)
            tracker.log(step, metrics)
            history.append(metrics["total"])
            if step == 1 or step % log_every == 0:
                print(json.dumps({"step": step, **metrics}), flush=True)
            metadata = {"component": "dreamrefine_system", "teacher": teacher_meta, "teacher_review": review,
                        "dataset_fingerprint": fingerprint, "synthetic": all(r.get("synthetic") is True for r in train_data.rows),
                        "identity_quality_validated": False, "production_ready": False}
            if val_data is not None and (step == steps or (val_interval and step % val_interval == 0)):
                measured = validate_refiner(system, val_data, objective, settings=validation, device=device, dtype=dtype,
                                sample_directory=output / "samples" / f"step_{step:08d}" if validation.get("samples") else None)
                tracker.log(step, measured)
                val_history.append({"step": step, **measured})
                if best is None or measured["validation/total"] < best:
                    best = measured["validation/total"]
                    save_checkpoint(best_path, system, optimizer, scheduler, config=config, step=step, data_cursor=cursor,
                                     metadata={**metadata, "best_score": best, "validation": measured})
            if step == steps or (interval and step % interval == 0):
                save_checkpoint(checkpoint, system, optimizer, scheduler, config=config, step=step, data_cursor=cursor,
                                 metadata={**metadata, "best_score": best})
    finally:
        tracker.close()
    return {"step": step, "checkpoint": str(checkpoint.resolve()), "loss_history": history,
            "validation_history": val_history, "best_checkpoint": str(best_path.resolve()) if best_path.is_file() else None,
            "teacher_frozen": True, "teacher_review": review, "identity_quality_validated": False,
            "scope": "Paired residual-reconstruction experiment; automatic loss is not proof of realism"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--resume")
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    print(json.dumps(train_refiner(config, args.resume), indent=2))


if __name__ == "__main__":
    main()
