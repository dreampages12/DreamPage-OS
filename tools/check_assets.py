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

# Spraak der en manglende forsidelogo er en FEIL, ikke et valg.
#
# nb og nn deler logo: alle 18 filene i flow/text/logo/nn/ er byte-identiske
# kopier av bokmaalsfilene, og to av dem staar paa boeker der nynorsk-tittelen
# er en annen (Dragejakten/"Dragejakta", Enhjoerningsdalen/"Einhyrningdalen").
# Omslaget viser bokmaalsordet; historien inni er nynorsk.
#
# en-US, en-GB og sv er IKKE med: der finnes ingen oversatt logo ennaa, og
# `None` betyr med vilje "tegn linje 2 som tekst". En norsk logo paa en
# engelsk bok ville vaert verre enn hvit tekst. Lages en engelsk logo, legges
# spraaket til her.
LOGO_REQUIRED_LOCALES = ("nb", "nn")


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


def scan_cover_logos() -> list[tuple[str, str]]:
    """(hvor, sti) for forsidelogoen hvert norsk tekstscript ber om.

    Egen skanner fordi logonavnet IKKE er en modulnivaa-streng man kan lese
    med ASSET_RE eller scan_text_scripts: de fleste script bygger det inne i
    `resolve_front_cover_logo()`, flere med en ordbok per spraak, og navnet
    joines med en variabel. Regex finner det ikke; AST gjoer det.

    Dette er tredje variant av samme feilklasse, og den dyreste hittil fordi
    den naadde kunden: ordre 1532-b1 (Aksel, nynorsk) fikk forsiden sin som
    ren hvit kursiv i stedet for gulllogoen, og gikk til Gelato-utkast slik
    17.09.2026. Tekstscriptet hadde FRONT_COVER_LOGO_NAME = None, og fila
    laa ikke i flow/text/logo/nn/. Hele kjeden er fail-soft: scriptet skriver
    "[FORSIDE] Fant ingen logo ... - linje 2 tegnes som tekst", avslutter med
    0, og boka blir trykkeklar.

    Bare nb og nn - se LOGO_REQUIRED_LOCALES for hvorfor engelsk og svensk
    ikke er med.
    """
    found: list[tuple[str, str]] = []
    for path in sorted(glob.glob(os.path.join(ROOT, "flow", "text", "*", "*.py"))):
        if ".backup" in path or ".bak" in path:
            continue
        locale = os.path.basename(os.path.dirname(path))
        if locale not in LOGO_REQUIRED_LOCALES:
            continue
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        try:
            with open(path, encoding="utf-8", errors="surrogateescape") as fh:
                src = fh.read()
        except OSError:
            continue
        if "resolve_front_cover_logo" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue        # scan_text_scripts rapporterer syntaksfeilen

        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "resolve_front_cover_logo":
                for sub in ast.walk(node):
                    if (isinstance(sub, ast.Constant)
                            and isinstance(sub.value, str)
                            and sub.value.lower().endswith((".png", ".webp", ".jpg"))):
                        names.append(sub.value)
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "FRONT_COVER_LOGO_NAME"
                            for t in node.targets)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                names.append(node.value.value)

        if not names:
            found.append((rel, f"<INGEN FORSIDELOGO NAVNGITT for {locale}>"))
            continue
        # Scriptet proever flere kandidater og bruker den foerste som finnes.
        # Er ingen av dem der, blir forsiden hvit tekst.
        paths = [f"flow/text/logo/{locale}/{n}" for n in dict.fromkeys(names)]
        if any(os.path.isfile(resolve(p)) for p in paths):
            found.append((rel, next(p for p in paths if os.path.isfile(resolve(p)))))
        else:
            found.append((rel, paths[0]))
    return found


def scan_script_root_paths() -> list[tuple[str, str]]:
    """(hvor, sti) for kunst og fonter tekstscriptene loeser mot SIN EGEN mappe.

    scan_text_scripts() ser bare paa os.path.join(DP_ROOT, ...). Men den
    vanligste formen i tekstscriptene er relativ til scriptet selv:

        FRONT_COVER_LINE1_FONT = os.path.join(SCRIPT_ROOT_DIR, "pre", "Trebuchet MS Bold.ttf")
        BACK_TEXT_FONT         = os.path.join(SCRIPT_ROOT_DIR, "pre", "Fredoka.ttf")

    SCRIPT_ROOT_DIR er flow/text for alle fem spraak, saa disse peker paa
    flow/text/pre/. Den mappa fantes IKKE fram til 17.09.2026: migreringen
    (tools/migrate/rewrite_paths.py) la <gammel>/script/pre til flow/pre -
    altsaa ETT NIVAA for hoeyt - mens scriptene flyttet til flow/text/.

    Konsekvensen var stille, som alltid i denne kjeden: `_front_cover_font`
    faller tilbake paa COVER_FONT (PlayfairDisplay) naar fila mangler. Linje 1
    paa forsiden ble serif-kursiv i stedet for Trebuchet, og bakside-teksten
    paa 85 script-kombinasjoner brukte feil font. Brukeren oppdaget det paa
    ordre 1532-b1; ingenting i systemet hadde sagt fra.

    Dette er fjerde variant av samme feilklasse: 1510 (line2-logo), 1506
    (aapningsside), forsidelogoen, og na fontene. Alle fire hadde et
    fallback som gjorde en feil sti til en stille kvalitetsfeil.
    """
    found: list[tuple[str, str]] = []
    for path in sorted(glob.glob(os.path.join(ROOT, "flow", "text", "*", "*.py"))):
        if ".backup" in path or ".bak" in path:
            continue
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        try:
            with open(path, encoding="utf-8", errors="surrogateescape") as fh:
                tree = ast.parse(fh.read())
        except (OSError, SyntaxError):
            continue        # scan_text_scripts rapporterer syntaksfeilen

        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "join"):
                continue
            args = node.args
            if not args:
                continue
            # Foerste argument skal vaere SCRIPT_ROOT_DIR, enten direkte
            # eller via globals().get("SCRIPT_ROOT_DIR", ...) som flere
            # script bruker.
            first = args[0]
            # BARE SCRIPT_ROOT_DIR. LOGO_DIR er flow/text/logo/<sprak> og
            # SCRIPT_DIR er flow/text/<sprak> - begge har en annen base, og
            # aa behandle dem likt ga 56 falske treff paa foerste forsoek.
            # Det er ikke en kosmetisk feil: check_assets er FOERSTE steg i
            # pipelinen og kaster JobError, saa en skanner som roper ulv
            # stopper hver eneste nye ordre. Logoene dekkes av
            # scan_cover_logos().
            anchored = (isinstance(first, ast.Name)
                        and first.id == "SCRIPT_ROOT_DIR")
            if not anchored and isinstance(first, ast.Call):
                anchored = any(isinstance(a, ast.Constant)
                               and a.value == "SCRIPT_ROOT_DIR"
                               for a in first.args)
            if not anchored:
                continue
            parts = [a.value for a in args[1:]
                     if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if len(parts) != len(args) - 1 or not parts:
                continue        # sti satt sammen av variabler
            if not parts[-1].lower().endswith(
                    (".png", ".webp", ".jpg", ".jpeg", ".ttf", ".otf")):
                continue
            found.append((rel, "flow/text/" + "/".join(parts)))
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
    found += scan_cover_logos()
    found += scan_script_root_paths()

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
