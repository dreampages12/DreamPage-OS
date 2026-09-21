"""Lokal mottakskontroll og bildekatalog. Ingen innroemming eller trening."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path

from PIL import Image, ImageOps

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff"}


def inspect_intake(incoming, output):
    incoming, output = Path(incoming).resolve(), Path(output).resolve()
    if not incoming.is_dir():
        raise ValueError("Mottaksmappa mangler")
    if output.is_relative_to(incoming):
        raise ValueError("Review skal ligge utenfor originalbildene")
    # Et review er et oeyeblikksbilde. Aldri overskriv det noen allerede har sett.
    output.mkdir(parents=True, exist_ok=False)
    previews = output / "previews"
    previews.mkdir()
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass  # HEIC blir rapportert som lesefeil; ikke stilletiende utelatt.
    records, errors, hashes = [], [], {}
    for path in sorted(incoming.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            continue
        relative = path.relative_to(incoming).as_posix()
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with Image.open(path) as image:
                oriented = ImageOps.exif_transpose(image)
                rgb = oriented.convert("RGB")
                width, height = rgb.size
                decoded = hashlib.sha256(f"{width}x{height}:".encode() + rgb.tobytes()).hexdigest()
                rgb.thumbnail((360, 360))
                preview = f"previews/{len(records):05d}.png"
                # EXIF/kundeopplysninger kopieres ikke til visningsbildet.
                rgb.save(output / preview)
            hashes.setdefault(decoded, []).append(relative)
            records.append({"path": relative, "sha256": digest, "decoded_sha256": decoded,
                            "width": width, "height": height, "preview": preview,
                            "photorealism_reviewed": False, "rights_reviewed": False})
        except Exception as exc:
            errors.append({"path": relative, "error": f"{type(exc).__name__}: {exc}"})
    swaps = []
    swap_root = incoming / "swaps"
    for folder in sorted(swap_root.glob("*")):
        items = [r for r in records if Path(r["path"]).parent.as_posix() == f"swaps/{folder.name}"]
        if not items:
            continue
        roles = {}
        for item in items:
            roles.setdefault(Path(item["path"]).stem.lower(), []).append(item)
        missing = [key for key in ("person", "for", "etter", "maske") if not roles.get(key)]
        ambiguous = [key for key in ("person", "for", "etter", "maske") if len(roles.get(key, [])) > 1]
        sizes = {(r["width"], r["height"]) for key in ("for", "etter", "maske") for r in roles.get(key, [])}
        swaps.append({"folder": folder.name, "missing": missing, "ambiguous": ambiguous,
                      "scene_dimensions_match": len(sizes) == 1,
                      "provenance": "DreamPage pipeline, user declaration; individual outputs await review"})
    inventory = [{k: r[k] for k in ("path", "sha256", "width", "height")} for r in records]
    report = {"schema_version": 1, "scope": "intake_only_not_training_approval", "approved": False,
              "inventory_sha256": hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest(),
              "images": records, "errors": errors, "swaps": swaps,
              "duplicates": [paths for paths in hashes.values() if len(paths) > 1],
              "pending": ["Visuell fotorealisme og identitet", "Samtykke og kilder", "Masker og par",
                          "Identitetssplitter og korpusregister", "Brukerens eksplisitte datasettgodkjenning"]}
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    cards = "\n".join(f'<figure><img loading="lazy" src="{r["preview"]}"><figcaption>'
                      f'{html.escape(r["path"])}<br>{r["width"]} x {r["height"]}</figcaption></figure>' for r in records)
    page = '<!doctype html><html lang="nb"><meta charset="utf-8"><title>DreamPage dataset review</title>'
    page += '<style>body{font:16px system-ui;margin:32px;background:#eee}main{display:flex;flex-wrap:wrap}figure{width:360px;margin:12px;background:white;padding:12px}img{max-width:360px}figcaption{overflow-wrap:anywhere}</style>'
    page += f'<h1>Datasett til gjennomgang</h1><p>{len(records)} bilder. Ikke godkjent for trening.</p>'
    page += f'<p>{len(errors)} lesefeil. Se report.json for mangler og duplikater. Originalene er bevart.</p><main>{cards}</main></html>'
    (output / "index.html").write_text(page, encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = inspect_intake(args.input, args.output)
    print(json.dumps({"images": len(report["images"]), "errors": len(report["errors"]),
                      "approved": False, "review": str(Path(args.output).resolve() / "index.html")}))


if __name__ == "__main__":
    main()
