"""Synk tittelparametre fra DP Title Tester til next_book_titles.json.

Fontstørrelser i render-title er ABSOLUTTE piksler, mens logo_scale, top_margin
og line_spacing er andeler av bredden. Testeren kjøres ofte mot et oppskalert
bilde, så fontene normaliseres til forside-malens bredde (baseline) her.
build_last_page.py skalerer dem opp igjen etter faktisk bildestørrelse.

Bruk:
  python sync_title_params.py --node <Set-nodens navn> --slug <bok-slug> --lang nb \
      [--tested-width 2048] [--apply]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

DB = r"C:\Users\tobia\.n8n\database.sqlite"
TESTER_ID = "1BqeGkXyjbUBsR9N"
TITLES_CONFIG = "C:/DreamPage-OS/config/next_book_titles.json"

FRACTIONAL = {"top_margin", "line_spacing", "logo_scale"}
ABSOLUTE = {"font_small", "font_large"}


def template_width(slug: str) -> int:
    from PIL import Image
    with open(f"C:/DreamPage-OS/books/{slug}/config.json", encoding="utf-8-sig") as fh:
        cfg = json.load(fh)
    front = next(p for p in cfg["pages"] if p["page_key"] == "page00")
    with Image.open("C:/DreamPage-OS/input/" + front["template_image"]) as im:
        return im.width


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", required=True, help="Set-nodens navn i DP Title Tester")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--lang", default="nb")
    ap.add_argument("--tested-width", type=int, default=0,
                    help="Bredden på bildet parametrene ble tunet mot (0 = anta malen)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    nodes = json.loads(con.execute(
        "select nodes from workflow_entity where id=?", (TESTER_ID,)).fetchone()[0])
    con.close()

    node = next((n for n in nodes if n["name"] == args.node), None)
    if node is None:
        raise SystemExit(f"fant ikke Set-noden '{args.node}' i DP Title Tester")
    raw = {a["name"]: str(a.get("value", ""))
           for a in node["parameters"]["assignments"]["assignments"]}

    baseline = template_width(args.slug)
    tested = args.tested_width or baseline
    factor = baseline / tested
    if factor != 1.0:
        print(f"  normaliserer fonter: tunet mot {tested}px -> mal {baseline}px "
              f"(x{factor:g})")

    line1 = raw.get("line1", "")
    entry = {
        "source": f"title-tester:{args.node}",
        "title_node": args.node,
        "line1_suffix": line1.split("}}")[-1].strip() if "}}" in line1 else "",
        "line2": raw.get("line2", ""),
        "line2_image": raw.get("line2_image", ""),
        "gold": raw.get("gold", ""),
        "shadow": raw.get("shadow", ""),
        "font_small_path": raw.get("font_small_path", ""),
        "font_large_path": raw.get("font_large_path", ""),
    }
    for key in ABSOLUTE:
        entry[key] = round(float(raw.get(key, 80)) * factor)
    for key in FRACTIONAL:
        entry[key] = float(raw.get(key, 0) or 0)
    entry["logo_x_offset"] = round(float(raw.get("logo_x_offset", 0) or 0) * factor)

    # Valgfrie felt: sendes bare videre naar noden faktisk har dem, saa boeker
    # uten dem beholder rendererens standardverdier. build_last_page.py leser
    # akkurat disse (glod bak linje 1 + skygge bak line2-logoen), og uten dem
    # her ville en tunet node miste finjusteringen paa vei til forsiden.
    for key in ("glow_color", "glow_opacity", "glow_radius_scale",
                "logo_shadow_opacity", "shadow_opacity", "shadow_blur"):
        value = raw.get(key)
        if value not in (None, ""):
            entry[key] = value

    with open(TITLES_CONFIG, encoding="utf-8-sig") as fh:
        cfg = json.load(fh)
    before = cfg.get(args.slug, {}).get(args.lang, {})
    for k, v in sorted(entry.items()):
        old = before.get(k)
        mark = "  " if old == v else "->"
        print(f"  {mark} {k:16} {old!r:28} {v!r}")

    if args.apply:
        cfg.setdefault(args.slug, {})[args.lang] = entry
        with open(TITLES_CONFIG, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
        print(f"Skrevet til {TITLES_CONFIG}")
    else:
        print("(tørrkjøring – bruk --apply for å lagre)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
