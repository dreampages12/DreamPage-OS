from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import time

import torch

from .pipeline import load_pipeline, save_debug
from dreampage_headswap.masking import load_headmask
from dreampage_headswap.types import ChildIdentityInput, TemplateInput
from dreampage_headswap.utils.images import load_rgb, save_rgb


def main():
    parser = argparse.ArgumentParser(description="DreamPage HeadSwap research inference; output is lossless PNG")
    parser.add_argument("--config", required=True)
    parser.add_argument("--checkpoint")
    parser.add_argument("--child", nargs="+", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--mask", required=True)
    parser.add_argument("--mask-channel", default="luminance", choices=["red", "green", "blue", "alpha", "luminance"])
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--age", type=float)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--allow-untrained", action="store_true")
    parser.add_argument("--debug-dir")
    args = parser.parse_args()
    pipeline = load_pipeline(args.config, checkpoint=args.checkpoint, device=args.device, allow_untrained=args.allow_untrained)
    config = replace(pipeline.config, debug=bool(args.debug_dir), seed=args.seed if args.seed is not None else pipeline.config.seed)
    child = ChildIdentityInput([load_rgb(path, orient=True) for path in args.child], args.age)
    template = TemplateInput(load_rgb(args.template))
    headmask = load_headmask(args.mask, channel=args.mask_channel)
    if args.device.startswith("cuda"):
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
    start = time.perf_counter()
    output = pipeline(child, template, headmask, config=config)
    if args.device.startswith("cuda"):
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - start
    vram = torch.cuda.max_memory_allocated() if args.device.startswith("cuda") else None
    save_rgb(args.output, output.image)
    report = {"quality": asdict(output.quality), "latency_seconds": elapsed, "peak_vram_bytes": vram,
              "latency_scope": "warm inference; excludes model load and image IO", "device": args.device,
              "checkpoint_metadata": pipeline.checkpoint_metadata, "config": asdict(config)}
    report_path = Path(args.output).with_suffix(".json")
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    if args.debug_dir:
        save_debug(output, args.debug_dir)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
