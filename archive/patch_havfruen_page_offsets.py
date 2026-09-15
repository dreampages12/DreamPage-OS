# -*- coding: utf-8 -*-
"""Hvor de to tekstblokkene havner per side i Havfruen.

`_dp_apply_universal_layout` deler hver innerside i to blokker og setter
`y_offset` selv, saa sidedikten i `build_pages` bestemmer BARE halvsida
(`side`) - den vertikale plasseringen ligger her. Verdiene er offsets fra
standardstarten `sy(MARGIN_Y + 150)`.

Tallene som fulgte med fra den forrige boka var tunet mot ANDRE motiv. Paa den
nye kunsten (2026-09-06) la side 6 teksten over haaret og kinnet til barnet, og
side 10 la den tvers over haka. Begge sidene har barnet i venstre halvdel, saa
det finnes bare to rene felt: stripa OVER hodet, og sanden UNDER kroppen.

  side 6:  begge blokkene ned under henne, i vannet over revet
  side 10: begge blokkene ned i sanden under kroppen

Foerste forsoek paa side 6 var aa loefte blokk 1 opp i vannstripa OVER hodet
(hodemasken starter paa y=150 av 1024). Det saa bra ut paa skjermen, men
teksten havnet 5 mm fra PDF-kanten - innenfor beskjaeringa paa et 8,5"-ark som
trimmes til 8". Regelen: `sy(MARGIN_Y + 150) + top_y` maa vaere stoerre enn ca.
54 px av 1024, ellers kan teksten bli kuttet i trykk.

Funksjonen skrives om til en tabell, saa neste justering er ett tall og ikke en
ny if-setning. Se ogsaa [[dreampage-text-shadow-rendering]].

  python patch_havfruen_page_offsets.py --dry-run
  python patch_havfruen_page_offsets.py --apply
  python patch_havfruen_page_offsets.py --revert
"""
from __future__ import annotations

import argparse
import ast
import glob
import io
import os
import shutil
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TAG = "havfrue-sideoffsets"
LOCALES = ["nb", "nn", "en-US", "en-GB", "sv"]

START = "def _dp_layout_offsets(filename: str):"
END = "    return number, top_y, bottom_y\n"

NEW = '''# Vertikal plassering av de to tekstblokkene, per sidetall. Maalt mot den NYE
# kunsten - se patch_havfruen_page_offsets.py for hvorfor 6 og 10 skiller seg ut.
_DP_PAGE_OFFSETS = {
    3:  (40, 365),
    6:  (370, 555),    # begge blokkene under henne - se merknaden om beskjaering
    7:  (115, 410),
    10: (330, 530),    # begge blokkene ned i sanden, klar av haka
    12: (330, 545),    # tekst flyttet til hoyre side - blokkene under krystallen
    13: (50, 365),
}


def _dp_layout_offsets(filename: str):
    number = _dp_page_number(filename)
    top_y, bottom_y = _DP_PAGE_OFFSETS.get(number, (25, 345))
    return number, top_y, bottom_y
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run or args.revert):
        ap.error("velg --dry-run, --apply eller --revert")

    if args.revert:
        for bak in sorted(glob.glob(os.path.join(SCRIPT_DIR, "*", "*.backup-before-%s-*" % TAG))):
            orig = bak.split(".backup-before-")[0]
            shutil.copy2(bak, orig)
            print("  tilbakestilt", os.path.relpath(orig, SCRIPT_DIR))
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    for locale in LOCALES:
        path = os.path.join(SCRIPT_DIR, locale, "havfruen-text-%s.py" % locale)
        rel = os.path.relpath(path, SCRIPT_DIR).replace(os.sep, "/")
        text = io.open(path, encoding="utf-8").read()
        if "_DP_PAGE_OFFSETS" in text:
            i = text.index("_DP_PAGE_OFFSETS = {")
            j = text.index(END, i) + len(END)
            new_text = text[:i] + NEW[NEW.index("_DP_PAGE_OFFSETS = {"):] + text[j:]
        else:
            if START not in text:
                print("  HOPPER OVER %-32s fant ikke _dp_layout_offsets" % rel)
                continue
            i = text.index(START)
            j = text.index(END, i) + len(END)
            new_text = text[:i] + NEW + text[j:]
        if new_text == text:
            print("  %-32s uendret" % rel)
            continue
        ast.parse(new_text)
        print("  %-32s ok" % rel)
        if args.apply:
            shutil.copy2(path, "%s.backup-before-%s-%s" % (path, TAG, stamp))
            io.open(path, "w", encoding="utf-8", newline="").write(new_text)
    print("APPLIED" if args.apply else "DRY-RUN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
