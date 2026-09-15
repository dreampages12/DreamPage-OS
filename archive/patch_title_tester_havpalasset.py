"""Legg 'Havpalasset' (norsk) inn i DP Title Tester.

Legger til:
  - en ny Switch-utgang for book == 'havpalasset'
  - en ny Set-node 'havpalasset' med tittelparametrene (line2 = logo-bilde)
  - koblingene Switch[ny] -> havpalasset -> Execute Command

Startverdiene er arvet fra 'havfruen'-noden (bok 1 i samme serie), med to
endringer: linje 1 er "<navn> og" (havfruen har "blir", fordi logoen der bare
sier "Havfrue"), og logo_scale er 0.62 i stedet for 0.50 - Havpalasset-logoen
er bredere og 0.50 ble for spinkel mot dette motivet. 0.72 kom bort i haaret
paa jenta.

Skrives via n8n sitt PUBLIC API - direkte sqlite-endringer lastes ikke inn i en
kjorende n8n. Idempotent.

Bruk:
  python patch_title_tester_havpalasset.py --dry-run
  python patch_title_tester_havpalasset.py --apply
"""
from __future__ import annotations

import argparse
import sys

import patch_title_tester_havfruen as v1

WF = "1BqeGkXyjbUBsR9N"
SLUG = "havpalasset"
NODE = "havpalasset"
NODE_ID = "tt-book-havpalasset"
NODE_Y = 3296          # forste ledige rad under 'dragedalen' (3152)
COVER = "C:/ComfyUI/input/forside(havpalasset).png"
LOGO = "C:/ComfyUI/script/logo/nb/havpalasset-logo-nb.png"

FIELDS = [
    ("cover_image", "={{ $json.cover_image_path || '%s' }}" % COVER),
    ("line1", '={{ $node["Set Test Inputs"].json["name"] }} og'),
    ("line2", ""),
    ("line2_image", LOGO),
    ("logo_scale", "0.62"),
    ("logo_x_offset", "0"),
    ("font_small", "80"),
    ("font_large", "120"),
    ("gold", "255, 255, 255"),
    ("shadow", "15, 35, 65"),
    ("top_margin", "0.04"),
    ("line_spacing", "0.020"),
    ("font_small_path", "C:/ComfyUI/script/pre/Trebuchet MS Bold.ttf"),
    ("font_large_path", "C:/ComfyUI/script/pre/PlayfairDisplay.ttf"),
    ("logo_shadow_opacity", "255"),
    # Moerk glod i samme farge som skyggen. Motivet er lys himmel med
    # solstraaler rett bak linje 1; standardgloden er varm hvit og vasker
    # teksten ut i stedet for aa loefte den (samme grep som fotball-vm).
    # Liten radius er viktig: gloden er en gaussisk uskarphet av teksten, saa
    # en stor radius sprer alfaen tynn og blir usynlig. 0.25 * 80 px = 20 px
    # gir en tett, moerk kant. Rendereren har uansett gulv paa 18 px.
    ("glow_color", "15,35,65"),
    ("glow_opacity", "1.0"),
    ("glow_radius_scale", "0.25"),
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
