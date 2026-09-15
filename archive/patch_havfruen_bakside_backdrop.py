# -*- coding: utf-8 -*-
"""Bakside-skygge i Havfruen - samme MYKE SKY som alle de andre bokene.

Den nye bakside(havfrue).png er en LYS solnedgang; den gamle var moerkt
undervannsblaatt. Hvit tekst uten noe bak seg forsvant rett inn i himmelen, saa
baksiden trenger `shape="block"` - ETT felt bak hele bolken, ikke en pille per
linje slik innersidene har.

**To smaker finnes, og bare den ene er husstandarden.**

  `patch_motet_bakside_backdrop.py` er et gammelt oyeblikksbilde: crisp plate
  (`plate_alpha` 64/88, liten blur, pad x1.35/x1.6). Den gir en synlig graa
  boks. Motet selv har for lengst gaatt bort fra den.

  Alle 12 andre boker bruker i dag varianten fra `den-magiske-bursdagen-jente`:
  ingen plate (`plate_alpha = 0`), `shadow_alpha = 110`, kraftig blur
  (`max(30, fs * 2.1)`) og romsligere luft (pad x1.9/x2.4) - en myk sky uten
  synlig kant.

Derfor leses block-grenen HER rett ut av bursdagen-fila i stedet for aa
dupliseres: da kan ikke de to drive fra hverandre igjen.

Scriptet er idempotent og gjor opptil to ting:
  1. Mangler `shape`-parameteren helt, hentes signatur + bakside-kall fra
     patch_motet_bakside_backdrop (den delen er lik i begge smakene).
  2. Block-grenen normaliseres til bursdagen-varianten.

  python patch_havfruen_bakside_backdrop.py --dry-run
  python patch_havfruen_bakside_backdrop.py --apply
  python patch_havfruen_bakside_backdrop.py --revert
"""
from __future__ import annotations

import argparse
import ast
import glob
import io
import os
import shutil
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from patch_motet_bakside_backdrop import patch as motet_patch   # noqa: E402

TAG = "havfrue-baksideplate"
LOCALES = ["nb", "nn", "en-US", "en-GB", "sv"]
REFERENCE = os.path.join(SCRIPT_DIR, "nb", "den-magiske-bursdagen-jente-text-nb.py")

BLOCK_START = '    if shape == "block":\n'
BLOCK_END = "        boxes = [(\n"


def block_branch(text: str) -> str | None:
    """Kroppen av `if shape == "block":` fram til `boxes = [(`."""
    i = text.find(BLOCK_START)
    if i < 0:
        return None
    j = text.find(BLOCK_END, i)
    if j < 0:
        return None
    return text[i:j]


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

    want = block_branch(io.open(REFERENCE, encoding="utf-8").read())
    if not want:
        raise SystemExit("fant ikke block-grenen i %s" % REFERENCE)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    for locale in LOCALES:
        path = os.path.join(SCRIPT_DIR, locale, "havfruen-text-%s.py" % locale)
        rel = os.path.relpath(path, SCRIPT_DIR).replace(os.sep, "/")
        src = io.open(path, encoding="utf-8").read()
        out = src if 'shape="block"' in src else motet_patch(src, path)

        have = block_branch(out)
        if have is None:
            print("  HOPPER OVER %-32s fant ikke block-grenen" % rel)
            continue
        if have != want:
            out = out.replace(have, want, 1)

        if out == src:
            print("  %-32s allerede lik bursdagen" % rel)
            continue
        ast.parse(out)
        print("  %-32s myk sky" % rel)
        if args.apply:
            shutil.copy2(path, "%s.backup-before-%s-%s" % (path, TAG, stamp))
            io.open(path, "w", encoding="utf-8", newline="").write(out)
    print("APPLIED" if args.apply else "DRY-RUN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
