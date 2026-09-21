# -*- coding: utf-8 -*-
"""Klargjoer HeadSwap uten aa starte trening eller endre bokproduksjonen."""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
import venv

_os_root = next(p for p in Path(__file__).resolve().parents if (p / "flow/paths.py").is_file())
sys.path.insert(0, str(_os_root / "flow"))
import paths


def configuration():
    cfg = json.loads((paths.ROOT / "config/headswap.json").read_text(encoding="utf-8-sig"))
    if cfg.get("schema_version") != 1:
        raise ValueError("Ukjent HeadSwap-konfigurasjon")
    if cfg.get("training_backbone") != "flux-klein-9b" or cfg.get("training_model_id") != "black-forest-labs/FLUX.2-klein-9B":
        raise ValueError("Treningsmaalet er eksplisitt vanlig Klein 9B. 4B eller automatisk variantbytte er ikke tillatt.")
    if cfg.get("dataset_approval_required") is not True or cfg.get("photorealistic_only") is not True:
        raise ValueError("Datasettgodkjenning og fotorealisme skal vaere paakrevd")
    if cfg.get("automatic_customer_enrollment") is not False:
        raise ValueError("Kundedata skal ikke innroemmes automatisk")
    return cfg


def location(cfg, key):
    return paths.resolve(cfg[key], root=paths.ROOT).resolve()


def environment_python(env):
    # venv-mappa er laget lokalt. Plattformvalg hoerer bare til oppsettet.
    return env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def get_json(url):
    with urllib.request.urlopen(url, timeout=8) as response:
        return json.load(response)


def comfy_url():
    cfg = json.loads((paths.ROOT / "config/flow.json").read_text(encoding="utf-8-sig"))
    return cfg["comfy"]["url"].rstrip("/")


def expected_nodes(package):
    # Les deklarasjonene, ikke importer torch i en lett driftskontroll.
    names = []
    for name in ("nodes.py", "native_nodes.py"):
        tree = ast.parse((package / "comfyui_dreampage_headswap" / name).read_text(encoding="utf-8-sig"))
        names.extend(n.name for n in tree.body if isinstance(n, ast.ClassDef) and n.name.startswith("DP_"))
    return sorted(names)


def environment_status(python):
    if not python.is_file():
        return {"ready": False, "reason": "Treningsmiljoe mangler; kjoer setup-env"}
    code = """import importlib.metadata as m,json,importlib.util,sys
names=['torch','diffusers','transformers','accelerate','pillow-heif','dreampage-headswap']
out={}
for n in names:
 try: out[n]=m.version(n)
 except m.PackageNotFoundError: out[n]=None
s=importlib.util.find_spec('dreampage_headswap')
print(json.dumps({'versions':out,'package_origin':s.origin if s else None,'python':sys.executable}))
"""
    run = subprocess.run([str(python), "-c", code], capture_output=True, text=True, timeout=30)
    if run.returncode:
        return {"ready": False, "reason": run.stderr[-1200:]}
    result = json.loads(run.stdout)
    versions = result["versions"]
    result["ready"] = (versions.get("diffusers") == "0.37.1" and versions.get("transformers") == "4.56.2"
                       and all(versions.values()))
    result["ready"] = bool(result["ready"])
    return result


def doctor(cfg, offline=False):
    package = location(cfg, "package")
    weights = location(cfg, "training_weights")
    missing, wrong_size = [], []
    receipt_path = weights / "dreampage_provenance.json"
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        for entry in receipt["files"]:
            file = (weights / entry["path"]).resolve()
            if not file.is_relative_to(weights):
                raise ValueError("Modellkvitteringen peker utenfor modellmappa")
            if not file.is_file():
                missing.append(entry["path"])
            elif file.stat().st_size != entry["bytes"]:
                wrong_size.append(entry["path"])
        model = {"receipt_present": True, "model_id": receipt.get("model_id"),
                 "target_matches": receipt.get("model_id") == cfg["training_model_id"],
                 "commercial_use_reviewed": receipt.get("commercial_use_reviewed", False),
                 "file_count": len(receipt["files"]),
                 "missing": missing, "wrong_size": wrong_size,
                 "check_scope": "filnavn og stoerrelser; full SHA256 kontrolleres foer modellinnlasting",
                 "revision": receipt["revision"]}
    else:
        model = {"receipt_present": False, "missing": [str(receipt_path)]}
    # Arkitektur leses uten aa importere torch eller laste selve vektene.
    sys.path.insert(0, str(package / "src"))
    from dreampage_headswap.model_target import inspect_single_file
    try:
        transformer = inspect_single_file(location(cfg, "training_transformer"))
        receipt_file = location(cfg, "training_transformer_receipt")
        if receipt_file.is_file():
            verification = json.loads(receipt_file.read_text(encoding="utf-8"))
            stat = location(cfg, "training_transformer").stat()
            valid = (verification.get("model_id") == cfg["training_model_id"]
                     and verification.get("matches_upstream") is True
                     and verification.get("sha256") == verification.get("expected_sha256")
                     and verification.get("bytes") == stat.st_size and verification.get("mtime_ns") == stat.st_mtime_ns)
            transformer.update(variant_provenance_verified=valid, verification_receipt=str(receipt_file),
                               sha256=verification.get("sha256"), revision=verification.get("revision"),
                               scope="header plus prior streaming SHA256 receipt; current size/mtime checked")
    except (OSError, ValueError) as exc:
        transformer = {"architecture_verified": False, "error": str(exc)}
    incoming = location(cfg, "incoming_dataset")
    suffixes = {".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp", ".tif", ".tiff"}
    images = [p for p in incoming.rglob("*") if p.is_file() and p.suffix.lower() in suffixes]
    spec = importlib.util.find_spec("dreampage_headswap")
    origin = Path(spec.origin).resolve() if spec and spec.origin else None
    source = {"path": str(package), "current_python_origin": str(origin) if origin else None,
              "current_python_uses_os_copy": bool(origin and origin.is_relative_to(package))}
    live = {"checked": False}
    if not offline:
        try:
            oi = get_json(comfy_url() + "/object_info")
            queue = get_json(comfy_url() + "/queue")
            live = {"checked": True, "url": comfy_url(),
                    "expected_nodes": len(expected_nodes(package)),
                    "missing_nodes": sorted(set(expected_nodes(package)) - set(oi)),
                    "running": len(queue.get("queue_running", [])), "pending": len(queue.get("queue_pending", []))}
        except Exception as exc:
            live = {"checked": False, "error": str(exc)}
    env = environment_status(environment_python(location(cfg, "training_environment")))
    if env.get("package_origin") and not Path(env["package_origin"]).resolve().is_relative_to(package):
        env.update(ready=False, reason="Treningsmiljoe peker paa feil kildekopi")
    blockers = ["Datasettgodkjenning kontrolleres per run ved start; doctor godkjenner ingen data."]
    if not images:
        blockers.append("Venter paa brukerens personbilder og swap-mapper.")
    if not env["ready"]:
        blockers.append("Treningsmiljoe er ikke klart.")
    if not model.get("receipt_present") or missing or wrong_size:
        blockers.append("9B-transformeren alene er ikke komplett treningsoppsett; 9B komponent-snapshot/kildekvittering mangler eller maa repareres.")
    if model.get("receipt_present") and (not model.get("target_matches") or not model.get("commercial_use_reviewed")):
        blockers.append("9B modellens opphav/bruksrettigheter er ikke ferdig registrert.")
    if not transformer["architecture_verified"]:
        blockers.append("Den konfigurerte 9B-transformeren mangler eller har feil arkitektur.")
    if live.get("missing_nodes"):
        blockers.append("ComfyUI mangler noen DreamPage-noder; last dem inn ved neste planlagte omstart.")
    return {"package": source, "environment": env, "training_weights": model,
            "training_model_id": cfg["training_model_id"], "local_transformer": transformer, "comfy": live,
            "incoming": {"path": str(incoming), "image_count": len(images)},
            "training_ready": None, "approval_status": "run_specific_check_required", "blockers": blockers,
            "architecture_note": "Trening og Studio sikter mot vanlig Klein 9B. 4B er utgaatt. DreamSwap-checkpoints er egne adapterpakker; vanlig LoRA-eksport er ikke implementert.",
            "training_action": "none; read-only check"}


def init_data(cfg):
    incoming = location(cfg, "incoming_dataset")
    for i in range(1, 21):
        (incoming / f"person_{i:03d}").mkdir(parents=True, exist_ok=True)
    for i in range(1, 26):
        (incoming / "swaps" / f"swap_{i:03d}").mkdir(parents=True, exist_ok=True)
    print(incoming)


def setup_env(cfg):
    package, env = location(cfg, "package"), location(cfg, "training_environment")
    if env.exists() and not (env / "pyvenv.cfg").is_file():
        raise ValueError("Miljoemappa finnes uten pyvenv.cfg; nekter aa overskrive den")
    if not env.exists():
        venv.EnvBuilder(with_pip=True).create(env)
    python = environment_python(env)
    commands = [
        [str(python), "-m", "pip", "install", "--upgrade", "pip"],
        [str(python), "-m", "pip", "install", "torch==2.5.1+cu121", "--index-url", "https://download.pytorch.org/whl/cu121"],
        [str(python), "-m", "pip", "install", "-r", str(package / "requirements-training.txt")],
        [str(python), "-m", "pip", "install", "--no-deps", "-e", str(package)],
    ]
    for command in commands:
        subprocess.run(command, check=True)
    print(json.dumps(environment_status(python), indent=2))


def studio(cfg):
    package = location(cfg, "package")
    subprocess.run([sys.executable, str(package / "scripts/build_klein_workflow.py"), "--server", comfy_url()],
                   cwd=package, check=True)
    # Kun brukerdata, aldri upstream ComfyUI-kilde eller bokworkflowene.
    source = package / "workflows/DreamPage_Klein9B_Studio.json"
    destination = paths.COMFY_USER / "default/workflows" / cfg["studio_filename"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_bytes() != source.read_bytes():
        backup = paths.ROOT / "state/headswap/workflow-backups"
        backup.mkdir(parents=True, exist_ok=True)
        import hashlib
        previous = destination.read_bytes()
        name = hashlib.sha256(previous).hexdigest()[:16] + ".json"
        (backup / name).write_bytes(previous)
    destination.write_bytes(source.read_bytes())
    print(destination)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["doctor", "init-data", "setup-env", "studio"])
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    cfg = configuration()
    if args.command == "doctor":
        report = doctor(cfg, args.offline)
        text = json.dumps(report, indent=2, ensure_ascii=False)
        print(text)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(text + "\n", encoding="utf-8")
    else:
        {"init-data": init_data, "setup-env": setup_env, "studio": studio}[args.command](cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
