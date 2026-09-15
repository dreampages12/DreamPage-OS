"""Train DreamFace on its own objective, separately from the generator.

Two captures of one person are two views. The encoder learns to place the views of one
identity together and different identities apart, using the supervised cross-view
contrastive objective in `losses.suite`.

Three deliberate constraints:

* An encoder that is trained jointly with a generator and then used to score it can agree
  with itself. This trainer exists so the encoder can be optimized and judged on its own.
* The objective needs several distinct identities per batch to have negatives at all, so
  batches are built identity-aware rather than by shuffling pairs and hoping.
* Both views are framed the same way, through the production crop, when enrolment supplied
  a headmask for every capture. Otherwise the encoder can learn framing instead of a face.

Held-out retrieval accuracy here is within-batch cross-view matching among the identities in
that batch. It measures separability of the enrolled captures under this encoder. It is not a
calibrated identity evaluator, and it is not evidence about recognizing a child.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import torch
from torch.utils.data import DataLoader, Subset
import yaml

from ..data import PairDataset
from ..dreamface import DreamFaceEncoder
from ..losses.suite import supervised_identity_contrastive
from ..utils.checkpoint import load_checkpoint, rng_state, restore_rng, save_checkpoint, seed_everything
from ..utils.tracking import JsonlTracker, NullTracker, TensorBoardTracker
from .loop import make_optimizer, make_scheduler, pair_dataset_options
from .validation import dataset_fingerprint


def build_encoder(config: dict, device="cpu") -> DreamFaceEncoder:
    spec = config.get("model", config)
    encoder = DreamFaceEncoder(int(spec.get("identity_dim", 64)), int(spec.get("structure_dim", 16)),
                               int(spec.get("token_grid", 4)))
    return encoder.to(device)


def identity_batches(dataset, identities_per_batch: int, seed: int, epoch: int) -> list[list[int]]:
    """Group pair indices so every batch holds that many distinct identities, one pair each.

    Deterministic in the seed and epoch, so a resumed run replays the same batches. Identities
    with several pairs contribute one per batch; the rest are used in later epochs.
    """
    if identities_per_batch < 2:
        raise ValueError("The contrastive objective needs at least two distinct identities per batch")
    groups: dict[str, list[int]] = {}
    for index, row in enumerate(dataset.rows):
        groups.setdefault(row["identity_id"], []).append(index)
    if len(groups) < identities_per_batch:
        raise ValueError(f"Split holds {len(groups)} identities; objective.identities_per_batch is {identities_per_batch}")
    generator = torch.Generator().manual_seed(seed + epoch)
    order = sorted(groups)
    shuffled = [order[position] for position in torch.randperm(len(order), generator=generator).tolist()]
    batches = []
    for start in range(0, len(shuffled) - identities_per_batch + 1, identities_per_batch):
        chosen = shuffled[start:start + identities_per_batch]
        batch = []
        for identity in chosen:
            candidates = groups[identity]
            pick = int(torch.randint(len(candidates), (1,), generator=generator).item())
            batch.append(candidates[pick])
        batches.append(batch)
    return batches


def cross_view_objective(encoder: DreamFaceEncoder, batch: dict, temperature: float) -> tuple[torch.Tensor, dict]:
    """View A is the source capture, view B is the target capture's head crop."""
    references = batch["references"]
    if references.shape[1] < 1:
        raise ValueError("Every pair needs at least one source capture")
    first = encoder(references).global_embedding
    second = encoder(batch["target"][:, None]).global_embedding
    identity_ids = list(batch["identity_id"])
    loss = supervised_identity_contrastive(first, second, identity_ids, temperature)
    metrics = {"contrastive": float(loss.detach()), "total": float(loss.detach()),
               **retrieval_metrics(first, second, identity_ids)}
    return loss, metrics


@torch.no_grad()
def retrieval_metrics(first: torch.Tensor, second: torch.Tensor, identity_ids: list[str]) -> dict:
    """Within-batch cross-view top-1 accuracy, both directions, plus the margin."""
    normalized_first = torch.nn.functional.normalize(first.float(), dim=-1)
    normalized_second = torch.nn.functional.normalize(second.float(), dim=-1)
    similarity = normalized_first @ normalized_second.T
    positive = torch.tensor([[a == b for b in identity_ids] for a in identity_ids], device=similarity.device)
    forward = positive.gather(1, similarity.argmax(1, keepdim=True)).float().mean()
    backward = positive.T.gather(1, similarity.T.argmax(1, keepdim=True)).float().mean()
    matched = similarity[positive].mean()
    others = similarity[~positive].mean() if (~positive).any() else torch.zeros((), device=similarity.device)
    return {"retrieval_top1": float((forward + backward) / 2), "positive_similarity": float(matched),
            "negative_similarity": float(others), "similarity_margin": float(matched - others)}


@torch.no_grad()
def validate_identity(encoder, dataset, *, settings: dict, device, dtype, temperature: float) -> dict:
    previous_rng, was_training = rng_state(), encoder.training
    seed = int(settings.get("seed", 4321))
    identities_per_batch = int(settings.get("identities_per_batch", 4))
    max_batches = int(settings.get("max_batches", 8))
    if max_batches < 1:
        raise ValueError("validation.max_batches must be positive")
    try:
        seed_everything(seed)
        encoder.eval()
        totals, seen = {}, 0
        for index, indices in enumerate(identity_batches(dataset, identities_per_batch, seed, 0)):
            if index >= max_batches:
                break
            batch = next(iter(DataLoader(Subset(dataset, indices), batch_size=len(indices), shuffle=False)))
            batch = {key: value.to(device=device, dtype=dtype if value.is_floating_point() else value.dtype)
                     if isinstance(value, torch.Tensor) else value for key, value in batch.items()}
            _, metrics = cross_view_objective(encoder, batch, temperature)
            for name, value in metrics.items():
                totals[name] = totals.get(name, 0.0) + value
            seen += 1
        if not seen:
            raise ValueError("Validation split produced no identity batch")
        result = {"validation/" + name: value / seen for name, value in totals.items()}
        result["validation/batches"] = seen
        return result
    finally:
        encoder.train(was_training)
        restore_rng(previous_rng)


def train_identity_encoder(config: dict, resume: str | None = None) -> dict:
    settings = config.get("training", {})
    objective = config.get("objective", {})
    name = objective.get("name", "supervised_contrastive")
    if name != "supervised_contrastive":
        raise ValueError("The implemented identity objective is supervised_contrastive")
    temperature = float(objective.get("temperature", 0.1))
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("objective.temperature must be finite and positive")
    identities_per_batch = int(objective.get("identities_per_batch", 4))
    device = torch.device(settings.get("device", "cpu"))
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    precision = settings.get("precision", "fp32")
    if precision not in ("fp32", "bf16"):
        raise ValueError("precision must be fp32 or bf16; fp16 loss scaling is not implemented")
    if precision == "bf16" and device.type == "cuda" and not torch.cuda.is_bf16_supported():
        raise ValueError("Selected GPU does not support bf16")
    seed = int(settings.get("seed", 1234))
    seed_everything(seed)
    torch.set_num_threads(int(settings.get("cpu_threads", 2)))

    data = config["dataset"]
    source_crops = bool(data.get("source_crops", True))
    dataset = PairDataset(data["manifest"], resolution=int(data.get("resolution", 64)), split="train",
                          peer_manifests=data.get("peer_manifests", []),
                          reference_count=int(data.get("reference_count", 1)),
                          **pair_dataset_options({**data, "source_crops": source_crops}))
    validation_settings = dict(config.get("validation", {}))
    validation_dataset = None
    if validation_settings:
        validation_dataset = PairDataset(validation_settings.get("manifest", data["manifest"]),
                                         resolution=int(data.get("resolution", 64)),
                                         split=str(validation_settings.get("split", "validation")),
                                         peer_manifests=[data["manifest"], *data.get("peer_manifests", [])],
                                         reference_count=int(data.get("reference_count", 1)),
                                         **pair_dataset_options({**data, "source_crops": source_crops}))

    encoder = build_encoder(config, device)
    optimizer = make_optimizer(encoder, config)
    scheduler = make_scheduler(optimizer, config)
    output = Path(settings.get("output_dir", "runs/identity"))
    output.mkdir(parents=True, exist_ok=True)
    checkpoint_path, best_path = output / "checkpoint.pt", output / "checkpoint.best.pt"
    fingerprint = (dataset_fingerprint(dataset, validation_dataset)
                   if bool(settings.get("verify_dataset_fingerprint", True)) else None)
    step, cursor, best_score = 0, 0, None
    if resume:
        state = load_checkpoint(resume, encoder, optimizer, scheduler, expected_config=config, map_location=device)
        stored = state["metadata"].get("dataset_fingerprint")
        if fingerprint is not None and stored is not None and stored != fingerprint:
            raise ValueError("Cannot exactly resume: the enrolled records or their image bytes changed")
        step, cursor, best_score = state["step"], state["data_cursor"], state["metadata"].get("best_score")

    tracker_name = settings.get("tracker", "jsonl")
    if tracker_name not in ("jsonl", "tensorboard", "none"):
        raise ValueError("tracker must be jsonl, tensorboard or none")
    max_steps = int(settings.get("max_steps", 1000))
    checkpoint_every = int(settings.get("checkpoint_every", 100))
    validation_every = int(validation_settings.get("every", 0))
    validation_metric = str(validation_settings.get("metric", "validation/total"))
    if validation_dataset is None and validation_every:
        raise ValueError("Validation requires a held-out split; configure validation.manifest or validation.split")
    if max_steps < 1:
        raise ValueError("training.max_steps must be positive")

    history, validation_history = [], []
    dtype = next(encoder.parameters()).dtype
    encoder.train()
    epoch, offset = 0, 0
    batches = identity_batches(dataset, identities_per_batch, seed, epoch)
    epoch, offset = divmod(cursor, len(batches))
    batches = identity_batches(dataset, identities_per_batch, seed, epoch)
    tracker = (NullTracker() if tracker_name == "none" else TensorBoardTracker(output / "tensorboard")
               if tracker_name == "tensorboard" else JsonlTracker(output / "metrics.jsonl"))
    try:
        while step < max_steps:
            epoch, offset = divmod(cursor, len(batches))
            if offset == 0 and cursor > 0:
                batches = identity_batches(dataset, identities_per_batch, seed, epoch)
            indices = batches[offset]
            batch = next(iter(DataLoader(Subset(dataset, indices), batch_size=len(indices), shuffle=False)))
            batch = {key: value.to(device=device, dtype=dtype if value.is_floating_point() else value.dtype)
                     if isinstance(value, torch.Tensor) else value for key, value in batch.items()}
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=precision == "bf16"):
                loss, metrics = cross_view_objective(encoder, batch, temperature)
            loss.backward()
            gradient_norm = torch.nn.utils.clip_grad_norm_(encoder.parameters(), float(settings.get("gradient_clip", 1.0)))
            if not torch.isfinite(gradient_norm):
                raise FloatingPointError("Non-finite gradient norm; optimizer step aborted")
            optimizer.step()
            scheduler.step()
            step, cursor = step + 1, cursor + 1
            metrics["lr"] = optimizer.param_groups[0]["lr"]
            tracker.log(step, metrics)
            history.append(metrics["total"])
            if step == 1 or step % int(settings.get("log_every", 20)) == 0:
                print(json.dumps({"step": step, **metrics}), flush=True)

            metadata = {"dataset_fingerprint": fingerprint, "synthetic": all(row.get("synthetic") is True for row in dataset.rows),
                        "component": "dreamface_encoder", "supervised_outputs": ["global_embedding"],
                        "training_identity_ids": sorted({row["identity_id"] for row in dataset.rows}),
                        "identity_quality_validated": False}
            if validation_dataset is not None and (step == max_steps or (validation_every and step % validation_every == 0)):
                measured = validate_identity(encoder, validation_dataset, settings=validation_settings,
                                             device=device, dtype=dtype, temperature=temperature)
                if validation_metric not in measured:
                    raise ValueError(f"validation.metric {validation_metric!r} is not among {sorted(measured)}")
                tracker.log(step, measured)
                validation_history.append({"step": step, **measured})
                print(json.dumps({"step": step, **measured}), flush=True)
                # Loss-like metrics improve downwards, accuracy and margin upwards.
                score = measured[validation_metric]
                improved = best_score is None or (score > best_score if _higher_is_better(validation_metric)
                                                  else score < best_score)
                if improved:
                    best_score = score
                    save_checkpoint(best_path, encoder, optimizer, scheduler, config=config, step=step,
                                    data_cursor=cursor, metadata={**metadata, "best_score": best_score,
                                                                  "best_metric": validation_metric,
                                                                  "validation": measured})
            if step == max_steps or (checkpoint_every > 0 and step % checkpoint_every == 0):
                save_checkpoint(checkpoint_path, encoder, optimizer, scheduler, config=config, step=step,
                                data_cursor=cursor, metadata={**metadata, "best_score": best_score,
                                                              "best_metric": validation_metric})
    finally:
        tracker.close()
    return {"step": step, "checkpoint": str(checkpoint_path.resolve()), "loss_history": history,
            "validation_history": validation_history,
            "best_checkpoint": str(best_path.resolve()) if best_path.is_file() else None,
            "best_score": best_score, "best_metric": validation_metric if validation_history else None,
            "dataset_fingerprint": fingerprint, "source_crops": source_crops,
            "identities_in_train_split": len({row["identity_id"] for row in dataset.rows}),
            # Within-batch separability of enrolled captures. Not a calibrated identity evaluator,
            # and never a claim about recognizing a child.
            "identity_quality_validated": False}


def _higher_is_better(metric: str) -> bool:
    return any(metric.endswith(suffix) for suffix in ("retrieval_top1", "similarity_margin", "positive_similarity"))


def main():
    parser = argparse.ArgumentParser(description="Train the DreamFace identity encoder on enrolled pairs")
    parser.add_argument("--config", required=True)
    parser.add_argument("--resume")
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    print(json.dumps(train_identity_encoder(config, args.resume), indent=2))


if __name__ == "__main__":
    main()
