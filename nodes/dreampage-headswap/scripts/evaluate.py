"""Apply the quality gate to a stored output without regenerating it.

Preservation is measured here. Identity, pose, realism and age stay unavailable until a
licensed, calibrated provider is configured, so this script cannot report a PASS on its own.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from dreampage_headswap.evaluation.benchmark import save_json
from dreampage_headswap.evaluation.quality import QualityConfig, evaluate_quality
from dreampage_headswap.masking import load_headmask
from dreampage_headswap.utils.images import load_rgb


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--template", required=True)
    parser.add_argument("--output", required=True, help="Stored result at the template's exact resolution")
    parser.add_argument("--mask", required=True)
    parser.add_argument("--mask-channel", default="luminance",
                        choices=["red", "green", "blue", "alpha", "luminance"])
    parser.add_argument("--child", nargs="*", default=[], help="References, passed to a provider when one exists")
    parser.add_argument("--age", type=float)
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--report")
    parser.add_argument("--model-validated", action="store_true",
                        help="Only set this once the checkpoint has passed a held-out benchmark")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    template = load_rgb(args.template)
    output = load_rgb(args.output)
    mask = load_headmask(args.mask, channel=args.mask_channel).values
    metrics = evaluate_quality(template, output, mask,
                               references=[load_rgb(path, orient=True) for path in args.child],
                               age=args.age, provider=None, config=QualityConfig(threshold=args.threshold),
                               model_validated=args.model_validated)
    report = {"template": str(Path(args.template).resolve()), "output": str(Path(args.output).resolve()),
              "headmask": str(Path(args.mask).resolve()), "quality": asdict(metrics),
              "provider": "none_configured",
              "scope": "Preservation is measured; identity, pose, realism and age require a licensed provider"}
    if args.report:
        save_json(args.report, report)
    print(json.dumps(report, indent=2))
    return 0 if metrics.status != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
