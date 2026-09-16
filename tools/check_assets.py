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
import ast
import glob
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


def _optional_names(tree: ast.Module) -> set[str]:
    """Konstanter som HAR et fallback i fila selv, og derfor kan mangle.

    Moenstret er "if not os.path.exists(X): X = <noe annet>" - fotball-vm
    laaner fotballstjernens aapningsside paa den maaten med vilje.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)):
            continue
        call = test.operand
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "exists" and len(call.args) == 1
                and isinstance(call.args[0], ast.Name)):
            continue
        target = call.args[0].id
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == target for t in stmt.targets):
                names.add(target)
    return names


def scan_text_scripts() -> list[tuple[str, str]]:
    """(hvor, sti) for hver bok-spesifikk kunstfil et tekstscript peker paa.

    Finnes fordi ordre 1506 ble bygget om med den DELTE gamle aapningssida:
    tekstscriptene laa i <rot>/script/<sprak> og regnet ut bokmappa som
    dirname(SCRIPT_ROOT_DIR). Etter flyttingen til <rot>/flow/text/<sprak> ga
    det <rot>/flow/books - som ikke finnes - og alle bok-spesifikke sider falt
    stille tilbake til den delte malen. Regexen over ser bare paa JSON; disse
    stiene bygges i kode, saa de maa leses ut av syntakstreet.
    """
    found: list[tuple[str, str]] = []
    for path in sorted(glob.glob(os.path.join(ROOT, "flow", "text", "*", "*.py"))):
        if ".backup" in path or ".bak" in path:
            continue
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        with open(path, encoding="utf-8", errors="surrogateescape") as fh:
            src = fh.read()
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            found.append((rel, f"<SYNTAKSFEIL: {exc}>"))
            continue
        optional = _optional_names(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
                continue
            if any(isinstance(t, ast.Name) and t.id in optional for t in node.targets):
                continue
            call = node.value
            if not (isinstance(call.func, ast.Attribute) and call.func.attr == "join"):
                continue
            args = call.args
            if not (args and isinstance(args[0], ast.Name) and args[0].id == "DP_ROOT"):
                continue
            parts = [a.value for a in args[1:]
                     if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if len(parts) != len(args) - 1:
                continue  # sti satt sammen av variabler - kan ikke sjekkes her
            found.append((rel, "/".join(parts)))
    return found


def audit() -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(alle stier, de som mangler). Selve sjekken, uten utskrift.

    Skilt ut fra main() slik at pipelinen kan kjoere den som et STEG
    (`steps.check_assets`) i stedet for at den er et verktoey noen maa huske
    aa kjoere. En guard som avhenger av at et menneske husker den, er ikke en
    guard - og fram til 16.09.2026 var det noeyaktig det denne var: ingenting
    i repoet kalte den.
    """
    found: list[tuple[str, str]] = []
    for rel in ("config/next_book_titles.json",
                "config/flow.json",
                "config/merge_orders.json"):
        found += scan_json(rel)
    found += scan_text_scripts()

    missing = [(where, p) for where, p in found if not os.path.isfile(resolve(p))]

    # De delte kunstmappene: en TOM mappe er like galt som en borte mappe, og
    # ingen enkeltsti ville avsloert det.
    for rel in SHARED_DIRS:
        full = resolve(rel)
        n = sum(len(files) for _, _, files in os.walk(full)) if os.path.isdir(full) else 0
        if not n:
            missing.append((rel, rel))
    return found, missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true",
                    help="vis ogsaa stiene som er i orden")
    args = ap.parse_args()

    found, missing = audit()

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

    print()
    if missing:
        print(f"{len(missing)} MANGLER:")
        for where, p in missing:
            print(f"  {where}: {p}")
        print()
        print("En manglende line2-logo gir en forside med halv tittel, og en")
        print("manglende dreampage-first gir den DELTE gamle aapningssida. Hele")
        print("kjeden er fail-soft - den stopper ingenting. Rett stien foer du")
        print("bygger noe som skal trykkes.")
        return 1

    print("alt finnes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
