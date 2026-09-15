# -*- coding: utf-8 -*-
"""Oppdater DP Title Tester for Havfruen etter at boka ble bygd paa nytt.

Tre ting var galt (2026-09-06):

1. **Logostiene pekte paa filer som ikke finnes.** Alle tre nodene laa igjen paa
   den gamle `C:/ComfyUI/input/<...>-logo.png`-konvensjonen; logoene ble flyttet
   til `script/logo/<locale>/` for lenge siden. Testeren rendret altsaa
   forsiden uten linje 2 - og med den nye "Havfrue"-logoen hadde den uansett
   vist feil bilde.

2. **Parametrene stemte ikke med det som faktisk trykkes.** Tekst-scriptets
   `draw_centered_title_cover` har verdiene hardkodet, og de har drevet fra
   noden: font 0.07*kortsiden (= 71 px paa 1024-malen), line_spacing 0.060,
   logo_scale 0.50, skygge (15,35,65), logoskygge alpha 180, og linje 1 i
   **Trebuchet MS Bold** - ikke PlayfairDisplay. Testeren viste noe annet enn
   trykket. Fasiten her er scriptet, siden det er det som gaar i produksjon.

3. **nb-noden het `kartet1`** - en kopi av `kartet` som aldri ble doept om.
   `next_book_titles.json` slaar opp `title_node: "havfruen"`, saa
   `sync_title_params.py --node havfruen` feilet. Noden doepes om, og
   Switch-koblingen folger med.

Skrives via n8n sitt PUBLIC API - direkte sqlite-endringer lastes ikke inn i en
kjorende n8n.

  python patch_title_tester_havfruen.py --dry-run
  python patch_title_tester_havfruen.py --apply
  python patch_title_tester_havfruen.py --revert
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE = "http://localhost:5678/api/v1"
WF = "1BqeGkXyjbUBsR9N"
# Forhandsvisningen kunden ser for kjop maa vise samme tittel som trykket.
# Nodene der hadde riktige logostier, men samme gamle typografi som testeren.
PREVIEW_WF = "Qp8tl6tKUvssCpmK"
BACKUP_DIR = os.path.join(os.path.expanduser("~"), ".n8n")

OLD_NB_NAME = "kartet1"
NEW_NB_NAME = "havfruen"

# Verdiene speiler draw_centered_title_cover i script/<locale>/havfruen-text-*.py.
SHARED = {
    "font_small": "71",             # int(1024 * 0.07) - absolutt px mot malen
    "top_margin": "0.04",
    "line_spacing": "0.060",
    "logo_scale": "0.50",
    "logo_x_offset": "0",
    "gold": "255, 255, 255",
    "shadow": "15, 35, 65",
    "logo_shadow_opacity": "180",
    "font_small_path": "C:/ComfyUI/script/pre/Trebuchet MS Bold.ttf",
}

# node -> felt som er unike for spraket
PER_NODE = {
    NEW_NB_NAME: {"line2_image": "C:/ComfyUI/script/logo/nb/havfruen-logo.png"},
    "EN - Mermaid": {"line2_image": "C:/ComfyUI/script/logo/en-US/havfruen-logo.png"},
    "SV - Sj\u00f6jungfru": {"line2_image": "C:/ComfyUI/script/logo/sv/sjojungfru-logo-sv.png"},
}

# Slik saa nodene ut for patchen - brukt av --revert.
BEFORE = {
    OLD_NB_NAME: {"line2_image": "C:/ComfyUI/input/havfrue-logo.png", "font_small": "89",
                  "line_spacing": "0.040", "logo_scale": "0.57", "shadow": "40, 20, 0",
                  "font_small_path": "C:/ComfyUI/script/pre/PlayfairDisplay.ttf"},
    "EN - Mermaid": {"line2_image": "C:/ComfyUI/input/mermaid-logo-en.png", "font_small": "71",
                     "line_spacing": "0.040", "logo_scale": "0.57", "shadow": "40, 20, 0",
                     "font_small_path": "C:/ComfyUI/script/pre/PlayfairDisplay.ttf"},
    "SV - Sj\u00f6jungfru": {"line2_image": "C:/ComfyUI/input/sjojungfru-logo-sv.png", "font_small": "77",
                             "line_spacing": "0.040", "logo_scale": "0.60", "shadow": "40, 20, 0",
                             "font_small_path": "C:/ComfyUI/script/pre/PlayfairDisplay.ttf"},
}


# DP Preview Worker har egne nodenavn for nb; resten heter det samme.
PREVIEW_PER_NODE = {
    "havfruen": {"line2_image": "C:/ComfyUI/script/logo/nb/havfruen-logo.png"},
    "EN - Mermaid": {"line2_image": "C:/ComfyUI/script/logo/en-US/havfruen-logo.png"},
    "SV - Sjöjungfru": {
        "line2_image": "C:/ComfyUI/script/logo/sv/sjojungfru-logo-sv.png",
        # Logoen sier bare "Sjojungfru" - artikkelen maa henge paa linje 1,
        # akkurat som i testeren og i sv-tekstscriptet.
        "line1": '={{ $node["Edit Fields"].json["child_name"] }} blir en',
    },
}

PREVIEW_BEFORE = {
    "havfruen": {"font_small": "79", "line_spacing": "0.037", "logo_scale": "0.57",
                 "shadow": "40, 20, 0",
                 "font_small_path": "C:/ComfyUI/script/pre/PlayfairDisplay.ttf"},
    "EN - Mermaid": {"font_small": "71", "line_spacing": "0.040", "logo_scale": "0.57",
                     "shadow": "40, 20, 0",
                     "font_small_path": "C:/ComfyUI/script/pre/PlayfairDisplay.ttf"},
    "SV - Sjöjungfru": {"font_small": "71", "line_spacing": "0.040", "logo_scale": "0.57",
                              "shadow": "40, 20, 0",
                              "font_small_path": "C:/ComfyUI/script/pre/PlayfairDisplay.ttf",
                              "line1": '={{ $node["Edit Fields"].json["child_name"] }} blir'},
}


def load_api_key() -> str:
    """n8n sin API-noekkel. Laa hardkodet i patch_worker_face_expressions.py og
    ble lest ut derfra som tekst; naa i config/secrets.json (.gitignore)."""
    import json as _json
    if os.environ.get("DP_N8N_API_KEY"):
        return os.environ["DP_N8N_API_KEY"]
    here = os.path.dirname(os.path.abspath(__file__))
    while True:
        candidate = os.path.join(here, "config", "secrets.json")
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8-sig") as fh:
                return _json.load(fh).get("n8n_api_key", "")
        parent = os.path.dirname(here)
        if parent == here:
            raise SystemExit("fant ingen config/secrets.json med n8n_api_key")
        here = parent


def req(method, path, payload=None, key=""):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    r = urllib.request.Request(BASE + path, body, method=method, headers={
        "X-N8N-API-KEY": key, "Accept": "application/json",
        "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=120))


def set_fields(node, updates, create=True):
    """Sett verdier i en Set-nodes assignments. Nye felt legges bakerst."""
    assigns = node["parameters"]["assignments"]["assignments"]
    by_name = {a["name"]: a for a in assigns}
    changed = []
    for field, value in updates.items():
        cur = by_name.get(field)
        if cur is None:
            if not create:
                continue
            assigns.append({"id": "tt-havfrue-%s" % field, "name": field,
                            "value": value, "type": "string"})
            changed.append("  + %-20s = %s" % (field, value))
            continue
        if str(cur.get("value")) != value:
            changed.append("  ~ %-20s %s -> %s" % (field, cur.get("value"), value))
            cur["value"] = value
    return changed


def rename_node(wf, old, new):
    """Doep om en node OG alle referanser til den i connections."""
    hit = False
    for n in wf["nodes"]:
        if n["name"] == old:
            n["name"] = new
            hit = True
    conns = wf["connections"]
    if old in conns:
        conns[new] = conns.pop(old)
    for outputs in conns.values():
        for branch in outputs.get("main", []) or []:
            for link in branch or []:
                if link.get("node") == old:
                    link["node"] = new
    return hit


def push(key, wf_id, plan, rename=None, label=""):
    """Les, endre og skriv tilbake en workflow. Returnerer antall endringer."""
    wf = req("GET", "/workflows/" + wf_id, key=key)
    print("\n%s  %s (aktiv: %s, %d noder)" % (label, wf["name"], wf.get("active"), len(wf["nodes"])))
    if rename:
        old, new = rename
        if rename_node(wf, old, new):
            print("  doept om %r -> %r (koblingene fulgte med)" % (old, new))

    by_name = {n["name"]: n for n in wf["nodes"]}
    total = 0
    for name, updates in plan.items():
        node = by_name.get(name)
        if node is None:
            raise SystemExit("%s: fant ingen node som heter %r" % (wf["name"], name))
        print("%s:" % name)
        lines = set_fields(node, updates)
        total += len(lines)
        print("\n".join(lines) if lines else "  (uendret)")
    return wf, total


def write(key, wf, wf_id):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    slug = "".join(c if c.isalnum() else "-" for c in wf["name"]).strip("-").lower()
    bak = os.path.join(BACKUP_DIR, "backup-%s-%s.json" % (slug, stamp))
    with open(bak, "w", encoding="utf-8") as fh:
        json.dump(req("GET", "/workflows/" + wf_id, key=key), fh, ensure_ascii=False, indent=1)
    print("  backup:", bak)
    req("PUT", "/workflows/" + wf_id, {
        "name": wf["name"], "nodes": wf["nodes"],
        "connections": wf["connections"], "settings": wf.get("settings", {}),
    }, key=key)
    if wf.get("active"):
        # En kjorende n8n laster ikke inn endringen for workflowen aktiveres paa
        # nytt - derfor er dette ikke valgfritt for de aktive workerne.
        req("POST", "/workflows/%s/activate" % wf_id, {}, key=key)
        print("  reaktivert")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run or args.revert):
        ap.error("velg --dry-run, --apply eller --revert")

    key = load_api_key()

    if args.revert:
        tester_plan = BEFORE
        tester_rename = (NEW_NB_NAME, OLD_NB_NAME)
        preview_plan = PREVIEW_BEFORE
    else:
        tester_plan = {n: dict(SHARED, **extra) for n, extra in PER_NODE.items()}
        tester_rename = (OLD_NB_NAME, NEW_NB_NAME)
        # Preview-workerens "line 2 = LOGO"-kommando sender ikke
        # --logo_shadow_opacity, saa feltet ville blitt dodt der.
        shared = {k: v for k, v in SHARED.items() if k != "logo_shadow_opacity"}
        preview_plan = {n: dict(shared, **extra) for n, extra in PREVIEW_PER_NODE.items()}

    tester, n1 = push(key, WF, tester_plan, rename=tester_rename, label="TESTER  ")
    preview, n2 = push(key, PREVIEW_WF, preview_plan, label="PREVIEW ")

    if not (args.apply or args.revert):
        print("\nDRY-RUN: %d endringer (%d tester, %d preview)" % (n1 + n2, n1, n2))
        return 0

    write(key, tester, WF)
    write(key, preview, PREVIEW_WF)
    print("\nSKREVET: %d endringer (%d tester, %d preview)" % (n1 + n2, n1, n2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
