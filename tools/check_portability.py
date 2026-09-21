# -*- coding: utf-8 -*-
"""Vil dette treet kjoere paa Linux? Sjekk det FRA Windows, foer flyttingen.

DreamPage OS er skrevet paa Windows og trykker boeker fra Windows i dag. Nye
maskiner settes opp paa Linux. Forskjellen mellom de to er ikke synlig naar
man jobber paa Windows - den viser seg foerste gang noen starter serveren et
annet sted, og da er det en bok som ikke blir laget.

Dette scriptet finner de tre forskjellene som faktisk brekker ting, og det
finner dem HER, paa maskinen der de ikke gjoer noe:

  1. Hardkodede stier    `C:/DreamPage-OS/...` i kode. Paa Linux blir de et
                         rart filnavn i arbeidsmappa. Bruk flow/paths.py.
  2. Feil bokstav i filnavn
                         Windows bryr seg ikke om stor/liten bokstav; Linux
                         gjoer. En config som sier `Georgia.TTF` mens fila
                         heter `Georgia.ttf` virker her og feiler der. Dette
                         er den farligste av de tre, fordi den er USYNLIG
                         paa maskinen som lager boekene i dag.
  3. Windows-bare API-er `ctypes.windll`, `winreg`, `os.startfile`,
                         PowerShell-kall. De hoerer hjemme bak
                         flow/dp_platform.py, ikke i produksjonskoden.

    python tools/check_portability.py           # exit 1 hvis noe brekker
    python tools/check_portability.py --list    # vis ogsaa alt som er OK

Kjoeres av `.\\dreampage.ps1 test` og `./dreampage.sh test`, saa en ny
hardkodet sti blir tatt i samme oeyeblikk som den skrives - ikke den dagen
noen prøver aa sette opp maskin nummer to.
"""
from __future__ import annotations

import argparse
import ast
import glob
import io
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "flow"))
sys.path.insert(0, str(ROOT / "tools"))

from paths import resolve as resolve_path  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

SKIP_DIRS = {"archive", "DreamPage-image", "node_modules", "__pycache__",
             "frontend", "models", "output", "state", "tmp", ".git", ".venv"}

# Filer som HAR lov til aa nevne den gamle roten, og hvorfor.
ALLOWED = {
    # Definerer selv hva den gamle roten var, og oversetter den.
    "flow/paths.py",
    # Migreringsverktoeyene. De LETER etter gamle stier.
    "tools/migrate/rewrite_paths.py",
    "tools/migrate/unhardcode_paths.py",
    # Dette scriptet.
    "tools/check_portability.py",
    # Testene har gamle Windows-stier som TESTDATA: de beviser at
    # paths.resolve() oversetter dem. Uten unntaket ville denne sjekken
    # klaget paa testen som beviser at den ikke trenger aa klage.
    "flow/worker/tests/test_flow.py",
}

# Windows-bare API-er som ikke skal finnes utenfor dp_platform.
WINDOWS_ONLY = (
    (r"ctypes\.windll", "ctypes.windll"),
    (r"\bimport winreg\b", "winreg"),
    (r"os\.startfile", "os.startfile"),
    (r"\bwin32\w+", "win32-modulene"),
    (r"\bmsvcrt\b", "msvcrt"),
    (r"CREATE_NO_WINDOW|STARTUPINFO", "subprocess-flagg for Windows"),
    (r"powershell(?:\.exe)?['\"]", "PowerShell som underprosess"),
)
WINDOWS_ONLY_ALLOWED = {"flow/dp_platform.py", "tools/check_portability.py"}


def rel(path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def python_files() -> list[Path]:
    out = []
    for path in ROOT.rglob("*.py"):
        if set(path.parts) & SKIP_DIRS:
            continue
        if ".backup" in path.name or ".bak" in path.name:
            continue
        out.append(path)
    return sorted(out)


# ---------------------------------------------------------------------------
# 1. Hardkodede stier
# ---------------------------------------------------------------------------
DRIVE_RE = re.compile(r"[A-Za-z]:[\\/]")


def _skip_string_nodes(tree: ast.Module) -> set[int]:
    """Docstrings og f-streng-deler. I en docstring er en Windows-sti
    forklarende tekst; en f-strengs deler daekkes av f-strengen selv."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add(id(body[0].value))
        if isinstance(node, ast.JoinedStr):
            for child in ast.walk(node):
                if child is not node:
                    out.add(id(child))
    return out


def hardcoded_paths() -> list[tuple[str, int, str]]:
    """(fil, linje, sti) for hver absolutt Windows-sti i EKTE kode."""
    found = []
    for path in python_files():
        name = rel(path)
        if name in ALLOWED:
            continue
        src = io.open(path, encoding="utf-8", errors="surrogateescape",
                      newline="").read()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            found.append((name, 0, "<kan ikke parses>"))
            continue
        skip = _skip_string_nodes(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Constant, ast.JoinedStr)):
                continue
            if id(node) in skip:
                continue
            text = ""
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value
            elif isinstance(node, ast.JoinedStr):
                for part in node.values:
                    if isinstance(part, ast.Constant) and isinstance(part.value, str):
                        text = part.value
                    break
            if text and DRIVE_RE.match(text):
                found.append((name, node.lineno, text))
    return found


def hardcoded_in_config() -> list[tuple[str, str]]:
    """Absolutte stier i configfiler som IKKE gaar gjennom paths.resolve().

    Bokconfigene og next_book_titles.json er fulle av dem, og det er greit:
    de leses gjennom `paths.resolve`, som oversetter dem til denne maskinens
    rot. Denne sjekken finner de OEVRIGE - stier som ikke ligger under den
    gamle roten, og som derfor ikke kan oversettes av noen.
    """
    from paths import LEGACY_ROOT
    bad = []
    for pattern in ("config/*.json", "config/preview/**/*.json",
                    "books/*/config.json"):
        for path in sorted(glob.glob(str(ROOT / pattern), recursive=True)):
            try:
                raw = io.open(path, encoding="utf-8-sig").read()
            except OSError:
                continue
            for match in set(re.findall(r'"([A-Za-z]:[\\/][^"]*)"', raw)):
                normalized = match.replace("\\", "/").lower()
                if normalized.startswith(LEGACY_ROOT):
                    continue        # oversettes av paths.resolve
                bad.append((rel(path), match))
    return bad


# ---------------------------------------------------------------------------
# 2. Feil bokstav i filnavn - den som er usynlig paa Windows
# ---------------------------------------------------------------------------
def _case_exact(path: Path) -> bool:
    """Heter fila paa disk NOEYAKTIG det stien sier?

    `os.listdir` gir det ekte navnet fra filsystemet. Paa Windows aapner
    `Georgia.TTF` en fil som heter `Georgia.ttf` uten aa klage; paa Linux
    finnes den ikke. Vi sammenligner hvert ledd, ikke bare filnavnet, fordi
    en mappe med feil bokstav er like doedelig.

    `os.path.abspath`, IKKE `Path.resolve()`. resolve() spoer filsystemet og
    faar tilbake det EKTE navnet - altsaa retter den stille opp nettopp den
    feilen vi leter etter, og sjekken ville alltid sagt ja. abspath er rent
    tekstlig og beholder bokstavene slik configen skrev dem.
    """
    parts = Path(os.path.abspath(path)).parts
    walked = Path(parts[0])
    for part in parts[1:]:
        try:
            entries = os.listdir(walked)
        except OSError:
            return True          # kan ikke sjekke - ikke meld feil
        if part not in entries:
            return False
        walked = walked / part
    return True


def case_mismatches() -> list[tuple[str, str, str]]:
    """(hvor, sti i config, ekte navn paa disk) for hver feil bokstav."""
    import check_assets

    checked: set[str] = set()
    bad = []

    def check(where: str, raw: str) -> None:
        if not raw or raw in checked:
            return
        checked.add(raw)
        path = resolve_path(raw, root=ROOT)
        if not path.exists():
            return               # manglende filer er check_assets sin jobb
        if _case_exact(path):
            return
        try:
            real = [n for n in os.listdir(path.parent)
                    if n.lower() == path.name.lower()]
        except OSError:
            real = []
        bad.append((where, raw, real[0] if real else "?"))

    # Alt check_assets alt vet om: logoer, fonter, bok-spesifikke sider.
    for where, raw in check_assets.audit()[0]:
        check(where, raw)

    # Malene og maskene hver bok bruker. De ligger i input/ og er IKKE med i
    # check_assets, fordi den bare daekker delt kunst. For Linux er de like
    # viktige: `01(enhjørning).png` er et filnavn med tegn utenfor ASCII, og
    # det er noeyaktig den slags navn som blir skrevet litt forskjellig.
    for config_path in sorted(glob.glob(str(ROOT / "books" / "*" / "config.json"))):
        try:
            with io.open(config_path, encoding="utf-8-sig") as fh:
                config = json.load(fh)
        except (OSError, ValueError):
            continue
        where = rel(config_path)
        for page in config.get("pages") or []:
            for key in ("template_image", "mask_image"):
                name = page.get(key)
                if name:
                    check(where, str(ROOT / "input" / name))
    return bad


# ---------------------------------------------------------------------------
# 3. Windows-bare API-er
# ---------------------------------------------------------------------------
def windows_only_api() -> list[tuple[str, int, str]]:
    found = []
    for path in python_files():
        name = rel(path)
        if name in WINDOWS_ONLY_ALLOWED:
            continue
        src = io.open(path, encoding="utf-8", errors="surrogateescape").read()
        for pattern, label in WINDOWS_ONLY:
            for match in re.finditer(pattern, src):
                line = src.count("\n", 0, match.start()) + 1
                found.append((name, line, label))
    return found


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true",
                    help="vis ogsaa det som er i orden")
    args = ap.parse_args()

    paths = hardcoded_paths()
    configs = hardcoded_in_config()
    cases = case_mismatches()
    apis = windows_only_api()

    if args.list:
        print(f"{len(python_files())} Python-filer skannet")

    problems = 0

    if paths:
        problems += len(paths)
        print(f"\n{len(paths)} HARDKODEDE STIER i kode:")
        for name, line, text in paths:
            print(f"  {name}:{line}  {text}")
        print("  -> bruk flow/paths.py (ROOT, under(), resolve())")

    if configs:
        problems += len(configs)
        print(f"\n{len(configs)} ABSOLUTTE STIER i config som ikke kan oversettes:")
        for name, text in configs:
            print(f"  {name}  {text}")
        print("  -> skriv dem relativt til roten, eller under den gamle roten")

    if cases:
        problems += len(cases)
        print(f"\n{len(cases)} FILNAVN MED FEIL BOKSTAV (virker paa Windows, "
              f"feiler paa Linux):")
        for where, raw, real in cases:
            print(f"  {where}")
            print(f"    config sier : {raw}")
            print(f"    disken sier : {real}")

    if apis:
        problems += len(apis)
        print(f"\n{len(apis)} WINDOWS-BARE API-er utenfor flow/dp_platform.py:")
        for name, line, label in apis:
            print(f"  {name}:{line}  {label}")
        print("  -> legg forskjellen i flow/dp_platform.py")

    print()
    if problems:
        print(f"{problems} ting ville brutt paa Linux.")
        return 1
    print("ingenting her ville brutt paa Linux.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
