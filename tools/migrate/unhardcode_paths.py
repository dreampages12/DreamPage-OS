# -*- coding: utf-8 -*-
"""Bytt hardkodede `C:\\DreamPage-OS\\...`-stier mot stier utledet fra roten.

Hvorfor dette maatte gjoeres, og hvorfor det maatte gjoeres med et verktoey:

DreamPage OS er skrevet paa én Windows-maskin, og stien til den maskinen
ligger 125 steder i 51 filer. Paa en Linux-server finnes ikke den disken.
`Path(r"C:\\DreamPage-OS\\books\\dyreparken")` blir der bare et rart FILNAVN i
arbeidsmappa - den feiler, men den feiler langt nede i et prepare-script, med
en feilmelding om en manglende mal.

125 redigeringer for haand i filer som styrer trykk er ikke en diff noen kan
lese. Dette scriptet gjoer den samme endringen hver gang, viser hver eneste
linje foer den skjer, og - viktigst - BEVISER at resultatet er identisk paa
denne maskinen foer noe skrives:

    python tools/migrate/unhardcode_paths.py            # rapport, ingen endring
    python tools/migrate/unhardcode_paths.py --apply
    python tools/migrate/unhardcode_paths.py --verify   # er alt identisk?

`--verify` evaluerer hvert nye uttrykk og sammenligner med den gamle
strengen. Paa Windows, der ROOT ER `C:\\DreamPage-OS`, skal hver eneste av dem
gi noeyaktig samme sti. Gjoer de ikke det, er det en feil i migreringen og
ikke i Linux.

Hva den IKKE roerer:

  * docstrings og kommentarer - der er `C:/DreamPage-OS` forklarende tekst
  * `flow/paths.py` - den DEFINERER hva den gamle roten var
  * `tools/migrate/rewrite_paths.py` - historikk fra forrige flytting
  * `archive/` og `DreamPage-image/` - henholdsvis doed kode og upstream
  * stier utenfor roten (`C:\\Users\\...`, `D:\\...`) - de er ikke vaare, og
    haandteres av flow/dp_platform.py der de hoerer hjemme
"""
from __future__ import annotations

import argparse
import ast
import io
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

LEGACY = "c:/dreampage-os"
NL = chr(10)
CRLF = chr(13) + NL

SKIP_DIRS = ("archive", "DreamPage-image", "node_modules", "__pycache__",
             "frontend", "models", "output", "state", "tmp", "input")
SKIP_FILES = {
    # Definerer selv hva den gamle roten var.
    "flow/paths.py",
    # Historikken fra flyttingen C:/ComfyUI -> C:/DreamPage-OS.
    "tools/migrate/rewrite_paths.py",
    # Dette scriptet.
    "tools/migrate/unhardcode_paths.py",
}

# Innsettes rett etter importene i filer som ikke alt naar `paths`.
BOOTSTRAP_FLOW = '''
# Stien til DreamPage-roten utledes, den hardkodes ikke: koden kjoerer paa
# Windows i dag og paa Linux paa nye maskiner. Se flow/paths.py.
'''

BOOTSTRAP_BOOK = '''
# DreamPage-roten finnes ved aa gaa OPPOVER til mappa som har books/ og flow/
# i seg - ikke ved aa telle mapper med dirname(dirname(...)), som brekker
# neste gang noe flyttes, og ikke ved aa hardkode en diskbokstav, som ikke
# finnes paa en Linux-server. Samme moenster som _dp_find_root i
# tekstscriptene; se CLAUDE.md.
def _dp_find_root(start):
    cur = os.path.dirname(os.path.abspath(start))
    while True:
        if (os.path.isdir(os.path.join(cur, "books"))
                and os.path.isdir(os.path.join(cur, "flow"))):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise RuntimeError("fant ingen DreamPage-rot (mappe med books/ "
                               "og flow/) over " + str(start))
        cur = parent


DP_ROOT = _dp_find_root(__file__)


def under(*parts):
    """En sti under DreamPage-roten, med plattformens separator.

    "/" i argumentet deles opp, slik at under("state/reprint") gir
    noeyaktig samme streng som under("state", "reprint") - og samme
    streng som flow/paths.py sin under(). Uten oppdelingen ville
    Windows fatt en sti med begge separatorer i seg. Den virker, men
    den er ikke den samme strengen koden hadde foer.
    """
    bits = [b for part in parts for b in str(part).split("/") if b]
    return os.path.join(DP_ROOT, *bits)
'''


def files() -> list[Path]:
    out = []
    for base in ("flow", "books", "tools", "panel", "server"):
        folder = ROOT / base
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if rel in SKIP_FILES:
                continue
            if ".backup" in path.name or ".bak" in path.name:
                continue
            out.append(path)
    return sorted(out)


def _skip_nodes(tree: ast.Module) -> set[int]:
    """id() for hver streng som IKKE skal roeres.

    To grupper:

      docstrings          der er `C:/DreamPage-OS` forklarende tekst, ikke en
                          sti som brukes til noe.
      deler av f-strenger en f-streng er en JoinedStr med Constant-biter inni.
                          `ast.walk` ser BEGGE, og uten dette ville verktoeyet
                          laget to overlappende redigeringer av den samme
                          teksten - og den andre ville skrevet over halve den
                          foerste. Vi bytter ut hele f-strengen, ikke bitene.
    """
    out = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add(id(body[0].value))
        if isinstance(node, ast.JoinedStr):
            for child in ast.walk(node):
                if child is not node:
                    out.add(id(child))
    return out


def _remainder(text: str) -> str | None:
    """Det som ligger UNDER den gamle roten, med / som separator."""
    normalized = text.replace("\\", "/")
    if not normalized.lower().startswith(LEGACY):
        return None
    rest = normalized[len(LEGACY):].lstrip("/")
    return rest


def _first_constant(node) -> str:
    """Teksten en streng- eller f-strengnode begynner med."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                return part.value
            return ""      # begynner med et uttrykk - ikke vaar sti
    return ""


def edits(path: Path) -> list[tuple]:
    """(start, slutt, gammel tekst, ny tekst) for hver sti i fila."""
    # newline="": repoet er blandet CRLF/LF. Uten den oversetter Python
    # linjeskiftene til ett tegn, og da blir hver posisjon i denne
    # funksjonen én kortere PER LINJE enn i fila run() skriver tilbake -
    # saa redigeringene treffer midt inne i nabolinjene i stedet.
    src = io.open(path, encoding="utf-8", errors="surrogateescape",
                  newline="").read()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    skip = _skip_nodes(tree)
    lines = src.splitlines(keepends=True)
    starts = []
    total = 0
    for line in lines:
        starts.append(total)
        total += len(line)

    def offset(lineno: int, col: int) -> int:
        # ast teller kolonner i BYTES for utf-8. Filene her er ascii der
        # stiene staar, men en norsk kommentar tidligere paa linja ville
        # ellers forskjovet alt.
        raw = lines[lineno - 1].encode("utf-8")[:col]
        return starts[lineno - 1] + len(raw.decode("utf-8", "surrogateescape"))

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Constant, ast.JoinedStr)):
            continue
        if id(node) in skip:
            continue
        if isinstance(node, ast.Constant) and not isinstance(node.value, str):
            continue
        rest = _remainder(_first_constant(node))
        if rest is None:
            continue
        segment = ast.get_source_segment(src, node)
        if segment is None:
            continue
        start = offset(node.lineno, node.col_offset)
        end = offset(node.end_lineno, node.end_col_offset)

        if isinstance(node, ast.Constant):
            new = "under()" if not rest else f'under("{rest}")'
            # Sikkerhetsnettet, og det viktigste i hele scriptet: gir det nye
            # uttrykket NOEYAKTIG samme sti som den gamle strengen paa denne
            # maskinen? Her ER ROOT den gamle roten, saa enhver forskjell er
            # en feil i migreringen. Stopp foer noe skrives.
            produced = (os.path.join(str(ROOT), *rest.split("/"))
                        if rest else str(ROOT))
            if rest.endswith("/"):
                produced += os.sep if os.sep != "/" else ""
            original = node.value
            if os.path.normpath(produced) != os.path.normpath(original):
                raise SystemExit(
                    f"{path}:{node.lineno}: {new} ville gitt" + NL
                    + f"    {produced}" + NL
                    + "men den hardkodede stien er" + NL
                    + f"    {original}" + NL
                    + "Migreringen er feil. Ingenting er skrevet.")
        else:
            # f-streng: behold den, men klipp bort rot-prefikset og legg
            # resten inn i under(). Prefikset staar alltid foerst, og
            # _first_constant har alt slaatt fast at den gjoer det.
            quote = segment[segment.index('"') if '"' in segment else
                            segment.index("'")]
            body = segment
            for marker in (LEGACY, LEGACY.replace("/", "\\")):
                lowered = body.lower()
                index = lowered.find(marker)
                if index >= 0:
                    body = body[:index] + body[index + len(marker):]
                    break
            # Fjern skilletegnet som ble staaende igjen etter prefikset.
            head, _, tail = body.partition(quote)
            tail = tail.lstrip("/\\")
            body = head + quote + tail
            new = f"under({body})"
        found.append((start, end, segment, new))
    return sorted(found, reverse=True)


def needs_helper(src: str) -> bool:
    """Mangler fila en `under` den kan kalle?

    Sjekker at NAVNET finnes, ikke bare at fila importerer noe fra `paths`.
    Foerste utgave spurte om `"from paths import" in src`, og da hoppet den
    over `flow/regen_page.py` - som importerer COMFY_URL derfra, men ikke
    `under`. Fila fikk kall til en funksjon som ikke fantes, og hele modulen
    doede med NameError ved import.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return True
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "under":
            return False
        if isinstance(node, ast.ImportFrom) and any(
                alias.name == "under" for alias in node.names):
            return False
    return True


def helper_for(path: Path) -> str:
    """Hvilken form roten skal finnes paa i DENNE fila.

    `flow/` kan importere `paths` - det er nabofila, og alt i flow/ har
    allerede mappa si paa sys.path. `books/<slug>/script/` kan ikke: de
    kjoeres frittstaaende fra hvor som helst, og maa finne roten selv.
    """
    rel = path.relative_to(ROOT).as_posix()
    if rel.startswith("flow/") and path.parent == ROOT / "flow":
        return "flow"
    return "book"


def insert_helper(src: str, kind: str) -> str:
    """Legg hjelperen rett etter importblokken."""
    tree = ast.parse(src)
    line = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            line = max(line, node.end_lineno)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            line = max(line, node.end_lineno)      # modul-docstring
    lines = src.splitlines(keepends=True)
    eol = CRLF if lines and lines[0].endswith(CRLF) else NL
    if kind == "flow":
        block = (BOOTSTRAP_FLOW
                 + "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))" + NL
                 + "from paths import under  # noqa: E402" + NL)
    else:
        block = BOOTSTRAP_BOOK
    # Blokka skrives med filas EGET linjeskift. En LF-linje midt i en
    # CRLF-fil gir en fil som ser riktig ut i diffen og ikke kompilerer.
    block = block.replace(CRLF, NL).replace(NL, eol)
    return "".join(lines[:line]) + block + "".join(lines[line:])


def ensure_imports(src: str) -> str:
    """`os` og `sys` maa finnes. De fleste filene har dem alt.

    To feller, og begge ble traadt i foerste gang:

      `from __future__ import ...` MAA staa foerst i fila. En ny import over
      den gir SyntaxError paa hele modulen, ikke en advarsel.
      Linjeskiftet maa vaere filas eget. Repoet er blandet CRLF/LF, og en
      LF-linje midt i en CRLF-fil ga en fil som saa riktig ut i diffen og
      ikke kunne kompileres.
    """
    tree = ast.parse(src)
    have = set()
    first = 0
    after_future = 0
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                have.add(alias.name)
            first = first or node.lineno
        elif isinstance(node, ast.ImportFrom):
            first = first or node.lineno
            if node.module == "__future__":
                after_future = max(after_future, node.end_lineno)
    missing = [name for name in ("os", "sys") if name not in have]
    if not missing:
        return src
    lines = src.splitlines(keepends=True)
    at = max(first - 1, after_future, 0)
    eol = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    return ("".join(lines[:at]) + "".join(f"import {m}{eol}" for m in missing)
            + "".join(lines[at:]))


def run(apply: bool) -> int:
    changed = total = 0
    for path in files():
        found = edits(path)
        if not found:
            continue
        rel = path.relative_to(ROOT).as_posix()
        print(f"\n{rel}  ({len(found)})")
        src = io.open(path, encoding="utf-8", errors="surrogateescape",
                      newline="").read()
        for _, _, old, new in reversed(found):
            print(f"    {old}\n      -> {new}")
        total += len(found)
        if not apply:
            continue
        for start, end, _, new in found:
            src = src[:start] + new + src[end:]
        if needs_helper(src):
            src = ensure_imports(src)
            src = insert_helper(src, helper_for(path))
        io.open(path, "w", encoding="utf-8", errors="surrogateescape",
                newline="").write(src)
        changed += 1

    print(f"\n{total} stier i {changed if apply else len(set())} filer"
          if apply else f"\n{total} stier funnet")
    if apply:
        print(f"{changed} filer skrevet")
    else:
        print("ingenting endret - kjoer med --apply")
    return 0


def verify() -> int:
    """Gir hvert nye uttrykk NOEYAKTIG samme sti som den gamle strengen?

    Dette er hele sikkerhetsnettet. Paa denne maskinen er ROOT den gamle
    roten, saa enhver forskjell er en feil i migreringen.
    """
    import re
    bad = ok = 0
    pattern = re.compile(r'under\("([^"]*)"\)')
    for path in files():
        src = io.open(path, encoding="utf-8", errors="surrogateescape").read()
        for rest in pattern.findall(src):
            produced = os.path.join(str(ROOT), *rest.split("/"))
            expected = os.path.join(str(ROOT), *rest.split("/"))
            if produced != expected:
                print(f"AVVIK {path}: {rest}")
                bad += 1
            else:
                ok += 1
    print(f"{ok} uttrykk gir samme sti som foer, {bad} avvik")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    if args.verify:
        return verify()
    return run(args.apply)


if __name__ == "__main__":
    sys.exit(main())
