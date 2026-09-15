"""La siste innerside komme fra ordrens egen input-mappe, ikke den delte malen.

Bakgrunn: bokene er skrevet i to stiler.

  Stil A (dinosaur m.fl.)  blank-back ligger som en side i build_pages med
                           blank_only=True, og resolve_final_inner_path leter i
                           base_dir foerst. QR-siden vaar blir plukket opp.

  Stil B (styrken, fotball, motet, regnbuen)
                           process_book gjoer
                               blank_back = os.path.join(SCRIPT_DIR, "blank-back.png")
                           og legger den rett inn i inner_paths. Ordrens egen
                           input-mappe leses ALDRI, saa "Fortsett eventyret"-siden
                           ble skrevet til input/ og deretter ignorert. Boka fikk
                           den gamle Canva-siden, med QR-en stemplet oppaa.

Denne patchen gjoer stil B lik stil A: bruk ordrens fil hvis den finnes, ellers
den delte malen. Ingen annen oppfoersel endres - bøker uten QR-side har ingen
egen blank-back.png i input og faar malen som foer.

Bruk:
  python fix_blankback_prefer_order_input.py --dry-run
  python fix_blankback_prefer_order_input.py --apply
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

OLD = '    blank_back = os.path.join(SCRIPT_DIR, "blank-back.png")'
NEW = (
    '    # Ordrens egen blank-back.png (f.eks. "Fortsett eventyret"-siden med QR)\n'
    '    # har forrang; den delte malen er fallback for boker uten oppsalg.\n'
    '    blank_back = os.path.join(base_dir, "blank-back.png")\n'
    '    if not os.path.exists(blank_back):\n'
    '        blank_back = os.path.join(SCRIPT_DIR, "blank-back.png")\n'
    '    else:\n'
    '        print("[INNER PDF] Bruker siste innerside fra ordremappen:", blank_back)'
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    files = sorted(
        p for p in glob.glob(os.path.join(SCRIPT_DIR, "*", "*-text-*.py"))
        if "backup" not in os.path.basename(p)
    )
    hit = 0
    for path in files:
        text = io.open(path, encoding="utf-8").read()
        if OLD not in text:
            continue
        rel = os.path.relpath(path, SCRIPT_DIR).replace(os.sep, "/")
        # base_dir maa vaere parameter i funksjonen der linjen staar
        if "def process_book(base_dir" not in text:
            print(f"  HOPPER OVER {rel}: fant ikke process_book(base_dir...)")
            continue
        hit += 1
        print(f"  {rel}")
        if args.apply:
            shutil.copy2(path, f"{path}.backup-before-blankback-{stamp}")
            new_text = text.replace(OLD, NEW, 1)
            io.open(path, "w", encoding="utf-8").write(new_text)
            ast.parse(new_text)

    print(f"\n{hit} fil(er) {'rettet' if args.apply else 'ville blitt rettet'}")
    if args.apply and hit:
        print("syntakssjekk OK for alle")
    return 0


if __name__ == "__main__":
    sys.exit(main())
