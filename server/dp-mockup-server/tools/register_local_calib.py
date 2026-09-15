"""Marker en lokalt kalibrert mal som klar i malregisteret.

calibrate_local.py skriver kartene; dette skrittet gjor dem synlige for
serveren. Skilt fra kalibreringen med vilje: kartene kan inspiseres for de tas
i bruk, og en feilet kalibrering kan aldri havne i produksjon ved et uhell.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template-id", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    reg_path = os.path.join(args.data_dir, "templates.json")
    with open(reg_path, encoding="utf-8") as fh:
        reg = json.load(fh)
    if args.template_id not in reg:
        raise SystemExit(f"ukjent mal: {args.template_id}")

    maps_dir = os.path.join(args.data_dir, "calib", args.template_id)
    with open(os.path.join(maps_dir, "meta.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    if not meta.get("accepted"):
        raise SystemExit("kalibreringen er ikke godkjent - nekter aa registrere den")

    reg[args.template_id].update({
        "status": "ready",
        "width": meta["width"],
        "height": meta["height"],
        "mapsDir": os.path.abspath(maps_dir).replace(os.sep, "/"),
        "validation": meta["validation"],
        "influenceRatio": meta["influenceRatio"],
        "coverRect": meta.get("coverRect"),
        "calibratedAt": meta["calibratedAt"],
        "calibrationVersion": meta["calibrationVersion"],
        "error": None,
    })
    with open(reg_path, "w", encoding="utf-8") as fh:
        json.dump(reg, fh, indent=2, ensure_ascii=False)

    print(f"registrert: {args.template_id} -> ready "
          f"({meta['width']}x{meta['height']}, "
          f"mean-avvik {meta['validation']['model']['mean']:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
