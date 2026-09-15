"""PyTorch dataset sharing the production crop geometry and authoritative masks."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset

from ..masking import load_headmask, process_mask
from ..template import CropConfig, extract_crop
from ..geometry import MaskContextGeometry
from .records import read_jsonl, validate_pair_manifests
from .registry import resolve_manifest_inventory


class PairDataset(Dataset):
    def __init__(self, manifest: str | Path, resolution: int = 64, split: str = "train",
                 peer_manifests=(), allow_synthetic: bool = False, reference_count: int = 1,
                 context: float = 1.5, registry_path=None, mask_channel: str = "red",
                 degradation: str = "neutral", degradation_seed: int = 0, source_crops: bool = False):
        if resolution < 8 or reference_count < 1:
            raise ValueError("resolution must be >=8 and reference_count >=1")
        self.source_crops = bool(source_crops)
        manifest = Path(manifest).resolve()
        if not isinstance(allow_synthetic, bool):
            raise ValueError("allow_synthetic must be an explicit boolean")
        primary = read_jsonl(manifest)
        require_registry = any(row.get("synthetic") is not True for row in primary)
        inventory, self.audit = resolve_manifest_inventory([manifest, *peer_manifests], registry_path=registry_path,
                                                           require_registry=require_registry)
        all_rows = validate_pair_manifests(inventory, allow_synthetic=allow_synthetic, registry_path=registry_path,
                                           require_registry=require_registry)
        self.rows = [row for row in all_rows if row["_manifest"] == str(manifest) and row["split"] == split]
        if not self.rows:
            raise ValueError(f"No {split!r} pairs in {manifest}")
        self.resolution, self.reference_count = resolution, reference_count
        self.mask_channel = mask_channel
        self.degradation, self.degradation_seed = degradation, degradation_seed
        self.crop_config = CropConfig(resolution=resolution, context=context)
        for row in self.rows:
            if len(row["sources"]) < reference_count:
                raise ValueError(f"{row['pair_id']}: requires {reference_count} distinct references")
            if self.source_crops and len(row.get("source_headmasks", [])) < reference_count:
                raise ValueError(f"{row['pair_id']}: source_crops needs a headmask per source capture. "
                                 "Regenerate the pairs from an enrolment that masks every capture")

    def __len__(self):
        return len(self.rows)

    @staticmethod
    def _rgb(path):
        with Image.open(path) as image:
            if image.getexif().get(274, 1) != 1:
                raise ValueError("Normalize EXIF orientation before creating masks or pairs")
            return np.asarray(image.convert("RGB")).copy()

    @staticmethod
    def _tensor(array):
        return torch.from_numpy(np.ascontiguousarray(array.transpose(2, 0, 1))).float()

    def __getitem__(self, index):
        row = self.rows[index]
        template, target = self._rgb(row["template"]), self._rgb(row["ground_truth"])
        if template.shape != target.shape:
            raise ValueError("Template and ground truth must have identical geometry")
        masks = process_mask(load_headmask(row["headmask"], channel=row.get("mask_channel", self.mask_channel)).values)
        crop = extract_crop(template, masks, self.crop_config)
        target_crop = extract_crop(target, masks, self.crop_config)
        from ..template.degradation import prepare_condition_crop
        condition_crop = prepare_condition_crop(template, crop, strategy=self.degradation,
                                                 seed=self.degradation_seed + index)
        safe_crop = condition_crop if self.degradation == "neutral" else prepare_condition_crop(template, crop, strategy="neutral")
        template_tensor = self._tensor(crop.image)
        mask_tensor = torch.from_numpy(np.ascontiguousarray(crop.mask[None])).float()
        supplied = row.get("target_metadata", {}).get("geometry", {})
        geometry = MaskContextGeometry().extract(self._tensor(safe_crop)[None], mask_tensor[None], supplied)
        references = []
        for position, path in enumerate(row["sources"][:self.reference_count]):
            if self.source_crops:
                # Frame the reference like the target crop. Matching a whole photo against a
                # head crop teaches framing, not identity.
                source_mask = load_headmask(row["source_headmasks"][position],
                                            channel=row["source_mask_channels"][position]).values
                source_crop = extract_crop(self._rgb(path), process_mask(source_mask), self.crop_config)
                references.append(self._tensor(source_crop.image))
                continue
            reference = Image.fromarray(self._rgb(path)).resize((self.resolution, self.resolution), Image.Resampling.LANCZOS)
            references.append(self._tensor(np.asarray(reference, dtype=np.float32) / 255.0))
        return {
            "references": torch.stack(references), "template": template_tensor,
            "condition_template": self._tensor(condition_crop), "condition_strategy": self.degradation,
            "target": self._tensor(target_crop.image),
            "mask": mask_tensor,
            "age": torch.tensor(row["age"] if row.get("age") is not None else -1.0, dtype=torch.float32),
            # Measured mask/context features; face estimates remain explicitly unavailable unless supplied.
            "geometry_spatial": geometry.spatial[0], "geometry_vector": geometry.vector[0],
            "geometry_available": geometry.measurements["face_geometry_available"],
            "identity_id": row["identity_id"], "pair_id": row["pair_id"],
            "synthetic": row.get("synthetic", False),
        }
