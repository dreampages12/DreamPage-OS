"""Turn a cleaned identity manifest into deterministic, identity-disjoint training pairs.

Splitting is by identity, never by image, and the written manifests are re-validated for
rights, duplicate captures and cross-split content leakage before the script reports success.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from dreampage_headswap.data.pairing import PAIR_STRATEGIES, generate_pairs
from dreampage_headswap.data.records import load_identities, validate_pair_manifests, write_jsonl
from dreampage_headswap.data.registry import create_registry
from dreampage_headswap.evaluation.benchmark import save_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--identities", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--strategy", default="same_identity", choices=sorted(PAIR_STRATEGIES))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-pairs-per-identity", type=int)
    parser.add_argument("--train-fraction", type=float, default=0.8)
    parser.add_argument("--validation-fraction", type=float, default=0.1)
    parser.add_argument("--allow-synthetic", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    identities = load_identities(args.identities, allow_synthetic=args.allow_synthetic)
    rows = generate_pairs(identities, seed=args.seed, strategy=args.strategy,
                          max_pairs_per_identity=args.max_pairs_per_identity,
                          train_fraction=args.train_fraction, validation_fraction=args.validation_fraction)
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("Use a fresh empty pairs directory; stale split manifests must not survive regeneration")
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for split in sorted({row["split"] for row in rows}):
        path = output_dir / f"pairs.{split}.jsonl"
        write_jsonl(path, [row for row in rows if row["split"] == split])
        written[split] = str(path)
    # Re-read every written manifest together: this is the real split-leakage gate.
    validated = validate_pair_manifests(written.values(), allow_synthetic=args.allow_synthetic)
    registry_path = output_dir / "dataset_registry.json"
    create_registry(written.values(), registry_path, identity_manifest=args.identities)
    summary = {"schema_version": 1, "strategy": args.strategy, "seed": args.seed,
               "identity_manifest": str(Path(args.identities).resolve()),
               "manifests": written, "registry": str(registry_path), "pair_count": len(validated),
               "pairs_per_split": dict(sorted(Counter(row["split"] for row in validated).items())),
               "identities_per_split": {split: len({row["identity_id"] for row in validated if row["split"] == split})
                                        for split in sorted(written)},
               "leakage_audit": "Identity, file-hash and decoded-pixel checks passed across all written manifests",
               "synthetic_fixture_run": bool(args.allow_synthetic)}
    save_json(output_dir / "pairs_summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
