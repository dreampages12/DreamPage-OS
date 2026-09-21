"""Versjonerte treningsloep. Planlegging bruker ingen modell eller optimizer.

Fresh lager nye vekter, finetune arver bare modellvekter, resume gjenoppretter
optimizer/scheduler/RNG og dataposisjon. Et nytt datasett krever et nytt loep.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import socket
import sys

import yaml

COMPONENTS = {"identity", "swap", "refiner"}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def package_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file() and (parent / "configs/training").is_dir():
            return parent
    raise ValueError("Fant ikke HeadSwap-prosjektet")


def source_snapshot():
    root = package_root()
    inventory = {p.relative_to(root).as_posix(): sha256(p)
                 for folder in ("src", "training") for p in sorted((root / folder).rglob("*.py"))}
    return {"files": inventory, "sha256": hashlib.sha256(canonical(inventory)).hexdigest()}


def dataset_snapshot(config):
    """Bind hele den registrerte korpusen og bildefilene, ikke bare filnavn.

    Rettigheter og lekkasje valideres dessuten av eksisterende PairDataset foer
    optimizersteget. Fotorealisme kan bare bekreftes ved menneskelig review.
    """
    data = config["dataset"]
    if data.get("allow_synthetic", False):
        raise ValueError("Prosedyre-/syntetiske testdata er ikke tillatt i administrerte treningsloep")
    requested = {Path(data["manifest"]).resolve(), *[Path(x).resolve() for x in data.get("peer_manifests", [])]}
    if config.get("validation", {}).get("manifest"):
        requested.add(Path(config["validation"]["manifest"]).resolve())
    registries = ({Path(data["registry_path"]).resolve()} if data.get("registry_path") else
                  {p.parent / "dataset_registry.json" for p in requested if (p.parent / "dataset_registry.json").is_file()})
    if not registries:
        raise ValueError("dataset_registry.json mangler; hele korpusen maa vaere registrert")
    manifests, files = set(), set(registries)
    for path in registries:
        registry = json.loads(path.read_text(encoding="utf-8-sig"))
        if registry.get("scope") != "complete_declared_enrolled_corpus" or registry.get("schema_version") != 1:
            raise ValueError("Ugyldig korpusregister")
        for item in registry["manifests"]:
            manifest = (path.parent / item["path"]).resolve()
            if sha256(manifest) != item["sha256"]:
                raise ValueError("Manifest er endret siden korpusregisteret ble laget")
            manifests.add(manifest)
    if not requested <= manifests:
        raise ValueError("Trenings-/valideringsmanifest finnes ikke i korpusregisteret")
    identities = {}
    files.update(manifests)
    for manifest in sorted(manifests):
        for line in manifest.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            identity, split = row["identity_id"], row["split"]
            if split not in {"train", "validation", "test", "benchmark"} or row.get("synthetic", False):
                raise ValueError("Ugyldig split eller testdata i manifest")
            if identity in identities and identities[identity] != split:
                raise ValueError("Samme person finnes i ulike splitter")
            identities[identity] = split
            from ..data.records import RightsMetadata
            RightsMetadata.from_dict(row.get("rights"))
            for key in ("source", "template", "ground_truth", "headmask"):
                files.add((manifest.parent / row[key]).resolve())
            for key in ("sources", "source_headmasks"):
                files.update((manifest.parent / value).resolve() for value in row.get(key, []))
    if not identities or "train" not in identities.values() or "validation" not in identities.values():
        raise ValueError("Krever ikke-tomme train- og validation-splitter med forskjellige personer")
    if data.get("artifacts_manifest"):
        artifacts = Path(data["artifacts_manifest"]).resolve()
        files.add(artifacts)
        for line in artifacts.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                files.add((artifacts.parent / json.loads(line)["generated"]).resolve())
    # Innholdshasher holder godkjenningen gyldig ved flytting til en annen server.
    inventory = sorted({(sha256(file), file.stat().st_size) for file in files})
    payload = {"files": [{"sha256": digest, "bytes": size} for digest, size in inventory],
               "identities": dict(sorted(identities.items()))}
    return {**payload, "sha256": hashlib.sha256(canonical(payload)).hexdigest()}


def require_approval(config, approval_path, component):
    if component not in COMPONENTS or not approval_path:
        raise ValueError("Eksplisitt datasettgodkjenning mangler")
    approval = json.loads(Path(approval_path).read_text(encoding="utf-8-sig"))
    if (approval.get("approved") is not True or approval.get("photorealistic_only") is not True
            or component not in approval.get("components", [])
            or not isinstance(approval.get("user_approval_reference"), str)
            or not approval["user_approval_reference"].strip()):
        raise ValueError("Venter paa brukerens eksplisitte godkjenning av det viste datasettet")
    snapshot = dataset_snapshot(config)
    if approval.get("dataset_sha256") != snapshot["sha256"]:
        raise ValueError("Datasettet er endret eller feil datasett er godkjent; nytt review kreves")
    return snapshot


def authorize_training(config, component):
    """Samme grense gjelder ogsaa eldre CLI-er og direkte Python-kall."""
    snapshot = require_approval(config, config.get("training", {}).get("dataset_approval"), component)
    from ..model_target import training_target
    training_target(config, component)
    if os.getenv("WORLD_SIZE", "1") != "1":
        raise ValueError("Administrerte loep krever en prosess; distribuert FLUX-trening er ikke validert")
    for parent in package_root().parents:
        cfg_file = parent / "config/flow.json"
        if cfg_file.is_file():
            os_config = json.loads(cfg_file.read_text(encoding="utf-8-sig"))
            if os_config.get("server", {}).get("role") == "production":
                raise ValueError("Serveren er merket production. Bruk en dedikert treningsserver.")
            break
    return snapshot


def prepare_run(config, run_id, component, mode="fresh", parent_checkpoint=None, root=None):
    root = Path(root or package_root()).resolve()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", run_id):
        raise ValueError("Run-ID maa vaere et enkelt navn uten mapper")
    if component not in COMPONENTS or mode not in {"fresh", "finetune"}:
        raise ValueError("Ukjent komponent eller modus; resume bruker eksisterende run")
    from ..model_target import training_target
    training_target(config, component)
    if (mode == "finetune") != bool(parent_checkpoint):
        raise ValueError("Bare finetune skal ha et forelder-checkpoint")
    config = copy.deepcopy(config)
    if config.get("training", {}).get("initialize_from"):
        raise ValueError("Bruk --parent for aa registrere modellens opphav")
    snapshot = dataset_snapshot(config)
    parent = None
    inherited = set()
    if parent_checkpoint:
        checkpoint = Path(parent_checkpoint).resolve()
        parent_file = checkpoint.parent.parent / "run.json"
        if not checkpoint.is_file() or not parent_file.is_file():
            raise ValueError("Finetune krever checkpoint fra et administrert run; gamle testvekter importeres ikke automatisk")
        parent_run = json.loads(parent_file.read_text(encoding="utf-8"))
        if parent_run["component"] != component or not parent_run.get("approval"):
            raise ValueError("Foreldermodell har feil komponent eller mangler datasettgodkjenning")
        recorded = parent_run.get("checkpoints", {}).get(checkpoint.name)
        if not recorded or recorded["sha256"] != sha256(checkpoint):
            raise ValueError("Forelder-checkpoint er ikke registrert eller er endret")
        inherited.update(parent_run.get("training_identity_lineage", []))
        held_out = {name for name, split in snapshot["identities"].items() if split != "train"}
        if inherited & held_out:
            raise ValueError("Validerings-/testpersoner er allerede brukt til aa trene foreldermodellen")
        parent = {"run_id": parent_run["run_id"], "checkpoint": Path(os.path.relpath(checkpoint, root)).as_posix(),
                  "sha256": recorded["sha256"]}
        config.setdefault("training", {})["initialize_from"] = parent["checkpoint"]
        config["training"]["initialize_sha256"] = parent["sha256"]
    inherited.update(name for name, split in snapshot["identities"].items() if split == "train")
    destination = root / "runs/managed" / run_id
    config.setdefault("training", {})["output_dir"] = Path(os.path.relpath(destination / "model", root)).as_posix()
    config["training"]["verify_dataset_fingerprint"] = True
    config["training"]["run_id"] = run_id
    config["training"]["training_identity_lineage"] = sorted(inherited)
    run = {"schema_version": 1, "run_id": run_id, "component": component, "mode": mode,
           "status": "awaiting_dataset_approval", "created_utc": now(), "dataset": snapshot,
           "config_sha256": hashlib.sha256(canonical(config)).hexdigest(), "parent": parent,
           "training_identity_lineage": sorted(inherited), "approval": None,
           "quality_validated": False, "checkpoints": {}, "source": source_snapshot()}
    # mkdir uten exist_ok beskytter gamle eksperimenter mot overskriving.
    destination.mkdir(parents=True, exist_ok=False)
    write_json(destination / "config.json", config)
    write_json(destination / "run.json", run)
    write_json(destination / "approval.request.json", {
        "approved": False, "photorealistic_only": False, "components": [component],
        "dataset_sha256": snapshot["sha256"], "user_approval_reference": "",
        "note": "Dette er en forespoersel, IKKE en godkjenning. Vis bildene, rettigheter, kvalitet og splitter til brukeren."})
    return destination


def execute_run(directory, approval_path, resume=False, max_steps=None):
    directory = Path(directory).resolve()
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    run = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    if hashlib.sha256(canonical(config)).hexdigest() != run["config_sha256"]:
        raise ValueError("Run-konfigurasjonen er endret; lag et nytt run")
    if source_snapshot()["sha256"] != run["source"]["sha256"]:
        raise ValueError("Treningskoden er endret; gjenopprett kodeversjonen eller planlegg et nytt run")
    snapshot = require_approval(config, approval_path, run["component"])
    if snapshot["sha256"] != run["dataset"]["sha256"]:
        raise ValueError("Datasettet har endret seg siden planlegging")
    if os.getenv("WORLD_SIZE", "1") != "1":
        raise ValueError("Administrerte loep krever en prosess; distribuert FLUX-trening er ikke validert")
    # Produksjonsworkeren kan ta en ny ordre selv om Comfy-koen er tom akkurat naa.
    for parent in package_root().parents:
        cfg_file = parent / "config/flow.json"
        if cfg_file.is_file():
            os_config = json.loads(cfg_file.read_text(encoding="utf-8-sig"))
            if os_config.get("server", {}).get("role") == "production":
                raise ValueError("Denne serveren er merket production. Kjoer trening paa en dedikert treningsserver etter datasettgodkjenning.")
            break
    checkpoint = directory / "model/checkpoint.pt"
    if resume:
        if not checkpoint.is_file():
            raise ValueError("Ingen siste checkpoint aa fortsette fra")
        expected = run.get("checkpoints", {}).get(checkpoint.name)
        if not expected or sha256(checkpoint) != expected["sha256"]:
            raise ValueError("Checkpoint er endret etter registrering")
    elif run["status"] != "awaiting_dataset_approval" or (directory / "model").exists():
        raise ValueError("Run er allerede startet; bruk resume eller lag et nytt run")
    config["training"]["max_steps"] = run.get("last_max_steps", config["training"]["max_steps"])
    if max_steps is not None:
        if not resume or max_steps < config["training"]["max_steps"]:
            raise ValueError("Bare resume kan oeke max_steps")
        if config.get("scheduler", {}).get("name", "constant") != "constant":
            raise ValueError("Forlengelse krever constant scheduler; bruk et nytt finetune-run for en ny LR-plan")
        config["training"]["max_steps"] = max_steps
    config["training"]["dataset_approval"] = str(Path(approval_path).resolve())
    environment = {name: importlib.metadata.version(name) for name in
                   ["torch", "diffusers", "transformers", "numpy", "Pillow", "accelerate",
                    "huggingface-hub", "tokenizers", "safetensors", "scipy", "PyYAML", "pillow-heif"]}
    environment["python"] = ".".join(map(str, sys.version_info[:3]))
    if resume and run.get("environment") and run["environment"] != environment:
        raise ValueError("Biblioteksversjoner er endret; gjenopprett miljoeet foer resume")
    lock = directory / ".running.lock"
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    if json.loads((directory / "run.json").read_text(encoding="utf-8")) != run:
        lock.unlink()
        raise ValueError("Run ble endret av en annen prosess; les status og proev igjen")
    try:
        write_json(lock, {"host": socket.gethostname(), "pid": os.getpid(), "started_utc": now()})
        run.update(status="running", started_utc=now(), host=socket.gethostname(),
                   approval=json.loads(Path(approval_path).read_text(encoding="utf-8-sig")))
        run["last_max_steps"] = config["training"]["max_steps"]
        attempt = {"number": len(run.get("attempts", [])) + 1, "started_utc": now(),
                   "resume": resume, "max_steps": run["last_max_steps"], "host": socket.gethostname()}
        run.setdefault("attempts", []).append(attempt)
        run.pop("error", None)
        run["environment"] = environment
        write_json(directory / "run.json", run)
        if run["component"] == "swap":
            from .loop import train as trainer
        elif run["component"] == "identity":
            from .identity import train_identity_encoder as trainer
        else:
            from .refiner import train_refiner as trainer
        # Optimizer og GPU finnes bare bak denne godkjenningsgrensen.
        outcome = trainer(config, str(checkpoint) if resume else None)
        write_json(directory / f"result.attempt-{attempt['number']:03d}.json", outcome)
        write_json(directory / "result.json", outcome)
        run["status"] = "completed"
    except BaseException as exc:
        run.update(status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                   error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        run["ended_utc"] = now()
        if run.get("attempts"):
            run["attempts"][-1].update(status=run["status"], ended_utc=run["ended_utc"],
                                      error=run.get("error"), environment=run.get("environment"))
        run["checkpoints"] = {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size}
                              for p in (directory / "model").glob("*.pt")}
        write_json(directory / "run.json", run)
        lock.unlink(missing_ok=True)
    return run


def recover_run(directory, reason, confirmed_stopped=False):
    """Registrer siste atomiske checkpoint etter stroembrudd, uten aa laste en modell."""
    import psutil
    directory = Path(directory).resolve()
    lock = directory / ".running.lock"
    if not reason.strip() or not confirmed_stopped:
        raise ValueError("Recovery krever begrunnelse og --confirmed-stopped")
    owner = json.loads(lock.read_text(encoding="utf-8"))
    if owner.get("host") == socket.gethostname() and psutil.pid_exists(owner.get("pid", -1)):
        raise ValueError("Prosessen fra laasen eksisterer fortsatt; nekter recovery")
    run = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    run.setdefault("recoveries", []).append({"utc": now(), "reason": reason, "previous_lock": owner})
    run["checkpoints"] = {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size}
                          for p in (directory / "model").glob("*.pt")}
    run["status"] = "interrupted"
    if run.get("attempts"):
        run["attempts"][-1].update(status="interrupted", ended_utc=now(), error="Process terminated; operator recovery")
    write_json(directory / "run.json", run)
    lock.unlink()
    return {"run_id": run["run_id"], "status": run["status"], "checkpoints": run["checkpoints"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--config", required=True)
    plan.add_argument("--run-id", required=True)
    plan.add_argument("--component", required=True, choices=sorted(COMPONENTS))
    plan.add_argument("--mode", choices=["fresh", "finetune"], default="fresh")
    plan.add_argument("--parent")
    for command in ("start", "resume"):
        execute = sub.add_parser(command)
        execute.add_argument("--run", required=True)
        execute.add_argument("--approval", required=True)
        if command == "resume":
            execute.add_argument("--max-steps", type=int)
    sub.add_parser("list")
    recover = sub.add_parser("recover")
    recover.add_argument("--run", required=True)
    recover.add_argument("--reason", required=True)
    recover.add_argument("--confirmed-stopped", action="store_true")
    args = parser.parse_args(argv)
    os.chdir(package_root())
    if args.command == "list":
        for p in sorted(Path("runs/managed").glob("*/run.json")):
            r = json.loads(p.read_text(encoding="utf-8"))
            print(json.dumps({k: r[k] for k in ["run_id", "component", "mode", "status", "parent"]}))
    elif args.command == "recover":
        print(json.dumps(recover_run(args.run, args.reason, args.confirmed_stopped), indent=2))
    elif args.command == "plan":
        config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8-sig"))
        print(prepare_run(config, args.run_id, args.component, args.mode, args.parent))
    else:
        print(json.dumps(execute_run(args.run, args.approval, args.command == "resume",
                                     getattr(args, "max_steps", None)), indent=2))


if __name__ == "__main__":
    main()
