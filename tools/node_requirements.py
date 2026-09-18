# -*- coding: utf-8 -*-
"""Hvilke custom nodes MAA installeres for at boekene skal kunne bygges?

Ikke gjettet, og ikke "alt som tilfeldigvis ligger i custom_nodes". Dette
leser hver `class_type` i alle books/*/workflow_api.json og sporer hver av dem
til noden som registrerer den i NODE_CLASS_MAPPINGS.

Det er forskjellen paa en maskin som kan trykke boeker og en som starter
ComfyUI uten feil: en manglende custom node gir ikke en krasj ved oppstart,
den gir en prompt som avvises med "Cannot execute because node X does not
exist" - midt i en betalt ordre.

    python tools/node_requirements.py              # rapport
    python tools/node_requirements.py --json       # nodes/required.json
    python tools/node_requirements.py --check      # mangler noe i imaget?
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(os.environ.get("DP_ROOT") or Path(__file__).resolve().parent.parent)
BOOKS = ROOT / "books"
IMAGE = ROOT / "DreamPage-image"
OUT = ROOT / "nodes" / "required.json"

# Der custom nodes leter etter en node-pakke. Bruk --image-dir for aa peke paa
# den gamle installasjonen i stedet.
DEFAULT_NODE_DIRS = [IMAGE / "custom_nodes"]


# Workflows vi FAKTISK kjoerer, i to lag.
#
# BOK er det som maa virke for at en betalt ordre skal bli en bok. Feiler en
# node der, stopper produksjonen.
#
# VERKTOEY kjoeres ogsaa av systemet - uttrykksvariantene lages paa HVER ordre
# av face_variants/build_variants.py - men en manglende node der stopper
# ikke boka: siden faller tilbake paa originalbildet.
#
# Alt annet i user/default/workflows er GUI-eksperimenter. De teller ikke.
TIERS = {
    "bok": [("books", "*/workflow_api.json")],
    "verktoey": [("flow/face_variants/workflows", "*.json"),
                 ("script/face_variants/workflows", "*.json")],
}


def _classes_in(graph) -> set[str]:
    """Klassenavn fra baade API-formatet og GUI-formatet."""
    out = set()
    if isinstance(graph, dict) and "nodes" in graph and isinstance(graph["nodes"], list):
        nodes = graph["nodes"]                       # GUI-eksport
    elif isinstance(graph, dict):
        nodes = list(graph.values())                 # API-eksport
    else:
        return out
    for node in nodes:
        if isinstance(node, dict):
            name = node.get("class_type") or node.get("type")
            if name and not str(name).startswith("n8n-nodes-"):
                out.add(str(name))
    return out


def workflow_classes() -> tuple[dict[str, set[str]], dict[str, str]]:
    """({class_type: {workflow-navn}}, {class_type: laveste lag}).

    Laget er "bok" hvis klassen brukes i en bokworkflow, ellers "verktoey".
    """
    used: dict[str, set[str]] = defaultdict(set)
    tier: dict[str, str] = {}
    for name in ("bok", "verktoey"):
        for rel, pattern in TIERS[name]:
            base = ROOT / rel
            if not base.is_dir():
                continue
            for wf in sorted(base.glob(pattern)):
                try:
                    graph = json.loads(wf.read_text(encoding="utf-8-sig",
                                                    errors="replace"))
                except (OSError, json.JSONDecodeError) as exc:
                    print(f"  ADVARSEL: {wf} kunne ikke leses ({exc})")
                    continue
                label = (wf.parent.name if pattern.startswith("*/") else wf.name)
                for cls in _classes_in(graph):
                    used[cls].add(label)
                    # "bok" vinner: settes den foerst, overskrives den ikke.
                    tier.setdefault(cls, name)
    return dict(used), tier


def builtin_classes() -> set[str]:
    """Nodeklassene ComfyUI selv leverer.

    Leses fra kildekoden i DreamPage-image. Pakke-tilhoerigheten MAA komme
    herfra: en kjoerende ComfyUI har alle custom nodes lastet, og da kan man
    ikke skille kjernen fra tilleggene - som er hele spoersmaalet.

    Men kildekoden alene er ikke nok. ComfyUI 0.21 registrerer en del noder
    gjennom det nye V3-skjemaet (`define_schema`) i stedet for
    NODE_CLASS_MAPPINGS, og de blir usynlige her - FluxGuidance,
    ReferenceLatent, UpscaleModelLoader, ImageUpscaleWithModel og
    ImageScaleToTotalPixels er alle slike. Derfor suppleres dette med
    /object_info fra en kjoerende instans, se object_info_classes().
    """
    found: set[str] = set()
    targets = ([IMAGE / "nodes.py"]
               + sorted((IMAGE / "comfy_extras").glob("**/*.py"))
               + sorted((IMAGE / "comfy_api_nodes").glob("**/*.py")))
    for path in targets:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found |= _mapping_keys(text)
        # V3-skjemaet: `node_id="FluxGuidance"` inne i en define_schema.
        for m in re.finditer(r"node_id\s*=\s*[\"']([A-Za-z0-9_.\-|+ ()/]+)[\"']", text):
            found.add(m.group(1))
    return found


def object_info_classes(url: str) -> set[str]:
    """Alle nodeklasser en KJOERENDE ComfyUI har lastet.

    Autoriteten paa "finnes denne klassen i det hele tatt". Den sier ingenting
    om hvilken pakke som leverer den - derfor brukes den bare til aa avgjoere
    om noe mangler, ikke til aa attribuere.
    """
    import urllib.request
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/object_info",
                                    timeout=60) as res:
            return set(json.loads(res.read().decode("utf-8", "replace")))
    except Exception as exc:                          # noqa: BLE001
        print(f"  (naadde ikke {url}/object_info: {exc})")
        return set()


def _mapping_keys(text: str) -> set[str]:
    """Noeklene en fil registrerer i NODE_CLASS_MAPPINGS.

    Bruker `ast`, ikke regex. Foerste forsoek var et regex som krevde at
    dict-en lukket med `}` paa kolonne 0, og det feilet stille paa
    comfy_extras/nodes_flux.py og paa KJNodes - saa FluxGuidance,
    ReferenceLatent, UpscaleModelLoader, ImageScaleToTotalPixels og ColorMatch
    ble rapportert som "finnes ikke". Alle fem finnes. Et verktoey som skal si
    hva som MAA installeres kan ikke ha falske negativer.

    Daekker de fire formene som faktisk brukes:
        NODE_CLASS_MAPPINGS = {"Navn": Klasse}
        NODE_CLASS_MAPPINGS = {**A, "Navn": Klasse}
        NODE_CLASS_MAPPINGS["Navn"] = Klasse
        NODE_CLASS_MAPPINGS.update({"Navn": Klasse})
    """
    keys: set[str] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return keys

    def dict_keys(node) -> set[str]:
        out = set()
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    out.add(key.value)
        return out

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id == "NODE_CLASS_MAPPINGS":
                    keys |= dict_keys(node.value)
                elif (isinstance(target, ast.Subscript)
                      and isinstance(target.value, ast.Name)
                      and target.value.id == "NODE_CLASS_MAPPINGS"
                      and isinstance(target.slice, ast.Constant)
                      and isinstance(target.slice.value, str)):
                    keys.add(target.slice.value)
        elif isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr == "update"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "NODE_CLASS_MAPPINGS"):
                for arg in node.args:
                    keys |= dict_keys(arg)
    return keys


def node_packages(node_dirs: list[Path]) -> dict[str, set[str]]:
    """{class_type: {node-pakker som registrerer den}}."""
    out: dict[str, set[str]] = defaultdict(set)
    for base in node_dirs:
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if entry.name == "__pycache__":
                continue
            files = ([entry] if entry.is_file() and entry.suffix == ".py"
                     else [p for p in entry.rglob("*.py")
                           if "__pycache__" not in p.parts])
            for path in files:
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if "NODE_CLASS_MAPPINGS" not in text:
                    continue
                for key in _mapping_keys(text):
                    out[key].add(entry.name)
    return dict(out)


def package_origin(base: Path, name: str) -> dict:
    """Hvor kom denne node-pakken fra? Repo-URL og commit hvis den har git."""
    path = base / name
    info: dict = {"name": name}
    git_dir = path / ".git"
    if git_dir.exists():
        try:
            info["url"] = subprocess.run(
                ["git", "-C", str(path), "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=20).stdout.strip()
            info["commit"] = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=20).stdout.strip()
            dirty = subprocess.run(
                ["git", "-C", str(path), "status", "--porcelain",
                 "--untracked-files=no"],
                capture_output=True, text=True, timeout=30).stdout.strip()
            if dirty:
                info["local_changes"] = dirty.splitlines()[:10]
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        # Ingen git. Da er den installert via ComfyUI-Manager (som pakker ut
        # en zip) eller skrevet for haand. En verbatim kopi er den eneste
        # maaten aa bevare en haandpatch her - den kan ikke oppdages.
        info["url"] = ""
        info["note"] = ("ingen git - installert fra zip eller skrevet for "
                        "haand. Kopier verbatim; en reinstallasjon kan miste "
                        "lokale endringer.")
    if (path / "requirements.txt").is_file():
        try:
            info["requirements"] = [
                l.strip() for l in (path / "requirements.txt")
                .read_text(encoding="utf-8", errors="replace").splitlines()
                if l.strip() and not l.strip().startswith("#")][:40]
        except OSError:
            pass
    item = Path(path)
    if item.exists():
        try:
            info["is_link"] = bool(os.path.islink(path)) or bool(
                os.readlink(path)) if os.path.exists(path) else False
        except OSError:
            info["is_link"] = False
    return info


# DreamPage sine EGNE noder. De hoerer i nodes/ og junctes inn i
# DreamPage-image/custom_nodes - ikke som tredjeparts-kode inne i et tre vi
# har lovet aa aldri redigere.
OURS = {"dreampage_headswap", "comfyui_head_hair_mask_guard"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help=f"skriv {OUT}")
    ap.add_argument("--check", action="store_true",
                    help="mangler noen av dem i DreamPage-image?")
    ap.add_argument("--node-dir", action="append", default=None,
                    help="hvor node-pakkene ligger (kan gjentas)")
    ap.add_argument("--object-info", default="http://127.0.0.1:8188",
                    help="kjoerende ComfyUI, for aa avgjoere om en klasse "
                         "finnes i det hele tatt (V3-noder er usynlige i "
                         "kildekoden). Tom streng for aa hoppe over.")
    args = ap.parse_args()

    node_dirs = ([Path(d) for d in args.node_dir] if args.node_dir
                 else DEFAULT_NODE_DIRS)

    used, tier = workflow_classes()
    builtin = builtin_classes()
    loaded = object_info_classes(args.object_info) if args.object_info else set()
    provided = node_packages(node_dirs)

    print(f"{len(list(BOOKS.glob('*/workflow_api.json')))} bokworkflows")
    print(f"{len(used)} ulike class_type i bruk")
    print(f"{len(builtin)} nodeklasser lest ut av ComfyUI-kildekoden")
    if loaded:
        print(f"{len(loaded)} nodeklasser lastet i den kjoerende ComfyUI")
    print(f"{len(provided)} nodeklasser levert av {len(node_dirs)} node-mappe(r)\n")

    required: dict[str, set[str]] = defaultdict(set)   # pakke -> klasser
    pkg_tier: dict[str, str] = {}
    core: set[str] = set()
    unknown: dict[str, set[str]] = {}

    for cls, books in sorted(used.items()):
        pkgs = provided.get(cls)
        if pkgs:
            for pkg in pkgs:
                required[pkg].add(cls)
                if tier.get(cls) == "bok" or pkg_tier.get(pkg) != "bok":
                    pkg_tier[pkg] = tier.get(cls, "verktoey")
        elif cls in builtin or cls in loaded:
            core.add(cls)
        else:
            unknown[cls] = books

    print("=" * 74)
    print("PAAKREVDE CUSTOM NODES")
    print("=" * 74)
    base = node_dirs[0]
    entries = []
    for pkg in sorted(required, key=lambda p: (p not in OURS, p.lower())):
        classes = sorted(required[pkg])
        origin = package_origin(base, pkg)
        mark = "  <-- DreamPage" if pkg in OURS else ""
        print(f"\n{pkg}{mark}")
        print(f"    klasser  {', '.join(classes)}")
        if origin.get("url"):
            print(f"    repo     {origin['url']}")
            print(f"    commit   {origin.get('commit', '?')[:12]}")
        else:
            print(f"    repo     (ingen git)")
        if origin.get("local_changes"):
            print(f"    LOKALE ENDRINGER: {len(origin['local_changes'])} fil(er)"
                  f" - forsvinner ved en node-oppdatering")
            for line in origin["local_changes"]:
                print(f"        {line}")
        if origin.get("requirements"):
            print(f"    pip      {', '.join(origin['requirements'][:8])}")
        origin["classes"] = classes
        origin["dreampage_own"] = pkg in OURS
        origin["tier"] = pkg_tier.get(pkg, "verktoey")
        entries.append(origin)

    print("\n" + "=" * 74)
    print(f"ComfyUI-KJERNEN daekker {len(core)} av klassene")
    print("=" * 74)
    print("    " + ", ".join(sorted(core)))

    if unknown:
        print("\n" + "=" * 74)
        print(f"IKKE FUNNET - {len(unknown)} klasser")
        print("=" * 74)
        print("Disse er verken i kjernen eller i noen node-mappe vi saa i.")
        print("En prompt som bruker dem avvises med 'node does not exist'.")
        for cls, books in sorted(unknown.items()):
            print(f"    {cls:<38} brukt av {len(books)} bok(er): "
                  f"{', '.join(sorted(books)[:3])}"
                  + (" ..." if len(books) > 3 else ""))

    installed = {p.name for p in base.iterdir()} if base.is_dir() else set()
    extra = sorted(installed - set(required) - {"__pycache__"})
    print("\n" + "=" * 74)
    print("OPPSUMMERING")
    print("=" * 74)
    kritiske = [p for p in required if pkg_tier.get(p) == "bok"]
    print(f"  KRITISKE for bok    {len(kritiske)} node-pakker")
    for p in sorted(kritiske):
        print(f"      {p}")
    print(f"  verktoey            {len(required) - len(kritiske)}")
    print(f"  av alle: DreamPage  {len([p for p in required if p in OURS])}")
    print(f"  installert men ikke brukt av boekene: {len(extra)}")
    if extra:
        for name in extra:
            if not (base / name).is_dir():
                continue
            print(f"      {name}")

    if args.check:
        missing = [p for p in required if not (IMAGE / "custom_nodes" / p).exists()]
        print(f"\n  i DreamPage-image: {len(required) - len(missing)}/{len(required)}")
        for p in missing:
            print(f"      MANGLER {p}")
        if missing or unknown:
            return 1

    if args.json:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({
            "_": ("Generert av tools/node_requirements.py. Hver class_type i "
                  "books/*/workflow_api.json er sporet til noden som "
                  "registrerer den i NODE_CLASS_MAPPINGS. En manglende node "
                  "gir ikke oppstartsfeil - den gir 'node does not exist' "
                  "midt i en betalt ordre."),
            "generated": __import__("datetime").datetime.now()
                         .astimezone().isoformat(timespec="seconds"),
            "comfyui_commit": (subprocess.run(
                ["git", "-C", str(IMAGE), "rev-parse", "HEAD"],
                capture_output=True, text=True).stdout.strip() or None),
            "class_types_used": len(used),
            "core_classes": sorted(core),
            "unresolved_classes": {k: sorted(v) for k, v in unknown.items()},
            "required_nodes": entries,
            "installed_but_unused": extra,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nskrevet {OUT}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
