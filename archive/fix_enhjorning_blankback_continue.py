# -*- coding: utf-8 -*-
"""Enhjorningsdalen: la fortsett-siden erstatte «Dette eventyret er over».

Felle nr. 2 fra august, en gang til - Enhjorningsdalen ble ikke med den gangen
fordi den har en TREDJE stil:

  Stil A (dinosaur m.fl.)  blank_only-side som slaas opp i base_dir foerst.
                           Ordrens QR-side plukkes opp av seg selv.
  Stil B (styrken, fotball, motet, regnbuen)
                           blank_back = os.path.join(SCRIPT_DIR, ...) - rettet
                           2026-08-09 av fix_blankback_prefer_order_input.py.
  Stil C (Enhjorningsdalen nb/nn, dyreparken)
                           blank_only-side som heter blank-back.png UT, men
                           henter bildet fra en hardkodet "source":
                               "source": "Lastpage(enhjoerning).png"
                           Da gaar oppslaget rett i script/lastpages/<locale>/
                           og ordrens input-mappe leses ALDRI.

Resultat i ordre 1418: build_last_page skrev en perfekt fortsett-side til
input/blank-back.png, tekst-scriptet ignorerte den, og boka fikk den gamle
«Dette eventyret er over»-siden med QR-en stemplet oppaa. Nyaktig samme feil
som fotballstjernen hadde med page15.

Fiksen er den samme som dyreparken allerede bruker: ordrens egen blank-back.png
vinner - men bare naar den SKILLER seg fra malen. prepare_order kopierer alltid
den delte malen inn i ordren, saa eksistens alene sier ingenting.

Malen prepare_order_enhjorning kopierer er C:\\ComfyUI\\script\\blank-back.png.
For nb er script/nb/blank-back.png byte-identisk med den, men for **nn er den
en ANNEN fil**. Sammenlignes det bare mot SCRIPT_DIR, ville hver eneste
nn-ordre uten oppsalg blitt lest som en fortsett-side og faatt feil siste side.
Derfor sammenlignes det mot begge.

en-GB / en-US / sv har fortsatt den gamle 31-siders oppdelingen med
blank-back.png som egen side uten "source", og gaar allerede gjennom
resolve_final_inner_path som leter i base_dir foerst. De roeres ikke.

  python fix_enhjorning_blankback_continue.py --dry-run
  python fix_enhjorning_blankback_continue.py --apply
"""
from __future__ import annotations

import argparse
import ast
import os
import shutil
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

TARGETS = [
    os.path.join(SCRIPT_DIR, "nb", "Enhjorning-text-nb.py"),
    os.path.join(SCRIPT_DIR, "nn", "Enhjorning-text-nn.py"),
]

OLD = (
    '        source = resolve_final_inner_path('
    'page.get("source") or page["filename"], base_dir)\n'
)

NEW = (
    '        # Ordrens egen siste side ("Fortsett eventyret"-siden med QR)\n'
    '        # vinner over den hardkodede "source". prepare_order kopierer\n'
    '        # ALLTID den delte malen inn i ordren, saa eksistens alene sier\n'
    '        # ingenting - bare en fil som SKILLER seg fra malen er en ekte\n'
    '        # fortsett-side (se build_last_page.py).\n'
    '        #\n'
    '        # Det sammenlignes mot BEGGE malene: prepare kopierer\n'
    '        # script/blank-back.png, og for nn er script/nn/blank-back.png en\n'
    '        # annen fil. Bare mot SCRIPT_DIR ville hver nn-ordre uten oppsalg\n'
    '        # blitt lest som en fortsett-side.\n'
    '        source = None\n'
    '        order_last_page = os.path.join(base_dir, "blank-back.png")\n'
    '        templates = [os.path.join(SCRIPT_DIR, "blank-back.png"),\n'
    '                     os.path.join(SCRIPT_ROOT_DIR, "blank-back.png")]\n'
    '        if os.path.exists(order_last_page) and not any(\n'
    '            os.path.exists(t)\n'
    '            and filecmp.cmp(order_last_page, t, shallow=False)\n'
    '            for t in templates\n'
    '        ):\n'
    '            print("[INNER PDF] Fortsett-eventyret-siden erstatter siste side:",\n'
    '                  order_last_page)\n'
    '            source = order_last_page\n'
    '        if source is None:\n'
    '            source = resolve_final_inner_path('
    'page.get("source") or page["filename"], base_dir)\n'
)

IMPORT_OLD = "import os\n"
IMPORT_NEW = "import filecmp\nimport os\n"


def patch(path: str, apply: bool) -> bool:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    name = os.path.relpath(path, SCRIPT_DIR)

    if "Fortsett-eventyret-siden erstatter siste side" in text:
        print(f"  = {name}: allerede patchet")
        return True

    if text.count(OLD) != 1:
        print(f"  ! {name}: fant {text.count(OLD)} treff (ventet 1) - hopper over")
        return False

    new_text = text.replace(OLD, NEW)

    if "import filecmp" not in new_text:
        if new_text.count(IMPORT_OLD) < 1:
            print(f"  ! {name}: fant ingen 'import os' aa henge filecmp paa")
            return False
        new_text = new_text.replace(IMPORT_OLD, IMPORT_NEW, 1)

    # En syntaksfeil her stopper hver eneste ordre for denne boka.
    try:
        ast.parse(new_text)
    except SyntaxError as error:
        print(f"  ! {name}: patchen gir syntaksfeil ({error}) - hopper over")
        return False

    if not apply:
        print(f"  ~ {name}: ville blitt patchet")
        return True

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{path}.backup-before-continuepage-{stamp}"
    shutil.copy2(path, backup)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    print(f"  + {name}: patchet (backup: {os.path.basename(backup)})")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    ok = True
    for path in TARGETS:
        if not os.path.isfile(path):
            print(f"  ! fant ikke {path}")
            ok = False
            continue
        ok = patch(path, args.apply) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
