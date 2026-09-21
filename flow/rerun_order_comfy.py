# -*- coding: utf-8 -*-
"""Kjoer alle ComfyUI-sidene i en ordre paa nytt, rett inn i comfy/.

Bruksomraadet er "malene er byttet ut" - nye innsider/forside i
C:/DreamPage-OS/input - der hver eneste side maa lages paa nytt, ikke bare den
ene siden regen_page.py tar.

Forskjellene fra regen_page.py:

* Resultatet havner i comfy/, ikke i variants/. Det er dit prepare_order ser,
  og poenget her er nettopp aa erstatte den ferdige ordren.
* De gamle comfy-filene for siden flyttes til comfy-old-<tidsstempel>/ foer
  ny render. prepare_order plukker FOERSTE fil som matcher page_key, saa en
  gammel page03_00001_.png ville ellers vinne over den nye _00002_.
* Laasen tas EN gang for hele kjoeringen, ikke per side. En halvt ombygd
  ordre er verre enn aa vente.
* --face styrer barnebildet. Uten den faar hver side ordrens eget bilde
  med uttrykksvarianten fra config.face_expression (trist/glad), som
  workeren - se regen_page.page_face.

  python rerun_order_comfy.py --order 1296 --dry-run
  python rerun_order_comfy.py --order 1296 --apply
  python rerun_order_comfy.py --order 1296 --apply --face 1296.jpg
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import shutil
import sys
import datetime as dt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import dp_order
import importlib.util

# Stien til DreamPage-roten utledes, den hardkodes ikke: koden kjoerer paa
# Windows i dag og paa Linux paa nye maskiner. Se flow/paths.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import under  # noqa: E402

# regen_page.py har bindestrek-fritt navn, men ligger ved siden av oss og
# eier alt maskineriet vi trenger (laas, node-deteksjon, ventelogikk).
_spec = importlib.util.spec_from_file_location(
    "regen_page", os.path.join(SCRIPT_DIR, "regen_page.py"))
regen = importlib.util.module_from_spec(_spec)
sys.modules["regen_page"] = regen
_spec.loader.exec_module(regen)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--face", default="",
                    help="barnebilde i C:/DreamPage-OS/input (default: ordrens eget)")
    ap.add_argument("--pages", default="",
                    help="komma-separert liste, f.eks. page00,page03 (default: alle)")
    ap.add_argument("--wait-lock", type=int, default=3600)
    args = ap.parse_args()
    if not args.apply and not args.dry_run:
        ap.error("bruk --dry-run eller --apply")

    info = dp_order.resolve(args.order)
    config = info["config"]
    pages = config.get("pages") or []
    if args.pages:
        wanted = {p.strip() for p in args.pages.split(",") if p.strip()}
        pages = [p for p in pages if p["page_key"] in wanted]
    if not pages:
        raise SystemExit("ingen sider aa kjoere")

    # Kropps-, haar- og hudvariant. Bytter BARE malbildet (og for kroppen
    # ogsaa masken) - resultatet lagres fortsatt under page_key, saa prepare,
    # tekst-scriptet og PDF-bygget merker ingenting.
    body = dp_order.body_variant(info)
    hair = dp_order.hair_variant(info)
    skin = dp_order.skin_variant(info)
    if (body, hair, skin) != (dp_order.DEFAULT_BODY_VARIANT,
                              dp_order.DEFAULT_HAIR_VARIANT,
                              dp_order.DEFAULT_SKIN_VARIANT):
        print("variant: kropp=%s haar=%s hud=%s" % (body, hair, skin))
        pages = [dp_order.apply_variants(p, body, hair, skin) for p in pages]

    # Barnebildet velges PER SIDE: fotballstjernen side 04 skal ha den triste
    # varianten og side 14 den glade, akkurat som workeren lagde dem. Her stod
    # ett bilde for hele ordren, og en ombygging mistet uttrykkene stille.
    faces = {p["page_key"]: regen.page_face(info, p, args.face or None) for p in pages}
    for face in set(faces.values()):
        face_path = os.path.join(under("input"), face)
        if not os.path.isfile(face_path):
            raise SystemExit("fant ikke barnebildet " + face_path)

    workflow_file = (config.get("workflowApi")
                     or (config.get("workflowApis") or {}).get("innerpages")
                     or "workflow_api.json")
    workflow_path = os.path.join(under("books"), info["book_slug"], workflow_file)
    with open(workflow_path, encoding="utf-8-sig") as fh:
        base_prompt = json.load(fh)

    prefix = config.get("comfyOutputPrefix", info["book_slug"] + "/orders")
    out_rel = "%s/%s/comfy" % (prefix, info["order_id"])
    comfy_dir = info["comfy_dir"]

    print("ordre %s (%s), barn %s" % (info["order_id"], info["book_slug"], info["child_name"]))
    print("sider: %s" % ", ".join(p["page_key"] for p in pages))
    for page in pages:
        print("  %-8s %-28s %-32s %s" % (page["page_key"], page["template_image"],
                                        page.get("mask_image", "-"),
                                        faces[page["page_key"]]))
    if not args.apply:
        print("dry-run (ingenting kjoert)")
        return 0

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    old_dir = os.path.join(os.path.dirname(comfy_dir), "comfy-old-" + stamp)

    # Laasefila (.dreampage-comfy.lock) ble fjernet da regen_page gikk over
    # til aa spoerre flow-workeren direkte om hva som kjoerer - se den lange
    # kommentaren der. Denne fila ble aldri med paa flyttingen, saa --apply
    # kastet AttributeError paa acquire_lock og har vaert doed siden.
    # --dry-run returnerer foer dette punktet, som er grunnen til at ingen
    # saa det foer ordre 1522 skulle bygges om (18.09.2026).
    if not regen.wait_until_free(wait_seconds=args.wait_lock):
        raise SystemExit("ComfyUI er opptatt: %s. Proev igjen senere."
                         % (regen.busy_reason() or "noe annet"))
    try:
        for n, page in enumerate(pages, 1):
            page_key = page["page_key"]

            # Rydd bort den gamle renderen foer den nye lages, ellers vinner
            # den paa filnavn naar prepare_order plukker foerste treff.
            stale = glob.glob(os.path.join(comfy_dir, page_key + "_*"))
            if stale:
                os.makedirs(old_dir, exist_ok=True)
                for path in stale:
                    shutil.move(path, os.path.join(old_dir, os.path.basename(path)))

            prompt = json.loads(json.dumps(base_prompt))
            pn = regen.detect_nodes(
                prompt, config.get("patchNodes") or config.get("innerPatchNodes") or {})

            seed = random.randrange(1, 2 ** 53)
            prompt[pn["template"]]["inputs"]["image"] = page["template_image"]
            prompt[pn["face"]]["inputs"]["image"] = faces[page_key]
            if pn.get("mask") and page.get("mask_image"):
                prompt[pn["mask"]]["inputs"]["image"] = page["mask_image"]
            prompt[pn["output"]]["inputs"]["filename_prefix"] = "%s/%s" % (out_rel, page_key)
            regen.randomize_seeds(prompt, seed)

            for node in prompt.values():
                if isinstance(node, dict) and isinstance(node.get("inputs"), dict) \
                        and node["inputs"].get("scheduler") == "bong_tangent":
                    node["inputs"]["scheduler"] = "ddim_uniform"

            response = regen.comfy_post("/prompt", {"prompt": prompt})
            prompt_id = response.get("prompt_id") or response.get("promptId")
            if not prompt_id:
                raise SystemExit("ComfyUI ga ingen prompt_id: "
                                 + json.dumps(response)[:500])
            print("[%d/%d] %s seed=%s prompt_id=%s"
                  % (n, len(pages), page_key, seed, prompt_id), flush=True)

            got = False
            for image in regen.wait_for(prompt_id):
                path = os.path.join(regen.OUTPUT_ROOT,
                                    (image.get("subfolder") or "").replace("/", os.sep),
                                    image["filename"])
                if os.path.isfile(path):
                    got = True
                    print("      -> %s" % path, flush=True)
            if not got:
                raise SystemExit("ingen bilder ble produsert for " + page_key)
    finally:
        pass   # ingen laas aa slippe - flow-workeren er sannheten naa

    if os.path.isdir(old_dir):
        print("gamle rendere flyttet til %s" % old_dir)
    print("ferdig - kjoer reprint_order.py for aa bygge PDF paa nytt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
