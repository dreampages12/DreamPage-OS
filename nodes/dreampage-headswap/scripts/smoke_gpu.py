"""Bounded CUDA/BF16 training and full inference on an explicitly synthetic tiny-model corpus."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import torch
import yaml

from dreampage_headswap.data.records import read_jsonl
from dreampage_headswap.training.loop import train
from dreampage_headswap.training.factory import build_model
from dreampage_headswap.utils.checkpoint import load_checkpoint
from dreampage_headswap.inference.pipeline import HeadSwapPipeline, InferenceConfig
from dreampage_headswap.masking import load_headmask
from dreampage_headswap.template import CropConfig
from dreampage_headswap.types import ChildIdentityInput, TemplateInput
from dreampage_headswap.utils.images import load_rgb, save_rgb


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Generated training_smoke.yaml")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("This smoke test requires CUDA with BF16 support")
    free, _ = torch.cuda.mem_get_info()
    if free < 1536 * 1024**2:
        raise RuntimeError("Less than 1.5 GiB free CUDA memory; retry after other workloads finish")
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    rows = read_jsonl(config["dataset"]["manifest"])
    if config["model"].get("backbone") != "tiny" or not rows or any(row.get("synthetic") is not True for row in rows):
        raise ValueError("This bounded smoke tool accepts only the tiny backbone and explicitly synthetic fixtures")
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    config["training"].update(device="cuda", precision="bf16", max_steps=3, batch_size=1,
                              accumulation_steps=1, checkpoint_every=0, output_dir=str(output / "train"))
    config["validation"].update(max_batches=1, every=0, samples=False)
    config["dataset"]["resolution"] = 64
    (output / "training.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    trained = train(config)
    model = build_model(config, "cuda")
    load_checkpoint(trained["checkpoint"], model, restore_random=False, map_location="cuda")
    pipeline = HeadSwapPipeline(model, config=InferenceConfig(crop=CropConfig(64), reference_resolution=64, steps=4, seed=17))
    row = rows[0]
    child = ChildIdentityInput([load_rgb(row["source"])])
    template = TemplateInput(load_rgb(row["template"]))
    mask = load_headmask(row["headmask"], channel=row.get("mask_channel", "red"))
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    start = time.perf_counter()
    result = pipeline(child, template, mask)
    torch.cuda.synchronize()
    latency = time.perf_counter() - start
    report = {"training_steps": trained["step"], "training_precision": "bf16", "inference_precision": "fp32",
              "device": torch.cuda.get_device_name(0), "torch": torch.__version__, "inference_seconds": latency,
              "inference_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
              "scope": "Tiny random-initialized model, three synthetic training steps; not pretrained FLUX or a face benchmark",
              "quality": asdict(result.quality), "passed": result.quality.measurements["outside_mask_exact"],
              "trained_model_quality_validated": False}
    save_rgb(output / "result.png", result.image)
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
