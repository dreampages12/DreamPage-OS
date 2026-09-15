"""Benchmark command line over stored outputs. This script never generates images.

archive-baseline  freeze the current production workflow/config with checksums
record-run        attest to one stored result produced outside this tool
compare           measure stored current-versus-new results on byte-identical inputs
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dreampage_headswap.evaluation.benchmark import archive_baseline, benchmark, record_stored_result


def _performance(args) -> dict | None:
    if args.latency_ms is None and args.peak_vram_bytes is None:
        return None
    return {"latency_ms": args.latency_ms, "peak_vram_bytes": args.peak_vram_bytes,
            "measurement_protocol": args.measurement_protocol, "hardware": args.hardware,
            "device": args.device, "warmup_runs": args.warmup_runs}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    archive = sub.add_parser("archive-baseline", help="Copy and checksum the current workflow and its config")
    archive.add_argument("--workflow", required=True)
    archive.add_argument("--config", required=True)
    archive.add_argument("--destination", required=True, help="Must not already exist")

    record = sub.add_parser("record-run", help="Attest to inputs, output and provenance of one stored run")
    for name in ("source", "template", "headmask", "result", "workflow", "config"):
        record.add_argument(f"--{name}", required=True)
    record.add_argument("--method-id", required=True, help="e.g. current_klein_v6 or dreamswap_r3")
    record.add_argument("--destination", required=True)
    record.add_argument("--checkpoint-sha256")
    record.add_argument("--reference", action="append", help="Repeat for EVERY reference in model input order, including --source")
    record.add_argument("--mask-channel", choices=["red", "green", "blue", "alpha", "luminance"], default="red")
    record.add_argument("--latency-ms", type=float)
    record.add_argument("--peak-vram-bytes", type=float)
    record.add_argument("--measurement-protocol", help="Required whenever a performance number is given")
    record.add_argument("--hardware", help="Required whenever a performance number is given")
    record.add_argument("--device")
    record.add_argument("--warmup-runs", type=int)

    compare = sub.add_parser("compare", help="Measure a benchmark manifest and write report.json plus grids")
    compare.add_argument("--manifest", required=True)
    compare.add_argument("--output-dir", required=True)
    compare.add_argument("--training-manifest", action="append", default=[],
                         help="Repeatable. Supply every training/validation manifest for the leakage audit")
    compare.add_argument("--registry", help="Hash-bound dataset_registry.json required for comparisons involving real identities")
    compare.add_argument("--allow-synthetic", action="store_true",
                         help="Fixture mode; the report is labelled as not a quality benchmark")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "archive-baseline":
        result = archive_baseline(args.workflow, args.config, args.destination)
    elif args.command == "record-run":
        result = record_stored_result(source=args.source, template=args.template, headmask=args.headmask,
                                      result=args.result, workflow=args.workflow, config=args.config,
                                      method_id=args.method_id, destination=args.destination,
                                      performance=_performance(args), checkpoint_sha256=args.checkpoint_sha256,
                                      sources=args.reference, mask_channel=args.mask_channel)
    else:
        report = benchmark(args.manifest, args.output_dir, training_manifests=args.training_manifest,
                           allow_synthetic=args.allow_synthetic, registry_path=args.registry)
        result = {"report": str(Path(args.output_dir).resolve() / "report.json"), "case_count": report["case_count"],
                  "purpose": report["purpose"], "coverage": report["coverage"],
                  "missing_recommended_tags": report["missing_recommended_tags"],
                  "split_audit_complete": report["split_audit"]["complete"],
                  "aggregate": report["aggregate"]}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
