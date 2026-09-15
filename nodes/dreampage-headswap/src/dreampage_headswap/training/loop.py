from __future__ import annotations
import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import time

import torch
from torch import distributed as dist
from torch.nn.parallel import DistributedDataParallel
from torch.utils.data import DataLoader, Subset
import yaml

from .factory import build_model
from ..data import PairDataset
from ..losses import LossSuite
from ..template.degradation import suppress_template
from ..types import GeometryCondition
from ..utils.checkpoint import load_checkpoint, save_checkpoint, seed_everything
from ..utils.tracking import JsonlTracker, NullTracker, TensorBoardTracker
from .validation import dataset_fingerprint, validate_flow


def move_batch(batch: dict, device, dtype=torch.float32) -> dict:
    return {key: value.to(device=device, dtype=dtype if value.is_floating_point() else value.dtype)
            if isinstance(value, torch.Tensor) else value for key, value in batch.items()}


def condition_template(batch: dict, mask: torch.Tensor, degradation: str, seed: int) -> torch.Tensor:
    """The identity-suppressed template the model is allowed to see.

    Prefer the dataset's crop, which suppressed the native template BEFORE the crop was
    resized. Suppressing here instead would let interpolation carry the target face into
    neighbouring pixels first, which is the leak this indirection exists to prevent.
    Only batches without a prepared crop, such as the synthetic overfit fixture, fall back.
    """
    prepared = batch.get("condition_template")
    if prepared is None:
        return suppress_template(batch["template"], mask, strategy=degradation, seed=seed)
    strategies = batch.get("condition_strategy", degradation)
    strategies = [strategies] if isinstance(strategies, str) else list(strategies)
    if any(strategy != degradation for strategy in strategies):
        raise ValueError(f"Dataset prepared {sorted(set(strategies))} crops but training requests {degradation!r}; "
                         "set dataset.degradation and the training degradation to the same strategy")
    return prepared.to(batch["template"])


def flow_objective(model, batch: dict, loss_suite: LossSuite, *, degradation="neutral", seed=0,
                   noise: torch.Tensor | None = None, timestep: torch.Tensor | None = None):
    raw_model = model.module if isinstance(model, DistributedDataParallel) else model
    target = batch["target"]
    # Geometry is independent of degraded RGB. Unavailable metadata remains explicit.
    geometry = GeometryCondition(batch["geometry_spatial"], batch["geometry_vector"],
                                 {"available": batch.get("geometry_available", False)})
    mask = (batch["mask"] > 0).to(target)
    degraded = condition_template(batch, mask, degradation, seed)
    clean = raw_model.backbone.encode_images(target)
    noise = torch.randn_like(clean) if noise is None else noise
    timestep = torch.rand(target.shape[0], device=target.device) if timestep is None else timestep
    t = timestep[:, None, None, None]
    sample = (1-t) * clean + t * noise
    velocity_target = noise - clean
    prediction = model(sample, timestep, batch["references"], degraded, mask, geometry, batch.get("age"))
    predicted_image = raw_model.backbone.decode_latents(sample-t*prediction) if loss_suite.needs_images else None
    return loss_suite(velocity=prediction, target_velocity=velocity_target, predicted_image=predicted_image,
                      target=target, template=batch["template"], mask=mask, batch=batch)


def build_validation_dataset(data: dict, settings: dict):
    """Held-out pairs for periodic validation, audited together with the training manifest.

    The training manifest is always passed as a peer, so the same identity, file-hash and
    decoded-pixel leakage checks run across both. A validation split that shares an identity
    with training fails here rather than producing a flattering curve.
    """
    legacy = [name for name in ("validation_manifest", "validation_split", "validation_every") if name in data]
    if legacy:
        raise ValueError(f"dataset.{', dataset.'.join(legacy)} moved into the top-level validation section; "
                         "a config that only looks configured would never validate")
    if not settings:
        return None
    manifest = settings.get("manifest", data["manifest"])
    peers = [data["manifest"], *data.get("peer_manifests", []), *settings.get("peer_manifests", [])]
    return PairDataset(manifest, resolution=int(settings.get("resolution", data.get("resolution", 64))),
                       split=str(settings.get("split", "validation")), peer_manifests=peers,
                       reference_count=int(settings.get("reference_count", data.get("reference_count", 1))),
                       **pair_dataset_options(data))


def pair_dataset_options(data: dict) -> dict:
    """Keep preprocessing identical across training and validation; preserve strict booleans."""
    return {"allow_synthetic": data.get("allow_synthetic", False), "registry_path": data.get("registry_path"),
            "mask_channel": data.get("mask_channel", "red"), "degradation": data.get("degradation", "neutral"),
            "degradation_seed": int(data.get("degradation_seed", 0)), "context": float(data.get("context", 1.5)),
            "source_crops": data.get("source_crops", False)}


def make_optimizer(model, config):
    spec = config.get("optimizer", {})
    if spec.get("name", "adamw") != "adamw":
        raise ValueError("Supported optimizer is adamw")
    return torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=float(spec.get("lr", 1e-3)),
                             betas=tuple(spec.get("betas", [0.9, 0.999])), weight_decay=float(spec.get("weight_decay", 0.01)))


def make_scheduler(optimizer, config):
    spec = config.get("scheduler", {})
    warmup = int(spec.get("warmup_steps", 0))
    # Constant after warmup allows extending max_steps while preserving exact resume.
    if spec.get("name", "constant") != "constant":
        raise ValueError("Supported scheduler is constant, with optional linear warmup")
    return torch.optim.lr_scheduler.LambdaLR(optimizer, lambda step: min(1.0, (step+1)/max(1, warmup)))


def _epoch_batches(dataset, batch_size: int, seed: int, epoch: int, rank: int, world: int):
    indices = torch.randperm(len(dataset), generator=torch.Generator().manual_seed(seed+epoch)).tolist()
    # Same number of optimizer steps/rank, with no repeated samples within an epoch.
    full = len(indices) // (batch_size*world) * (batch_size*world)
    if full == 0:
        raise ValueError("Training split is smaller than batch_size * world_size")
    indices = indices[:full][rank::world]
    return DataLoader(Subset(dataset, indices), batch_size=batch_size, shuffle=False, num_workers=0,
                      generator=torch.Generator().manual_seed(seed+epoch), drop_last=True)


def train(config: dict, resume: str | None = None, providers=None) -> dict:
    settings = config.get("training", {})
    rank, world = int(os.getenv("RANK", "0")), int(os.getenv("WORLD_SIZE", "1"))
    local_rank = int(os.getenv("LOCAL_RANK", "0"))
    distributed = world > 1
    if distributed and config.get("model", {}).get("backbone") == "flux_klein":
        raise ValueError("FLUX distributed training is not validated. Use one process; FSDP/ZeRO is a separate integration milestone.")
    requested_device = settings.get("device", "cpu")
    device = torch.device(f"cuda:{local_rank}" if distributed and requested_device.startswith("cuda") else requested_device)
    if device.type == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but unavailable")
        if device.index is None:
            device = torch.device("cuda", torch.cuda.current_device())
        torch.cuda.set_device(device)
    if distributed:
        dist.init_process_group("nccl" if device.type == "cuda" and os.name != "nt" else "gloo")
    seed = int(settings.get("seed", 1234))
    seed_everything(seed)  # Same parameters across ranks, different RNG after DDP setup.
    torch.set_num_threads(int(settings.get("cpu_threads", 2)))
    precision = settings.get("precision", "fp32")
    if precision not in ("fp32", "bf16"):
        raise ValueError("precision must be fp32 or bf16; fp16 loss scaling is not implemented")
    if precision == "bf16" and device.type == "cuda" and not torch.cuda.is_bf16_supported():
        raise ValueError("Selected GPU does not support bf16")
    model = build_model(config, device)
    dtype = next(model.encoder.parameters()).dtype
    data = config["dataset"]
    dataset = PairDataset(data["manifest"], resolution=int(data.get("resolution", 64)), split="train",
                          peer_manifests=data.get("peer_manifests", []),
                          reference_count=int(data.get("reference_count", 1)), **pair_dataset_options(data))
    if "validation_every" in settings:
        raise ValueError("training.validation_every moved into the top-level validation section as validation.every")
    validation_settings = dict(config.get("validation", {}))
    validation_dataset = build_validation_dataset(data, validation_settings)
    optimizer = make_optimizer(model, config)
    scheduler = make_scheduler(optimizer, config)
    losses = LossSuite(config["losses"], providers)
    output = Path(settings.get("output_dir", "runs/train"))
    output.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output / (f"checkpoint.rank{rank}.pt" if distributed else "checkpoint.pt")
    best_path = output / "checkpoint.best.pt"
    # Hashing the enrolled records and the asset bytes turns "same manifest path" into
    # "same data", which is the only version of exact resume worth claiming.
    fingerprint = (dataset_fingerprint(dataset, validation_dataset)
                   if bool(settings.get("verify_dataset_fingerprint", True)) else None)
    step, cursor, best_score = 0, 0, None
    if resume:
        path = Path(resume)
        if distributed:
            path = path.parent / f"checkpoint.rank{rank}.pt"
        state = load_checkpoint(path, model, optimizer, scheduler, expected_config=config, map_location=device)
        if state["metadata"].get("world_size", 1) != world:
            raise ValueError("Exact resume requires the same world_size")
        stored = state["metadata"].get("dataset_fingerprint")
        if fingerprint is not None and stored is not None and stored != fingerprint:
            raise ValueError("Cannot exactly resume: the enrolled records or their image bytes changed")
        step, cursor, best_score = state["step"], state["data_cursor"], state["metadata"].get("best_score")
    elif distributed:
        seed_everything(seed+rank)
    forward_model = DistributedDataParallel(model, device_ids=[local_rank] if device.type == "cuda" else None) if distributed else model
    tracker_name = settings.get("tracker", "jsonl")
    if tracker_name not in ("jsonl", "tensorboard", "none"):
        raise ValueError("tracker must be jsonl, tensorboard or none")
    max_steps = int(settings.get("max_steps", 1000))
    accumulation = int(settings.get("accumulation_steps", 1))
    batch_size = int(settings.get("batch_size", 2))
    if accumulation < 1 or batch_size < 1 or max_steps < 1:
        raise ValueError("Positive steps, accumulation and batch size required")
    batches_per_epoch = len(dataset) // (batch_size*world)
    if batches_per_epoch == 0:
        raise ValueError("Dataset too small for one full batch per rank")
    checkpoint_every = int(settings.get("checkpoint_every", 100))
    validation_every = int(validation_settings.get("every", 0))
    validation_metric = str(validation_settings.get("metric", "validation/total"))
    write_samples = bool(validation_settings.get("samples", False))
    if validation_every < 0:
        raise ValueError("validation.every must be zero (end of run only) or positive")
    if validation_dataset is None and (validation_every or write_samples):
        raise ValueError("Validation requires a held-out split; configure validation.manifest or validation.split")
    history, validation_history = [], []
    model.train()
    optimizer.zero_grad(set_to_none=True)
    epoch, offset = divmod(cursor, batches_per_epoch)
    iterator = iter(_epoch_batches(dataset, batch_size, seed, epoch, rank, world))
    for _ in range(offset):
        next(iterator)
    tracker = NullTracker() if rank or tracker_name == "none" else (TensorBoardTracker(output / "tensorboard")
               if tracker_name == "tensorboard" else JsonlTracker(output / "metrics.jsonl"))
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    try:
        while step < max_steps:
            step_started = time.perf_counter()
            accumulated_metrics = {}
            for micro in range(accumulation):
                epoch, offset = divmod(cursor, batches_per_epoch)
                # Deterministic epoch iterator reconstructed at cursor, including exact resume.
                if offset == 0 and cursor > 0:
                    iterator = iter(_epoch_batches(dataset, batch_size, seed, epoch, rank, world))
                batch = move_batch(next(iterator), device, dtype)
                sync_context = forward_model.no_sync() if distributed and micro < accumulation-1 else nullcontext()
                with sync_context:
                    with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=precision == "bf16"):
                        loss, metrics = flow_objective(forward_model, batch, losses,
                                    degradation=data.get("degradation", "neutral"), seed=seed+cursor)
                    (loss / accumulation).backward()
                for name, value in metrics.items():
                    accumulated_metrics[name] = accumulated_metrics.get(name, 0) + value / accumulation
                cursor += 1
            gradient_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), float(settings.get("gradient_clip", 1.0)))
            if not torch.isfinite(gradient_norm):
                raise FloatingPointError("Non-finite gradient norm; optimizer step aborted")
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            step += 1
            if distributed:
                keys = list(accumulated_metrics)
                metric_tensor = torch.tensor([accumulated_metrics[k] for k in keys], device=device)
                dist.all_reduce(metric_tensor)
                accumulated_metrics = dict(zip(keys, (metric_tensor/world).tolist()))
            accumulated_metrics["lr"] = optimizer.param_groups[0]["lr"]
            if device.type == "cuda":
                torch.cuda.synchronize(device)
                accumulated_metrics["peak_vram_bytes"] = torch.cuda.max_memory_allocated(device)
            accumulated_metrics["gradient_norm"] = float(gradient_norm)
            accumulated_metrics["per_rank_pairs_per_second"] = batch_size * accumulation / (time.perf_counter() - step_started)
            tracker.log(step, accumulated_metrics)
            history.append(accumulated_metrics["total"])
            if rank == 0 and (step == 1 or step % int(settings.get("log_every", 20)) == 0):
                print(json.dumps({"step": step, **accumulated_metrics}), flush=True)
            metadata = {"world_size": world, "rank": rank, "synthetic": all(row.get("synthetic") is True for row in dataset.rows),
                        "dataset_fingerprint": fingerprint}
            if validation_dataset is not None and (step == max_steps or (validation_every and step % validation_every == 0)):
                # Rank 0 only, on the unwrapped module: no collective runs inside validation,
                # so the other ranks can simply wait at the barrier below.
                if rank == 0:
                    measured = validate_flow(model, validation_dataset, losses, settings=validation_settings,
                                             device=device, dtype=dtype, degradation=data.get("degradation", "neutral"),
                                             sample_directory=output / "samples" / f"step_{step:08d}" if write_samples else None)
                    if validation_metric not in measured:
                        raise ValueError(f"validation.metric {validation_metric!r} is not among {sorted(measured)}")
                    tracker.log(step, measured)
                    validation_history.append({"step": step, **measured})
                    print(json.dumps({"step": step, **measured}), flush=True)
                    score = measured[validation_metric]
                    if best_score is None or score < best_score:
                        best_score = score
                        save_checkpoint(best_path, model, optimizer, scheduler, config=config, step=step,
                                        data_cursor=cursor, metadata={**metadata, "best_score": best_score,
                                                                      "best_metric": validation_metric,
                                                                      "validation": measured})
                if distributed:
                    dist.barrier()
            if step == max_steps or (checkpoint_every > 0 and step % checkpoint_every == 0):
                save_checkpoint(checkpoint_path, model, optimizer, scheduler, config=config, step=step, data_cursor=cursor,
                                metadata={**metadata, "best_score": best_score, "best_metric": validation_metric})
                if distributed:
                    dist.barrier()
    finally:
        tracker.close()
        if distributed:
            dist.destroy_process_group()
    return {"step": step, "checkpoint": str(checkpoint_path.resolve()), "loss_history": history,
            "validation_history": validation_history,
            "best_checkpoint": str(best_path.resolve()) if best_path.is_file() else None,
            "best_score": best_score, "best_metric": validation_metric if validation_history else None,
            "dataset_fingerprint": fingerprint,
            # A held-out flow loss is an optimization measurement. It is not an identity,
            # realism or preservation result, and selecting on it proves none of those.
            "quality_validated": False}


def main():
    parser = argparse.ArgumentParser(description="Train DreamSwap on explicitly permitted pair manifests")
    parser.add_argument("--config", required=True)
    parser.add_argument("--resume")
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    print(json.dumps(train(config, args.resume), indent=2))


if __name__ == "__main__":
    main()
