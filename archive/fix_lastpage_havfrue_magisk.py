# -*- coding: utf-8 -*-
"""Ny siste innerside for havfruen og den magiske reisen (gutt + jente).

Tobias har laget nye "Dette eventyer er over"-sider til begge bokene. De ligger
som `blank-back(<merke>).png` i bokmappa, og skal erstatte den delte
`script/<locale>/blank-back.png` - men BARE for locales der kunsten faktisk er
pa riktig sprak. Teksten er bakt inn i bildet pa bokmal, saa nb er eneste
locale som far den na; nn/en/sv beholder sine egne maler til det finnes
oversatte varianter (da holder det a legge til en linje i BOOKS).

Samtidig rettes det som ellers ville blitt Felle 8 om igjen: begge de magiske
reise-bokene leste siste innerside fra en hardkodet
`os.path.join(SCRIPT_DIR, page["filename"])` og saa ALDRI i ordremappa. En
"Fortsett eventyret"-side skrevet til ordrens input/blank-back.png ble dermed
ignorert. Rekkefolgen er na overalt:

    ordrens egen side  >  bokas egen side  >  delt mal

Havfruen leste allerede ordremappa forst (resolve_final_inner_path), saa der
skytes bok-sida bare inn som mellomledd.

VIKTIG: prepare_order kopierer ALLTID en mal inn i ordren, saa eksistens alene
sier ingenting - bare en fil som SKILLER seg fra malene er en ekte
fortsett-side. Og det maa sammenlignes mot BEGGE malene: script/blank-back.png
og script/<locale>/blank-back.png er ULIKE filer for nn/en/sv.

Bruk:
  python fix_lastpage_havfrue_magisk.py --dry-run
  python fix_lastpage_havfrue_magisk.py --apply
  python fix_lastpage_havfrue_magisk.py --revert
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
LOCALES = ["nb", "nn", "en-US", "en-GB", "sv"]
TAG = "lastpage-havfrue-magisk"

# stem -> (bokmappe, const-navn, {locale: filnavn i bokmappa})
# Locales som IKKE staar i dicten faller tilbake til den delte malen. Det er
# MED VILJE: en norsk side skal aldri trykkes i en engelsk eller svensk bok.
BOOKS = {
    "havfruen-text": (
        "havfruen", "HAVFRUEN_BLANK_BACK",
        {"nb": "blank-back(havfruen).png"},
    ),
    "den-magiske-reisen-jente-text": (
        "den-magiske-reisen-jente", "MAGISK_BLANK_BACK",
        {"nb": "blank-back(magisk).png"},
    ),
    "det-magiske-kartet-text": (
        "den-magiske-reisen-gutt", "MAGISK_BLANK_BACK",
        {"nb": "blank-back(magisk).png"},
    ),
}

COMMON = '''# ------------------------------------------------------------
#  SISTE INNERSIDE - bokas egen "Dette eventyer er over"-side
# ------------------------------------------------------------
# Erstatter den delte blank-back.png, men viker ALLTID for ordrens egen
# "Fortsett eventyret"-side (QR-oppsalget). Tom streng = ingen egen side for
# dette spraket -> delt mal, som for.
_BB_LOCALES = {"nb", "nn", "en-US", "en-GB", "sv"}
_BB_LOCALE = os.path.basename(SCRIPT_DIR)
if _BB_LOCALE not in _BB_LOCALES:
    _BB_LOCALE = "nb"
_BB_NAME = %(names)r.get(_BB_LOCALE, "")
%(const)s = os.path.join(
    os.path.dirname(globals().get("SCRIPT_ROOT_DIR", os.path.dirname(SCRIPT_DIR))),
    "books", %(folder)r, _BB_NAME,
) if _BB_NAME else ""


def _is_shared_blank_back(path):
    """True hvis fila er en av de delte malene - altsa IKKE ordrens egen side.

    prepare_order kopierer alltid en mal inn i ordren, saa vi maa sammenligne
    innhold. Begge malene sjekkes: script/blank-back.png og
    script/<locale>/blank-back.png er ulike filer for nn/en/sv.
    """
    root = globals().get("SCRIPT_ROOT_DIR", os.path.dirname(SCRIPT_DIR))
    for tmpl in (os.path.join(SCRIPT_DIR, "blank-back.png"),
                 os.path.join(root, "blank-back.png")):
        if os.path.exists(tmpl) and filecmp.cmp(path, tmpl, shallow=False):
            return True
    return False


def resolve_book_blank_back(filename, base_dir):
    """Ordrens egen side > bokas egen side > None (= kalleren bruker malen)."""
    if os.path.basename(filename).lower() != "blank-back.png":
        return None
    order_page = os.path.join(base_dir, filename)
    if os.path.exists(order_page) and not _is_shared_blank_back(order_page):
        print("[INNER PDF] Fortsett-eventyret-siden erstatter siste side:", order_page)
        return order_page
    if %(const)s and os.path.exists(%(const)s):
        return %(const)s
    return None
'''

# --- havfruen (stil A: resolve_final_inner_path leter i base_dir allerede) ---
HAV_OLD = '''    source = os.path.join(base_dir, filename)
    if not os.path.exists(source):
'''
HAV_NEW = '''    source = os.path.join(base_dir, filename)

    book_page = resolve_book_blank_back(filename, base_dir)
    if book_page:
        return book_page

    if not os.path.exists(source):
'''

# --- magiske reisen (stil C: hardkodet SCRIPT_DIR, leste aldri ordremappa) ---
MAG_OLD = '''    if page.get("blank_only"):
        blank_path = os.path.join(SCRIPT_DIR, page["filename"])
'''
MAG_NEW = '''    if page.get("blank_only"):
        blank_path = (resolve_book_blank_back(page["filename"], base_dir)
                      or os.path.join(SCRIPT_DIR, page["filename"]))
'''

HAV_ANCHOR = "def is_lastpage_filename("
MAG_ANCHOR = "def render_page("


def targets():
    out = []
    for locale in LOCALES:
        for stem, (folder, const, names) in BOOKS.items():
            path = os.path.join(SCRIPT_DIR, locale, "%s-%s.py" % (stem, locale))
            if os.path.exists(path):
                out.append((path, stem, folder, const, names))
    return out


def patch_text(text, stem, folder, const, names):
    if const in text:
        return None, "allerede patchet"

    block = COMMON % {"names": names, "const": const, "folder": folder}

    if stem == "havfruen-text":
        if HAV_OLD not in text:
            return None, "fant ikke resolve_final_inner_path-ankeret"
        text = text.replace(HAV_OLD, HAV_NEW, 1)
        anchor = HAV_ANCHOR
    else:
        if MAG_OLD not in text:
            return None, "fant ikke blank_only-ankeret"
        text = text.replace(MAG_OLD, MAG_NEW, 1)
        anchor = MAG_ANCHOR

    i = text.index(anchor)
    text = text[:i] + block + "\n\n" + text[i:]

    if "\nimport filecmp\n" not in text:
        text = text.replace("\nimport re\n", "\nimport re\nimport filecmp\n", 1)
    if "\nimport filecmp\n" not in text:
        text = text.replace("\nimport os\n", "\nimport os\nimport filecmp\n", 1)
    if "\nimport filecmp\n" not in text:
        return None, "fikk ikke lagt inn 'import filecmp'"
    return text, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run or args.revert):
        ap.error("velg --dry-run, --apply eller --revert")

    if args.revert:
        pattern = os.path.join(SCRIPT_DIR, "*", "*.backup-before-%s-*" % TAG)
        for bak in sorted(glob.glob(pattern)):
            orig = bak.split(".backup-before-")[0]
            shutil.copy2(bak, orig)
            print("  tilbakestilt", os.path.relpath(orig, SCRIPT_DIR))
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    changed = 0
    for path, stem, folder, const, names in targets():
        rel = os.path.relpath(path, SCRIPT_DIR).replace(os.sep, "/")
        text = io.open(path, encoding="utf-8").read()
        new_text, err = patch_text(text, stem, folder, const, names)
        if err:
            print("  HOPPER OVER %-52s %s" % (rel, err))
            continue
        ast.parse(new_text)
        locale = os.path.basename(os.path.dirname(path))
        note = names.get(locale, "delt mal (ingen egen kunst)")
        print("  %-52s -> %s" % (rel, note))
        changed += 1
        if args.apply:
            shutil.copy2(path, "%s.backup-before-%s-%s" % (path, TAG, stamp))
            io.open(path, "w", encoding="utf-8", newline="").write(new_text)
    print(("APPLIED" if args.apply else "DRY-RUN") + ": %d filer" % changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
