"""Score an enrolled corpus against an explicit quality target, and name the gaps.

"A good dataset" is not a feeling. For identity-preserving head reconstruction it means a
specific, checkable list: enough distinct people, several captures of each, enough pixels
across the head itself rather than the page, sharp captures, reviewed masks, no duplicates,
identities that appear in exactly one split, and known ages when the product is for children.

This reads an identity manifest, measures each of those, and prints what passes and what is
short. Two things it will not do: score pose, expression or lighting diversity from the pixels,
because nothing here estimates them, and turn its own measurements into a quality claim about a
trained model. It measures the corpus, not the output.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path

import numpy as np

from dreampage_headswap.data.preprocessing import decoded_pixel_sha256, inspect_image
from dreampage_headswap.data.records import load_identities
from dreampage_headswap.evaluation.benchmark import save_json
from dreampage_headswap.masking import load_headmask

POSE_FIELDS = ("yaw", "pitch", "roll", "gaze_x", "gaze_y", "expression", "lighting")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--identities", required=True, help="Identity manifest, raw or preprocessed")
    parser.add_argument("--report", help="Write the full JSON report here")
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--min-identities", type=int, default=200,
                        help="Distinct people. Below this, a contrastive identity objective has few negatives "
                             "and a held-out split is too small to mean anything")
    parser.add_argument("--min-captures", type=int, default=3,
                        help="Captures per person. Two is the minimum that makes a pair; three lets the "
                             "source view vary independently of the target")
    parser.add_argument("--min-head-pixels", type=int, default=256,
                        help="Shorter side of the masked head region. The model crops around the head, so "
                             "this, not the image size, is the resolution that reaches it")
    parser.add_argument("--min-blur", type=float, default=40.0, help="Laplacian variance floor")
    parser.add_argument("--max-mask-fraction", type=float, default=0.6,
                        help="A mask covering most of the frame leaves no protected context to preserve")
    parser.add_argument("--min-reviewed-mask-fraction", type=float, default=0.9,
                        help="Share of captures whose mask a person prepared, rather than a box approximation")
    return parser


def _mask_measurements(path, hw) -> dict:
    values = load_headmask(path).values
    if values.shape != tuple(hw):
        return {"available": False, "reason": "mask_resolution_mismatch"}
    editable = values > 0
    if not editable.any():
        return {"available": False, "reason": "empty_mask"}
    rows, columns = np.nonzero(editable)
    y0, y1, x0, x1 = int(rows.min()), int(rows.max()) + 1, int(columns.min()), int(columns.max()) + 1
    height, width = hw
    touches = bool(y0 == 0 or x0 == 0 or y1 == height or x1 == width)
    return {"available": True, "fraction": float(editable.mean()),
            "box": [x0, y0, x1, y1], "head_pixels": int(min(y1 - y0, x1 - x0)),
            "relative_height": float((y1 - y0) / height), "touches_border": touches}


def _statistics(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    return {"count": len(values), "min": min(values), "max": max(values),
            "mean": statistics.fmean(values), "median": statistics.median(values)}


def measure(identities) -> dict:
    captures, per_identity, digests = [], {}, Counter()
    for identity in identities:
        rows = []
        for image in identity.images:
            quality = image.metadata.get("quality", {})
            measured = {"identity_id": identity.identity_id, "image_id": image.image_id,
                        "path": str(image.path)}
            if quality.get("width") and quality.get("height"):
                measured.update(width=quality["width"], height=quality["height"],
                                blur=quality.get("laplacian_variance"),
                                pixel_sha256=quality.get("pixel_sha256"))
            else:
                inspected = inspect_image(image.path)
                measured.update(width=inspected.get("width"), height=inspected.get("height"),
                                blur=inspected.get("laplacian_variance"),
                                pixel_sha256=inspected.get("pixel_sha256"),
                                integrity_reasons=inspected["reasons"])
            if measured.get("pixel_sha256"):
                digests[measured["pixel_sha256"]] += 1
            provenance = image.metadata.get("headmask_provenance", {})
            measured["mask_authority"] = provenance.get("authority")
            measured["mask_provider"] = provenance.get("provider")
            if image.headmask and measured.get("height"):
                measured["mask"] = _mask_measurements(image.headmask, (measured["height"], measured["width"]))
            else:
                measured["mask"] = {"available": False, "reason": "no_headmask_enrolled"}
            supplied = {field: image.metadata.get(field) for field in POSE_FIELDS
                        if image.metadata.get(field) is not None}
            measured["supplied_geometry"] = sorted(supplied)
            rows.append(measured)
        per_identity[identity.identity_id] = {"captures": len(rows), "split": identity.split,
                                              "age": identity.age, "synthetic": identity.synthetic}
        captures.extend(rows)
    return {"captures": captures, "per_identity": per_identity,
            "duplicate_pixel_groups": sum(1 for count in digests.values() if count > 1)}


def evaluate(measured: dict, args) -> list[dict]:
    captures, per_identity = measured["captures"], measured["per_identity"]
    identities = len(per_identity)
    capture_counts = [value["captures"] for value in per_identity.values()]
    masked = [row for row in captures if row["mask"].get("available")]
    head_pixels = [row["mask"]["head_pixels"] for row in masked]
    blurs = [row["blur"] for row in captures if isinstance(row.get("blur"), (int, float))]
    fractions = [row["mask"]["fraction"] for row in masked]
    reviewed = sum(1 for row in captures if row.get("mask_authority") == "reviewed_external")
    splits = Counter(value["split"] for value in per_identity.values())
    ages = [value["age"] for value in per_identity.values() if value["age"] is not None]
    with_geometry = sum(1 for row in captures if row["supplied_geometry"])

    def criterion(name, ok, measured_value, target, note=None):
        return {"criterion": name, "status": "pass" if ok else "gap", "measured": measured_value,
                "target": target, **({"note": note} if note else {})}

    results = [
        criterion("distinct identities", identities >= args.min_identities, identities,
                  f">= {args.min_identities}",
                  "Held-out identities and in-batch negatives both come out of this number"),
        criterion("captures per identity", bool(capture_counts) and min(capture_counts) >= args.min_captures,
                  {"min": min(capture_counts) if capture_counts else 0, **_statistics([float(c) for c in capture_counts])},
                  f"every identity >= {args.min_captures}"),
        criterion("headmask on every capture", len(masked) == len(captures),
                  f"{len(masked)} of {len(captures)}", "all",
                  "A capture without a mask can never be a training target"),
        criterion("reviewed masks", bool(captures) and reviewed / len(captures) >= args.min_reviewed_mask_fraction,
                  {"reviewed": reviewed, "total": len(captures)},
                  f">= {args.min_reviewed_mask_fraction:.0%}",
                  "Box-derived masks cut hair, ears and chin at the boundary"),
        criterion("head resolution", bool(head_pixels) and min(head_pixels) >= args.min_head_pixels,
                  _statistics([float(value) for value in head_pixels]), f"shorter side >= {args.min_head_pixels} px",
                  "Measured across the masked head, not the whole image"),
        criterion("sharpness", bool(blurs) and min(blurs) >= args.min_blur, _statistics(blurs),
                  f"Laplacian variance >= {args.min_blur}"),
        criterion("protected context remains", bool(fractions) and max(fractions) <= args.max_mask_fraction,
                  _statistics(fractions), f"mask covers <= {args.max_mask_fraction:.0%} of the frame"),
        criterion("head inside the frame", all(not row["mask"]["touches_border"] for row in masked),
                  sum(1 for row in masked if row["mask"]["touches_border"]), "0 captures touching the border",
                  "A head at the edge leaves no context for the padded crop"),
        criterion("no duplicate captures", measured["duplicate_pixel_groups"] == 0,
                  measured["duplicate_pixel_groups"], "0 repeated images"),
        criterion("splits populated", all(splits.get(name, 0) >= 2 for name in ("train", "validation", "test")),
                  dict(sorted((str(key), value) for key, value in splits.items())),
                  ">= 2 identities in each of train, validation and test",
                  "Unassigned identities are split later by a deterministic hash"),
        criterion("ages recorded", bool(ages) and len(ages) == len(per_identity),
                  {"known": len(ages), "identities": len(per_identity), **_statistics(ages)},
                  "an age for every identity",
                  "Age preservation cannot be evaluated for a capture whose age nobody recorded"),
        criterion("pose and expression metadata", with_geometry == len(captures) and bool(captures),
                  f"{with_geometry} of {len(captures)}", "every capture",
                  "Nothing here estimates these; they come from a reviewed provider or from enrolment"),
    ]
    return results


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    identities = load_identities(args.identities, allow_synthetic=args.allow_synthetic)
    measured = measure(identities)
    criteria = evaluate(measured, args)
    gaps = [item for item in criteria if item["status"] == "gap"]
    report = {"schema_version": 1, "manifest": str(Path(args.identities).resolve()),
              "identities": len(measured["per_identity"]),
              "captures": len(measured["captures"]),
              "criteria": criteria, "gap_count": len(gaps),
              "per_identity": measured["per_identity"], "per_capture": measured["captures"],
              "scope": "Corpus measurements only. Says nothing about a trained model's identity or realism.",
              "synthetic": any(value["synthetic"] for value in measured["per_identity"].values())}
    if args.report:
        save_json(args.report, report)
    print(json.dumps({"identities": report["identities"], "captures": report["captures"],
                      "gap_count": len(gaps), "criteria": criteria}, indent=2, allow_nan=False))
    return 0 if not gaps else 2


if __name__ == "__main__":
    raise SystemExit(main())
