"""Legg 'Juleprinsessen' (norsk) inn i DP Title Tester og forhaandsvelg den.

Legger til:
  - en ny Switch-utgang for book == 'juleprinsessen'
  - en ny Set-node 'juleprinsessen' med tittelparametrene (line2 = logo-bilde)
  - koblingene Switch[ny] -> juleprinsessen -> Execute Command
  - setter 'Set Test Inputs' til book=juleprinsessen, saa testeren rendrer
    denne boka rett ut av boksen (--no-select hopper over det)

Verdiene speiler FRONT_COVER_*-konstantene i script/<locale>/juleprinsessen-text-*.py,
saa testeren og trykket viser det samme. Logoen inneholder HELE tittelen, saa
linje 1 er bare barnets navn. font_small er ABSOLUTTE piksler mot malens bredde
(1254 px) - tekst-scriptet bruker 78/1254 av kortsiden.

Skrives via n8n sitt PUBLIC API - direkte sqlite-endringer lastes ikke inn i en
kjorende n8n. Idempotent.

Bruk:
  python patch_title_tester_juleprinsessen.py --dry-run
  python patch_title_tester_juleprinsessen.py --apply
"""
from __future__ import annotations

import argparse
import sys

import patch_title_tester_havfruen as v1

WF = "1BqeGkXyjbUBsR9N"
SLUG = "juleprinsessen"
NODE = "juleprinsessen"
NODE_ID = "tt-book-juleprinsessen"
NODE_Y = 3440          # forste ledige rad under 'havpalasset' (3296)
COVER = "C:/ComfyUI/input/forside(juleprinsessen).png"
LOGO = "C:/ComfyUI/script/logo/nb/juleprinsessen-logo-nb.png"

FIELDS = [
    ("cover_image", "={{ $json.cover_image_path || '%s' }}" % COVER),
    ("line1", '={{ $node["Set Test Inputs"].json["name"] }}'),
    ("line2", ""),
    ("line2_image", LOGO),
    # 0.62 og 0.55 la logoen rett over ansiktet til jenta; 0.48 lar halen av
    # logoen saavidt beroere haaret hennes og holder ansiktet fritt.
    ("logo_scale", "0.48"),
    ("logo_x_offset", "0"),
    ("font_small", "78"),
    ("font_large", "120"),
    ("gold", "255, 255, 255, 255, 245, 220"),
    ("shadow", "10, 14, 35"),
    ("top_margin", "0.010"),
    ("line_spacing", "-0.010"),
    ("font_small_path", "C:/ComfyUI/script/pre/Trebuchet MS Bold.ttf"),
    ("font_large_path", "C:/ComfyUI/script/pre/PlayfairDisplay.ttf"),
    ("logo_shadow_opacity", "180"),
    ("shadow_opacity", "200"),
    ("shadow_blur", "4"),
    # Motivet er moerkeblaa stjernehimmel - den varme standardgloden ville
    # lyst opp bakgrunnen rundt navnet. Lav opacity, moerk farge.
    ("glow_color", "10,14,35"),
    ("glow_opacity", "0.4"),
    ("glow_radius_scale", "0.3"),
]

TEST_INPUTS = {
    "book": SLUG,
    "output_filename": "%s-tester.png" % SLUG,
}


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


def patch(wf, select=True):
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

    if select:
        ti = next((n for n in nodes if n["name"] == "Set Test Inputs"), None)
        if ti is None:
            changed.append("ADVARSEL: fant ingen 'Set Test Inputs'")
        else:
            changed += v1.set_fields(ti, TEST_INPUTS)

    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-select", action="store_true",
                    help="ikke ror 'Set Test Inputs'")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    key = v1.load_api_key()
    wf = v1.req("GET", "/workflows/" + WF, key=key)
    print("%s (aktiv: %s, %d noder)" % (wf["name"], wf.get("active"), len(wf["nodes"])))

    changed = patch(wf, select=not args.no_select)
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
