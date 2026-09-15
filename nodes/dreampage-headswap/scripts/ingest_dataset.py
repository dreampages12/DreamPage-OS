"""Turn a folder of captures into an enrolled identity manifest with headmasks.

Expected input: one directory per person, several captures inside each.

```
raw/
  consented_0001/
    a.jpg
    b.jpg
  consented_0002/
    ...
```

What this does, in order: validate the rights record before touching anything, normalize each
capture's orientation into a lossless copy, obtain a headmask through an explicit provider, and
write `identities.jsonl` plus a report naming every accepted and rejected capture.

What it deliberately does not do: invent a headmask, guess a licence, infer consent, or accept a
capture it could not mask. Enrolment is where a corpus's rights story is fixed, so everything it
records has to be something a person actually asserted.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from dreampage_headswap.data.headmasks import build_provider
from dreampage_headswap.data.preprocessing import decoded_pixel_sha256
from dreampage_headswap.data.records import RightsMetadata, load_identities, write_jsonl
from dreampage_headswap.evaluation.benchmark import save_json

CAPTURE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="Directory holding one subdirectory per identity")
    parser.add_argument("--output-dir", required=True, help="A fresh directory; nothing is overwritten")
    parser.add_argument("--rights", required=True,
                        help="JSON rights record: provenance, licence, consent, permissions. Applied to every identity")
    parser.add_argument("--mask-provider", default="sidecar",
                        choices=["sidecar", "supplied-box", "sidecar-then-box", "none"],
                        help="Where headmasks come from. Model-backed providers are wired in code so their "
                             "weights' licence is stated explicitly")
    parser.add_argument("--mask-suffix", default="_mask.png", help="Sidecar naming, relative to each capture")
    parser.add_argument("--mask-channel", default="luminance",
                        choices=["red", "green", "blue", "alpha", "luminance"])
    parser.add_argument("--boxes", help="JSON mapping '<identity>/<capture stem>' to an xyxy head box "
                                        "in the normalized image's coordinates")
    parser.add_argument("--box-shape", default="ellipse", choices=["ellipse", "rectangle"])
    parser.add_argument("--box-padding", type=float, default=0.08)
    parser.add_argument("--ages", help="JSON mapping identity to age in years at capture time")
    parser.add_argument("--splits", help="JSON mapping identity to train, validation, test or benchmark. "
                                         "Omit to let the deterministic identity hash decide later")
    parser.add_argument("--synthetic", action="store_true", help="Mark the corpus as a fixture, not people")
    parser.add_argument("--min-captures", type=int, default=2,
                        help="Pair training needs at least two distinct captures of one person")
    return parser


def _load_json(path, what: str) -> dict:
    if path is None:
        return {}
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be a JSON object")
    return value


def _normalize(source: Path, destination: Path) -> dict:
    """Write a lossless, canonically oriented copy. Returns what had to change."""
    with Image.open(source) as image:
        image.load()
        orientation = image.getexif().get(274, 1)
        rotated = ImageOps.exif_transpose(image).convert("RGB")
    destination.parent.mkdir(parents=True, exist_ok=True)
    rotated.save(destination)
    return {"orientation_tag": int(orientation), "reoriented": orientation != 1,
            "width": rotated.width, "height": rotated.height}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"No such directory: {root}")
    rights = json.loads(Path(args.rights).read_text(encoding="utf-8"))
    # Validate before writing anything: an unusable corpus should never reach disk.
    RightsMetadata.from_dict(rights)
    boxes = _load_json(args.boxes, "Boxes file")
    ages = _load_json(args.ages, "Ages file")
    splits = _load_json(args.splits, "Splits file")
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)

    options = {"suffix": args.mask_suffix, "channel": args.mask_channel} if "sidecar" in args.mask_provider else {}
    if "box" in args.mask_provider:
        options.update(shape=args.box_shape, padding=args.box_padding)
    provider = build_provider(args.mask_provider, **options)

    identities, report_rows, seen_pixels = [], [], {}
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        identity_id = directory.name
        if identity_id in splits and splits[identity_id] not in {"train", "validation", "test", "benchmark"}:
            raise SystemExit(f"Invalid split for {identity_id}: {splits[identity_id]}")
        records = []
        for capture in sorted(path for path in directory.iterdir()
                              if path.suffix.lower() in CAPTURE_SUFFIXES and not path.name.endswith(args.mask_suffix)):
            key = f"{identity_id}/{capture.stem}"
            row = {"identity_id": identity_id, "image_id": capture.stem, "source": str(capture), "accepted": False}
            destination = output / "images" / identity_id / f"{capture.stem}.png"
            try:
                row.update(_normalize(capture, destination))
            except (OSError, ValueError) as error:
                row["reason"] = f"unreadable_capture:{type(error).__name__}"
                report_rows.append(row)
                continue
            digest = decoded_pixel_sha256(destination)
            if digest in seen_pixels:
                row["reason"] = f"duplicate_of:{seen_pixels[digest]}"
                destination.unlink()
                report_rows.append(row)
                continue
            seen_pixels[digest] = key
            image = np.asarray(Image.open(destination).convert("RGB"))
            metadata = {"path": str(capture), "mask_channel": args.mask_channel}
            if key in boxes:
                if row["reoriented"]:
                    # A box measured on the original would land somewhere else after rotation.
                    row["reason"] = "supplied_box_with_reoriented_capture_remeasure_on_the_normalized_copy"
                    report_rows.append(row)
                    continue
                metadata["head_bbox"] = boxes[key]
            result = provider.mask(image, metadata)
            if result.values is None:
                row["reason"] = f"no_headmask:{result.reason}"
                report_rows.append(row)
                continue
            mask_path = destination.with_name(destination.stem + "_mask.png")
            Image.fromarray(np.rint(result.values * 255).clip(0, 255).astype(np.uint8), mode="L").save(mask_path)
            record = {"image_id": capture.stem, "path": str(destination), "headmask": str(mask_path),
                      "headmask_provenance": result.as_metadata(),
                      "source_capture": {"path": str(capture), "sha256": digest,
                                         "orientation_tag": row["orientation_tag"], "reoriented": row["reoriented"]}}
            records.append(record)
            row.update(accepted=True, headmask=str(mask_path), mask_authority=result.authority,
                       mask_provider=result.provider)
            report_rows.append(row)
        if len(records) < args.min_captures:
            report_rows.append({"identity_id": identity_id, "accepted": False,
                                "reason": f"fewer_than_{args.min_captures}_usable_captures"})
            continue
        identity = {"identity_id": identity_id, "rights": rights, "synthetic": bool(args.synthetic),
                    "images": records}
        if identity_id in splits:
            identity["split"] = splits[identity_id]
        if identity_id in ages:
            identity["age"] = ages[identity_id]
        identities.append(identity)

    manifest = output / "identities.jsonl"
    write_jsonl(manifest, identities)
    if identities:
        # Prove the manifest passes the same gate the rest of the stack applies.
        load_identities(manifest, allow_synthetic=bool(args.synthetic))

    authorities = Counter(row.get("mask_authority") for row in report_rows if row.get("accepted"))
    report = {"schema_version": 1, "root": str(root), "manifest": str(manifest),
              "mask_provider": provider.name, "rights": rights, "synthetic": bool(args.synthetic),
              "identities_enrolled": len(identities),
              "captures_enrolled": sum(len(identity["images"]) for identity in identities),
              "captures_rejected": sum(1 for row in report_rows if not row.get("accepted")),
              "mask_authority_counts": dict(sorted((key, value) for key, value in authorities.items() if key)),
              "captures": report_rows,
              "note": "derived_geometric masks are coarse box approximations, not reviewed production masks",
              "next": "python scripts/preprocess_dataset.py --identities " + str(manifest) + " --output-dir <clean>"}
    save_json(output / "ingest_report.json", report)
    print(json.dumps({key: value for key, value in report.items() if key != "captures"}, indent=2))
    return 0 if identities else 1


if __name__ == "__main__":
    raise SystemExit(main())
