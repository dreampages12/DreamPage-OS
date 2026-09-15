"""Legg 'Det Forsvunne Dinosauregget' (norsk) inn i DP Title Tester.

Legger til:
  - én ny Switch-utgang for book == 'det-forsvunne-dinosauregget'
  - én ny Set-node med tittelparametrene (line2 = logo-bilde)
  - kobling Switch[ny] -> Set -> Execute Command

Parametrene holdes i synk med C:/ComfyUI/config/next_book_titles.json, som
build_last_page.py bruker når den setter tittel på neste-forsiden.

Bruk:
  python patch_title_tester_egget.py --dry-run
  python patch_title_tester_egget.py --apply
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

DB = r"C:\Users\tobia\.n8n\database.sqlite"
WF_ID = "1BqeGkXyjbUBsR9N"
TITLES_CONFIG = "C:/ComfyUI/config/next_book_titles.json"

# Settes fra kommandolinjen; standard er boka patchen ble skrevet for.
SLUG = "det-forsvunne-dinosauregget"
NODE_Y = 900
NODE_NAME = SLUG
NODE_ID = "tt-book-forsvunnedinoegget"
COVER = "C:/ComfyUI/input/forside(dinosauregget).png"


def load_params():
    with open(TITLES_CONFIG, encoding="utf-8-sig") as fh:
        return json.load(fh)[SLUG]["nb"]


def build_set_node(p):
    a = [
        ("cov", "cover_image", "={{ $json.cover_image_path || '%s' }}" % COVER),
        ("line2", "line2", p.get("line2", "")),
        ("font_sma", "font_small", str(p["font_small"])),
        ("font_lar", "font_large", str(p["font_large"])),
        ("gold", "gold", p["gold"]),
        ("shadow", "shadow", p["shadow"]),
        ("line1", "line1", '={{ $node["Set Test Inputs"].json["name"] }} %s' % p["line1_suffix"]),
        ("top_marg", "top_margin", str(p["top_margin"])),
        ("line_spa", "line_spacing", str(p["line_spacing"])),
        ("line2_image", "line2_image", p["line2_image"]),
        ("logo_scale", "logo_scale", str(p["logo_scale"])),
        ("logo_x_offset", "logo_x_offset", str(p["logo_x_offset"])),
    ]
    # Egne fonter er valgfrie i konfigen - ta dem bare med naar de er satt.
    for key in ("font_small_path", "font_large_path"):
        if p.get(key):
            a.append((key, key, p[key]))
    return {
        "parameters": {
            "assignments": {"assignments": [
                {"id": "tt-" + SLUG[:18] + "--" + i, "name": n, "value": v, "type": "string"}
                for i, n, v in a
            ]},
            "includeOtherFields": True,
            "options": {},
        },
        "id": NODE_ID,
        "name": NODE_NAME,
        "type": "n8n-nodes-base.set",
        "typeVersion": 3.4,
        "position": [-224, NODE_Y],
    }


def build_rule():
    return {
        "conditions": {
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
        }
    }


def patch(nodes, connections):
    changed = []
    names = {n["name"] for n in nodes}

    if NODE_NAME in names:
        print("  (Set-node finnes allerede)")
    else:
        nodes.append(build_set_node(load_params()))
        changed.append("ny Set-node '%s'" % NODE_NAME)

    sw = next(n for n in nodes if n["name"] == "Switch")
    values = sw["parameters"]["rules"]["values"]
    existing = [v["conditions"]["conditions"][0]["rightValue"] for v in values]
    if SLUG in existing:
        idx = existing.index(SLUG)
        print("  (Switch-regel finnes allerede paa utgang %d)" % idx)
    else:
        values.append(build_rule())
        idx = len(values) - 1
        changed.append("Switch-utgang [%d] for '%s'" % (idx, SLUG))

    branches = connections["Switch"]["main"]
    while len(branches) <= idx:
        branches.append([])
    if not any(t["node"] == NODE_NAME for t in branches[idx]):
        branches[idx] = [{"node": NODE_NAME, "type": "main", "index": 0}]
        changed.append("koblet Switch[%d] -> %s" % (idx, NODE_NAME))

    if NODE_NAME not in connections:
        connections[NODE_NAME] = {"main": [[{"node": "Execute Command",
                                             "type": "main", "index": 0}]]}
        changed.append("koblet %s -> Execute Command" % NODE_NAME)

    return changed


def main() -> int:
    global SLUG, NODE_NAME, COVER, NODE_ID, NODE_Y
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--slug", default="det-forsvunne-dinosauregget")
    ap.add_argument("--cover", default="", help="forside-mal (standard: forside(<kort>).png)")
    ap.add_argument("--node-id", default="", help="n8n-node-id (maa vaere unik)")
    ap.add_argument("--y", type=int, default=0,
                    help="y-posisjon i lerretet (velg en ledig rad)")
    args = ap.parse_args()

    SLUG = args.slug
    NODE_NAME = args.slug
    if args.cover:
        COVER = args.cover
    if args.y:
        NODE_Y = args.y
    NODE_ID = args.node_id or ("tt-book-" + args.slug.replace("-", "")[:22])
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    con = sqlite3.connect(DB)
    raw_n, raw_c = con.execute(
        "select nodes, connections from workflow_entity where id=?", (WF_ID,)).fetchone()
    nodes, connections = json.loads(raw_n), json.loads(raw_c)

    for c in patch(nodes, connections):
        print("  +", c)

    if args.apply:
        con.execute("update workflow_entity set nodes=?, connections=?, "
                    "updatedAt=datetime('now') where id=?",
                    (json.dumps(nodes, ensure_ascii=False),
                     json.dumps(connections, ensure_ascii=False), WF_ID))
        con.commit()
        print("Skrevet til n8n-databasen.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
