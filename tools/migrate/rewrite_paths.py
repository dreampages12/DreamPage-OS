# -*- coding: utf-8 -*-
"""Rett de hardkodede C:/ComfyUI-stiene til den nye strukturen.

Dette er ikke soek-og-erstatt. `C:/ComfyUI/script` splittes i FIRE retninger,
og en naiv erstatning ville sendt tekstscriptene, assetsene og verktoeyene til
samme sted:

    script/<locale>/        -> flow/text/<locale>/
    script/face_variants/   -> flow/face_variants/
    script/{logo,bakside,ryggrad,lastpages}/ -> assets/
    script/<verktoey>.py    -> flow/tools/
    script/<resten>.py      -> flow/

Derfor er reglene sortert paa lengste prefiks foerst, og hver regel skrives ut
med fil og linje saa endringen kan leses foer den skjer.

    python rewrite_paths.py --dry-run          # rapport, ingenting endres
    python rewrite_paths.py --apply
    python rewrite_paths.py --apply --n8n      # ogsaa de 24 n8n-nodene

Idempotent: kjoeres om igjen uten aa gjoere skade. Filer som allerede er rettet
telles som "uendret".
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

# Windows-konsollen her er cp1252 og kan ikke skrive aeoeaa. Uten dette krasjer
# et hvilket som helst print med norsk tekst i en UnicodeEncodeError - samme
# grep som dp_order.py maatte ha.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                      # C:\DreamPage-OS
OLD = "C:/ComfyUI"
NEW = str(ROOT).replace("\\", "/")             # C:/DreamPage-OS

# ---------------------------------------------------------------------------
# Verktoeyene laa foerst i flow/tools/, men de 12 filene der importerer
# hverandre og modulene i flow/ BART (`from finish_order import ...`,
# `import dp_order`) og stoler paa at scriptets egen mappe er paa sys.path.
# Undermappa brakk 12 importer, saa flow/ er flat. Det som faktisk skulle
# skilles ut var n8n-stillaset, og det ligger i archive/.
# ---------------------------------------------------------------------------
TOOLS: set[str] = set()
LOCALES = ("nb", "nn", "sv", "en-US", "en-GB")
ASSET_DIRS = ("logo", "bakside", "ryggrad", "lastpages")

# ---------------------------------------------------------------------------
# Reglene, lengste prefiks foerst. Alt med skraastrek fremover; separatorene
# haandteres av _variants() lenger ned.
# ---------------------------------------------------------------------------
def _rules() -> list[tuple[str, str]]:
    rules: list[tuple[str, str]] = []
    for loc in LOCALES:
        rules.append((f"{OLD}/script/{loc}", f"{NEW}/flow/text/{loc}"))
    for d in ASSET_DIRS:
        rules.append((f"{OLD}/script/{d}", f"{NEW}/assets/{d}"))
    rules.append((f"{OLD}/script/face_variants", f"{NEW}/flow/face_variants"))
    rules.append((f"{OLD}/script/pre", f"{NEW}/flow/pre"))
    for name in sorted(TOOLS):
        rules.append((f"{OLD}/script/{name}", f"{NEW}/flow/{name}"))

    # Toppmapper.
    rules += [
        (f"{OLD}/dreampage-headswap", f"{NEW}/nodes/dreampage-headswap"),
        (f"{OLD}/custom_nodes",       f"{NEW}/DreamPage-image/custom_nodes"),
        (f"{OLD}/venv",               f"{NEW}/DreamPage-image/venv"),
        (f"{OLD}/user",               f"{NEW}/DreamPage-image/user"),
        (f"{OLD}/main.py",            f"{NEW}/DreamPage-image/main.py"),
        (f"{OLD}/books",              f"{NEW}/books"),
        (f"{OLD}/script",             f"{NEW}/flow"),
        (f"{OLD}/output",             f"{NEW}/output"),
        (f"{OLD}/input",              f"{NEW}/input"),
        (f"{OLD}/models",             f"{NEW}/models"),
        (f"{OLD}/state",              f"{NEW}/state"),
        (f"{OLD}/config",             f"{NEW}/config"),
        (f"{OLD}/server",             f"{NEW}/server"),
        (f"{OLD}/tmp",                f"{NEW}/tmp"),
        # Bar rot til slutt - den ville ellers spist alle de andre.
        (OLD, f"{NEW}/DreamPage-image"),
    ]
    # Lengste foerst, saa /script/nb slaar /script som slaar rota.
    rules.sort(key=lambda r: len(r[0]), reverse=True)
    return rules


RULES = _rules()


def _variants(path: str) -> list[str]:
    """Samme sti i de tre skrivemaatene den faktisk forekommer i.

    `C:/ComfyUI/books` i python-strenger, `C:\\ComfyUI\\books` i raastrenger
    og PowerShell, og `C:\\\\ComfyUI\\\\books` naar den er JSON-kodet inne i en
    n8n-node. Rekkefoelgen er viktig: den dobbelt-escapede maa proeves foerst,
    ellers spiser enkelt-varianten halve treffet.
    """
    fwd = path
    back = path.replace("/", "\\")
    dbl = path.replace("/", "\\\\")
    return [dbl, back, fwd]


def rewrite(text: str) -> tuple[str, int]:
    """Bytt alle stier i en tekst. Returnerer (ny tekst, antall bytter)."""
    total = 0
    for old, new in RULES:
        for o, n in zip(_variants(old), _variants(new)):
            # Bare treff der stien faktisk slutter der, eller fortsetter med
            # en separator. Uten dette ville C:/ComfyUI/script truffet inne i
            # C:/ComfyUI/script_examples.
            pattern = re.escape(o) + r"(?=$|[\\/\"'\s,;:)\]}>]|\\\\)"
            text, k = re.subn(pattern, n.replace("\\", "\\\\"), text)
            total += k
    return text, total


# ---------------------------------------------------------------------------
# Hvilke filer
# ---------------------------------------------------------------------------
SKIP_DIRS = {".git", "__pycache__", "node_modules", "DreamPage-image",
             "local_data", ".venv-flux-test", "runs", "build", "orders",
             "cache", "psd", "models", "output", "input", "tmp"}

# Tre mapper skal IKKE rettes:
#   tools/migrate  - verktoeyet ville rettet seg selv midt i kjoeringen
#   docs           - sti-inventaret og n8n-eksporten er oeyeblikksbilder av
#                    hvordan det SAA UT, og mister verdien hvis de rettes
#   archive        - engangs-patcherne peker paa en n8n som snart ikke finnes.
#                    De er kvitteringer, ikke kode som skal kjoere igjen.
SKIP_RELATIVE = {os.path.join("tools", "migrate"), "docs", "archive"}

# PLAN.md beskriver selve migreringen. Den skal fortsatt kunne lese "fra
# C:\ComfyUI til DreamPage-image" etterpaa.
SKIP_FILES = {"PLAN.md",
              # Denne SKAL kunne nevne den gamle stien: den sjekker om den
              # fortsatt finnes. Foerste kjoering rettet sjekken til aa peke
              # paa seg selv.
              "dreampage.ps1",
              # Genereres av tools/models.py paths og tools/node_requirements.py
              "extra_model_paths.yaml", "required.json"}
TEXT_EXT = {".py", ".ps1", ".json", ".yaml", ".yml", ".js", ".mjs", ".md",
            ".ini", ".cfg", ".txt", ".bat", ".cmd"}


def candidates() -> list[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel_dir = os.path.relpath(dirpath, ROOT)
        if any(rel_dir == s or rel_dir.startswith(s + os.sep) for s in SKIP_RELATIVE):
            continue
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix.lower() not in TEXT_EXT:
                continue
            if ".backup" in name or name.endswith(".bak"):
                continue
            if name in SKIP_FILES:
                continue
            out.append(p)
    return out


def run(apply: bool) -> int:
    changed = files = hits = 0
    report = []
    for p in candidates():
        try:
            src = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "ComfyUI" not in src:
            continue
        new, k = rewrite(src)
        if k == 0 or new == src:
            continue
        files += 1
        hits += k
        rel = p.relative_to(ROOT)
        report.append(f"{rel}  ({k} bytter)")
        # Vis de faktiske linjene, saa endringen kan leses foer den skjer.
        for i, (a, b) in enumerate(zip(src.splitlines(), new.splitlines()), 1):
            if a != b:
                report.append(f"    {i:>5}  - {a.strip()[:110]}")
                report.append(f"    {i:>5}  + {b.strip()[:110]}")
        if apply:
            p.write_text(new, encoding="utf-8")
            changed += 1
    print("\n".join(report))
    print(f"\n{files} filer med treff, {hits} stier"
          + (f", {changed} skrevet" if apply else " - TORRKJORING, ingenting endret"))
    return 0


# ---------------------------------------------------------------------------
# n8n
#
# 24 av de 82 nodene har en hardkodet sti. De rettes over n8n sitt REST-API,
# ikke i SQLite-blobben - n8n cacher workflowen i minnet, saa en direkte
# skriving til databasen ville blitt overskrevet ved neste lagring.
#
# Workflowen deaktiveres IKKE her. Den maa vaere deaktivert foer dette kjoeres,
# ellers kan en ordre starte midt i.
# ---------------------------------------------------------------------------
WF_ID = "xy8qiRUzcBpH52CI"


def n8n_key() -> str:
    if os.environ.get("DP_N8N_API_KEY"):
        return os.environ["DP_N8N_API_KEY"]
    with open(ROOT / "config" / "secrets.json", encoding="utf-8-sig") as fh:
        return json.load(fh)["n8n_api_key"]


def n8n_req(method: str, path: str, payload=None):
    base = os.environ.get("DP_N8N_API_BASE", "http://localhost:5678/api/v1")
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, body, method=method, headers={
        "X-N8N-API-KEY": n8n_key(), "Accept": "application/json",
        "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=180))


def run_n8n(apply: bool) -> int:
    wf = n8n_req("GET", f"/workflows/{WF_ID}")
    print(f"workflow  {wf['name']}  (aktiv: {wf.get('active')})  {len(wf['nodes'])} noder")
    if wf.get("active") and apply:
        raise SystemExit("workflowen er AKTIV. Deaktiver den foerst - en ordre kan "
                         "ellers starte midt i rettingen.")

    touched = 0
    for node in wf["nodes"]:
        blob = json.dumps(node.get("parameters", {}), ensure_ascii=False)
        if "ComfyUI" not in blob:
            continue
        new_blob, k = rewrite(blob)
        if k == 0 or new_blob == blob:
            continue
        touched += 1
        print(f"\n-- [{node.get('type','').split('.')[-1]}] {node.get('name')}  ({k} bytter)")
        for old, nw in RULES:
            if old in blob:
                print(f"     {old}  ->  {nw}")
        if apply:
            node["parameters"] = json.loads(new_blob)

    print(f"\n{touched} noder med treff"
          + (" - TORRKJORING" if not apply else ""))
    if not apply:
        return 0

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = ROOT / "state" / f"n8n-worker-before-paths-{stamp}.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(json.dumps(wf, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"backup    {backup}")

    # n8n sitt API godtar bare disse fire feltene paa PUT - alt annet gir 400.
    n8n_req("PUT", f"/workflows/{WF_ID}", {
        "name": wf["name"], "nodes": wf["nodes"],
        "connections": wf["connections"], "settings": wf.get("settings", {}),
    })
    print("workflow oppdatert")

    check = n8n_req("GET", f"/workflows/{WF_ID}")
    left = [n["name"] for n in check["nodes"]
            if "C:/ComfyUI" in json.dumps(n.get("parameters", {}))
            or "C:\\ComfyUI" in json.dumps(n.get("parameters", {}))]
    print("kontroll  " + ("OK - ingen gamle stier igjen" if not left
                          else "GJENSTAAR: " + ", ".join(left)))
    return 0 if not left else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--n8n", action="store_true",
                    help="rett ogsaa de 24 n8n-nodene (krever deaktivert workflow)")
    ap.add_argument("--rules", action="store_true", help="skriv ut reglene og stopp")
    args = ap.parse_args()

    if args.rules:
        for old, new in RULES:
            print(f"{old:<52} -> {new}")
        return 0
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    print(f"ROOT = {ROOT}\n")
    rc = run(apply=args.apply)
    if args.n8n:
        print("\n" + "=" * 70 + "\nn8n\n" + "=" * 70)
        rc |= run_n8n(apply=args.apply)
    return rc


if __name__ == "__main__":
    sys.exit(main())
