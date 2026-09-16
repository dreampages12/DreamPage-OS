# -*- coding: utf-8 -*-
"""Sjekk at all delt kunst som konfigurasjonen peker paa faktisk finnes.

Finnes fordi ordre 1510 gikk til trykkeklart Gelato-utkast med en forside som
bare sa "Henry og det". Line2 paa den forsiden er ikke tekst, den er en
LOGOFIL - og fila hadde flyttet seg. Hele kjeden er fail-soft med vilje (et
oppsalg skal aldri stoppe en betalt ordre), saa rendereren skrev "ADVARSEL:
Fant ikke line2_image" og avsluttet med 0. Ingen saa det.

En manglende fontfil eller logo er ikke en kjoeretidsfeil vi kan oppdage naar
den skjer - da er bildet alt rendret. Den maa oppdages FOER. Dette scriptet er
det sjekkpunktet: det leser stiene ut av konfigurasjonen i stedet for aa ha en
egen liste, saa den kan ikke bli utdatert.

  python tools/check_assets.py            # exit 1 hvis noe mangler
  python tools/check_assets.py --list     # vis ogsaa alt som er OK
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Filtypene som er kunst eller font. En sti til en .py eller .json er kode og
# sjekkes andre steder.
ASSET_RE = re.compile(
    r'"((?:[A-Za-z]:)?[^"]*?\.(?:png|webp|jpg|jpeg|ttf|otf))"', re.IGNORECASE)

# Mappene tekstscriptene loeser kunst relativt til sin EGEN plassering. De
# ligger her og ingen andre steder - se kommentaren i flow/paths.py.
SHARED_DIRS = ("flow/text/logo", "flow/text/bakside",
               "flow/text/ryggrad", "flow/text/lastpages")


def resolve(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def scan_json(rel: str) -> list[tuple[str, str]]:
    """(hvor, sti) for hver kunst-/fontsti i en konfigurasjonsfil."""
    full = resolve(rel)
    if not os.path.isfile(full):
        return []
    with open(full, encoding="utf-8-sig") as fh:
        raw = fh.read()
    return [(rel, m) for m in sorted(set(ASSET_RE.findall(raw)))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true",
                    help="vis ogsaa stiene som er i orden")
    args = ap.parse_args()

    found: list[tuple[str, str]] = []
    for rel in ("config/next_book_titles.json",
                "config/flow.json",
                "config/merge_orders.json"):
        found += scan_json(rel)

    missing = [(where, p) for where, p in found if not os.path.isfile(resolve(p))]

    print(f"{len(found)} kunst-/fontstier i konfigurasjonen")
    if args.list:
        for where, p in found:
            ok = "OK " if os.path.isfile(resolve(p)) else "NEI"
            print(f"  {ok} {where}: {p}")

    print()
    for rel in SHARED_DIRS:
        full = resolve(rel)
        n = sum(len(files) for _, _, files in os.walk(full)) if os.path.isdir(full) else 0
        state = f"{n} filer" if n else "TOM ELLER BORTE"
        print(f"  {'OK ' if n else 'NEI'} {rel:24} {state}")
        if not n:
            missing.append((rel, rel))

    print()
    if missing:
        print(f"{len(missing)} MANGLER:")
        for where, p in missing:
            print(f"  {where}: {p}")
        print()
        print("En manglende line2-logo gir en forside med halv tittel, og hele")
        print("kjeden er fail-soft - den stopper ingenting. Rett stien foer du")
        print("bygger noe som skal trykkes.")
        return 1

    print("alt finnes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
