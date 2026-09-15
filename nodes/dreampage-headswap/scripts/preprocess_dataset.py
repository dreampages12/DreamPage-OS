"""Validate enrolled identity captures and emit a cleaned manifest plus an audit report.

Nothing here estimates faces. Detection, landmarks, pose and segmentation come from an
explicitly supplied licensed provider; without one those fields stay unavailable.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dreampage_headswap.data.preprocessing import PreprocessConfig, identity_to_dict, preprocess_identities
from dreampage_headswap.data.records import load_identities, write_jsonl
from dreampage_headswap.evaluation.benchmark import save_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--identities", required=True, help="JSONL identity manifest with rights metadata")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--min-width", type=int, default=64)
    parser.add_argument("--min-height", type=int, default=64)
    parser.add_argument("--min-laplacian-variance", type=float, default=20.0)
    parser.add_argument("--mask-channel", choices=["red", "green", "blue", "alpha", "luminance"], default="red")
    parser.add_argument("--allow-missing-headmask", action="store_true",
                        help="Keep captures without an authoritative headmask; they can never become pair targets")
    parser.add_argument("--allow-synthetic", action="store_true",
                        help="Permit fixture identities; results are infrastructure checks, not quality evidence")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    identities = load_identities(args.identities, allow_synthetic=args.allow_synthetic)
    config = PreprocessConfig(min_width=args.min_width, min_height=args.min_height,
                              min_laplacian_variance=args.min_laplacian_variance,
                              require_headmask=not args.allow_missing_headmask, mask_channel=args.mask_channel)
    accepted, report = preprocess_identities(identities, config)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = output_dir / "identities.clean.jsonl"
    write_jsonl(manifest, [identity_to_dict(identity) for identity in accepted])
    report["source_manifest"] = str(Path(args.identities).resolve())
    report["clean_manifest"] = str(manifest)
    report["config"] = vars(config)
    report["synthetic_fixture_run"] = bool(args.allow_synthetic)
    save_json(output_dir / "preprocess_report.json", report)
    print(json.dumps({"clean_manifest": str(manifest),
                      "accepted_identities": report["accepted_identity_count"],
                      "accepted_images": report["accepted_image_count"],
                      "rejected_identities": len(report["identities_rejected"]),
                      "report": str(output_dir / "preprocess_report.json")}, indent=2))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
