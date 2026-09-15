"""Deterministic synthetic infrastructure verification; does not measure faces."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import torch

from .factory import build_model
from .loop import flow_objective, make_optimizer, make_scheduler
from ..losses import LossSuite
from ..utils.checkpoint import seed_everything, save_checkpoint
from ..utils.tracking import JsonlTracker


def synthetic_batch(resolution=24, batch_size=2):
    axis = torch.linspace(-1, 1, resolution)
    yy, xx = torch.meshgrid(axis, axis, indexing="ij")
    mask = ((xx**2 + yy**2) < 0.45).float()[None, None].repeat(batch_size, 1, 1, 1)
    template = torch.stack([0.2+0.1*xx, 0.3+0.1*yy, torch.full_like(xx, 0.4)])[None].repeat(batch_size, 1, 1, 1)
    colors = torch.tensor([[0.8, 0.3, 0.2], [0.2, 0.7, 0.8]]).repeat((batch_size+1)//2, 1)[:batch_size, :, None, None]
    target = template * (1-mask) + (colors + 0.06*torch.cos(xx*10)[None, None]) * mask
    references = colors.expand(-1, -1, resolution, resolution).unsqueeze(1).contiguous()
    return {"references": references, "template": template, "target": target,
            "mask": mask, "age": torch.full((batch_size,), -1.),
            "geometry_spatial": torch.zeros(batch_size, 4, resolution, resolution),
            "geometry_vector": torch.zeros(batch_size, 16), "geometry_available": torch.zeros(batch_size, dtype=torch.bool)}


def run_overfit(output="runs/tiny-overfit", steps=120, seed=1234, resolution=24, assert_improvement=True):
    if steps < 1:
        raise ValueError("steps must be positive")
    torch.set_num_threads(2)
    seed_everything(seed)
    config = {"model": {"backbone": "tiny", "identity_dim": 32, "structure_dim": 16, "width": 24},
              "optimizer": {"name": "adamw", "lr": 0.004, "weight_decay": 0.0},
              "scheduler": {"name": "constant"}, "losses": {"flow_matching": 1.0, "reconstruction": 0.2},
              "training": {"seed": seed, "max_steps": steps, "precision": "fp32"},
              "dataset": {"synthetic": True, "resolution": resolution}}
    model = build_model(config)
    optimizer, losses = make_optimizer(model, config), LossSuite(config["losses"])
    scheduler = make_scheduler(optimizer, config)
    batch = synthetic_batch(resolution)
    noise = torch.randn_like(batch["target"])
    timestep = torch.tensor([0.35, 0.8])
    with torch.no_grad():
        initial = flow_objective(model, batch, losses, noise=noise, timestep=timestep)[1]["total"]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    tracker = JsonlTracker(output / "metrics.jsonl")
    for step in range(1, steps+1):
        optimizer.zero_grad(set_to_none=True)
        loss, metrics = flow_objective(model, batch, losses, noise=noise, timestep=timestep)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5)
        optimizer.step()
        scheduler.step()
        tracker.log(step, metrics)
    tracker.close()
    with torch.no_grad():
        final = flow_objective(model, batch, losses, noise=noise, timestep=timestep)[1]["total"]
    report = {"initial_loss": initial, "final_loss": final, "relative_improvement": (initial-final)/initial,
              "steps": steps, "seed": seed, "passed": final < 0.8*initial,
              "identity_quality_validated": False, "scope": "Two procedural colored shapes; fixed noise/time overfit only"}
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    save_checkpoint(output / "checkpoint.pt", model, optimizer, scheduler, config=config, step=steps,
                    data_cursor=steps, metadata={"synthetic": True, "production_ready": False})
    if assert_improvement and not report["passed"]:
        raise AssertionError(f"Synthetic overfit failed >=20% loss reduction: {report}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="runs/tiny-overfit")
    parser.add_argument("--steps", type=int, default=120)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--resolution", type=int, default=24)
    args = parser.parse_args()
    print(json.dumps(run_overfit(args.output, args.steps, args.seed, args.resolution), indent=2))


if __name__ == "__main__":
    main()
