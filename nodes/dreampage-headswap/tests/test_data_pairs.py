"""Dataset layer: rights, preprocessing, pairing, splitting and leakage.

Leakage is the failure this file exists for. A pair manifest that passes here has been checked
by identity, by file hash and by decoded pixels, across every manifest supplied together.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from _fixtures import identity_row, load_script, rights, write_image, write_mask
from dreampage_headswap.data import PairDataset, generate_pairs, identity_split, load_identities, validate_pair_manifests
from dreampage_headswap.data.preprocessing import PreprocessConfig, identity_to_dict, preprocess_identities
from dreampage_headswap.data.records import read_jsonl, write_jsonl


def pair_row(pair_id, identity_id, split, source, template, mask, ground_truth=None):
    return {"pair_id": pair_id, "identity_id": identity_id, "split": split, "rights": rights(),
            "synthetic": True, "source": str(source), "sources": [str(source)], "template": str(template),
            "headmask": str(mask), "ground_truth": str(ground_truth or template)}


class RightsTests(unittest.TestCase):
    def test_incomplete_or_withheld_rights_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            broken = [
                ({"consent": {"status": "pending", "reference": "x", "training_permitted": True}}, "consent"),
                ({"training_permitted": False}, "training"),
                ({"commercial_use_permitted": False}, "commercial"),
                ({"customer_data": True}, "customer inference data"),
            ]
            for index, (override, _) in enumerate(broken):
                row = identity_row(root, f"broken_{index}", index + 1)
                row["rights"] = rights(**override)
                manifest = root / f"broken_{index}.jsonl"
                write_jsonl(manifest, [row])
                with self.assertRaises(ValueError):
                    load_identities(manifest, allow_synthetic=True)

    def test_enrolled_customer_data_needs_explicit_enrollment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = identity_row(root, "customer", 7)
            row["rights"] = rights(customer_data=True, explicit_training_enrollment=True)
            manifest = root / "customer.jsonl"
            write_jsonl(manifest, [row])
            self.assertEqual(len(load_identities(manifest, allow_synthetic=True)), 1)

    def test_synthetic_fixtures_require_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "ids.jsonl"
            write_jsonl(manifest, [identity_row(root, "syn", 3)])
            with self.assertRaises(ValueError):
                load_identities(manifest)


class PreprocessTests(unittest.TestCase):
    def test_accepts_captures_and_leaves_face_annotation_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "ids.jsonl"
            write_jsonl(manifest, [identity_row(root, "a", 1), identity_row(root, "b", 2)])
            accepted, report = preprocess_identities(load_identities(manifest, allow_synthetic=True))
            self.assertEqual(report["accepted_identity_count"], 2)
            self.assertEqual(report["accepted_image_count"], 4)
            annotations = report["images"][0]["annotations"]
            self.assertFalse(annotations["available"])
            self.assertIsNone(annotations["landmarks"])

    def test_duplicate_captures_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            duplicate = write_image(root / "dup" / "image_000.png", 11)
            copy = root / "dup" / "image_001.png"
            copy.write_bytes(duplicate.read_bytes())
            mask = write_mask(root / "dup" / "image_001_mask.png")
            row = {"identity_id": "dup", "rights": rights(), "synthetic": True,
                   "images": [{"image_id": "image_000", "path": str(duplicate)},
                              {"image_id": "image_001", "path": str(copy), "headmask": str(mask)}]}
            manifest = root / "ids.jsonl"
            write_jsonl(manifest, [row])
            accepted, report = preprocess_identities(load_identities(manifest, allow_synthetic=True))
            self.assertEqual(accepted, [])
            self.assertIn("exact_duplicate_capture", report["images"][0]["reasons"])
            self.assertEqual(report["identities_rejected"][0]["identity_id"], "dup")

    def test_missing_headmask_is_rejected_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "ids.jsonl"
            write_jsonl(manifest, [identity_row(root, "nomask", 5, masked_from=99)])
            identities = load_identities(manifest, allow_synthetic=True)
            self.assertEqual(preprocess_identities(identities)[0], [])
            relaxed = PreprocessConfig(require_headmask=False)
            self.assertEqual(len(preprocess_identities(identities, relaxed)[0]), 1)

    def test_mask_geometry_mismatch_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = write_image(root / "m" / "image_000.png", 21, (64, 64))
            second = write_image(root / "m" / "image_001.png", 22, (64, 64))
            mask = write_mask(root / "m" / "wrong_mask.png", (32, 32), (4, 4, 20, 20))
            row = {"identity_id": "m", "rights": rights(), "synthetic": True,
                   "images": [{"image_id": "image_000", "path": str(image)},
                              {"image_id": "image_001", "path": str(second), "headmask": str(mask)}]}
            manifest = root / "ids.jsonl"
            write_jsonl(manifest, [row])
            _, report = preprocess_identities(load_identities(manifest, allow_synthetic=True))
            masked = [item for item in report["images"] if item["image_id"] == "image_001"][0]
            self.assertEqual(masked["headmask"]["reason"], "mask_resolution_mismatch")


class PairingTests(unittest.TestCase):
    def test_split_assignment_is_deterministic_and_identity_level(self):
        first = [identity_split(f"identity_{index}", seed=7) for index in range(64)]
        second = [identity_split(f"identity_{index}", seed=7) for index in range(64)]
        self.assertEqual(first, second)
        self.assertNotEqual(identity_split("identity_0", seed=7), identity_split("identity_0", seed=8))
        self.assertLessEqual(set(first), {"train", "validation", "test"})

    def test_pair_generation_is_stable_and_uses_the_targets_mask(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "ids.jsonl"
            write_jsonl(manifest, [identity_row(root, "a", 1, images=3, split="train", masked_from=1, age=5)])
            identities = load_identities(manifest, allow_synthetic=True)
            pairs = generate_pairs(identities, seed=3)
            self.assertEqual(len(pairs), 4)  # two masked targets, two distinct sources each
            self.assertEqual([row["pair_id"] for row in pairs],
                             [row["pair_id"] for row in generate_pairs(identities, seed=3)])
            for row in pairs:
                self.assertEqual(row["split"], "train")
                self.assertEqual(row["age"], 5)
                self.assertEqual(row["ground_truth"], row["template"])
                self.assertNotEqual(row["source"], row["template"])
                self.assertTrue(Path(row["headmask"]).is_file())

    def test_target_without_a_mask_cannot_become_a_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "ids.jsonl"
            write_jsonl(manifest, [identity_row(root, "a", 1, masked_from=99)])
            with self.assertRaises(ValueError):
                generate_pairs(load_identities(manifest, allow_synthetic=True))


class LeakageTests(unittest.TestCase):
    def _corpus(self, root: Path):
        write_jsonl(root / "ids.jsonl", [identity_row(root, f"id_{index}", index + 1, split=split)
                                         for index, split in enumerate(["train", "train", "validation", "test"])])
        identities = load_identities(root / "ids.jsonl", allow_synthetic=True)
        rows = generate_pairs(identities, seed=1, max_pairs_per_identity=1)
        manifests = {}
        for split in sorted({row["split"] for row in rows}):
            path = root / f"pairs.{split}.jsonl"
            write_jsonl(path, [row for row in rows if row["split"] == split])
            manifests[split] = path
        return manifests

    def test_clean_corpus_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifests = self._corpus(Path(tmp))
            validated = validate_pair_manifests(manifests.values(), allow_synthetic=True)
            self.assertEqual(len(validated), 4)
            self.assertEqual(len({row["identity_id"] for row in validated}), 4)

    def test_identity_in_two_splits_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifests = self._corpus(root)
            stolen = read_jsonl(manifests["train"])[0]
            stolen["split"] = "test"
            stolen["pair_id"] = stolen["pair_id"] + "x"
            write_jsonl(manifests["test"], read_jsonl(manifests["test"]) + [stolen])
            with self.assertRaisesRegex(ValueError, "Identity split leakage"):
                validate_pair_manifests(manifests.values(), allow_synthetic=True)

    def test_same_pixels_under_a_new_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifests = self._corpus(root)
            train = read_jsonl(manifests["train"])[0]
            reencoded = root / "reencoded.png"
            from PIL import Image
            with Image.open(train["template"]) as image:
                image.convert("RGB").save(reencoded, optimize=True)
            source = write_image(root / "other" / "source.png", 900)
            mask = write_mask(root / "other" / "mask.png")
            write_jsonl(manifests["test"], [pair_row("relabelled", "brand_new_identity", "test",
                                                     source, reencoded, mask)])
            with self.assertRaisesRegex(ValueError, "Image content split leakage"):
                validate_pair_manifests(manifests.values(), allow_synthetic=True)

    def test_duplicate_pair_ids_and_missing_assets_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = write_image(root / "a.png", 1)
            template = write_image(root / "b.png", 2)
            mask = write_mask(root / "m.png")
            duplicated = root / "dupe.jsonl"
            write_jsonl(duplicated, [pair_row("same", "a", "train", source, template, mask),
                                     pair_row("same", "b", "train", source, template, mask)])
            with self.assertRaisesRegex(ValueError, "duplicate pair_id"):
                validate_pair_manifests([duplicated], allow_synthetic=True)
            missing = root / "missing.jsonl"
            write_jsonl(missing, [pair_row("p", "a", "train", source, template, root / "absent.png")])
            with self.assertRaisesRegex(ValueError, "Missing pair asset"):
                validate_pair_manifests([missing], allow_synthetic=True)

    def test_source_and_target_must_be_distinct_captures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = write_image(root / "a.png", 1)
            mask = write_mask(root / "m.png")
            manifest = root / "same.jsonl"
            write_jsonl(manifest, [pair_row("p", "a", "train", image, image, mask)])
            with self.assertRaises(ValueError):
                validate_pair_manifests([manifest], allow_synthetic=True)


class DatasetTests(unittest.TestCase):
    def test_batch_shapes_and_unavailable_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_jsonl(root / "ids.jsonl", [identity_row(root, "a", 1, split="train"),
                                             identity_row(root, "b", 2, split="train")])
            rows = generate_pairs(load_identities(root / "ids.jsonl", allow_synthetic=True), seed=1,
                                  max_pairs_per_identity=1)
            manifest = root / "pairs.train.jsonl"
            write_jsonl(manifest, rows)
            dataset = PairDataset(manifest, resolution=32, split="train", allow_synthetic=True)
            self.assertEqual(len(dataset), 2)
            item = dataset[0]
            self.assertEqual(tuple(item["template"].shape), (3, 32, 32))
            self.assertEqual(tuple(item["target"].shape), (3, 32, 32))
            self.assertEqual(tuple(item["mask"].shape), (1, 32, 32))
            self.assertEqual(tuple(item["references"].shape), (1, 3, 32, 32))
            self.assertEqual(tuple(item["geometry_spatial"].shape), (4, 32, 32))
            self.assertFalse(item["geometry_available"])
            self.assertTrue(0.0 <= float(item["template"].min()) and float(item["template"].max()) <= 1.0)

    def test_requesting_more_references_than_enrolled_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_jsonl(root / "ids.jsonl", [identity_row(root, "a", 1, split="train")])
            manifest = root / "pairs.train.jsonl"
            write_jsonl(manifest, generate_pairs(load_identities(root / "ids.jsonl", allow_synthetic=True)))
            with self.assertRaises(ValueError):
                PairDataset(manifest, resolution=32, split="train", allow_synthetic=True, reference_count=2)


class ScriptTests(unittest.TestCase):
    def test_preprocess_then_pair_scripts_produce_a_validated_corpus(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "ids.jsonl"
            write_jsonl(manifest, [identity_row(root, f"id_{index}", index + 1, split=split)
                                   for index, split in enumerate(["train", "train", "validation", "test"])])
            preprocess = load_script("preprocess_dataset")
            self.assertEqual(preprocess.main(["--identities", str(manifest), "--output-dir",
                                              str(root / "clean"), "--allow-synthetic"]), 0)
            clean = root / "clean" / "identities.clean.jsonl"
            self.assertEqual(len(read_jsonl(clean)), 4)
            report = json.loads((root / "clean" / "preprocess_report.json").read_text(encoding="utf-8"))
            self.assertTrue(report["synthetic_fixture_run"])

            pairs = load_script("generate_training_pairs")
            self.assertEqual(pairs.main(["--identities", str(clean), "--output-dir", str(root / "pairs"),
                                         "--max-pairs-per-identity", "1", "--allow-synthetic"]), 0)
            summary = json.loads((root / "pairs" / "pairs_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["pair_count"], 4)
            self.assertEqual(summary["pairs_per_split"], {"test": 1, "train": 2, "validation": 1})
            self.assertEqual(summary["identities_per_split"], {"test": 1, "train": 2, "validation": 1})
            self.assertEqual(sorted(summary["manifests"]), ["test", "train", "validation"])

    def test_cleaned_manifest_round_trips_through_the_rights_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "ids.jsonl"
            write_jsonl(manifest, [identity_row(root, "a", 1, split="train", age=6)])
            identities = load_identities(manifest, allow_synthetic=True)
            accepted, _ = preprocess_identities(identities)
            round_trip = root / "clean.jsonl"
            write_jsonl(round_trip, [identity_to_dict(identity) for identity in accepted])
            reloaded = load_identities(round_trip, allow_synthetic=True)
            self.assertEqual(reloaded[0].identity_id, "a")
            self.assertEqual(reloaded[0].age, 6)
            self.assertEqual(reloaded[0].split, "train")
            quality = reloaded[0].images[0].metadata["quality"]
            self.assertTrue(np.isfinite(quality["laplacian_variance"]))


if __name__ == "__main__":
    unittest.main()
