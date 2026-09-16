# -*- coding: utf-8 -*-
"""Modellmanifest: hva maskinen MAA ha for aa kunne trykke en bok.

models/ er 159 GB og ligger ikke i git. Uten et manifest er den kunnskapen
bare noe som finnes paa én disk, og en gjenoppbygging ville bestaatt av aa
aapne 24 workflow_api.json og gjette.

Manifestet bygges FRA workflowene, ikke for haand: `build` gaar gjennom alle
books/*/workflow_api.json, finner hver node som navngir en modellfil, og slaar
opp filen i models/. Da kan manifestet ikke komme ut av takt med det boekene
faktisk trenger.

    python tools/models.py build      # skriv models/manifest.json
    python tools/models.py check      # mangler noe? feil stoerrelse?
    python tools/models.py verify     # ogsaa sha256 (tregt: 159 GB)
    python tools/models.py fetch      # last ned det som mangler

`check` er rask (navn + stoerrelse) og er den `dreampage.ps1 up` bruker.
`verify` leser hver byte og er for etter en diskfeil eller en flytting.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(os.environ.get("DP_ROOT") or Path(__file__).resolve().parent.parent)
BOOKS = ROOT / "books"
MODELS = ROOT / "models"
MANIFEST = MODELS / "manifest.json"

# Inputnavn i ComfyUI-noder som navngir en modellfil, og undermappa de
# hentes fra. Dette er ComfyUI sin folder_paths-konvensjon.
MODEL_INPUTS = {
    "ckpt_name": "checkpoints",
    "unet_name": "diffusion_models",
    "vae_name": "vae",
    "clip_name": "text_encoders",
    "clip_name1": "text_encoders",
    "clip_name2": "text_encoders",
    "lora_name": "loras",
    "control_net_name": "controlnet",
    "controlnet_name": "controlnet",
    "model_name": "upscale_models",
    "upscale_model": "upscale_models",
    "style_model_name": "style_models",
    "clip_vision": "clip_vision",
    "clip_vision_name": "clip_vision",
    "gguf_name": "unet",
    "pulid_file": "pulid",
    "sam_model_name": "sams",
    "grounding_dino_model": "grounding-dino",
    "ipadapter_file": "ipadapter",
    "insightface": "insightface",
}

MODEL_SUFFIXES = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf",
                  ".onnx", ".sft")


def _referenced() -> dict[str, set[str]]:
    """{filnavn: {boeker som bruker den}} fra alle workflow_api.json."""
    out: dict[str, set[str]] = {}
    for wf in sorted(BOOKS.glob("*/workflow_api.json")):
        slug = wf.parent.name
        try:
            with open(wf, encoding="utf-8-sig") as fh:
                graph = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  ADVARSEL: {wf} kunne ikke leses ({exc})")
            continue
        for node in graph.values():
            if not isinstance(node, dict):
                continue
            for name, value in (node.get("inputs") or {}).items():
                if not isinstance(value, str):
                    continue
                if name in MODEL_INPUTS or value.lower().endswith(MODEL_SUFFIXES):
                    if value.lower().endswith(MODEL_SUFFIXES):
                        out.setdefault(value, set()).add(slug)
    return out


def _find_on_disk(filename: str) -> Path | None:
    """Filen kan ligge i en vilkaarlig undermappe av models/.

    Workflowen navngir noen modeller med undermappe ("bbox/face_yolov8m.pt" -
    Impact Pack sin konvensjon). Da maa treffet vaere den filen som ogsaa har
    den undermappa, ellers skriver manifestet en sti som sender modellen til
    feil sted ved en gjenoppbygging.
    """
    wanted = filename.replace("\\", "/").lower()
    base = wanted.split("/")[-1]
    if not MODELS.is_dir():
        return None
    candidates = [p for p in MODELS.rglob("*")
                  if p.is_file() and p.name.lower() == base]
    if not candidates:
        return None
    # Eksakt haleslag foerst: .../ultralytics/bbox/face_yolov8m.pt for
    # "bbox/face_yolov8m.pt".
    for path in candidates:
        rel = str(path.relative_to(MODELS)).replace("\\", "/").lower()
        if rel == wanted or rel.endswith("/" + wanted):
            return path
    return candidates[0]


def _sha256(path: Path, chunk: int = 8 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def cmd_build(args) -> int:
    refs = _referenced()
    print(f"{len(refs)} modellfiler navngitt i {len(list(BOOKS.glob('*/workflow_api.json')))} workflows\n")

    previous = {}
    if MANIFEST.is_file():
        try:
            with open(MANIFEST, encoding="utf-8") as fh:
                previous = {m["file"]: m for m in json.load(fh).get("models", [])}
        except (OSError, json.JSONDecodeError, KeyError):
            previous = {}

    models = []
    missing = []
    for filename in sorted(refs):
        path = _find_on_disk(filename)
        old = previous.get(filename, {})
        entry = {
            "file": filename,
            "used_by": sorted(refs[filename]),
            # url maa fylles inn for haand én gang per modell. Den kan ikke
            # utledes: samme fil finnes paa Hugging Face, Civitai og i private
            # speil, og bare mennesket vet hvilken som er kilden.
            "url": old.get("url", ""),
            "note": old.get("note", ""),
        }
        if path:
            entry["path"] = str(path.relative_to(MODELS)).replace("\\", "/")
            entry["bytes"] = path.stat().st_size
            entry["sha256"] = old.get("sha256", "") if not args.hash else _sha256(path)
            if args.hash:
                print(f"  hashet  {filename}")
        else:
            missing.append(filename)
            entry["path"] = ""
            entry["bytes"] = old.get("bytes", 0)
            entry["sha256"] = old.get("sha256", "")
        models.append(entry)

    MODELS.mkdir(parents=True, exist_ok=True)
    total = sum(m["bytes"] for m in models)
    MANIFEST.write_text(json.dumps({
        "_": ("Generert av tools/models.py build FRA books/*/workflow_api.json. "
              "url og note maa fylles inn for haand - samme fil finnes paa flere "
              "steder, og bare mennesket vet hvilken kilde som er riktig."),
        "generated": __import__("datetime").datetime.now()
                     .astimezone().isoformat(timespec="seconds"),
        "total_bytes": total,
        "models": models,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\nskrevet {MANIFEST}")
    print(f"  {len(models)} modeller, {total / 1e9:.1f} GB funnet paa disk")
    if missing:
        print(f"  {len(missing)} navngitt i en workflow men IKKE paa disk:")
        for m in missing:
            print(f"      {m}  (brukt av {', '.join(sorted(refs[m]))})")
    no_url = [m["file"] for m in models if not m["url"]]
    if no_url:
        print(f"  {len(no_url)} mangler url - fyll inn i manifest.json for at "
              f"`fetch` skal kunne laste dem ned")
    return 0


# Mappenoekler som IKKE er navnet paa en mappe. Custom nodes ber om dem med
# egne navn, og en yaml som bare speiler mappelisten ville ikke daekket dem.
# Funnet ved aa greppe custom_nodes for add_model_folder_path/get_folder_paths.
ALIASES = {
    "ultralytics_bbox": "ultralytics/bbox",
    "ultralytics_segm": "ultralytics/segm",
    "facedetection_models": "facedetection",
    "nsfw": "nsfw_detector",
    "rmbg": "RMBG",
}


def cmd_paths(args) -> int:
    """Skriv config/extra_model_paths.yaml fra de faktiske mappene i models/.

    Denne filen er hele grunnen til at DreamPage-image kan forbli urediget:
    ComfyUI far modellstiene paa kommandolinja i stedet for aa lete i sitt
    eget tre.

    Den genereres, ikke skrives for haand. Foerste forsoek var en liste over
    ComfyUI sine standard-noekler, og da saa ansiktsdetektoren NULL modeller:
    `models/ultralytics/` er ikke en standard-noekkel - Impact Subpack
    registrerer den selv, og ber om `ultralytics`, `ultralytics_bbox` og
    `ultralytics_segm`. Hver side ville feilet paa
    "model_name: 'bbox/face_yolov8m.pt' not in []".
    """
    NL = chr(10)
    base = Path(args.base or MODELS)
    if not base.is_dir():
        raise SystemExit(f"{base} finnes ikke")
    dirs = sorted(d.name for d in base.iterdir() if d.is_dir())
    lines = [
        "# Modellstier for DreamPage-image. GENERERT av "
        "`python tools/models.py paths`.",
        "#",
        "# Gis til ComfyUI med --extra-model-paths-config. Skrives ALDRI inn i",
        "# DreamPage-image - det er nettopp slik vi endrer ComfyUI uten aa",
        "# redigere den.",
        "#",
        "# Hver undermappe i models/ blir en mappenoekkel, PLUSS aliasene som",
        "# custom nodes ber om under andre navn (ultralytics_bbox og",
        "# ultralytics_segm er de som faktisk stopper en bokside).",
        "",
        "dreampage:",
        f"  base_path: {str(base).replace(chr(92), '/')}",
    ]
    for name in dirs:
        lines.append(f"  {name}: {name}")
    lines.append("")
    lines.append("  # aliaser - noekkelnavn som ikke er et mappenavn")
    for key, rel in sorted(ALIASES.items()):
        if (base / rel.split("/")[0]).is_dir():
            lines.append(f"  {key}: {rel}")
    out = Path(args.out or (ROOT / "config" / "extra_model_paths.yaml"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(NL.join(lines) + NL, encoding="utf-8")
    print(f"skrevet {out}")
    print(f"  base_path   {base}")
    print(f"  {len(dirs)} mappenoekler + {len(ALIASES)} aliaser")
    return 0


def _load_manifest() -> dict:
    if not MANIFEST.is_file():
        raise SystemExit(f"fant ingen {MANIFEST}. Kjoer: python tools/models.py build")
    with open(MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)


def cmd_check(args) -> int:
    data = _load_manifest()
    missing, wrong, bad_hash = [], [], []
    for entry in data["models"]:
        path = MODELS / entry["path"] if entry.get("path") else None
        if not path or not path.is_file():
            hit = _find_on_disk(entry["file"])
            if hit is None:
                missing.append(entry)
                continue
            path = hit
        if entry.get("bytes") and path.stat().st_size != entry["bytes"]:
            wrong.append((entry, path.stat().st_size))
        if args.verify and entry.get("sha256"):
            if _sha256(path) != entry["sha256"]:
                bad_hash.append(entry)
            else:
                print(f"  OK  {entry['file']}")

    total = len(data["models"])
    print(f"{total - len(missing)}/{total} modeller finnes")
    for entry in missing:
        print(f"  MANGLER  {entry['file']}  (brukt av "
              f"{', '.join(entry.get('used_by') or ['?'])})")
    for entry, size in wrong:
        print(f"  STOERRELSE  {entry['file']}: {size} bytes, manifestet sier "
              f"{entry['bytes']}")
    for entry in bad_hash:
        print(f"  SHA256 STEMMER IKKE  {entry['file']}")

    if missing or wrong or bad_hash:
        print("\nDisse boekene kan ikke bygges foer modellene er paa plass.")
        return 1
    return 0


def cmd_fetch(args) -> int:
    data = _load_manifest()
    todo = []
    for entry in data["models"]:
        if entry.get("path") and (MODELS / entry["path"]).is_file():
            continue
        if _find_on_disk(entry["file"]):
            continue
        todo.append(entry)
    if not todo:
        print("ingenting mangler")
        return 0

    no_url = [e for e in todo if not e.get("url")]
    if no_url:
        print(f"{len(no_url)} av {len(todo)} manglende modeller har ingen url i "
              f"manifestet. Fyll dem inn foerst:")
        for e in no_url:
            print(f"    {e['file']}")
    for entry in todo:
        if not entry.get("url"):
            continue
        target_dir = MODELS / (entry.get("dir")
                               or MODEL_INPUTS.get(entry.get("input", ""), "checkpoints"))
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / entry["file"].split("/")[-1]
        print(f"laster ned {entry['file']} -> {target}")
        if args.dry_run:
            continue
        tmp = target.with_suffix(target.suffix + ".part")
        req = urllib.request.Request(entry["url"], headers={"User-Agent": "dreampage-os"})
        with urllib.request.urlopen(req, timeout=120) as res, open(tmp, "wb") as fh:
            done = 0
            while True:
                block = res.read(8 << 20)
                if not block:
                    break
                fh.write(block)
                done += len(block)
                print(f"\r    {done / 1e9:.2f} GB", end="", flush=True)
        print()
        if entry.get("sha256"):
            got = _sha256(tmp)
            if got != entry["sha256"]:
                tmp.unlink(missing_ok=True)
                raise SystemExit(f"sha256 stemmer ikke for {entry['file']}:\n"
                                 f"  ventet {entry['sha256']}\n  fikk   {got}")
        os.replace(tmp, target)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="skriv manifestet fra workflowene")
    b.add_argument("--hash", action="store_true",
                   help="regn ut sha256 (tregt: leser 159 GB)")
    b.set_defaults(func=cmd_build)

    c = sub.add_parser("check", help="mangler noe?")
    c.add_argument("--verify", action="store_true", help="ogsaa sha256")
    c.set_defaults(func=cmd_check)

    v = sub.add_parser("verify", help="check --verify")
    v.set_defaults(func=cmd_check, verify=True)

    pa = sub.add_parser("paths", help="skriv config/extra_model_paths.yaml")
    pa.add_argument("--base", help="models-mappa (standard: <ROOT>/models)")
    pa.add_argument("--out", help="hvor yaml-en skrives")
    pa.set_defaults(func=cmd_paths)

    f = sub.add_parser("fetch", help="last ned det som mangler")
    f.add_argument("--dry-run", action="store_true")
    f.set_defaults(func=cmd_fetch)

    args = ap.parse_args()
    if not hasattr(args, "verify"):
        args.verify = False
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
