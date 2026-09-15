"""Legg 'Dragedalen' (norsk) inn i DP Title Tester.

Legger til:
  - en ny Switch-utgang for book == 'dragedalen'
  - en ny Set-node 'dragedalen' med tittelparametrene (line2 = logo-bilde)
  - koblingene Switch[ny] -> dragedalen -> Execute Command

Startverdiene er arvet fra 'Dragejakten' (bok 1 i samme serie); logoen har
nesten identisk sideforhold, saa de traff med en gang. Fasit for trykk finnes
ikke enda - boka er en stubb uten tekst-script.

Skrives via n8n sitt PUBLIC API - direkte sqlite-endringer lastes ikke inn i en
kjorende n8n. Idempotent: kjor gjerne flere ganger.

Bruk:
  python patch_title_tester_dragedalen.py --dry-run
  python patch_title_tester_dragedalen.py --apply
"""
from __future__ import annotations

import argparse
import sys

import patch_title_tester_havfruen as v1

WF = "1BqeGkXyjbUBsR9N"
SLUG = "dragedalen"
NODE = "dragedalen"
NODE_ID = "tt-book-dragedalen"
NODE_Y = 3152          # forste ledige rad under 'skyggedalen' (3008)
COVER = "C:/ComfyUI/input/forside(dragedalen).png"
LOGO = "C:/ComfyUI/script/logo/nb/dragedalen-logo-nb.png"

FIELDS = [
    ("cover_image", "={{ $json.cover_image_path || '%s' }}" % COVER),
    ("line2", ""),
    ("font_small", "92"),
    ("font_large", "118"),
    ("gold", "255, 255, 255"),
    ("shadow", "5, 8, 18"),
    ("line1", '={{ $node["Set Test Inputs"].json["name"] }} og'),
    ("top_margin", "0.025"),
    ("line_spacing", "0.020"),
    ("line2_image", LOGO),
    ("logo_scale", "0.72"),
    ("logo_x_offset", "0"),
    ("logo_shadow_opacity", "110"),
    ("shadow_opacity", "150"),
    ("shadow_blur", "6"),
    ("glow_opacity", "0.5"),
    ("glow_radius_scale", "0.4"),
    ("bottom_logo_shadow_opacity", "220"),
    ("bottom_logo_shadow_blur", "8"),
    ("bottom_logo_shadow_offset", "10"),
]


def build_node():
    return {
        "parameters": {
            "assignments": {"assignments": [
                {"id": "tt-%s-%s" % (SLUG, name), "name": name,
                 "value": value, "type": "string"}
                for name, value in FIELDS
            ]},
            "includeOtherFields": True,
            "options": {},
        },
        "id": NODE_ID,
        "name": NODE,
        "type": "n8n-nodes-base.set",
        "typeVersion": 3.4,
        "position": [-224, NODE_Y],
    }


def build_rule():
    return {"conditions": {
        "options": {"caseSensitive": True, "leftValue": "",
                    "typeValidation": "strict", "version": 2},
        "conditions": [{
            "id": "tt-sw-" + SLUG,
            "leftValue": '={{$json["book"]}}',
            "rightValue": SLUG,
            "operator": {"type": "string", "operation": "equals",
                         "name": "filter.operator.equals"},
        }],
        "combinator": "and",
    }}


def patch(wf):
    nodes, conns = wf["nodes"], wf["connections"]
    changed = []

    node = next((n for n in nodes if n["name"] == NODE), None)
    if node is None:
        nodes.append(build_node())
        changed.append("ny Set-node %r paa y=%d" % (NODE, NODE_Y))
    else:
        changed += v1.set_fields(node, dict(FIELDS))

    sw = next(n for n in nodes if n["name"] == "Switch")
    values = sw["parameters"]["rules"]["values"]
    keys = [v["conditions"]["conditions"][0]["rightValue"] for v in values]
    if SLUG in keys:
        idx = keys.index(SLUG)
    else:
        values.append(build_rule())
        idx = len(values) - 1
        changed.append("Switch-utgang [%d] for %r" % (idx, SLUG))

    branches = conns["Switch"]["main"]
    while len(branches) <= idx:
        branches.append([])
    if not any(t["node"] == NODE for t in branches[idx] or []):
        branches[idx] = [{"node": NODE, "type": "main", "index": 0}]
        changed.append("koblet Switch[%d] -> %s" % (idx, NODE))

    if NODE not in conns:
        conns[NODE] = {"main": [[{"node": "Execute Command",
                                  "type": "main", "index": 0}]]}
        changed.append("koblet %s -> Execute Command" % NODE)

    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    key = v1.load_api_key()
    wf = v1.req("GET", "/workflows/" + WF, key=key)
    print("%s (aktiv: %s, %d noder)" % (wf["name"], wf.get("active"), len(wf["nodes"])))

    changed = patch(wf)
    for c in changed:
        print("  +", c)
    if not changed:
        print("  (alt paa plass fra for)")
        return 0

    if args.apply:
        v1.write(key, wf, WF)
        print("Skrevet.")
    else:
        print("(dry-run - ingenting skrevet)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
