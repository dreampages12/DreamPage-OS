# -*- coding: utf-8 -*-
"""Gjor den nedre DreamPage-logoen styrbar i DP Title Tester.

Legger fire felter paa bok-noden (samme sted som logo_scale allerede bor) og
sender dem videre i Execute Command. Feltene er valgfrie: uten dem faller
rendereren tilbake paa standardlogoen, saa alle andre boker er urort.

  python patch_title_tester_bottomlogo.py --book fotballsjernen --dry-run
  python patch_title_tester_bottomlogo.py --book fotballsjernen --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime

DB = "C:/Users/tobia/.n8n/database.sqlite"
WF = "1BqeGkXyjbUBsR9N"

# Flaggene legges bakerst, etter line2-logoen, slik at kommandoen leser i samme
# rekkefolge som forsiden bygges: linje 1, linje 2, nedre logo.
TAIL = (
    "{{ $json.bottom_logo ? ' --bottom_logo \"' + $json.bottom_logo"
    " + '\" --bottom_logo_scale ' + ($json.bottom_logo_scale || 0.40)"
    " + ' --bottom_logo_margin ' + ($json.bottom_logo_margin || 0.03)"
    " + ' --bottom_logo_x_offset ' + ($json.bottom_logo_x_offset || 0) : '' }}"
)

FIELDS = [
    ("bottom_logo", "C:/ComfyUI/script/pre/DreamPage_logo_blue.png"),
    ("bottom_logo_scale", "0.40"),
    ("bottom_logo_margin", "0.03"),
    ("bottom_logo_x_offset", "0"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True, help="navnet paa bok-noden i testeren")
    ap.add_argument("--select", default="", help="verdien Switch ruter paa (book i Set Test Inputs)")
    ap.add_argument("--cover", default="", help="forsidebilde Set Test Inputs skal bruke")
    ap.add_argument("--out-file", default="", help="filnavn for testbildet")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    db = sqlite3.connect(DB)
    row = db.execute("select nodes from workflow_entity where id=?", (WF,)).fetchone()
    nodes = json.loads(row[0]) if isinstance(row[0], str) else row[0]

    book = next((n for n in nodes if n["name"] == args.book), None)
    if book is None:
        raise SystemExit(f"fant ingen node som heter {args.book!r}")
    cmd = next((n for n in nodes if n["name"] == "Execute Command"), None)
    if cmd is None:
        raise SystemExit("fant ingen Execute Command-node")

    changed = []

    assigns = book["parameters"]["assignments"]["assignments"]
    have = {a["name"] for a in assigns}
    for name, value in FIELDS:
        if name in have:
            continue
        assigns.append({"id": f"tt-{args.book}-{name}", "name": name,
                        "value": value, "type": "string"})
        changed.append(f"{args.book}.{name} = {value}")

    wanted = {"book": args.select, "cover_image_path": args.cover,
              "output_filename": args.out_file}
    if any(wanted.values()):
        inputs = next(n for n in nodes if n["name"] == "Set Test Inputs")
        for a in inputs["parameters"]["assignments"]["assignments"]:
            new = wanted.get(a["name"])
            if new and a["value"] != new:
                changed.append(f"Set Test Inputs.{a['name']}: {a['value']} -> {new}")
                a["value"] = new

    text = cmd["parameters"]["command"]
    if "bottom_logo" not in text:
        # Kommandoen slutter med linjeskift; flaggene skal foran det.
        cmd["parameters"]["command"] = text.rstrip("\n") + TAIL + "\n"
        changed.append("Execute Command: sender nedre-logo-flaggene")

    for line in changed or ["ingenting aa endre"]:
        print("  " + line)

    if args.apply and changed:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy(DB, f"{DB}.backup-bottomlogo-{stamp}")
        db.execute("update workflow_entity set nodes=?, updatedAt=? where id=?",
                   (json.dumps(nodes, ensure_ascii=False),
                    datetime.utcnow().isoformat(sep=" ", timespec="milliseconds"), WF))
        db.commit()
        print("SKREVET - last inn workflowen paa nytt i n8n")
    else:
        print("TORRKJORING")
    return 0


if __name__ == "__main__":
    sys.exit(main())
