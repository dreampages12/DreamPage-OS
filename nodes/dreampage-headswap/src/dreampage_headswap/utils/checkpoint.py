"""Atomic, trusted-local checkpoints including optimizer, scheduler and RNG state."""
from __future__ import annotations
import os
import random
from pathlib import Path

import numpy as np
import torch


def initialize_weights(model, config, *, component, resume=None, teacher_sha256=None):
    """Videreutvikling arver bare vekter. Ny optimizer, scheduler og RNG beholdes."""
    settings = config.get("training", {})
    path = settings.get("initialize_from")
    if not path or resume:
        return
    from ..data.records import file_sha256
    if not settings.get("initialize_sha256") or file_sha256(path) != settings["initialize_sha256"]:
        raise ValueError("Forelder-checkpoint mangler verifisert hash eller er endret")
    state = torch.load(path, map_location="cpu", weights_only=False)
    meta = state.get("metadata", {})
    if state.get("format_version") != 1 or meta.get("synthetic") is not False or state.get("step", 0) < 1:
        raise ValueError("Bare registrerte checkpoints fra ikke-syntetiske data kan videreutvikles")
    expected = {"identity": "dreamface_encoder", "refiner": "dreamrefine_system"}
    if (component in expected and meta.get("component") != expected[component]) or (
            component == "swap" and meta.get("component") not in (None, "dreamswap")):
        raise ValueError("Forelder-checkpoint har feil komponent")
    # Arkitektur og frosne vekter maa vaere de samme; hyperparametre/datasett kan endres.
    if state.get("config", {}).get("model") != config.get("model"):
        raise ValueError("Videreutvikling krever samme modellkonfigurasjon")
    if component == "refiner" and meta.get("teacher", {}).get("checkpoint_sha256") != teacher_sha256:
        raise ValueError("Videreutvikling kan ikke bytte den frosne laerermodellen")
    model.load_state_dict(state["model"], strict=True)
    settings["training_identity_lineage"] = sorted(set(settings.get("training_identity_lineage", []))
                                                  | set(meta.get("training_identity_ids", [])))


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def rng_state() -> dict:
    return {"python": random.getstate(), "numpy": np.random.get_state(), "torch": torch.get_rng_state(),
            "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None}


def restore_rng(state: dict) -> None:
    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    torch.set_rng_state(state["torch"].cpu())
    if state.get("cuda") is not None and torch.cuda.is_available():
        torch.cuda.set_rng_state_all([x.cpu() for x in state["cuda"]])


def save_checkpoint(path, model, optimizer=None, scheduler=None, *, config=None, step=0,
                    data_cursor=0, metadata=None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {"format_version": 1, "model": model.state_dict(),
             "optimizer": optimizer.state_dict() if optimizer else None,
             "scheduler": scheduler.state_dict() if scheduler else None,
             "config": config or {}, "step": int(step), "data_cursor": int(data_cursor),
             "rng": rng_state(), "metadata": metadata or {},
             "quality_claim": "Research checkpoint; no validated identity or realism quality implied"}
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(state, temporary)
    os.replace(temporary, path)


def load_checkpoint(path, model, optimizer=None, scheduler=None, *, restore_random=True,
                    expected_config=None, map_location="cpu") -> dict:
    """Only load checkpoints you created/trust (optimizer/RNG requires pickle)."""
    state = torch.load(path, map_location=map_location, weights_only=False)
    if state.get("format_version") != 1:
        raise ValueError("Unsupported checkpoint format")
    if expected_config is not None:
        for section in ("model", "optimizer", "scheduler", "losses", "dataset", "validation", "objective", "teacher"):
            if expected_config.get(section) != state["config"].get(section):
                raise ValueError(f"Cannot exactly resume: {section} configuration changed")
        for name in ("seed", "batch_size", "accumulation_steps", "precision", "gradient_clip", "cpu_threads"):
            if expected_config.get("training", {}).get(name) != state["config"].get("training", {}).get(name):
                raise ValueError(f"Cannot exactly resume: training.{name} changed")
    model.load_state_dict(state["model"], strict=True)
    if optimizer is not None:
        if state["optimizer"] is None:
            raise ValueError("Checkpoint has no optimizer state")
        optimizer.load_state_dict(state["optimizer"])
    if scheduler is not None:
        if state["scheduler"] is None:
            raise ValueError("Checkpoint has no scheduler state")
        scheduler.load_state_dict(state["scheduler"])
    if restore_random:
        restore_rng(state["rng"])
    return state
