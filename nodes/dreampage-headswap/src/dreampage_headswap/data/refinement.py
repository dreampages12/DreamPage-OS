"""Pair verified generated artifacts with already enrolled reconstruction pairs."""
from __future__ import annotations

from pathlib import Path

from .dataset import PairDataset
from .records import file_sha256, read_jsonl, resolve_asset, validate_pair_manifests
from .preprocessing import decoded_pixel_sha256
from ..masking import load_headmask, process_mask
from ..template import extract_crop


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


class RefinementDataset(PairDataset):
    def __init__(self, manifest, *, artifacts_manifest, **kwargs):
        super().__init__(manifest, **kwargs)
        self.artifacts_manifest = str(Path(artifacts_manifest).resolve())
        all_pairs = validate_pair_manifests([entry["path"] for entry in self.audit["manifests"]],
                                            allow_synthetic=kwargs.get("allow_synthetic", False))
        pairs = {row["pair_id"]: row for row in all_pairs}
        annotations, owners, digest_cache = {}, {}, {}
        for pair in all_pairs:
            for asset in {*pair["sources"], pair["template"], pair["ground_truth"]}:
                path = Path(asset)
                if path not in digest_cache:
                    digest_cache[path] = decoded_pixel_sha256(path)
                owners[digest_cache[path]] = pair["split"]
        for row in read_jsonl(self.artifacts_manifest):
            pair_id = row.get("pair_id")
            if pair_id not in pairs or pair_id in annotations:
                raise ValueError("Refiner artifacts must have unique pair_id values in the enrolled corpus")
            path = resolve_asset(Path(self.artifacts_manifest).parent, row.get("generated"))
            if not path.is_file() or row.get("sha256") != file_sha256(path):
                raise ValueError(f"Generated artifact missing or hash mismatch: {path}")
            provenance = row.get("generator", {})
            synthetic = pairs[pair_id].get("synthetic") is True
            if provenance.get("kind") == "procedural_fixture":
                if not synthetic or not _digest(provenance.get("recipe_sha256")):
                    raise ValueError("Procedural artifacts require synthetic pairs and a recipe hash")
            elif provenance.get("kind") == "model":
                if not all(_digest(provenance.get(key)) for key in ("checkpoint_sha256", "config_sha256")):
                    raise ValueError("Generated model artifacts require checkpoint and config SHA256 provenance")
            else:
                raise ValueError("Refiner artifacts require explicit generator provenance")
            if path not in digest_cache:
                digest_cache[path] = decoded_pixel_sha256(path)
            digest = digest_cache[path]
            split = pairs[pair_id]["split"]
            if digest in owners and owners[digest] != split:
                raise ValueError("Generated artifact pixel leakage across dataset splits or enrolled base images")
            owners[digest] = split
            annotations[pair_id] = {**row, "generated": str(path), "artifact_manifest": self.artifacts_manifest}
        for row in self.rows:
            if row["pair_id"] not in annotations:
                raise ValueError(f"Missing generated artifact for pair {row['pair_id']}")
            row["generated"] = annotations[row["pair_id"]]["generated"]
            row["refinement_artifact"] = annotations[row["pair_id"]]
            row["refinement_artifact_manifest_sha256"] = file_sha256(self.artifacts_manifest)

    def __getitem__(self, index):
        result = super().__getitem__(index)
        row = self.rows[index]
        generated = self._rgb(row["generated"])
        template = self._rgb(row["template"])
        if generated.shape != template.shape:
            raise ValueError("Generated refiner artifact must have the original template's exact dimensions")
        mask = load_headmask(row["headmask"], channel=row.get("mask_channel", self.mask_channel))
        crop = extract_crop(generated, process_mask(mask.values), self.crop_config)
        result["generated"] = self._tensor(crop.image)
        return result
