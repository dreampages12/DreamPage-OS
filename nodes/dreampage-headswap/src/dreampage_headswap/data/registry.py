"""Hash-bound inventory of all manifests in an explicitly enrolled dataset corpus.

The registry establishes the audit scope. It cannot discover unregistered identities or
decide that differently named people are the same person; enrollment must resolve identity IDs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .records import file_sha256

REGISTRY_NAME = "dataset_registry.json"


def create_registry(manifests, destination: str | Path, *, identity_manifest=None) -> dict:
    destination = Path(destination).resolve()
    paths = sorted({Path(path).resolve() for path in manifests})
    registry = {"schema_version": 1, "scope": "complete_declared_enrolled_corpus",
                "identity_policy": "One resolved stable identity_id per person across every enrolled dataset",
                "manifests": [{"path": Path(os.path.relpath(path, destination.parent)).as_posix(), "sha256": file_sha256(path)} for path in paths]}
    if identity_manifest is not None:
        registry["identity_manifest_sha256"] = file_sha256(identity_manifest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return registry


def resolve_manifest_inventory(manifests, *, registry_path=None, require_registry=False) -> tuple[list[Path], dict]:
    requested = {Path(path).resolve() for path in manifests}
    registry_paths = {Path(registry_path).resolve()} if registry_path else {
        path.parent / REGISTRY_NAME for path in requested if (path.parent / REGISTRY_NAME).is_file()}
    if require_registry and not registry_paths:
        raise ValueError("Real data requires dataset_registry.json covering the complete enrolled corpus; generate or supply registry_path")
    expanded, enrolled, records = set(requested), set(), []
    for registry in sorted(registry_paths):
        payload = json.loads(registry.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1 or payload.get("scope") != "complete_declared_enrolled_corpus":
            raise ValueError("Unsupported or incomplete dataset registry scope")
        entries = payload.get("manifests")
        if not isinstance(entries, list):
            raise ValueError("Dataset registry manifests must be an explicit list")
        local = set()
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ValueError("Invalid dataset registry entry")
            asset = (registry.parent / entry["path"]).resolve()
            if asset in local:
                raise ValueError("Duplicate manifest in dataset registry")
            local.add(asset)
            if not asset.is_file() or entry.get("sha256") != file_sha256(asset):
                raise ValueError(f"Dataset registry hash mismatch or missing manifest: {asset}")
        expanded.update(local)
        enrolled.update(local)
        records.append({"path": str(registry), "sha256": file_sha256(registry)})
    # Once a registry is supplied, silently appending an unregistered manifest invalidates its scope.
    if registry_paths and not requested <= enrolled:
        missing = sorted(str(path) for path in requested - enrolled)
        raise ValueError(f"Manifest is outside the declared dataset registry: {missing}")
    audit = {"registries": records, "complete": bool(registry_paths),
             "scope": "complete_declared_enrolled_corpus" if registry_paths else "only_supplied_manifests",
             "manifests": [{"path": str(path), "sha256": file_sha256(path)} for path in sorted(expanded)]}
    return sorted(expanded), audit
