"""Explicitly enrolled identity data and portable, auditable JSONL pair records."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

SPLITS = frozenset({"train", "validation", "test", "benchmark"})


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with Path(path).open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"{path}:{line_number}: expected JSON object")
                rows.append(row)
    return rows


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")


def resolve_asset(base: Path, value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Asset path must be a nonempty string")
    path = Path(value)
    return (path if path.is_absolute() else base / path).resolve()


@dataclass(frozen=True)
class RightsMetadata:
    provenance: str
    license: str
    consent: dict[str, Any]
    training_permitted: bool
    commercial_use_permitted: bool
    customer_data: bool
    explicit_training_enrollment: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RightsMetadata":
        if not isinstance(value, dict):
            raise ValueError("rights must be an explicit object")
        try:
            rights = cls(**{key: value[key] for key in (
                "provenance", "license", "consent", "training_permitted",
                "commercial_use_permitted", "customer_data"
            )}, explicit_training_enrollment=value.get("explicit_training_enrollment", False))
        except (KeyError, TypeError) as error:
            raise ValueError(f"Incomplete rights metadata: {error}") from error
        rights.validate()
        return rights

    def validate(self) -> None:
        for name in ("training_permitted", "commercial_use_permitted", "customer_data", "explicit_training_enrollment"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"rights.{name} must be a JSON boolean, never a string or integer")
        for name in ("provenance", "license"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"rights.{name} must identify an auditable source")
        if self.training_permitted is not True or self.commercial_use_permitted is not True:
            raise ValueError("Explicit training and commercial-use permissions are required")
        if not isinstance(self.customer_data, bool):
            raise ValueError("rights.customer_data must explicitly be true or false")
        if not isinstance(self.consent, dict) or self.consent.get("status") != "granted":
            raise ValueError("Recorded granted consent is required")
        if not isinstance(self.consent.get("reference"), str) or not self.consent["reference"].strip():
            raise ValueError("Consent must include an auditable reference")
        if self.consent.get("training_permitted") is not True:
            raise ValueError("Consent must explicitly permit training")
        if self.customer_data and self.explicit_training_enrollment is not True:
            raise ValueError("Customer inference data cannot automatically enter training")


@dataclass
class ImageRecord:
    image_id: str
    path: Path
    headmask: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IdentityRecord:
    identity_id: str
    images: list[ImageRecord]
    rights: dict[str, Any]
    split: str | None = None
    age: float | None = None
    synthetic: bool = False


def load_identities(manifest: str | Path, *, allow_synthetic: bool = False) -> list[IdentityRecord]:
    manifest = Path(manifest).resolve()
    identities, seen_ids = [], set()
    for row in read_jsonl(manifest):
        identity_id = row.get("identity_id")
        if not isinstance(identity_id, str) or not identity_id.strip() or identity_id in seen_ids:
            raise ValueError(f"Missing or duplicate identity_id: {identity_id!r}")
        seen_ids.add(identity_id)
        RightsMetadata.from_dict(row.get("rights"))
        synthetic = row.get("synthetic", False)
        if not isinstance(synthetic, bool):
            raise ValueError("synthetic must be a boolean")
        if synthetic and not allow_synthetic:
            raise ValueError("Synthetic fixtures require explicit allow_synthetic=True")
        split = row.get("split")
        if split is not None and split not in SPLITS:
            raise ValueError(f"Invalid split {split!r}")
        age = row.get("age")
        if age is not None and (isinstance(age, bool) or not isinstance(age, (int, float)) or not 0 <= age <= 120):
            raise ValueError("Age must be supplied explicitly in [0,120], or omitted")
        images, image_ids = [], set()
        for item in row.get("images", []):
            image_id = item.get("image_id")
            if not isinstance(image_id, str) or not image_id or image_id in image_ids:
                raise ValueError(f"Missing/duplicate image_id within {identity_id}")
            image_ids.add(image_id)
            if "rights" in item:
                RightsMetadata.from_dict(item["rights"])
            images.append(ImageRecord(
                image_id=image_id, path=resolve_asset(manifest.parent, item["path"]),
                headmask=resolve_asset(manifest.parent, item["headmask"]) if item.get("headmask") else None,
                metadata={k: v for k, v in item.items() if k not in {"image_id", "path", "headmask"}},
            ))
        if len(images) < 2 or len({image.path for image in images}) != len(images):
            raise ValueError(f"{identity_id}: at least two distinct image paths are required")
        identities.append(IdentityRecord(identity_id, images, row["rights"], split, age, synthetic))
    if not identities:
        raise ValueError("Identity manifest is empty")
    return identities


def validate_pair_manifests(manifests: Iterable[str | Path], *, allow_synthetic: bool = False,
                            check_files: bool = True, registry_path=None,
                            require_registry: bool = False) -> list[dict[str, Any]]:
    """Check ALL supplied manifests before any split filtering, including asset leakage."""
    identities: dict[str, str] = {}
    assets: dict[str, tuple[str, str]] = {}
    pair_ids, rows, visited = set(), [], set()
    from .registry import resolve_manifest_inventory
    manifests, _ = resolve_manifest_inventory(manifests, registry_path=registry_path, require_registry=require_registry)
    hash_cache: dict[str, tuple[str, str]] = {}
    def hashes(asset):
        if asset not in hash_cache:
            from .preprocessing import decoded_pixel_sha256
            hash_cache[asset] = (file_sha256(asset), decoded_pixel_sha256(asset))
        return hash_cache[asset]
    for manifest in manifests:
        manifest = Path(manifest).resolve()
        if manifest in visited:
            continue
        visited.add(manifest)
        for row in read_jsonl(manifest):
            pair_id, identity_id, split = row.get("pair_id"), row.get("identity_id"), row.get("split")
            if not isinstance(pair_id, str) or not pair_id or pair_id in pair_ids:
                raise ValueError(f"Missing/duplicate pair_id: {pair_id!r}")
            pair_ids.add(pair_id)
            if not isinstance(identity_id, str) or not identity_id or split not in SPLITS:
                raise ValueError("Every pair needs identity_id and a valid split")
            if identity_id in identities and identities[identity_id] != split:
                raise ValueError(f"Identity split leakage: {identity_id}")
            identities[identity_id] = split
            RightsMetadata.from_dict(row.get("rights"))
            if not isinstance(row.get("synthetic", False), bool):
                raise ValueError("synthetic must be boolean")
            if row.get("synthetic") and not allow_synthetic:
                raise ValueError("Synthetic fixtures require explicit allow_synthetic=True")
            age = row.get("age")
            if age is not None and (isinstance(age, bool) or not isinstance(age, (int, float))
                                    or not math.isfinite(age) or not 0 <= age <= 120):
                raise ValueError("Age must be explicitly supplied in [0,120] or absent")
            resolved = dict(row)
            resolved["_manifest"] = str(manifest)
            for key in ("source", "template", "headmask", "ground_truth"):
                resolved[key] = str(resolve_asset(manifest.parent, row.get(key)))
            sources = row.get("sources", [row["source"]])
            if not isinstance(sources, list) or not sources:
                raise ValueError("sources must be a nonempty list")
            resolved["sources"] = [str(resolve_asset(manifest.parent, source)) for source in sources]
            source_masks = row.get("source_headmasks")
            if source_masks is not None:
                if not isinstance(source_masks, list) or len(source_masks) != len(resolved["sources"]):
                    raise ValueError("source_headmasks must list one mask per source capture")
                resolved["source_headmasks"] = [str(resolve_asset(manifest.parent, mask)) for mask in source_masks]
                channels = row.get("source_mask_channels", [row.get("mask_channel", "red")] * len(source_masks))
                if (not isinstance(channels, list) or len(channels) != len(source_masks) or
                        any(c not in {"red", "green", "blue", "alpha", "luminance"} for c in channels)):
                    raise ValueError("source_mask_channels must list one valid channel per source mask")
                resolved["source_mask_channels"] = channels
            if len(set(resolved["sources"])) != len(resolved["sources"]):
                raise ValueError("Multiple references must be distinct captures")
            if resolved["source"] not in resolved["sources"]:
                raise ValueError("source must also occur in sources")
            if set((resolved["template"], resolved["ground_truth"])) & set(resolved["sources"]):
                raise ValueError("Source and target must be distinct captures")
            channel = row.get("mask_channel", "red")
            if channel not in {"red", "green", "blue", "alpha", "luminance"}:
                raise ValueError("Invalid explicit mask_channel")
            if check_files:
                image_paths = set(resolved["sources"] + [resolved["template"], resolved["ground_truth"]])
                for asset in image_paths | {resolved["headmask"], *resolved.get("source_headmasks", [])}:
                    if not Path(asset).is_file():
                        raise ValueError(f"Missing pair asset: {asset}")
                # File and decoded-pixel hashes prevent exact copies or re-encodings in other splits.
                for asset in image_paths:
                    file_hash, pixel_hash = hashes(asset)
                    for digest in ("file:" + file_hash, "pixels:" + pixel_hash):
                        previous = assets.get(digest)
                        if previous and previous[0] != split:
                            raise ValueError(f"Image content split leakage: {asset} ({previous[1]})")
                        assets[digest] = (split, identity_id)
                source_hashes = {hashes(asset)[1] for asset in resolved["sources"]}
                if len(source_hashes) != len(resolved["sources"]):
                    raise ValueError("Multiple references contain duplicate capture pixels")
                if any(hashes(resolved[key])[1] in source_hashes for key in ("template", "ground_truth")):
                    raise ValueError("Source and target are duplicate captures")
            rows.append(resolved)
    return rows
